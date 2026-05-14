"""Pipeline store failure status propagation tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.pipeline import CrawlPipeline, PipelineResult
from core.models import CrawlResult, CrawlStatus


def _make_pipeline(mock_registry, mock_crawler, db_url="http://fake:9999/api/prices/bulk"):
    mock_registry.get_crawler.return_value = mock_crawler
    return CrawlPipeline(registry=mock_registry, db_api_url=db_url)


def _make_registry():
    reg = MagicMock()
    reg._registry = {
        "test": {
            "config": {
                "output": {"model": "DiscountItem", "required_fields": ["name", "price"]},
                "schedule": {"retry_count": 1},
            }
        }
    }
    reg.list_crawlers.return_value = [{"name": "test", "category": "mart"}]
    return reg


def _make_crawler(items):
    c = MagicMock()
    c.crawl = AsyncMock(return_value=CrawlResult(
        status=CrawlStatus.SUCCESS, crawler_name="test",
        items_count=len(items), items=items,
    ))
    return c


class TestStoreFailurePropagation:
    """Pipeline must report 'partial_failure' when valid items exist but store returns 0."""

    @pytest.mark.asyncio
    async def test_store_failure_sets_partial_status(self):
        reg = _make_registry()
        crawler = _make_crawler([{"name": "사과", "price": 3000}])
        pipeline = _make_pipeline(reg, crawler)

        with patch("pipeline.pipeline.SKIP_REVIEW", True):
            with patch.object(pipeline, "_store", new_callable=AsyncMock, return_value=0):
                result = await pipeline.run_crawler("test")

        assert result.status == "partial_failure"
        assert result.items_saved == 0
        assert result.items_valid >= 1

    @pytest.mark.asyncio
    async def test_store_success_keeps_success_status(self):
        reg = _make_registry()
        crawler = _make_crawler([{"name": "사과", "price": 3000}])
        pipeline = _make_pipeline(reg, crawler)

        with patch("pipeline.pipeline.SKIP_REVIEW", True):
            with patch.object(pipeline, "_store", new_callable=AsyncMock, return_value=1):
                result = await pipeline.run_crawler("test")

        assert result.status == "success"
        assert result.items_saved == 1


class TestBatchIsolation:
    """One crawler failure in run_batch must not cancel the others."""

    @pytest.mark.asyncio
    async def test_batch_isolates_exception(self):
        reg = MagicMock()
        reg._registry = {
            "good": {"config": {"output": {"model": "DiscountItem", "required_fields": ["name"]}, "schedule": {"retry_count": 1}}},
            "bad": {"config": {"output": {"model": "DiscountItem", "required_fields": ["name"]}, "schedule": {"retry_count": 1}}},
        }
        good_crawler = _make_crawler([{"name": "사과", "price": 3000}])
        bad_crawler = MagicMock()
        bad_crawler.crawl = AsyncMock(side_effect=RuntimeError("boom"))

        def get_crawler(name):
            return good_crawler if name == "good" else bad_crawler

        reg.get_crawler.side_effect = get_crawler
        pipeline = CrawlPipeline(registry=reg, db_api_url="http://fake:9999/api/prices/bulk")
        results = await pipeline.run_batch(["good", "bad"])

        assert len(results) == 2
        statuses = {r.crawler_name: r.status for r in results}
        assert statuses["bad"] == "failed"
