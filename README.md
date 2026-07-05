# JanAwaaz (जन आवाज़ — "people's voice")

> The agent that tells you when your government is asking for your opinion — with proof, in your own language, before the window closes.

**HACKHAZARDS '26 submission** · Tracks: Render Workflows, Sarvam AI · Theme: Public Systems, Governance & Civic Tech

India's Pre-Legislative Consultation Policy (2014) requires ministries to publish draft bills for 30 days of public comment, and regulators like TRAI run continuous consultation streams. In practice the comment boxes fill with industry stakeholders, because ordinary citizens never learn a consultation exists until it has closed. **Discovery is the broken step, not access.** JanAwaaz is a durable agent that watches every source, matches consultations to what you told it you care about, verifies each match against the source document, and pushes an alert in your language with the deadline and a link to comment.

## How it works

```
Render Cron ──▶ sweep_sources (root task, Render Workflows)
                   ├─▶ fetch_source(trai) ─ retries survive flaky gov sites
                   ├─▶ parse_document ─ PDF text + comment-deadline extraction
                   │      (regex-first, LLM fallback; every deadline carries a
                   │       verbatim evidence span, string-checked against the doc)
                   ├─▶ summarize_and_embed ─ 150-word plain-English summary
                   │      (Gemini) + text-embedding-004 vector → pgvector
                   ├─▶ match_users ─ cosine similarity vs. every citizen profile
                   ├─▶ gate_match ─ THE DETERMINISTIC GATE (below)
                   └─▶ translate_and_notify ─ Sarvam translation → Telegram push
```

### The gate

Embedding similarity alone fires garbage ("interested in agriculture" matches a telecom tariff paper because both say "rural"). Every candidate match passes a deterministic gate:

- **Tier 1 — Confirmed:** similarity ≥ threshold **and** an LLM verifier answers a strict yes/no **and** returns a verbatim span from the document as evidence, string-checked against the actual text. Only Tier 1 wakes you up.
- **Tier 2 — Possible:** similarity passes but verification is weak → dashboard feed only.
- **Tier 3 — Rejected:** below threshold or verifier says no → ledger only.

Every decision is written to an immutable **match ledger** (similarity score, verdict, evidence span, span-check result, tier) and rendered at `/ledger/{id}` — every alert shows its work.

## Status

Day 1 of a 9-day build (July 4–12, 2026). Working today: TRAI adapter (live listing → normalized records), deadline extraction with evidence spans, schema + gate + pipeline running locally end-to-end. See commits for progress.

## Run it locally

```bash
docker compose up -d          # Postgres 16 + pgvector on :5433
cp .env.example .env          # add GEMINI_API_KEY (or EMBEDDINGS_PROVIDER=dev to run keyless)
uv sync
uv run python scripts/init_db.py
uv run python -m janawaaz.pipeline.runner --limit 5   # sweep → parse → match → gate
uv run uvicorn janawaaz.web.app:app --reload          # POST /users, GET /feed, GET /ledger/{id}
```

## Sponsor tech

- **Render**: the pipeline is a Render **Workflows** service (`render_sdk`, `@app.task`, per-task retries) triggered by Render Cron; Render Postgres with pgvector; FastAPI web service on Render. Task-chain and retry screenshots in `docs/` (Day 7).
- **Sarvam AI**: every alert is translated into the citizen's language (Hindi/Marathi at launch) via the Sarvam API — automatically, for every consultation, not a hand-picked subset.

## Who else is in this space

Civis (civis.vote) proved the demand for plain-language consultation summaries — with fellows, interns, and manual deadline tracking. OurGov.in aggregates open laws; MyGov hosts some consultations; Congress.gov/GovTrack offer keyword email alerts (US); enterprise regulatory-intelligence suites (Compliance.ai, FiscalNote) do automated monitoring at enterprise prices, in English. Nobody — at any price — shows *why* you got an alert with cited spans from the source document. That verification layer is JanAwaaz's contribution; everything else here exists so a farmer gets it for free, in her language, without asking.

## License

MIT
