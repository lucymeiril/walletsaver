"""알구몬 핫딜 — F1 플러그인 등록."""
from __future__ import annotations

from crawlers.hotdeals.algumon.crawler import AlgumonCrawler

try:
    from core.models import RawBatch  # noqa: F401 (re-export for type hints)
except ImportError:
    RawBatch = None  # type: ignore[assignment]


class AlgumonPlugin:
    name = "algumon"
    mart_kind = "hotdeal_aggregator"
    supports_targeted_search = True
    manual_only = False
    crawler_class = AlgumonCrawler

    def crawl(self, targets=None):
        import asyncio
        crawler = AlgumonCrawler()
        return asyncio.run(crawler.crawl())


try:
    from crawler_admin.services.crawl_orchestrator import register_plugin, CrawlerPlugin  # type: ignore[import]  # noqa: F401
    register_plugin(AlgumonPlugin())
except ImportError:
    # F1 오케스트레이터 미완성 — 플러그인 등록 보류
    pass
