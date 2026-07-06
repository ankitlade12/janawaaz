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
    log.info("rbi: %s consultation-shaped items across feeds", len(seen))
    return list(seen.values())
