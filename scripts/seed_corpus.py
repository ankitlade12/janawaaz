"""Seed the demo corpus with real historical consultations.

TRAI's /open-consultation is empty whenever no window is live, so the demo runs
on genuinely real, recently-closed papers: TRAI archive pages + SEBI consultation
papers. Everything goes through the exact same pipeline as a live sweep —
nothing is faked, the documents are simply not all currently open.

    uv run python scripts/seed_corpus.py --trai-pages 3 --sebi-limit 12
"""

import argparse
import logging

import httpx

from janawaaz.adapters import sebi, trai
from janawaaz.config import settings
from janawaaz.db import init_db, session
from janawaaz.pipeline import runner

log = logging.getLogger("janawaaz.seed")


def trai_archive_records(pages: int):
    cfg = settings()
    headers = {"User-Agent": cfg.user_agent}
    records = []
    with httpx.Client(timeout=cfg.http_timeout_seconds, follow_redirects=True) as client:
        for page in range(pages):
            url = f"{trai.base_url}/release-publication/consultation?page={page}"
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            rows = trai.parse_listing(resp.text)
            log.info("trai archive page %s: %s rows", page, len(rows))
            records.extend(rows)
    return records


def backfill() -> None:
    """Finish documents that were ingested but not fully processed."""
    from sqlalchemy import or_, select

    from janawaaz.models import Document
    from janawaaz.pipeline import summarize

    with session() as s:
        docs = s.execute(
            select(Document).where(
                or_(
                    Document.body_text.is_(None),
                    Document.embedding.is_(None),
                    Document.summary_en.is_(None),
                )
            )
        ).scalars().all()
        log.info("backfill: %s documents to finish", len(docs))
        for doc in docs:
            try:
                if doc.body_text is None:
                    runner.parse_document(s, doc)
                if doc.embedding is None:
                    runner.summarize_and_embed(s, doc)
                if (
                    doc.summary_en is None
                    and doc.body_text
                    and settings().llm_provider != "none"
                ):
                    doc.summary_en = summarize.summarize_en(doc.body_text, doc.title)
                    log.info("backfill: doc %s summarized", doc.id)
                s.commit()  # keep progress if a later doc fails
            except Exception:
                log.exception("backfill: doc %s failed; continuing", doc.id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Seed demo corpus from real consultations")
    ap.add_argument("--trai-pages", type=int, default=3)
    ap.add_argument("--sebi-limit", type=int, default=12)
    ap.add_argument("--skip-parse", action="store_true", help="ingest listings only")
    ap.add_argument(
        "--backfill", action="store_true",
        help="re-parse already-ingested docs that are missing text or embeddings",
    )
    args = ap.parse_args()

    init_db()
    if args.backfill:
        backfill()
        return
    ingested = 0
    with session() as s:
        batches = [
            ("trai", trai_archive_records(args.trai_pages)),
            ("sebi", sebi.fetch_records(limit=args.sebi_limit)),
        ]
        for adapter_name, records in batches:
            src = runner.upsert_source(s, adapter_name)
            for rec in records:
                doc = runner.ingest_record(s, src, rec)
                if doc is None:
                    continue
                ingested += 1
                if args.skip_parse:
                    continue
                try:
                    runner.parse_document(s, doc)
                    runner.summarize_and_embed(s, doc)
                except Exception:
                    log.exception("seed: doc %s failed; continuing", doc.id)
    log.info("seeded %s new documents", ingested)


if __name__ == "__main__":
    main()
