# Demo video shot list (3:00, YouTube)

Covers the playbook's five beats: problem → solution → features → technical implementation → live demo.
Record at 1080p; UI shots from the deployed Render URL, not localhost.

| Time | Beat | Shot | Talking track |
|---|---|---|---|
| 0:00–0:30 | Problem | Slide 2 imagery / headlines | "In 2015, TRAI's net-neutrality consultation nearly passed unnoticed. Every month, rules that change farmers' insurance, small-business compliance and your data privacy open for public comment — and close before citizens hear about them. The comment boxes fill with lobbyists instead." |
| 0:30–1:00 | Solution + live demo | `/onboard` — type the farmer persona in one sentence, submit; cut to Telegram alert arriving on a real phone | "You tell JanAwaaz who you are, once. When a consultation genuinely affects you, your phone buzzes: what's proposed, what changes for you, days left, where to comment." |
| 1:00–1:45 | Features (vernacular) | Same alert in हिन्दी and मराठी; play 5s of the Sarvam voice alert audio | "Today, translating consultations is done by hand, for a handful of drafts, days after publication. Sarvam lets the agent do every one of them, in hours — text and voice." |
| 1:45–2:30 | Live demo (the money shot) | `/ledger/19`: farmer vs telecom paper — similarity bar passes, verifier verdict NO, Tier 3. Then `/ledger/21`: Tier 1 with the green string-verified quote | "Embedding similarity said this telecom paper matched a farmer. The gate killed it — and wrote down why. And when a match is real, the alert carries a quote from the document itself, string-checked. If we can't prove it, we don't wake you up. Nobody else in this space — at any price — shows their work." |
| 2:30–3:00 | Technical implementation + close | Render dashboard: workflow task chain, one retry recovering on a gov-site fetch, cron history. End card: repo + URL + bot handle | "The whole pipeline is durable Render Workflows — government sites fail; retries make that a dashboard entry, not an outage. It ran while we slept. That's the point. JanAwaaz — जन आवाज़." |

Pre-record checklist:
- [ ] Seeded corpus summarized (feed cards show summaries)
- [ ] Telegram bot live, test alert delivered to a real phone (screen-record the phone)
- [ ] Voice alert audio saved (VOICE_ALERTS=true, one send)
- [ ] Render dashboard: force one retry (temporarily break an adapter URL), screenshot
- [ ] Ledger IDs for the demo pairs confirmed (currently 19 = kill, 21/22 = Tier 1)
