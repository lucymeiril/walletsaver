"""OPINET fixture and live-service entrypoint adapter."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from crawlers.opinet.crawler import GasStationRecord, OpinetCrawler


class OpinetEntrypoints:
    def __init__(self, crawler: OpinetCrawler | None = None) -> None:
        self._crawler = crawler or OpinetCrawler()

    def crawl_region(self, sido: str) -> list[GasStationRecord]:
        """Read a saved fixture by region; no network access."""
        return self._crawler.crawl_region(sido)

    def ingest_fixture(self, fixture_path: str | Path) -> list[GasStationRecord]:
        return self._crawler.parse_fixture(fixture_path)

    async def crawl_live(
        self,
        *,
        sido_codes: Iterable[str] | None = None,
        fuel_types: Iterable[str] | None = None,
    ) -> list[GasStationRecord]:
        """Fetch real OPINET rows when ``OPINET_API_KEY`` is configured."""
        return await self._crawler.crawl(
            sido_codes=sido_codes,
            fuel_types=fuel_types,
        )


__all__ = ["OpinetEntrypoints"]
