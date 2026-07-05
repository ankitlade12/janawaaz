"""SEBI adapter.

SEBI consultation papers live at
  /reports-and-statistics/reports/<mon-yyyy>/consultation-paper-..._<id>.html

Discovery uses SEBI's own sitemap.xml (server-provided, stable) rather than the
JS-driven listing UI — a production system prefers the feed that cannot
restructure under it. Detail pages carry the title (h1), the publish date, and
the actual paper PDF under sebi_data/attachdocs/. Comment deadlines are inside
the PDFs and handled by the shared extractor.
"""

import logging
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from janawaaz.adapters.base import ConsultationRecord
from janawaaz.config import settings

log = logging.getLogger(__name__)

name = "sebi"
base_url = "https://www.sebi.gov.in"

SITEMAP_URL = f"{base_url}/sitemap.xml"
DEFAULT_LIMIT = 12

_CONSULTATION_PATH = re.compile(
    r"/reports-and-statistics/reports/([a-z]{3})-(\d{4})/[^/]*consultation[^/]*_(\d+)\.html$"
)
_ATTACH_PDF = re.compile(r"(https://www\.sebi\.gov\.in/sebi_data/attachdocs/[^\"'#]+\.pdf)")
_PAGE_DATE = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})")
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}


def consultation_urls(sitemap_xml: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """Filter sitemap <loc> entries down to consultation papers, newest first."""
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap_xml)
    hits = []
    for loc in locs:
        m = _CONSULTATION_PATH.search(loc)
        if m:
            mon, year, ext_id = m.group(1), int(m.group(2)), m.group(3)
            hits.append(((year, _MONTHS.get(mon, 0), int(ext_id)), loc))
    hits.sort(reverse=True)
    return [loc for _, loc in hits[:limit]]


def external_id_of(url: str) -> str:
    m = _CONSULTATION_PATH.search(url)
    return f"sebi-{m.group(3)}" if m else url.rstrip("/").rsplit("/", 1)[-1]


def parse_detail(html: str, url: str) -> ConsultationRecord | None:
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    title = re.sub(r"\s+", " ", h1.get_text(" ")).strip() if h1 else ""
    # SEBI appends UI chrome like "[Click here to see rationale ...]" to some titles
    title = re.sub(r"\s*\[Click here[^\]]*\]\s*", " ", title, flags=re.IGNORECASE).strip()
    if not title:
        return None

    published = None
    m = _PAGE_DATE.search(html)
    if m:
        try:
            published = datetime.strptime(" ".join(m.groups()), "%b %d %Y").date()
        except ValueError:
            published = None
    if published is None:
        pm = _CONSULTATION_PATH.search(url)
        if pm:
            published = date(int(pm.group(2)), _MONTHS.get(pm.group(1), 1), 1)

    pdf = None
    pdf_match = _ATTACH_PDF.search(html)
    if pdf_match:
        pdf = pdf_match.group(1)

    return ConsultationRecord(
        source=name,
        external_id=external_id_of(url),
        title=title,
        body_url=pdf or url,
        published_at=published,
        comment_channel=url,  # SEBI takes comments via the paper's page / email in the PDF
        ministry="SEBI",
        status="unknown",  # SEBI does not expose open/closed on the page; deadline decides
    )


def fetch_records(limit: int = DEFAULT_LIMIT) -> list[ConsultationRecord]:
    cfg = settings()
    headers = {"User-Agent": cfg.user_agent}
    records: list[ConsultationRecord] = []
    with httpx.Client(timeout=cfg.http_timeout_seconds, follow_redirects=True) as client:
        sitemap = client.get(SITEMAP_URL, headers=headers)
        sitemap.raise_for_status()
        urls = consultation_urls(sitemap.text, limit=limit)
        log.info("sebi: %s consultation papers in sitemap window", len(urls))
        for url in urls:
            try:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                rec = parse_detail(resp.text, url)
                if rec:
                    records.append(rec)
            except httpx.HTTPError as exc:
                log.warning("sebi: %s failed (%s); skipping", url, exc)
    return records
