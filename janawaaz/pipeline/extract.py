"""Document text + comment-deadline extraction.

Deadline strategy (a wrong deadline is worse than no alert):
  1. Regex-first over sentences that talk about submitting comments.
  2. LLM fallback (Day 5) must return a verbatim span; the span is string-checked
     against the document text before the date is trusted.
  3. No verifiable span -> deadline stays None and alerts say "deadline unverified,
     check source" rather than inventing a date.

Every extracted deadline carries its evidence: the exact substring of the document
it came from (`span`), which the ledger and alert render verbatim.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)

# 15/07/2026, 15-07-2026, 15.07.2026
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
# 15th July, 2026 / 5 August 2026
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:\s*(?:st|nd|rd|th))?\s+({MONTHS})[a-z]*\.?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
# July 15, 2026
_MONTH_DAY = re.compile(
    rf"\b({MONTHS})[a-z]*\.?\s+(\d{{1,2}})(?:\s*(?:st|nd|rd|th))?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)

_MONTH_INDEX = {m: i + 1 for i, m in enumerate(MONTHS.split("|"))}

# A sentence is deadline-bearing if it mentions submitting input AND a bounding phrase.
_SUBJECT = re.compile(
    r"comments?|counter[\s-]?comments?|suggestions?|views|inputs?|feedback|responses?|objections?",
    re.IGNORECASE,
)
_BOUND = re.compile(
    r"on or before|not later than|latest by|last date|by|before|till|until|upto|up to",
    re.IGNORECASE,
)
_COUNTER = re.compile(r"counter[\s-]?comments?", re.IGNORECASE)


@dataclass
class DeadlineResult:
    deadline: date | None
    span: str | None  # verbatim substring of the source text
    method: str  # "regex" | "llm" | "none"
    verified: bool  # span confirmed to appear verbatim in the text


def pdf_text(data: bytes) -> str:
    """Extract text from a PDF using pymupdf."""
    import fitz

    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def _parse_date_match(m: re.Match, pattern: re.Pattern) -> date | None:
    try:
        if pattern is _NUMERIC_DATE:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif pattern is _DAY_MONTH:
            d, mo, y = int(m.group(1)), _MONTH_INDEX[m.group(2).lower()[:20]], int(m.group(3))
        else:  # _MONTH_DAY
            d, mo, y = int(m.group(2)), _MONTH_INDEX[m.group(1).lower()[:20]], int(m.group(3))
        return date(y, mo, d)
    except (ValueError, KeyError):
        return None


def _dates_in(text: str) -> list[tuple[date, re.Match]]:
    found = []
    for pattern in (_NUMERIC_DATE, _DAY_MONTH, _MONTH_DAY):
        for m in pattern.finditer(text):
            parsed = _parse_date_match(m, pattern)
            if parsed:
                found.append((parsed, m))
    return found


def _sentences(text: str) -> list[str]:
    # PDF text is noisy; split on sentence enders and hard newlines, keep fragments sizable.
    rough = re.split(r"(?<=[.;])\s+|\n{2,}", text)
    return [s.strip() for s in rough if len(s.strip()) >= 20]


def extract_deadline(text: str, published_after: date | None = None) -> DeadlineResult:
    """Regex-first comment-deadline extraction with verbatim evidence spans.

    `published_after`: consultation papers cite years of older documents; any
    candidate date on or before the publication date is a historical reference,
    not a comment window, and is discarded.
    """
    plain_hits: list[tuple[date, str]] = []
    counter_hits: list[tuple[date, str]] = []

    for sentence in _sentences(text):
        if not (_SUBJECT.search(sentence) and _BOUND.search(sentence)):
            continue
        dates = [
            (d, m) for d, m in _dates_in(sentence)
            if published_after is None or d > published_after
        ]
        if not dates:
            continue
        # A sentence may carry both comment and counter-comment dates; take the
        # earliest date in comment sentences (comments close first in TRAI practice).
        best = min(d for d, _ in dates)
        # span must be recoverable from the original text for verification
        bucket = counter_hits if _COUNTER.search(sentence) and "comment" not in _strip_counter(sentence).lower() else plain_hits
        bucket.append((best, sentence.strip()))

    hits = plain_hits or counter_hits
    if not hits:
        return DeadlineResult(None, None, "none", False)

    # Prefer the earliest upcoming-style mention; ties broken by first occurrence.
    deadline, span = min(hits, key=lambda t: t[0])
    verified = span in text
    return DeadlineResult(deadline, span, "regex", verified)


def _strip_counter(sentence: str) -> str:
    return _COUNTER.sub("", sentence)
