# Your government asked for your opinion last month. Did you hear about it?

*Draft for Hashnode/Medium/Dev.to — HACKHAZARDS '26 bonus-points task. Publish under the team account, add screenshots of /feed and /ledger before posting.*

---

In 2015, TRAI published a 118-page consultation with the unassuming title "Regulatory Framework for OTT Services" — the paper that could have ended net neutrality in India. Its official comments table lists just 27 institutional submissions. What actually saved net neutrality was a viral AIB video and a volunteer team at savetheinternet.in who condensed those 118 pages into plain language people could act on; a million emails followed. Since then, hundreds of consultations — crop insurance rules, broadband tariffs, mutual-fund regulations — have opened and closed without their viral video, comment boxes filled almost entirely by industry. Not because citizens don't care. Because **nobody told them, in words they could use, that the window was open**.

We built [JanAwaaz](https://github.com/ankitlade12/janawaaz) (जन आवाज़, "people's voice") at HACKHAZARDS '26 to fix the discovery step: a durable agent that watches every consultation source, matches new papers to what *you* told it you care about, and pushes an alert in your language — with the deadline, a link to comment, and something no other tool at any price point offers: **proof**.

## The problem with "AI matched you to this"

Our first prototype did what every recommender does: embed the citizen's profile, embed the consultation, cosine similarity, threshold, notify. It fired garbage. *"I am a farmer interested in agriculture"* matched a telecom tariff paper — both mention "rural" a lot.

Embedding similarity is a candidate generator, not a decision-maker. So every match has to survive what we call **the gate**:

1. **Similarity** ≥ threshold gets you considered — never notified.
2. An **independent LLM verifier** answers a strict yes/no: *does this consultation materially affect a person matching this profile?*
3. The verifier must return a **verbatim quote from the document** as evidence — and we **string-check that span against the actual document text**. Paraphrase? Hallucinated quote? The match is demoted. No push.

Only Tier 1 — verified yes, with quotable, checkable evidence — wakes you up. Everything else lands in a feed or stays in the ledger.

## The ledger: every decision is auditable

Every gate decision — including every rejection — is an append-only row: similarity score, verdict, evidence span, span-check result, tier, timestamp. Our `/ledger/{id}` page renders it as a decision rail anyone can inspect.

When we ran the real verifier (Claude, with structured outputs so the verdict JSON is guaranteed valid) over our corpus, the farmer-vs-telecom false positive died exactly as designed — and the reasoning is right there in the ledger: *"The consultation concerns V2X vehicular telecom spectrum regulation, unrelated to the farmer's interests in crop insurance, subsidies, rural broadband, or water regulation."*

And a connected-vehicle founder matched the same paper at Tier 1, with this string-verified quote as evidence: *"License-exempt use of On-Board Units (OBUs) may be permitted under defined technical conditions."*

## Deadlines: honesty as a feature

A wrong deadline is worse than no alert. Extraction is regex-first over sentences that talk about submitting comments, and every extracted date carries its verbatim source sentence. Two real-world lessons from real TRAI PDFs:

- **Papers cite older consultations.** An April 2026 paper referenced a January 2023 comment window; without a published-date guard, that becomes your "deadline". Any candidate date on or before publication is discarded.
- **Comments and counter-comments close on different dates.** *"Written comments … by 28.05.2026 and counter-comments by 11.06.2026"* — the extractor prefers the comments date.

95 of the 100 real consultations we seeded extracted with span-verified deadlines. The other five say "deadline unverified — check source" rather than guessing.

## Durability is the product

Government websites fail in creative ways (MCA greeted our crawler with a 403 bot-wall; RBI's listing renders client-side). The pipeline is a chain of Render Workflows tasks — `sweep → fetch → parse → summarize/embed → match → gate → notify` — with per-task retry and backoff, so a flaky site is a dashboard entry, not an outage. Sources are one-file adapters behind a normalized record contract; TRAI and SEBI are live today.

The vernacular layer is Sarvam AI: every alert is machine-translated at send time (and optionally spoken, via TTS, for users who can't comfortably read it). Today, translating consultations is done by hand, for a handful of drafts, days after publication. The agent does all of them, in hours.

## What we'd tell you to steal

- **Gate your matcher.** Similarity proposes; verification disposes. Make the verifier prove its answer with evidence you can mechanically check.
- **Make every automated decision auditable.** The append-only ledger costs one table and buys you trust no black-box recommender can.
- **Treat uncertainty as UI.** "Deadline unverified — check source" is a feature, not a failure state.

JanAwaaz is MIT-licensed: [github.com/ankitlade12/janawaaz](https://github.com/ankitlade12/janawaaz). If we can't prove the match, we don't wake you up.
