from janawaaz.adapters import rbi, sebi, trai
from janawaaz.adapters.base import Adapter, ConsultationRecord

# Adding a source == one module implementing fetch_records() + one line here.
# Go/no-go log: MCA 403 bot-wall (Jul 4, out). RBI listing JS-rendered but the
# RSS feeds are server-side (Jul 5, in). SEBI in via sitemap discovery. MyGov
# listing URL still unknown.
REGISTRY: dict[str, Adapter] = {
    trai.name: trai,
    sebi.name: sebi,
    rbi.name: rbi,
}

__all__ = ["Adapter", "ConsultationRecord", "REGISTRY"]
