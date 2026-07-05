"""Local synchronous pipeline runner.

Same steps as the Render Workflows chain (janawaaz/workflows.py), runnable on a
laptop: sweep -> fetch -> parse -> summarize/embed -> match -> gate -> notify.

    python -m janawaaz.pipeline.runner --limit 5 --skip-notify
"""

import argparse
import hashlib
import logging
from datetime import datetime, timezone

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
    exists = s.execute(
        select(Document.id).where(
            Document.source_id == src.id, Document.external_id == rec.external_id
        )
    ).scalar_one_or_none()
    if exists:
        return None
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


def parse_document(s, doc: Document) -> None:
    """Download the body (PDF expected), extract text + deadline with evidence span."""
    cfg = settings()
    if not doc.body_url or not doc.body_url.lower().split("?")[0].endswith(".pdf"):
        log.info("doc %s: no PDF body (%s); skipping text extraction", doc.id, doc.body_url)
        return
    resp = httpx.get(
        doc.body_url,
        headers={"User-Agent": cfg.user_agent},
        timeout=cfg.http_timeout_seconds,
        follow_redirects=True,
    )
    resp.raise_for_status()
    doc.body_text = extract.pdf_text(resp.content)
    doc.content_hash = hashlib.sha256(resp.content).hexdigest()

    found = extract.extract_deadline(doc.body_text, published_after=doc.published_at)
    if found.deadline:
        doc.deadline = found.deadline
        doc.deadline_span = found.span
        doc.deadline_verified = found.verified
    log.info(
        "doc %s: %s chars, deadline=%s (%s, verified=%s)",
        doc.id, len(doc.body_text or ""), doc.deadline, found.method, found.verified,
    )


def summarize_and_embed(s, doc: Document) -> None:
    cfg = settings()
    base_text = doc.body_text or doc.title
    if cfg.gemini_api_key:
        doc.summary_en = summarize.summarize_en(base_text, doc.title)
    else:
        log.info("doc %s: GEMINI_API_KEY unset; skipping summary", doc.id)
    doc.embedding = summarize.embed(f"{doc.title}\n\n{doc.summary_en or base_text[:2000]}")


def match_and_notify(s, doc: Document, skip_notify: bool = False) -> None:
    if doc.embedding is None:
        return
    for user, sim in matching.candidates_for_document(s, doc):
        ledger = matching.gate_match(s, doc, user, sim)
        if ledger.tier == 1 and not skip_notify:
            notify.send_alert(s, doc, user, ledger)


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
                    parse_document(s, doc)
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
