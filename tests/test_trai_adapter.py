from datetime import date
from pathlib import Path

from janawaaz.adapters import trai

FIXTURE = Path(__file__).parent / "fixtures" / "trai_listing.html"
# Snapshot of trai.gov.in/release-publication/consultation (fetched 2026-07-04).


def _records():
    return trai.parse_listing(FIXTURE.read_text(encoding="utf-8"))


def test_parses_rows_from_real_listing_snapshot():
    records = _records()
    assert len(records) >= 4


def test_v2x_row_fields():
    records = _records()
    v2x = next(r for r in records if "Vehicle-to-Everything" in r.title)
    assert v2x.source == "trai"
    assert v2x.published_at == date(2026, 4, 30)
    assert v2x.status == "closed"
    assert v2x.ministry.startswith("TRAI")
    assert "trai.gov.in" in (v2x.comment_channel or "")
    assert v2x.external_id  # stable slug


def test_body_url_is_absolute_pdf_when_available():
    records = _records()
    with_pdf = [r for r in records if r.body_url.lower().endswith(".pdf")]
    assert with_pdf, "expected at least one row with a PDF body"
    assert all(r.body_url.startswith("https://trai.gov.in/") for r in with_pdf)


def test_external_ids_unique():
    records = _records()
    ids = [r.external_id for r in records]
    assert len(ids) == len(set(ids))
