from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

import crawlers.opinet.plugin as plugin_module


@dataclass(frozen=True)
class _Price:
    fuel_type: str = "gasoline"
    price: int = 1590
    observed_at: datetime = datetime(2026, 8, 25, 9, 0, 0)
    source: str = "opinet"


@dataclass(frozen=True)
class _Station:
    station_code: str = "A1"
    brand: str = "알뜰"
    name: str = "테스트주유소"
    address: str = "서울특별시 강서구 테스트로 1"
    sido: str = "서울특별시"
    sigungu: str = "강서구"
    lat: float | None = None
    lng: float | None = None
    has_self_service: bool = True
    updated_at: datetime = datetime(2026, 8, 25, 9, 0, 0)
    prices: tuple[_Price, ...] = (_Price(),)


@pytest.mark.asyncio
async def test_opinet_plugin_fails_clearly_without_api_key(monkeypatch):
    class FakeCrawler:
        live_ready = False

    monkeypatch.setattr(plugin_module, "OpinetCrawler", FakeCrawler)

    batch = await plugin_module.OpinetPlugin().crawl()

    assert batch.items_found == 0
    assert batch.items_saved == 0
    assert batch.errors == ["OPINET_API_KEY is not configured"]


@pytest.mark.asyncio
async def test_opinet_plugin_persists_live_snapshot(monkeypatch):
    records = [_Station()]
    saved_records = []

    class FakeCrawler:
        live_ready = True

        async def crawl(self):
            return records

    class FakeStore:
        def save_snapshot(self, rows):
            saved_records.extend(rows)
            return {"stations": 1, "prices": 1}

    monkeypatch.setattr(plugin_module, "OpinetCrawler", FakeCrawler)
    monkeypatch.setattr(plugin_module, "FuelStore", FakeStore)

    batch = await plugin_module.OpinetPlugin().crawl()

    assert saved_records == records
    assert batch.items_found == 1
    assert batch.items_saved == 1
    assert batch.errors == []
    assert batch.items[0]["station_code"] == "A1"
