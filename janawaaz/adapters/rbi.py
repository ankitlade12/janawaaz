"""RBI adapter.

RBI's modern listing pages are JS-rendered, but the bank still publishes
server-side RSS 2.0 feeds. We watch the notifications and press-release feeds
and keep items whose titles signal a draft/consultation inviting comments.

Quiet weeks legitimately return zero records — that is what watching looks
like. Detail pages are HTML (handled by the shared HTML text extractor);
comment deadlines come from the body like every other source.
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime

import httpx

from janawaaz.adapters.base import ConsultationRecord
from janawaaz.config import settings

log = logging.getLogger(__name__)

name = "rbi"
base_url = "https://rbi.org.in"

FEEDS = ["/notifications_rss.xml", "/pressreleases_rss.xml"]
# "Draft Directions (RE-wise)" — RBI's Connect 2 Regulate consultation stream.
# Server-rendered (unlike the JS-walled draft-notifications page) and rich:
# every row carries the draft title, a PDF, and the Connect 2 Regulate detail
# page where comments are submitted.
DRAFTS_URL = f"{base_url}/Scripts/BS_ViewREwiseDraftDirections.aspx"
DRAFTS_LIMIT = 12

_DATE_HEADER = re.compile(r"<b>\s*([A-Z][a-z]{2} \d{1,2}, \d{4})\s*</b>")
_CATEGORY_HEADER = re.compile(r'class="tableheader"[^>]*>\s*<b>\s*([^<]{3,60})\s*</b>')
_ITEM_ROW = re.compile(
    r'href=\s*"?BS_ViewREwiseDraftDirections\.aspx\?id=(\d+)"?\s*>\s*([^<]+?)\s*<a\s+'
    r'href="\s*(https://www\.rbi\.org\.in/scripts/Bs_Connect2RegulateDetails\.aspx\?prid=\d+)"',
    re.IGNORECASE,
)
_PDF_LINK = re.compile(r'href="(https?://rbidocs\.rbi\.org\.in/[^"]+\.PDF)"', re.IGNORECASE)

# Titles that signal an open invitation for public input.
CONSULTATION_TITLE = re.compile(
    r"draft|comments?\s+(?:are\s+)?invited|consultation|discussion\s+paper|"
    r"seeking\s+(?:public\s+)?(?:comments?|feedback)",
    re.IGNORECASE,
)


def _parse_pubdate(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S", "%a, %d %b %Y %H:%M"):
        try:
            return datetime.strptime(raw.strip()[:31].rsplit(" GMT", 1)[0].rstrip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_feed(xml_text: str) -> list[ConsultationRecord]:
    """RSS items -> normalized records, keeping only consultation-shaped titles."""
    records: list[ConsultationRecord] = []
    try:
        root = ET.fromstring(xml_text.lstrip("﻿"))
    except ET.ParseError as exc:
        log.warning("rbi: feed parse error: %s", exc)
        return records

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link or not CONSULTATION_TITLE.search(title):
            continue
        records.append(
            ConsultationRecord(
                source=name,
                external_id=link.rstrip("/").rsplit("=", 1)[-1] or link,
                title=title,
                body_url=link,
                published_at=_parse_pubdate(item.findtext("pubDate")),
                comment_channel=link,
                ministry="RBI",
                status="open",
            )
        )
    return records


def parse_draft_listing(html: str, limit: int = DRAFTS_LIMIT) -> list[ConsultationRecord]:
    """Row-walk the Draft Directions table: date/category headers apply to the
    item rows that follow them."""
    records: list[ConsultationRecord] = []
    current_date: date | None = None
    current_category = "RBI"
    for row in re.split(r"<tr", html):
        dm = _DATE_HEADER.search(row)
        if dm:
            try:
                current_date = datetime.strptime(dm.group(1), "%b %d, %Y").date()
            except ValueError:
                pass
            continue
        cm = _CATEGORY_HEADER.search(row)
        if cm and not dm:
            current_category = cm.group(1).strip()
            continue
        im = _ITEM_ROW.search(row)
        if not im:
            continue
        item_id, title, c2r_link = im.group(1), im.group(2).strip(), im.group(3)
        pdf = _PDF_LINK.search(row)
        records.append(
            ConsultationRecord(
                source=name,
                external_id=f"rbi-draft-{item_id}",
                title=title,
                body_url=pdf.group(1) if pdf else c2r_link,
                published_at=current_date,
                comment_channel=c2r_link,
                ministry=f"RBI — {current_category}",
                status="open",
            )
        )
    records.sort(key=lambda r: r.published_at or date.min, reverse=True)
    return records[:limit]


def fetch_records() -> list[ConsultationRecord]:
    cfg = settings()
    headers = {"User-Agent": cfg.user_agent}
    seen: dict[str, ConsultationRecord] = {}
    with httpx.Client(timeout=cfg.http_timeout_seconds, follow_redirects=True) as client:
        for path in FEEDS:
            resp = client.get(f"{base_url}{path}", headers=headers)
            resp.raise_for_status()
            for rec in parse_feed(resp.text):
                seen.setdefault(rec.external_id, rec)
        try:
            resp = client.get(DRAFTS_URL, headers=headers)
            resp.raise_for_status()
            for rec in parse_draft_listing(resp.text):
                seen.setdefault(rec.external_id, rec)
        except httpx.HTTPError as exc:
            log.warning("rbi: drafts listing failed (%s); feeds-only this sweep", exc)
    log.info("rbi: %s consultation-shaped items across feeds + drafts", len(seen))
    return list(seen.values())
