"""Pipeline store failure status propagation tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.pipeline import CrawlPipeline, PipelineResult
from core.models import CrawlResult, CrawlStatus


@pytest.fixture(autouse=True)
def isolated_pipeline_boundaries(monkeypatch):
    monkeypatch.setattr("pipeline.pipeline.enrich_items_with_matching_entries", lambda items: items)
    monkeypatch.setattr(CrawlPipeline, "_store_to_ingestion", AsyncMock(return_value=1))
    monkeypatch.setattr(CrawlPipeline, "_store", AsyncMock(return_value=1))


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
    """Zero acknowledged rows fail; genuinely partial positive saves remain partial."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("saved,status", [(0, "failed"), (1, "partial_failure")])
    async def test_store_failure_reports_actual_delivery_status(self, saved, status):
        reg = _make_registry()
        crawler = _make_crawler([{"name": "사과", "price": 3000}, {"name": "배", "price": 4000}])
        pipeline = _make_pipeline(reg, crawler)

        with patch("pipeline.pipeline.SKIP_REVIEW", True):
            with patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=saved) as review, patch.object(
                pipeline, "_store", new_callable=AsyncMock
            ) as direct:
                result = await pipeline.run_crawler("test")

        assert result.status == status
        assert result.items_saved == saved
        assert result.items_valid == 2
        review.assert_awaited_once()
        direct.assert_not_awaited()
        assert result.quality_details["delivery"]["target"] == "pending_review"

    @pytest.mark.asyncio
    async def test_store_success_keeps_success_status(self):
        reg = _make_registry()
        crawler = _make_crawler([{"name": "사과", "price": 3000}])
        pipeline = _make_pipeline(reg, crawler)

        with patch("pipeline.pipeline.SKIP_REVIEW", True):
            with patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=1) as review, patch.object(
                pipeline, "_store", new_callable=AsyncMock
            ) as direct:
                result = await pipeline.run_crawler("test")

        assert result.status == "success"
        assert result.items_saved == 1
        review.assert_awaited_once()
        direct.assert_not_awaited()
        assert result.quality_details["delivery"]["target"] == "pending_review"

    @pytest.mark.asyncio
    async def test_hotdeal_skip_review_keeps_existing_direct_target(self):
        reg = _make_registry()
        reg._registry["test"]["config"]["output"] = {"model": "HotdealPost", "required_fields": ["title", "price"]}
        pipeline = _make_pipeline(reg, _make_crawler([{"title": "source post", "price": 3000, "url": "https://example.test/post"}]))
        with patch("pipeline.pipeline.SKIP_REVIEW", True), patch.object(
            pipeline, "_store", new_callable=AsyncMock, return_value=1
        ) as direct, patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock) as review:
            result = await pipeline.run_crawler("test")
        review.assert_not_awaited()
        direct.assert_awaited_once()
        assert direct.await_args.args[0][0]["title"] == "source post"
        assert result.quality_details["delivery"]["target"] == "direct_store"
        assert result.status == "success" and result.items_saved == 1


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
