"""Current crawler pipeline contracts."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models import CrawlResult, CrawlStatus, ErrorType, StrategyFailure
from pipeline.pipeline import CrawlPipeline, PipelineResult
from pipeline.transformer import enrich_with_category, to_discount_history, to_hotdeal_prices
from pipeline.validator import deduplicate, normalize_prices, validate_items, validate_price_range


def test_validate_items_rejects_missing_or_wrong_required_fields():
    valid, invalid = validate_items(
        [
            {"name": "사과", "price": "3,000원"},
            {"name": "배"},
            {"name": 123, "price": 5000},
        ],
        ["name", "price"],
    )
    assert valid == [{"name": "사과", "price": "3,000원"}]
    assert len(invalid) == 2
    assert all("_validation_error" in row for row in invalid)


def test_price_normalization_range_and_deduplication():
    items = [
        {"name": "두부", "sale_price": "1,980원"},
        {"name": "두부", "sale_price": "1,980원"},
        {"name": "두부", "sale_price": "2,180원"},
        {"name": "오류", "sale_price": -1},
    ]
    normalize_prices(items, price_field="sale_price")
    valid, invalid = validate_price_range(items, price_field="sale_price")
    assert len(invalid) == 1
    assert [row["sale_price"] for row in deduplicate(valid, ["name", "sale_price"])] == [1980, 2180]


def test_deduplicate_does_not_collapse_all_none_identity_rows():
    rows = [
        {"name": None, "price": None, "url": "https://a.test"},
        {"name": None, "price": None, "url": "https://b.test"},
    ]
    assert deduplicate(rows, ["name", "price"]) == rows


def test_discount_and_hotdeal_transformers_preserve_public_facts():
    discount = to_discount_history(
        [
            {
                "name": "삼겹살 500g",
                "normalized_name": "삼겹살",
                "store": "이마트",
                "sale_price": 8900,
                "original_price": 12000,
                "detail_url": "https://emart.test/1",
            }
        ]
    )[0]
    assert discount["product_name"] == "삼겹살"
    assert discount["sale_price"] == 8900
    assert discount["source_url"] == "https://emart.test/1"

    hotdeal = to_hotdeal_prices(
        [{"title": "핫딜", "url": "https://deal.test/1", "price": 1000}]
    )[0]
    assert hotdeal["title"] == "핫딜"
    assert hotdeal["price"] == 1000


def test_legacy_category_hook_does_not_guess_or_overwrite():
    rows = [
        {"name": "국내산 삼겹살 500g"},
        {"name": "두부", "category": "기존카테고리"},
    ]
    returned = enrich_with_category(rows)
    assert returned is rows
    assert "category" not in rows[0]
    assert rows[1]["category"] == "기존카테고리"


def _registry(items: list[dict], *, required_fields: list[str] | None = None):
    registry = MagicMock()
    registry._registry = {
        "test_crawler": {
            "config": {
                "name": "test_crawler",
                "category": "mart",
                "output": {
                    "model": "DiscountItem",
                    "required_fields": required_fields or ["name", "sale_price"],
                },
                "schedule": {"retry_count": 1},
            }
        }
    }
    registry.list_crawlers.return_value = [
        {"name": "test_crawler", "category": "mart", "schedule": "0 7 * * *"}
    ]
    registry.get_crawler.return_value = MagicMock(
        crawl=AsyncMock(
            return_value=CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name="test_crawler",
                items_count=len(items),
                items=items,
            )
        )
    )
    return registry


def _matching_passthrough(items):
    for row in items:
        row.setdefault("matching_status", "miss")
        row.setdefault("matching_miss_reason", "key_not_found")
    return items


def test_pipeline_result_rounds_duration():
    result = PipelineResult(
        crawler_name="x",
        items_found=10,
        items_valid=8,
        items_saved=8,
        duration=1.234,
    )
    assert result.to_dict()["duration"] == 1.23


@pytest.mark.asyncio
async def test_run_crawler_calls_matching_once_and_submits_deduplicated_rows():
    registry = _registry(
        [
            {"name": "두부 300g", "sale_price": "1,980원", "detail_url": "https://x.test/a"},
            {"name": "두부 300g", "sale_price": "2,180원", "detail_url": "https://x.test/b"},
            {"name": "두부 300g", "sale_price": "2,180원", "detail_url": "https://x.test/b"},
        ]
    )
    pipeline = CrawlPipeline(registry=registry)

    with patch(
        "pipeline.pipeline.enrich_items_with_matching_entries",
        side_effect=_matching_passthrough,
    ) as matching, patch.object(
        pipeline,
        "_store_to_ingestion",
        new_callable=AsyncMock,
        return_value=2,
    ) as store:
        result = await pipeline.run_crawler("test_crawler")

    assert result.status == "success"
    assert result.items_found == 3
    assert result.items_valid == 2
    matching.assert_called_once()
    submitted = store.await_args.kwargs["items"]
    assert [row["sale_price"] for row in submitted] == [1980, 2180]
    assert store.await_args.kwargs["quality_details"]["deduplicated_count"] == 1
    assert store.await_args.kwargs["quality_details"]["matching"] == {"hits": 0, "misses": 2}


@pytest.mark.asyncio
async def test_run_crawler_not_found_returns_failed_result():
    registry = MagicMock()
    registry._registry = {}
    registry.get_crawler.side_effect = KeyError("not found")
    result = await CrawlPipeline(registry=registry).run_crawler("missing")
    assert result.status == "failed"


@pytest.mark.asyncio
async def test_run_crawler_does_not_retry_forbidden_response():
    crawler = MagicMock()
    crawler.crawl = AsyncMock(
        return_value=CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="test_crawler",
            errors=[
                StrategyFailure(
                    strategy_name="requests",
                    error_type=ErrorType.HTTP_ERROR,
                    error_msg="HTTP 403",
                    status_code=403,
                )
            ],
            error_msg="blocked",
        )
    )
    registry = MagicMock()
    registry._registry = {
        "test_crawler": {
            "config": {
                "schedule": {"retry_count": 3},
                "output": {"model": "DiscountItem"},
            }
        }
    }
    registry.get_crawler.return_value = crawler

    result = await CrawlPipeline(registry=registry).run_crawler("test_crawler")

    assert result.status == "failed"
    assert crawler.crawl.await_count == 1
    assert any("not retrying" in error for error in result.errors)


@pytest.mark.asyncio
async def test_run_batch_and_category_filter_use_current_registry():
    registry = _registry(
        [{"name": "사과", "sale_price": 3000, "detail_url": "https://x.test/a"}]
    )
    pipeline = CrawlPipeline(registry=registry)

    with patch(
        "pipeline.pipeline.enrich_items_with_matching_entries",
        side_effect=_matching_passthrough,
    ), patch.object(
        pipeline,
        "_store_to_ingestion",
        new_callable=AsyncMock,
        return_value=1,
    ):
        batch = await pipeline.run_batch(["test_crawler"])
        filtered = await pipeline.run_all(category="mart")
        empty = await pipeline.run_all(category="nonexistent")

    assert len(batch) == 1 and batch[0].items_saved == 1
    assert len(filtered) == 1
    assert empty == []
