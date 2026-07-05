from janawaaz.adapters import sebi, trai
from janawaaz.adapters.base import Adapter, ConsultationRecord

# Adding a source == one module implementing fetch_records() + one line here.
# Go/no-go log: MCA 403 bot-wall (Jul 4, out). RBI listing is JS-rendered (Jul 5,
# out for now). SEBI in via sitemap discovery. MyGov listing URL still unknown.
REGISTRY: dict[str, Adapter] = {
    trai.name: trai,
    sebi.name: sebi,
}

__all__ = ["Adapter", "ConsultationRecord", "REGISTRY"]
