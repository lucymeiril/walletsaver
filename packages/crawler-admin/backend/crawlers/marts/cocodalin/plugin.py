"""코코달인 (코스트코 할인) — F1 플러그인 등록."""
from __future__ import annotations

from crawlers.marts.cocodalin.crawler import CocodalinCrawler


class CocodalinPlugin:
    name = "kokodalin"
    mart_kind = "mart_discount"
    supports_targeted_search = False
    manual_only = False
    crawler_class = CocodalinCrawler

    def crawl(self, targets=None):
        import asyncio
        crawler = CocodalinCrawler()
        return asyncio.run(crawler.crawl())


try:
    from crawler_admin.services.crawl_orchestrator import register_plugin, CrawlerPlugin  # type: ignore[import]  # noqa: F401
    register_plugin(CocodalinPlugin())
except ImportError:
    pass
