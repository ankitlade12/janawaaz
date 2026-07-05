# JanAwaaz — deck outline (export to PPT/PDF for submission)

One slide per heading. Keep each slide to the bold line + 3 bullets max.
The playbook scores "Documentation & Presentation" — this is that artifact.

## 1. Title
**JanAwaaz (जन आवाज़) — the agent that tells you when your government is asking.**
With proof. In your language. Before the window closes.
HACKHAZARDS '26 · Render Workflows · Sarvam AI · Public Systems & Civic Tech

## 2. The problem — discovery is broken, not access
**Rules that change your life open for public comment — and close before you hear about them.**
- India's 2014 pre-legislative policy mandates 30-day comment windows; TRAI/SEBI/RBI run continuous streams
- In 2015 the net-neutrality consultation nearly passed unnoticed; the ones since mostly have
- Comment boxes fill with lobbyists because citizens never learn the window existed

## 3. What we built
**A durable agent that watches, matches, verifies, and speaks your language.**
- Tell it who you are once, in one plain sentence
- It sweeps every source daily, extracts deadlines with quoted evidence, matches semantically
- Tier-1 verified matches push to Telegram in English / हिन्दी / मराठी — with the deadline and where to comment

## 4. The gate — every alert shows its work (demo: /ledger)
**If we can't prove the match, we don't wake you up.**
- Tier 1 = similarity + independent verifier "yes" + verbatim span string-checked against the document
- Weak evidence → feed only; rejected → ledger only; every decision immutable and auditable
- Live example: farmer profile vs telecom paper — similarity passed, verifier killed it, span check visible

## 5. Deadline honesty
**A wrong deadline is worse than no alert.**
- Regex-first extraction, every date carries a verbatim quoted span from the PDF
- Historical-reference guard (papers cite years of older consultations)
- Unverifiable → alert says "deadline unverified — check source", never a guess
- 95/100 seeded real documents extracted with verified spans

## 6. Architecture (diagram from README)
**Render Workflows is the spine, not a checkbox.**
- Cron → sweep_sources → fetch (retries survive flaky gov sites) → parse → summarize+embed → match → gate → notify
- Render Postgres + pgvector; FastAPI product UI on Render
- Adding a source = one file (adapter contract); TRAI + SEBI live today

## 7. Vernacular at scale — Sarvam
**Civis translates by hand, for a few drafts, days later. The agent does all of them, in hours.**
- Every alert machine-translated at send time (Mayura)
- Optional voice alerts (Bulbul TTS → Telegram audio) for low-literacy users
- Languages are a config line, not a fellowship cohort

## 8. Who else is in this space
**Nobody — at any price — shows why you got the alert with cited spans.**
- Civis: proved demand, human-powered pipeline; OurGov/MyGov: portals you must visit
- GovTrack (US): keyword email; enterprise reg-intel: five figures/year, English-only
- The unclaimed intersection: automated + personalized + verified + vernacular + push + free

## 9. Honest limitations & roadmap
**Two sources today; three well-documented no-gos.**
- MCA bot-walled, RBI listing JS-rendered — adapter candidates via other entry points
- Roadmap: RBI/MeitY/state governments, WhatsApp channel, comment-drafting help
- Civis-style partners could run on top of the ledger as an API

## 10. Close
**It ran while we slept. That's the point.**
- github.com/ankitlade12/janawaaz (MIT) · live demo URL · @JanAwaazBot
