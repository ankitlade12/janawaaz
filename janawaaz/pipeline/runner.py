"""Local synchronous pipeline runner.

Same steps as the Render Workflows chain (janawaaz/workflows.py), runnable on a
laptop: sweep -> fetch -> parse -> summarize/embed -> match -> gate -> notify.

    python -m janawaaz.pipeline.runner --limit 5 --skip-notify
"""

import argparse
import hashlib
import logging
from datetime import date, datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from janawaaz.adapters import REGISTRY
from janawaaz.adapters.base import ConsultationRecord
from janawaaz.config import settings
from janawaaz.db import init_db, session
from janawaaz.models import Document, Source
from janawaaz.pipeline import extract, matching, notify, summarize

log = logging.getLogger("janawaaz.runner")


def upsert_source(s, adapter_name: str) -> Source:
    adapter = REGISTRY[adapter_name]
    src = s.execute(select(Source).where(Source.adapter == adapter_name)).scalar_one_or_none()
    if src is None:
        src = Source(name=adapter_name.upper(), base_url=adapter.base_url, adapter=adapter_name)
        s.add(src)
        s.flush()
    return src


def ingest_record(s, src: Source, rec: ConsultationRecord) -> Document | None:
    """Insert a new document row, or return None if we already have it.

    The insert runs in a savepoint so a concurrent sweep inserting the same
    (source_id, external_id) loses only this record, not the whole batch —
    the unique constraint is the arbiter, not the racy pre-check.
    """
    existing = s.execute(
        select(Document).where(
            Document.source_id == src.id, Document.external_id == rec.external_id
        )
    ).scalar_one_or_none()
    if existing:
        # Listing metadata can change when agencies extend a deadline or replace
        # a PDF. Recheck currently actionable/unknown records; parse_document
        # will cheaply stop the downstream chain when content is unchanged.
        changed = False
        for field in ("title", "body_url", "comment_channel", "published_at", "ministry"):
            value = getattr(rec, field)
            if value and value != getattr(existing, field):
                setattr(existing, field, value)
                changed = True
        if rec.deadline and rec.deadline != existing.deadline:
            existing.deadline = rec.deadline
            changed = True
        if rec.status == "closed" and existing.status != "closed":
            existing.status = "closed"
            changed = True
        elif rec.status == "open" and (
            existing.deadline is None or existing.deadline >= date.today()
        ):
            existing.status = "open"
        actionable = (
            existing.deadline is None
            or existing.deadline >= date.today()
            or existing.status == "open"
            or rec.status == "open"
        )
        return existing if changed or actionable or existing.embedding is None else None
    doc = Document(
        source_id=src.id,
        external_id=rec.external_id,
        title=rec.title,
        body_url=rec.body_url,
        ministry=rec.ministry,
        deadline=rec.deadline,
        comment_channel=rec.comment_channel,
        published_at=rec.published_at,
        status=rec.status,
    )
    try:
        with s.begin_nested():
            s.add(doc)
            s.flush()
    except IntegrityError:
        log.info("doc %s/%s inserted concurrently elsewhere; skipping", src.adapter, rec.external_id)
        return None
    return doc


def parse_document(s, doc: Document) -> bool:
    """Download the body (PDF or HTML page), extract text + deadline with evidence span."""
    cfg = settings()
    if not doc.body_url or not doc.body_url.startswith("http"):
        log.info("doc %s: no fetchable body (%s); skipping text extraction", doc.id, doc.body_url)
        return False
    previous = (doc.content_hash, doc.deadline, doc.deadline_verified, doc.status)
    resp = httpx.get(
        doc.body_url,
        headers={"User-Agent": cfg.user_agent},
        timeout=cfg.http_timeout_seconds,
        follow_redirects=True,
    )
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if doc.body_url.lower().split("?")[0].endswith(".pdf") or "pdf" in content_type:
        # A nominal .PDF URL sometimes returns an HTML anti-bot page with 200.
        if resp.content[:20].lstrip().lower().startswith(b"<"):
            challenge = extract.html_text(resp.text)
            if extract.is_challenge_text(challenge):
                raise ValueError("source returned an anti-bot challenge instead of the PDF")
        body_text = extract.pdf_text(resp.content)
    else:
        body_text = extract.html_text(resp.text)
    if extract.is_challenge_text(body_text or ""):
        raise ValueError("source returned an anti-bot challenge instead of consultation text")
    if len((body_text or "").strip()) < 200:
        raise ValueError("consultation body is too short to process safely")
    doc.body_text = body_text
    doc.content_hash = hashlib.sha256(resp.content).hexdigest()

    found = extract.extract_deadline(doc.body_text, published_after=doc.published_at)
    if doc.comment_channel and doc.comment_channel != doc.body_url:
        # Some regulators (RBI's Connect 2 Regulate) state the deadline on the
        # comment page, not inside the document. Same extractor, same evidence rules.
        try:
            channel = httpx.get(
                doc.comment_channel,
                headers={"User-Agent": cfg.user_agent},
                timeout=cfg.http_timeout_seconds,
                follow_redirects=True,
            )
            channel.raise_for_status()
            channel_found = extract.extract_deadline(
                extract.html_text(channel.text), published_after=doc.published_at
            )
            # Detail/comment pages are where agencies announce extensions. Prefer
            # a later verified comment-page date over the paper's original date.
            if channel_found.deadline and (
                not found.deadline or channel_found.deadline > found.deadline
            ):
                found = channel_found
        except httpx.HTTPError as exc:
            log.info("doc %s: comment-channel fetch failed (%s)", doc.id, exc)
    if found.deadline:
        doc.deadline = found.deadline
        doc.deadline_span = found.span
        doc.deadline_verified = found.verified
    if doc.deadline:
        doc.status = "closed" if doc.deadline < date.today() else "open"
    log.info(
        "doc %s: %s chars, deadline=%s (%s, verified=%s)",
        doc.id, len(doc.body_text or ""), doc.deadline, found.method, found.verified,
    )
    current = (doc.content_hash, doc.deadline, doc.deadline_verified, doc.status)
    return current != previous or doc.embedding is None


def summarize_and_embed(s, doc: Document) -> None:
    cfg = settings()
    base_text = doc.body_text or doc.title
    if cfg.llm_provider != "none":
        doc.summary_en = summarize.summarize_en(base_text, doc.title)
    else:
        log.info("doc %s: no LLM key set; skipping summary", doc.id)
    doc.embedding = summarize.embed(f"{doc.title}\n\n{doc.summary_en or base_text[:2000]}")


def match_and_notify(s, doc: Document, skip_notify: bool = False) -> None:
    """Gate only plausible candidates: above threshold, best-first, capped.

    Sub-threshold pairs are skipped without a ledger row — the ledger records
    decisions about candidates, not the cross product of all users and papers.
    """
    if (
        doc.embedding is None
        or doc.status == "closed"
        or (doc.deadline is not None and doc.deadline < date.today())
    ):
        return
    cfg = settings()
    candidates = [
        (user, sim)
        for user, sim in matching.candidates_for_document(s, doc)
        if sim >= cfg.similarity_threshold
    ][: cfg.max_gate_candidates]
    log.info("doc %s: %s candidates above %.2f", doc.id, len(candidates), cfg.similarity_threshold)
    for user, sim in candidates:
        ledger = matching.gate_match(s, doc, user, sim)
        if ledger.tier == 1 and not skip_notify:
            notify.send_alert(s, doc, user, ledger)


def match_existing_for_user(s, user, skip_notify: bool = False) -> list:
    """Evaluate a new profile against consultations it can still act on."""
    cfg = settings()
    today = date.today()
    candidates = [
        (doc, sim)
        for doc, sim in matching.candidates_for_user(s, user)
        if sim >= cfg.similarity_threshold
        and (doc.deadline is None or doc.deadline >= today)
        and doc.status != "closed"
    ][: cfg.max_gate_candidates]
    rows = []
    for doc, sim in candidates:
        ledger = matching.gate_match(s, doc, user, sim)
        rows.append(ledger)
        if ledger.tier == 1 and not skip_notify and user.telegram_chat_id:
            notify.send_alert(s, doc, user, ledger)
    return rows


def sweep(limit: int | None = None, skip_notify: bool = False) -> dict:
    """Root step: run every adapter, process new documents through the chain."""
    stats = {"sources": 0, "new_documents": 0}
    with session() as s:
        for adapter_name, adapter in REGISTRY.items():
            src = upsert_source(s, adapter_name)
            records = adapter.fetch_records()
            stats["sources"] += 1
            new_docs = []
            for rec in records:
                doc = ingest_record(s, src, rec)
                if doc is not None:
                    new_docs.append(doc)
            if limit:
                new_docs = new_docs[:limit]
            log.info("%s: %s records, %s new", adapter_name, len(records), len(new_docs))
            for doc in new_docs:
                try:
                    changed = parse_document(s, doc)
                    if changed:
                        summarize_and_embed(s, doc)
                        match_and_notify(s, doc, skip_notify=skip_notify)
                    stats["new_documents"] += 1
                except Exception:
                    log.exception("doc %s (%s) failed; continuing", doc.id, doc.title[:60])
            src.last_swept_at = datetime.now(timezone.utc)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Run the JanAwaaz pipeline locally")
    ap.add_argument("--limit", type=int, default=None, help="max new docs per source")
    ap.add_argument("--skip-notify", action="store_true", help="run the gate but send nothing")
    args = ap.parse_args()
    init_db()
    stats = sweep(limit=args.limit, skip_notify=args.skip_notify)
    log.info("sweep complete: %s", stats)


if __name__ == "__main__":
    main()
