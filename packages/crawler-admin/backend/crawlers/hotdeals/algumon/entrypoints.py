"""알구몬 핫딜 entrypoint 등록."""
from __future__ import annotations

from crawlers.hotdeals.algumon.crawler import AlgumonCrawler, HotdealRecord


def crawl_list(html: str | None = None) -> list[HotdealRecord]:
    return AlgumonCrawler().crawl_list(html)


__all__ = ["AlgumonCrawler", "HotdealRecord", "crawl_list"]
