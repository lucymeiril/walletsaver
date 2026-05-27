"""오피넷 fixture 진입점 어댑터."""

from __future__ import annotations

from pathlib import Path

from crawlers.opinet.crawler import GasStationRecord, OpinetCrawler


class OpinetEntrypoints:
    def __init__(self, crawler: OpinetCrawler | None = None) -> None:
        self._crawler = crawler or OpinetCrawler()

    def crawl_region(self, sido: str) -> list[GasStationRecord]:
        return self._crawler.crawl_region(sido)

    def ingest_fixture(self, fixture_path: str | Path) -> list[GasStationRecord]:
        return self._crawler.parse_fixture(fixture_path)


__all__ = ["OpinetEntrypoints"]
