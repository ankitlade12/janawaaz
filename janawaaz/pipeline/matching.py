"""Candidate matching + the deterministic gate.

Tier logic:
  Tier 1 (Confirmed) - similarity >= threshold AND the LLM verifier says yes AND
                       the verifier's evidence span appears verbatim in the document
                       text. Only Tier 1 triggers a push alert.
  Tier 2 (Possible)  - similarity passes but verification is weak (verifier
                       unavailable, indirect answer, or span fails the string check).
                       Feed only, no push.
  Tier 3 (Rejected)  - below threshold, or verifier says no.

Every decision — including rejections — is written to the immutable match_ledger.
"""

import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select

from janawaaz.config import settings
from janawaaz.models import Document, MatchLedger, User

log = logging.getLogger(__name__)

VERIFIER_PROMPT = """You are a strict verifier for a civic-alert system. A citizen described their situation; a government consultation paper was matched to them by embedding similarity. Your job is to kill false positives.

CITIZEN PROFILE:
{profile}

CONSULTATION (title + summary + excerpt):
{doc}

Answer in strict JSON, nothing else:
{{"affects": "yes" or "no",
  "reason": "one sentence",
  "evidence_span": "an EXACT verbatim quote (<=40 words) copied character-for-character from the consultation text above that shows the material effect, or empty string"}}

Rules: "yes" only if the consultation materially affects a person matching this profile. The evidence_span MUST be copied exactly from the text — do not paraphrase."""


@dataclass
class Verdict:
    verdict: str  # yes | no | skipped
    reason: str
    span: str | None
    span_verified: bool


def candidates_for_document(session, doc: Document) -> list[tuple[User, float]]:
    """All users with similarity to this document, best first (pgvector cosine)."""
    sim = (1 - User.embedding.cosine_distance(doc.embedding)).label("sim")
    rows = session.execute(
        select(User, sim).where(User.embedding.is_not(None)).order_by(sim.desc())
    ).all()
    return [(u, float(s)) for u, s in rows]


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def span_in_text(span: str, text: str) -> bool:
    """Strict-but-fair span check: exact, else whitespace-normalized containment."""
    if not span:
        return False
    if span in text:
        return True
    return _normalize(span) in _normalize(text)


# Structured-output schema for the Claude verifier: the API guarantees the
# response is valid JSON matching this shape, so no fence-stripping is needed.
VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "affects": {"type": "string", "enum": ["yes", "no"]},
        "reason": {"type": "string"},
        "evidence_span": {"type": "string"},
    },
    "required": ["affects", "reason", "evidence_span"],
    "additionalProperties": False,
}


def _verifier_raw(profile: str, doc_blob: str) -> dict:
    """One verifier call -> parsed dict, routed by provider."""
    cfg = settings()
    prompt = VERIFIER_PROMPT.format(profile=profile, doc=doc_blob)

    if cfg.llm_provider == "claude":
        import anthropic

        client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        resp = client.messages.create(
            model=cfg.claude_model,
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": VERIFIER_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError("verifier request declined")
        raw = next(b.text for b in resp.content if b.type == "text")
        return json.loads(raw)

    from google import genai

    client = genai.Client(api_key=cfg.gemini_api_key)
    resp = client.models.generate_content(model=cfg.gemini_model, contents=prompt)
    raw = (resp.text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    return json.loads(raw)


def verify_match(profile: str, doc_title: str, doc_summary: str, doc_text: str) -> Verdict:
    cfg = settings()
    if cfg.llm_provider == "none":
        return Verdict("skipped", "verifier not configured", None, False)

    doc_blob = f"TITLE: {doc_title}\n\nSUMMARY: {doc_summary}\n\nEXCERPT:\n{doc_text[:20000]}"
    try:
        data = _verifier_raw(profile, doc_blob)
    except Exception as exc:  # malformed output or API failure -> weak verification
        log.warning("verifier failed: %s", exc)
        return Verdict("skipped", f"verifier error: {exc}", None, False)

    span = (data.get("evidence_span") or "").strip()
    verdict = "yes" if str(data.get("affects", "")).lower() == "yes" else "no"
    verified = span_in_text(span, doc_text) if span else False
    return Verdict(verdict, str(data.get("reason", "")), span or None, verified)


def gate_match(session, doc: Document, user: User, similarity: float) -> MatchLedger:
    """Apply the gate to one (document, user) candidate and write the ledger row."""
    cfg = settings()

    if similarity < cfg.similarity_threshold:
        tier, verdict = 3, Verdict("skipped", "below similarity threshold", None, False)
    else:
        verdict = verify_match(
            user.interests_text, doc.title, doc.summary_en or "", doc.body_text or ""
        )
        if verdict.verdict == "yes" and verdict.span_verified:
            tier = 1
        elif verdict.verdict == "no":
            tier = 3
        else:
            # yes-without-verifiable-span, or verifier unavailable -> demote, never promote
            tier = 2

    row = MatchLedger(
        document_id=doc.id,
        user_id=user.id,
        similarity=round(similarity, 4),
        verifier_verdict=verdict.verdict,
        verifier_reason=verdict.reason,
        evidence_span=verdict.span,
        span_verified=verdict.span_verified,
        tier=tier,
    )
    session.add(row)
    session.flush()
    log.info(
        "gate: doc=%s user=%s sim=%.3f verdict=%s span_ok=%s -> tier %s",
        doc.id, user.id, similarity, verdict.verdict, verdict.span_verified, tier,
    )
    return row
