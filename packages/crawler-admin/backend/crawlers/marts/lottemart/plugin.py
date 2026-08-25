"""롯데마트 orchestrator adapter."""
from __future__ import annotations

import os

from crawlers.marts.pipeline_plugin import run_mart_pipeline
from services.crawl_orchestrator import RawBatch, get_registry


def _fixture_batch() -> RawBatch:
    return RawBatch(
        plugin_name="lottemart",
        items=[{"name": "fixture_item", "sale_price": 2000, "mart": "lottemart"}],
        items_found=1,
        items_saved=0,
        errors=[],
        partial=False,
    )


class LottemartPlugin:
    @property
    def name(self) -> str:
        return "lottemart"

    @property
    def mart_kind(self) -> str:
        return "lottemart"

    @property
    def display_name(self) -> str:
        return "롯데마트"

    def supports_targeted_search(self, query: str) -> bool:
        return False

    async def crawl(self, targets: list[str] | None = None) -> RawBatch:
        if os.getenv("WALLETSAVIOR_FIXTURE_ONLY") == "1":
            return _fixture_batch()
        return await run_mart_pipeline(self.name)


def register() -> None:
    get_registry().register(LottemartPlugin())
