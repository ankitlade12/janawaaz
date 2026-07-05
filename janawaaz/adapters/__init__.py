from janawaaz.adapters import trai
from janawaaz.adapters.base import Adapter, ConsultationRecord

# Adding a source == one module implementing fetch_records() + one line here.
# Day 6: add RBI draft notifications (rbi.org.in server-rendered listing verified
# reachable) as the second regulator; MCA is a no-go (403 bot-wall, decided Jul 4).
REGISTRY: dict[str, Adapter] = {
    trai.name: trai,
}

__all__ = ["Adapter", "ConsultationRecord", "REGISTRY"]
