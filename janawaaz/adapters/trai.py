"""TRAI adapter.

TRAI (trai.gov.in) runs Drupal. Two relevant listings share one row schema:
  - /open-consultation — currently-open consultations (empty when none are open)
  - /release-publication/consultation — full archive with an Open/Closed status field

Each row is an <li> with labelled field divs (.title-number, .release-date,
.division-section, .status-feild [sic — TRAI's own class name], .download-field)
plus a comments/detail link. The comment deadline is NOT on the listing — it is
extracted later from the consultation PDF.
"""

import logging
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from janawaaz.adapters.base import ConsultationRecord
from janawaaz.config import settings

log = logging.getLogger(__name__)

name = "trai"
base_url = "https://trai.gov.in"

LISTING_PATHS = ["/open-consultation", "/release-publication/consultation"]

# Preferred document to parse, in order.
_PDF_PREFERENCE = ["consultation paper", "draft", "extension"]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_release_date(raw: str) -> date | None:
    raw = _clean(raw)
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _field(li, css_class: str) -> str:
    el = li.select_one(f"div.{css_class} .field-content")
    return _clean(el.get_text(" ")) if el else ""


def parse_listing(html: str) -> list[ConsultationRecord]:
    """Parse a TRAI listing page (works for both open and archive listings)."""
    soup = BeautifulSoup(html, "lxml")
    records: list[ConsultationRecord] = []

    for li in soup.find_all("li"):
        title = _field(li, "title-number")
        if not title:
            continue  # not a consultation row

        status_raw = _field(li, "status-feild").lower()
        status = status_raw if status_raw in ("open", "closed") else "unknown"

        # Detail / comments page doubles as the stable external id and comment channel.
        detail_href = None
        comments_el = li.select_one("div.comment-field a[href]")
        if comments_el:
            detail_href = comments_el["href"]

        # Collect labelled PDFs from the nested documents block.
        pdfs: dict[str, str] = {}
        for block in li.select("div.download-field div.views-row"):
            label_el = block.select_one("span")
            link_el = block.select_one("a[href]")
            if not link_el:
                continue
            label = _clean(label_el.get_text(" ")) if label_el else "Document"
            href = link_el["href"]
            if href.lower().split("?")[0].endswith(".pdf"):
                pdfs.setdefault(label, href)

        body_url = None
        for pref in _PDF_PREFERENCE:
            for label, href in pdfs.items():
                if pref in label.lower():
                    body_url = href
                    break
            if body_url:
                break
        if body_url is None and pdfs:
            body_url = next(iter(pdfs.values()))
        if body_url is None:
            body_url = detail_href or ""

        external_id = (detail_href or body_url or title).strip("/") or title

        def absolute(u: str | None) -> str | None:
            if not u:
                return u
            return u if u.startswith("http") else f"{base_url}{u}"

        records.append(
            ConsultationRecord(
                source=name,
                external_id=external_id,
                title=title,
                body_url=absolute(body_url) or "",
                published_at=_parse_release_date(_field(li, "release-date")),
                comment_channel=absolute(detail_href),
                ministry=f"TRAI — {_field(li, 'division-section')}".rstrip(" —"),
                status=status,
                extra_urls={k: absolute(v) for k, v in pdfs.items()},
            )
        )
    return records


def fetch_records() -> list[ConsultationRecord]:
    cfg = settings()
    seen: dict[str, ConsultationRecord] = {}
    headers = {"User-Agent": cfg.user_agent}
    with httpx.Client(timeout=cfg.http_timeout_seconds, follow_redirects=True) as client:
        for path in LISTING_PATHS:
            url = f"{base_url}{path}"
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            page_records = parse_listing(resp.text)
            log.info("trai: %s rows from %s", len(page_records), url)
            for rec in page_records:
                seen.setdefault(rec.external_id, rec)
    return list(seen.values())
