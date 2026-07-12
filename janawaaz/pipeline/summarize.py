"""English summary + embeddings.

Embeddings: Gemini text-embedding-004 (768-dim, matches vector(768) in the schema).
`EMBEDDINGS_PROVIDER=dev` switches to a deterministic offline embedder so the whole
pipeline can run end-to-end without API keys during development — never in demos
that claim semantic matching.
"""

import hashlib
import logging
import math
import re

from janawaaz.config import EMBEDDING_DIM, settings

log = logging.getLogger(__name__)

SUMMARY_PROMPT = """You summarize Indian government consultation papers for ordinary citizens.

Write a plain-English summary of at most 150 words as ONE flowing paragraph covering:
what is being proposed, who is affected and what changes for them, and why it
matters now.

Plain prose only — no markdown, no asterisks, no headings, no bullet points,
no preamble like "Summary:". No jargon; expand acronyms on first use.

Text of the consultation:

{text}"""

_FAILED_SUMMARY_MARKERS = (
    "can't summarize",
    "cannot summarize",
    "unable to summarize",
    "could not be summarized",
    "does not actually contain",
    "doesn't actually contain",
    "security check",
    "captcha",
)


def _clean_summary(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in _FAILED_SUMMARY_MARKERS):
        log.warning("discarding model response that describes missing/challenge content")
        return ""
    # Models occasionally ignore the one-paragraph instruction. Normalize the
    # stored result so web cards, translations and Telegram alerts stay clean.
    value = re.sub(r"\*\*(.+?)\*\*", r"\1", value)
    value = re.sub(r"^#+\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"\(?word count:\s*\d+\)?", "", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _gemini_client():
    from google import genai

    key = settings().gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    return genai.Client(api_key=key)


def summarize_en(text: str, title: str) -> str:
    """LLM plain-English summary. Tries Claude first, fails over to Gemini —
    a dead key or exhausted credit balance must degrade, not halt, the sweep."""
    cfg = settings()
    prompt = SUMMARY_PROMPT.format(text=f"TITLE: {title}\n\n{text[:60000]}")

    if cfg.llm_provider == "claude":
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
            resp = client.messages.create(
                model=cfg.claude_model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            if resp.stop_reason == "refusal":
                log.warning("claude declined summary for %r", title[:60])
                return ""
            return _clean_summary("".join(b.text for b in resp.content if b.type == "text"))
        except Exception as exc:
            if not cfg.gemini_api_key:
                raise
            log.warning("claude summary failed (%s); falling back to gemini", exc)

    client = _gemini_client()
    resp = client.models.generate_content(model=cfg.gemini_model, contents=prompt)
    return _clean_summary(resp.text or "")


def embed(text: str) -> list[float]:
    return embed_many([text])[0]


def embed_many(texts: list[str]) -> list[list[float]]:
    """Batch embeddings — one API call per chunk keeps free-tier rate limits happy.

    Model: gemini-embedding-001 truncated to 768 dims (matches vector(768));
    truncated vectors are re-normalized per Google's guidance.
    """
    provider = settings().embeddings_provider
    if provider == "dev":
        return [_dev_embedding(t) for t in texts]

    import time

    from google.genai import errors as genai_errors
    from google.genai import types

    client = _gemini_client()
    out: list[list[float]] = []
    for i in range(0, len(texts), 20):
        chunk = [t[:9000] for t in texts[i : i + 20]]
        for attempt in range(6):
            try:
                resp = client.models.embed_content(
                    model="gemini-embedding-001",
                    contents=chunk,
                    config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
                )
                break
            except genai_errors.ClientError as exc:
                # free tier: 100 embed units/minute — wait out the window and retry
                if exc.code == 429 and attempt < 5:
                    log.info("embedding rate limit; sleeping 30s (attempt %s)", attempt + 1)
                    time.sleep(30)
                    continue
                raise
        for e in resp.embeddings:
            v = list(e.values)
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
    return out


def _dev_embedding(text: str) -> list[float]:
    """Deterministic hashing-trick bag-of-words embedding. DEV ONLY.

    Good enough to exercise storage, cosine queries, and the gate locally without
    API keys. Not semantically meaningful — never use for demo claims.
    """
    vec = [0.0] * EMBEDDING_DIM
    for token in re.findall(r"[a-z]{3,}", text.lower()):
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % EMBEDDING_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]
