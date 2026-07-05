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

Write a plain-English summary of at most 150 words structured as:
1) What is being proposed (1-2 sentences).
2) Who is affected and what changes for them ("what changes for whom").
3) Why it matters now.

No jargon, no acronyms without expansion, no preamble. Text of the consultation:

{text}"""


def _gemini_client():
    from google import genai

    key = settings().gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY not configured")
    return genai.Client(api_key=key)


def summarize_en(text: str, title: str) -> str:
    """LLM plain-English summary, routed to whichever provider has a key."""
    cfg = settings()
    prompt = SUMMARY_PROMPT.format(text=f"TITLE: {title}\n\n{text[:60000]}")

    if cfg.llm_provider == "claude":
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
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    client = _gemini_client()
    resp = client.models.generate_content(model=cfg.gemini_model, contents=prompt)
    return (resp.text or "").strip()


def embed(text: str) -> list[float]:
    provider = settings().embeddings_provider
    if provider == "dev":
        return _dev_embedding(text)
    client = _gemini_client()
    resp = client.models.embed_content(model="text-embedding-004", contents=text[:9000])
    return list(resp.embeddings[0].values)


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
