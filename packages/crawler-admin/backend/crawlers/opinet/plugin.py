"""OPINET orchestrator adapter backed by the dedicated fuel SQLite store."""
from __future__ import annotations

import sys
from pathlib import Path

from crawlers.opinet.crawler import OpinetCrawler
from services.crawl_orchestrator import RawBatch, get_registry

_BACKEND = Path(__file__).resolve().parents[2]
_SHARED = _BACKEND.parent.parent / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from core.fuel_store import FuelStore


class OpinetPlugin:
    @property
    def name(self) -> str:
        return "opinet"

    @property
    def mart_kind(self) -> str:
        return "fuel"

    @property
    def display_name(self) -> str:
        return "오피넷 주유소"

    def supports_targeted_search(self, query: str) -> bool:
        return False

    async def crawl(self, targets: list[str] | None = None) -> RawBatch:
        crawler = OpinetCrawler()
        if not crawler.live_ready:
            return RawBatch(
                plugin_name=self.name,
                items=[],
                items_found=0,
                items_saved=0,
                errors=["OPINET_API_KEY is not configured"],
                partial=False,
            )

        records = await crawler.crawl()
        if not records:
            return RawBatch(
                plugin_name=self.name,
                items=[],
                items_found=0,
                items_saved=0,
                errors=["OPINET returned no usable station prices"],
                partial=False,
            )

        saved = FuelStore().save_snapshot(records)
        preview = [
            {
                "station_code": record.station_code,
                "name": record.name,
                "brand": record.brand,
                "sido": record.sido,
                "sigungu": record.sigungu,
                "price_count": len(record.prices),
            }
            for record in records[:20]
        ]
        return RawBatch(
            plugin_name=self.name,
            items=preview,
            items_found=len(records),
            items_saved=saved["stations"],
            errors=[],
            partial=False,
        )


def register() -> None:
    get_registry().register(OpinetPlugin())


__all__ = ["OpinetPlugin", "register"]
