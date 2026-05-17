"""홈플러스 플러그인 adapter — CrawlerPlugin Protocol 구현."""
from __future__ import annotations

import logging
import os

from services.crawl_orchestrator import RawBatch, get_registry

logger = logging.getLogger(__name__)


def _fixture_batch() -> RawBatch:
    return RawBatch(
        plugin_name="homeplus",
        items=[{"name": "fixture_item", "sale_price": 1500, "mart": "homeplus"}],
        items_found=1,
        items_saved=0,
        errors=[],
        partial=False,
    )


class HomeplusPlugin:
    @property
    def name(self) -> str:
        return "homeplus"

    @property
    def mart_kind(self) -> str:
        return "homeplus"

    @property
    def display_name(self) -> str:
        return "홈플러스"

    def supports_targeted_search(self, query: str) -> bool:
        return True

    async def crawl(self, targets: list[str] | None = None) -> RawBatch:
        if os.getenv("WALLETSAVIOR_FIXTURE_ONLY") == "1":
            return _fixture_batch()
        try:
            from crawlers.marts.homeplus.crawler import HomeplusCrawler
        except Exception as exc:
            logger.warning("[HomeplusPlugin] import failed: %s", exc)
            return RawBatch(plugin_name="homeplus", errors=[f"import_failed: {exc}"])
        crawler = HomeplusCrawler()
        result = await crawler.crawl()
        items_raw = list(getattr(result, "items", []) or [])
        items = [it.__dict__ if hasattr(it, "__dict__") else it for it in items_raw]
        errors_raw = list(getattr(result, "errors", []) or [])
        errors = [getattr(e, "error_msg", None) or str(e) for e in errors_raw]
        items_found = getattr(result, "items_count", None) or len(items)
        items_saved = getattr(result, "items_saved", 0) or 0
        return RawBatch(
            plugin_name="homeplus",
            items=items,
            items_found=items_found,
            items_saved=items_saved,
            errors=errors,
            partial=bool(errors and items),
        )


def register() -> None:
    get_registry().register(HomeplusPlugin())
