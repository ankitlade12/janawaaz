"""Adapter contract.

Every source adapter returns the same normalized record, so adding a source is
one file: implement `fetch_records()` and register it in `janawaaz.adapters.REGISTRY`.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass
class ConsultationRecord:
    source: str  # registry key, e.g. "trai"
    external_id: str  # stable id within the source (slug, doc number, ...)
    title: str
    body_url: str  # the document we parse (PDF preferred) or detail page
    published_at: date | None = None
    deadline: date | None = None  # rarely on listings; usually extracted from the PDF
    comment_channel: str | None = None  # where a citizen actually submits comments
    ministry: str | None = None  # ministry / regulator / division label
    status: str = "unknown"  # open | closed | unknown
    extra_urls: dict[str, str] = field(default_factory=dict)  # label -> url


class Adapter(Protocol):
    name: str
    base_url: str

    def fetch_records(self) -> list[ConsultationRecord]:
        """Fetch the live listing(s) and return normalized records."""
        ...
