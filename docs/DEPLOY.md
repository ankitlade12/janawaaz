# Deploying JanAwaaz to Render

Everything is blueprint-driven; the only manual step is the Workflow service
(early-access, not yet supported in blueprints).

## 0. Prerequisites

- Render account (free tier works for the demo)
- A Render **API key**: Dashboard → Account Settings → API Keys
- This repo pushed to GitHub (it is: `ankitlade12/janawaaz`)

## 1. Blueprint deploy (web + cron + Postgres)

Dashboard → **New → Blueprint** → pick `ankitlade12/janawaaz` → Render reads
`render.yaml` and provisions:

| Service | Plan | What it is |
|---|---|---|
| `janawaaz-web` | free | FastAPI product UI + API (`uvicorn janawaaz.web.app:app`) |
| `janawaaz-sweep-trigger` | starter (pennies) | Cron (every 6h) that starts the workflow root task. **Optional** — deselect it and use the free GitHub Actions scheduler instead (`.github/workflows/sweep-trigger.yml`; set repo secret `RENDER_API_KEY`). |
| `janawaaz-db` | free | Postgres 16 — pgvector is created by the app (`CREATE EXTENSION IF NOT EXISTS vector`) |

Set the `sync: false` env vars when prompted:

- `ANTHROPIC_API_KEY` (or `GEMINI_API_KEY`) — summaries + verifier
- `GEMINI_API_KEY` — embeddings (required for real matching; Claude has no embeddings API)
- `SARVAM_API_KEY` — alert translation / TTS
- `TELEGRAM_BOT_TOKEN` — push delivery
- `TELEGRAM_BOT_USERNAME` — bot username without `@`
- `TELEGRAM_WEBHOOK_SECRET` — random value also passed to Telegram as `secret_token`
- `APP_SECRET` — random signing secret for consent and profile-management links
- `RENDER_API_KEY` (on the cron service) — lets the trigger script start the workflow task

## 2. Workflow service (manual, one time)

Dashboard → **New → Workflow** (early access):

- Repo: `ankitlade12/janawaaz`, branch `main`
- Build: `pip install .`
- Start: `python main.py`
- Name it `janawaaz-workflows` (the cron's `SWEEP_TASK=janawaaz-workflows/sweep_sources` expects this)
- Env vars: same `DATABASE_URL` (from `janawaaz-db`) + the API keys above

Local validation of the same chain: `render workflows dev -- python main.py`
(Render CLI), or run the synchronous twin `python -m janawaaz.pipeline.runner`.

Connect the Telegram webhook after the web deploy:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://janawaaz-web.onrender.com/api/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

## 3. Seed the demo corpus (once, from your machine)

```bash
DATABASE_URL=<render-postgres-external-url> uv run python scripts/init_db.py
DATABASE_URL=<render-postgres-external-url> uv run python scripts/seed_corpus.py
```

## 4. Prove durability (demo asset)

Trigger a run (`python scripts/trigger_sweep.py` or the dashboard's Run button),
then screenshot: the task chain, one retry recovering from a failed government
fetch (kill wifi mid-fetch or point one adapter at a 500ing URL), and the cron
history. These go in the README and the 20-second durability segment of the video.
