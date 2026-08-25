"""Contracts for the orchestrator -> ingestion pipeline bridge."""
from types import SimpleNamespace

import pytest

import crawlers.marts.pipeline_plugin as bridge


@pytest.mark.asyncio
async def test_mart_bridge_runs_allowlisted_pipeline_and_reports_persisted_counts(monkeypatch):
    discovered = {"called": False}

    class FakeRegistry:
        def discover(self):
            discovered["called"] = True
            return {"emart": {}}

    class FakePipeline:
        def __init__(self, registry):
            assert isinstance(registry, FakeRegistry)

        async def run_crawler(self, crawler_name):
            assert crawler_name == "emart"
            return SimpleNamespace(
                status="partial_failure",
                items_found=12,
                items_saved=10,
                errors=["2 rows rejected"],
            )

    monkeypatch.setattr(bridge, "CrawlerRegistry", FakeRegistry)
    monkeypatch.setattr(bridge, "CrawlPipeline", FakePipeline)

    batch = await bridge.run_mart_pipeline("emart")

    assert discovered["called"] is True
    assert batch.plugin_name == "emart"
    assert batch.items_found == 12
    assert batch.items_saved == 10
    assert batch.errors == ["2 rows rejected"]
    assert batch.partial is True
