"""Render Workflows task chain — the durable version of the pipeline.

Deployed as a Render Workflow service (start command: `python main.py`).
Render Cron triggers the root task via the API (see scripts/trigger_sweep.py),
since Workflows has no native scheduler yet.

Each task is small and idempotent; per-task Retry handles flaky government sites
(the retry recovering from a failed fetch is a demo point — visible in the
Render dashboard run history).
"""

import logging

from render_sdk import Retry, Workflows

from janawaaz.adapters import REGISTRY
from janawaaz.db import init_db, session
from janawaaz.models import Document
from janawaaz.pipeline import runner

log = logging.getLogger("janawaaz.workflows")

app = Workflows(
    default_retry=Retry(max_retries=3, wait_duration_ms=2000, backoff_scaling=2.0),
    default_timeout=600,
)


@app.task
async def sweep_sources() -> dict:
    """Root task: fan out one fetch_source per registered adapter."""
    init_db()
    totals = {"sources": 0, "new_documents": 0}
    for adapter_name in REGISTRY:
        result = await fetch_source(adapter_name)
        totals["sources"] += 1
        totals["new_documents"] += result["new_documents"]
    return totals


@app.task(retry=Retry(max_retries=5, wait_duration_ms=3000, backoff_scaling=2.0))
async def fetch_source(adapter_name: str) -> dict:
    """Pull one source listing, diff against known documents, chain per-doc tasks."""
    from datetime import datetime, timezone

    adapter = REGISTRY[adapter_name]
    new_ids: list[int] = []
    with session() as s:
        src = runner.upsert_source(s, adapter_name)
        for rec in adapter.fetch_records():
            doc = runner.ingest_record(s, src, rec)
            if doc is not None:
                new_ids.append(doc.id)
        src.last_swept_at = datetime.now(timezone.utc)
    for doc_id in new_ids:
        await parse_document(doc_id)
    return {"source": adapter_name, "new_documents": len(new_ids)}


@app.task(retry=Retry(max_retries=4, wait_duration_ms=5000, backoff_scaling=2.0))
async def parse_document(doc_id: int) -> dict:
    with session() as s:
        doc = s.get(Document, doc_id)
        runner.parse_document(s, doc)
    await summarize_and_embed(doc_id)
    return {"doc_id": doc_id}


@app.task
async def summarize_and_embed(doc_id: int) -> dict:
    with session() as s:
        doc = s.get(Document, doc_id)
        runner.summarize_and_embed(s, doc)
    await match_users(doc_id)
    return {"doc_id": doc_id}


@app.task
async def match_users(doc_id: int) -> dict:
    """Similarity candidates -> gate -> Tier 1 alerts (gate + notify in one txn)."""
    with session() as s:
        doc = s.get(Document, doc_id)
        runner.match_and_notify(s, doc)
    return {"doc_id": doc_id}
