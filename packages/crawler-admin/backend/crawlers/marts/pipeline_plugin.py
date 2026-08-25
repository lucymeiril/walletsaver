"""Bridge mart orchestrator plugins to the ingestion-capable CrawlPipeline.

The orchestrator owns scheduling/run history, while CrawlPipeline owns the
actual data path: validation -> matching enrichment -> PendingIngestion submit.
Keeping that boundary explicit prevents the newer scheduler from silently
running crawlers without persisting their collected rows.
"""
from __future__ import annotations

from crawlers.registry.registry import CrawlerRegistry
from pipeline.pipeline import CrawlPipeline
from services.crawl_orchestrator import RawBatch


async def run_mart_pipeline(plugin_name: str) -> RawBatch:
    """Run one allowlisted mart through the current ingestion pipeline."""
    registry = CrawlerRegistry()
    registry.discover()
    pipeline = CrawlPipeline(registry=registry)
    result = await pipeline.run_crawler(plugin_name)

    return RawBatch(
        plugin_name=plugin_name,
        items=[],
        items_found=result.items_found,
        items_saved=result.items_saved,
        errors=list(result.errors or []),
        partial=result.status == "partial_failure",
    )
