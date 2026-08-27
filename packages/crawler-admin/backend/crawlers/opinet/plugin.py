"""OPINET orchestrator adapter backed by the dedicated fuel SQLite store."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from crawlers.opinet.crawler import OpinetCrawler
from services.crawl_orchestrator import RawBatch, get_registry
from services.remote_snapshot_upload import (
    RemoteSnapshotUploadError,
    remote_publish_configured,
    upload_snapshot,
)

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

        store = FuelStore()
        saved = store.save_snapshot(records)
        errors: list[str] = []
        partial = False

        # Publishing is optional. Keeping it here means OPINET remains
        # crawler-owned and does not acquire a db-admin dependency.
        if remote_publish_configured():
            try:
                with tempfile.TemporaryDirectory(prefix="walletsavior-opinet-") as tmpdir:
                    snapshot_path = Path(tmpdir) / "opinet.db"
                    await asyncio.to_thread(store.export_snapshot, snapshot_path)
                    await asyncio.to_thread(upload_snapshot, "opinet", snapshot_path)
            except RemoteSnapshotUploadError as exc:
                errors.append(f"OPINET remote snapshot publish failed: {exc}")
                partial = True
            except Exception as exc:
                errors.append(f"OPINET snapshot export/publish failed: {exc}")
                partial = True

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
            errors=errors,
            partial=partial,
        )


def register() -> None:
    get_registry().register(OpinetPlugin())


__all__ = ["OpinetPlugin", "register"]
