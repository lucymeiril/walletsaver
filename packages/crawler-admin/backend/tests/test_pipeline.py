"""Current crawler pipeline contracts."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.events import CRAWL_COMPLETED, CRAWL_FAILED
from core.models import CrawlResult, CrawlStatus, ErrorType, StrategyFailure
from pipeline.pipeline import CrawlPipeline, PipelineResult
from pipeline.transformer import enrich_with_category, to_discount_history, to_hotdeal_prices
from pipeline.validator import deduplicate, normalize_prices, validate_items, validate_price_range


@pytest.fixture
def curated_mart_observation():
    root = Path(__file__).resolve().parents[4]
    return json.loads((root / '.debug-artifacts/review-proposals/continuation222-homeplus-genuine-enriched-row.json').read_text())


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


@pytest.mark.parametrize("quote", [None, 0])
def test_discount_transformer_does_not_replace_explicit_unknown_source_quote(quote):
    record = to_discount_history([{"name": "원문 관측", "sale_price": quote, "price": 10000,
        "attributes": {"promotion_conditions": {"payable_price_unconfirmed": True}}}])[0]
    assert record["sale_price"] == quote
    assert record["attributes"]["promotion_conditions"]["payable_price_unconfirmed"] is True


def test_discount_and_hotdeal_transformers_preserve_public_facts(curated_mart_observation):
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
    assert discount["source"] == "mart_discount"

    quoted = to_discount_history([curated_mart_observation])[0]
    assert quoted["name"] == curated_mart_observation["name"]
    assert quoted["source"] == "homeplus" and quoted["sale_price"] == 2190
    assert quoted["public_product_id"] == "prod-1e9f3e5d432cb63f0a77a208dfaa8de0"
    assert quoted["public_variant_id"] == "var-d4af5db5c0fd206dbcf06e1b8f6dba2d"
    assert quoted["matching_entry_id"] == 660
    assert (quoted["package_quantity"], quoted["package_unit"], quoted["display_unit"]) == (2, "L", "2L×6")
    assert quoted["recorded_at"] == quoted["crawled_at"] == curated_mart_observation["crawled_at"]
    assert quoted["attributes"] == curated_mart_observation["attributes"]
    conditions = quoted["attributes"]["promotion_conditions"]
    assert conditions["payable_price_unconfirmed"] is True
    assert conditions["minimum_purchase_quantity_unconfirmed"] is True
    assert conditions["coupon_application_unconfirmed"] is True
    assert quoted["original_price"] is None and quoted["discount_percent"] is None
    assert quoted["price_per_100g"] is None and "final_price" not in quoted
    # Displayed coupon amounts are source terms, not applied quote deductions.
    coupons = quoted["attributes"]["homeplus_detail_source_fields"]["promo"]["couponList"]
    assert [coupon["discount"] for coupon in coupons] == [4000, 2000]
    coupons[0]["discount"] = 0
    conditions["payable_price_unconfirmed"] = False
    assert curated_mart_observation["attributes"]["promotion_conditions"]["payable_price_unconfirmed"] is True
    assert curated_mart_observation["attributes"]["homeplus_detail_source_fields"]["promo"]["couponList"][0]["discount"] == 4000

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


@pytest.mark.asyncio
@pytest.mark.parametrize("skip_review", [False, True])
async def test_mart_review_keeps_unknown_purchase_terms_even_when_skip_requested(curated_mart_observation, skip_review):
    pipeline = CrawlPipeline(registry=_registry([curated_mart_observation]), event_bus=MagicMock(publish=AsyncMock()))
    with patch("pipeline.pipeline.SKIP_REVIEW", skip_review), patch(
        "pipeline.pipeline.enrich_items_with_matching_entries", side_effect=_matching_passthrough
    ), patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=1) as review, patch.object(
        pipeline, "_store", new_callable=AsyncMock
    ) as direct:
        result = await pipeline.run_crawler("test_crawler")
    direct.assert_not_awaited()
    review.assert_awaited_once()
    submitted = review.await_args.kwargs["items"][0]
    assert submitted["attributes"] == curated_mart_observation["attributes"]
    assert submitted["public_variant_id"] == curated_mart_observation["public_variant_id"]
    assert submitted["package_quantity"] == 2 and submitted["attributes"]["bundle_count"] == 6
    assert submitted["sale_price"] == 2190 and submitted["price_per_100g"] is None
    assert submitted["crawled_at"] == curated_mart_observation["crawled_at"]
    assert "final_price" not in submitted
    assert review.await_args.kwargs["schema_type"] == "DiscountItem"
    assert result.status == "success" and result.items_saved == 1
    assert result.quality_details["delivery"] == {"target": "pending_review", "status": "success", "attempted": 1, "acknowledged": 1}


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
@pytest.mark.parametrize("source_quality", [{}, {"fixture_fallback": False}])
async def test_run_crawler_calls_matching_once_and_submits_deduplicated_rows(source_quality):
    registry = _registry(
        [
            {"name": "두부 300g", "sale_price": "1,980원", "detail_url": "https://x.test/a"},
            {"name": "두부 300g", "sale_price": "2,180원", "detail_url": "https://x.test/b"},
            {"name": "두부 300g", "sale_price": "2,180원", "detail_url": "https://x.test/b"},
        ]
    )
    registry.get_crawler.return_value.crawl.return_value.strategy_used = "real_fallback"
    registry.get_crawler.return_value.crawl.return_value.quality_details = source_quality
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
    assert result.quality_details["item_counts"]["invalid_or_dropped"] == 0


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


def test_dedup_preserves_complete_source_spec_and_offer_contexts():
    base = {"name": "동일 표시명", "sale_price": 1000, "native_product_id": "sku-a",
            "detail_url": "https://example.test/item?sku=a", "attributes": {"spec": {"unit": "g", "quantity": 50}, "coupon_required": False}}
    rows = [
        base,
        {**base, "native_product_id": "sku-b"},
        {**base, "detail_url": "https://example.test/item?sku=b"},
        {**base, "attributes": {"spec": {"quantity": 100, "unit": "g"}, "coupon_required": False}},
        {**base, "attributes": {"spec": {"quantity": 50, "unit": "g"}, "coupon_required": True}},
        {**base, "sale_price": 1100},
        {**base, "attributes": {"coupon_required": False, "spec": {"quantity": 50, "unit": "g"}}},
    ]
    assert deduplicate(rows, ["name", "sale_price"]) == rows[:-1]


@pytest.mark.asyncio
async def test_pipeline_keeps_source_receipt_times_and_complete_quantity_scopes():
    base = {
        "name": "동일 표시명 2L×6", "sale_price": 1000, "source": "homeplus",
        "detail_url": "https://example.test/item/a", "crawled_at": "2026-10-05T10:00:00+00:00",
        "package_quantity": 2, "package_unit": "L",
        "attributes": {"source_record_key": "a", "bundle_count": 6,
                       "promotion_conditions": {"payable_price_unconfirmed": True}},
    }
    rows = [
        base,
        {**base, "source": "costco"},
        {**base, "detail_url": "https://example.test/item/b",
         "attributes": {**base["attributes"], "source_record_key": "b"}},
        {**base, "crawled_at": "2026-10-05T11:00:00+00:00"},
        {**base, "attributes": {**base["attributes"], "bundle_count": 12}},
        {**base, "package_quantity": 1.5},
        {**base, "attributes": dict(reversed(list(base["attributes"].items())))},
    ]
    expected = rows[:-1]
    pipeline = CrawlPipeline(registry=_registry(rows), event_bus=MagicMock(publish=AsyncMock()))
    with patch("pipeline.pipeline.enrich_items_with_matching_entries", side_effect=_matching_passthrough), patch.object(
        pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=len(expected)
    ) as store:
        result = await pipeline.run_crawler("test_crawler")
    submitted = store.await_args.kwargs["items"]
    assert len(submitted) == len(expected)
    assert [(row["source"], row["detail_url"], row["crawled_at"], row["package_quantity"],
             row["package_unit"], row["attributes"]) for row in submitted] == [
        (row["source"], row["detail_url"], row["crawled_at"], row["package_quantity"],
         row["package_unit"], row["attributes"]) for row in expected]
    assert all(row["sale_price"] == 1000 for row in submitted)
    assert result.status == "success" and result.items_saved == len(expected)
    assert result.quality_details["deduplicated_count"] == 1


def test_price_validation_keeps_actual_amounts_and_rejects_wrong_quotes():
    rows = [{"name": "가격", "price": value} for value in
            [0, 12.5, "12.5원", "₩1,000", "-500원", "상품100원", "1,23원", True, float("nan"), float("inf")]]
    valid, invalid = validate_items(rows, ["name", "price"])
    assert len(invalid) == 1  # bool is not a monetary amount; raw zero is retained, not confirmed as free.
    normalize_prices(valid)
    valid, invalid = validate_price_range(valid)
    assert [row["price"] for row in valid] == [0, 12.5, 12.5, 1000]
    assert len(invalid) == 5
    assert validate_items([{"name": "  ", "price": 100}], ["name"])[0] == []
    assert validate_items([{"name": "가격", "price": 100, "attributes": []}], [])[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["DiscountItem", "HotdealPost"])
async def test_pipeline_preserves_source_identity_and_full_context_for_both_models(model):
    label, quote = ("title", "price") if model == "HotdealPost" else ("name", "sale_price")
    rows = [{label: "같은 상품", quote: 1000, "native_product_id": sku,
             "url": "https://example.test/item", "source_context": "x" * 5000 + sku,
             "attributes": {"package_quantity": 50, "package_unit": "g"}}
            for sku in ["a", "b"]]
    registry = _registry(rows, required_fields=[label, quote])
    registry._registry["test_crawler"]["config"]["output"]["model"] = model
    pipeline = CrawlPipeline(registry=registry, event_bus=MagicMock(publish=AsyncMock()))
    with patch("pipeline.pipeline.enrich_items_with_matching_entries", side_effect=_matching_passthrough), patch.object(
        pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=2
    ) as store:
        result = await pipeline.run_crawler("test_crawler")
    submitted = store.await_args.kwargs["items"]
    assert result.status == "success" and result.items_valid == 2
    assert [row["native_product_id"] for row in submitted] == ["a", "b"]
    assert [row["source_context"] for row in submitted] == [row["source_context"] for row in rows]
    assert result.quality_details["item_counts"]["duplicates_after_validation"] == 0
    assert "high_duplicate_rate" not in result.quality_details["alerts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model,status", [("DiscountItem", CrawlStatus.SUCCESS), ("HotdealPost", CrawlStatus.FAILED)])
async def test_pipeline_rejects_explicit_fixture_fallback_before_submission(model, status):
    rows = [{"name": "offline sample", "title": "offline sample", "sale_price": 1000, "price": 1000}]
    registry = _registry(rows)
    registry._registry["test_crawler"]["config"]["schedule"]["retry_count"] = 3
    registry._registry["test_crawler"]["config"]["output"]["model"] = model
    crawl_result = registry.get_crawler.return_value.crawl.return_value
    crawl_result.status = status
    crawl_result.strategy_used = "fixture"
    crawl_result.quality_details = {"fixture_fallback": True}
    events = MagicMock(publish=AsyncMock())
    progress = AsyncMock()
    pipeline = CrawlPipeline(registry=registry, event_bus=events)
    with patch("pipeline.pipeline.SKIP_REVIEW", True), patch("pipeline.pipeline.validate_items") as validation, patch(
        "pipeline.pipeline.enrich_with_category"
    ) as categories, patch("pipeline.pipeline.enrich_items_with_matching_entries") as matching, patch(
        "pipeline.pipeline.to_hotdeal_prices"
    ) as export, patch.object(pipeline, "_store", new_callable=AsyncMock) as direct_store, patch.object(
        pipeline, "_store_to_ingestion", new_callable=AsyncMock
    ) as review_store:
        result = await pipeline.run_crawler("test_crawler", progress_callback=progress)
    assert result.status == "failed"
    assert result.items_found == result.items_valid == result.items_saved == 0
    assert result.quality_details["fixture_items_count"] == 1
    diagnostic = result.quality_details["zero_result_diagnostic"]
    assert diagnostic["stage"] == "fixture_fallback_not_live"
    assert diagnostic["counts"]["source_raw"] is None
    assert result.quality_details["quality_summary"]["status"] == "failing"
    registry.get_crawler.return_value.crawl.assert_awaited_once()
    for consumer in (validation, categories, matching, export):
        consumer.assert_not_called()
    direct_store.assert_not_awaited()
    review_store.assert_not_awaited()
    assert not any(call.args[0].event_type == CRAWL_COMPLETED for call in events.publish.await_args_list)
    assert events.publish.await_args.args[0].event_type == CRAWL_FAILED
    assert events.publish.await_args.args[0].data["quality_details"]["zero_result_diagnostic"]["stage"] == "fixture_fallback_not_live"
    assert progress.await_args.args[0]["stage"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("rows,reason", [
    ([], "source_zero_raw_rows"),
    ([{"name": "잘못된가격", "sale_price": "상품100원"}], "validation_rejected_all_rows"),
    ([{"name": "필드누락"}], "validation_rejected_all_rows"),
])
async def test_pipeline_zero_valid_rows_fail_without_store_or_completed_event(rows, reason):
    events = MagicMock(publish=AsyncMock())
    progress = AsyncMock()
    pipeline = CrawlPipeline(registry=_registry(rows), event_bus=events)
    with patch("pipeline.pipeline.enrich_items_with_matching_entries") as matching, patch.object(
        pipeline, "_store_to_ingestion", new_callable=AsyncMock
    ) as store:
        result = await pipeline.run_crawler("test_crawler", progress_callback=progress)
    assert result.status == "failed"
    assert result.items_found == len(rows) and result.items_valid == result.items_saved == 0
    assert result.quality_details["zero_result_diagnostic"]["stage"] == reason
    assert result.quality_details["quality_summary"]["status"] == "failing"
    store.assert_not_awaited()
    matching.assert_not_called()
    assert events.publish.await_args.args[0].event_type == CRAWL_FAILED
    assert events.publish.await_args.args[0].data["error"] == result.errors[-1]
    assert progress.await_args.args[0]["stage"] == "failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("saved,status,event", [(0, "failed", CRAWL_FAILED), (1, "partial_failure", CRAWL_COMPLETED)])
async def test_pipeline_storage_failure_reports_acknowledged_counts(saved, status, event):
    events = MagicMock(publish=AsyncMock())
    progress = AsyncMock()
    pipeline = CrawlPipeline(registry=_registry([
        {"name": "상품a", "sale_price": 1000}, {"name": "상품b", "sale_price": 2000}
    ]), event_bus=events)
    with patch("pipeline.pipeline.enrich_items_with_matching_entries", side_effect=_matching_passthrough), patch.object(
        pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=saved
    ):
        result = await pipeline.run_crawler("test_crawler", progress_callback=progress)
    assert result.status == status and result.items_valid == 2 and result.items_saved == saved
    assert result.quality_details["delivery"] == {"target": "pending_review", "status": status, "attempted": 2, "acknowledged": saved}
    assert result.quality_details["quality_summary"]["status"] == ("failing" if saved == 0 else "warning")
    assert events.publish.await_args.args[0].event_type == event
    if saved == 0:
        assert events.publish.await_args.args[0].data["error"] == result.errors[-1]
    assert progress.await_args.args[0]["stage"] == status


@pytest.mark.asyncio
async def test_pipeline_validates_each_rows_own_price_field_without_required_fields():
    registry = _registry([{"name": "정상", "sale_price": 100}, {"name": "잘못된레거시", "price": -20}])
    registry._registry["test_crawler"]["config"]["output"]["required_fields"] = []
    pipeline = CrawlPipeline(registry=registry, event_bus=MagicMock(publish=AsyncMock()))
    with patch("pipeline.pipeline.enrich_items_with_matching_entries", side_effect=_matching_passthrough), patch.object(
        pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=1
    ) as store:
        result = await pipeline.run_crawler("test_crawler")
    assert result.items_found == 2 and result.items_valid == 1
    assert [row["name"] for row in store.await_args.kwargs["items"]] == ["정상"]


@pytest.mark.asyncio
@pytest.mark.parametrize("target,body,expected", [
    ("direct", {"saved": 0}, 0),
    ("direct", {"saved": 1}, 1),
    ("direct", {"saved": True}, 0),
    ("pending", {"id": 12, "status": "pending", "idempotent": True}, 2),
    ("pending", {"ids": [12], "status": "pending", "total_items": 1, "items_per_chunk": [1]}, 1),
    ("pending", {"status": "ok"}, 0),
])
async def test_storage_counts_only_actual_acknowledgements_without_ambiguous_retries(target, body, expected):
    pipeline = CrawlPipeline(registry=MagicMock())
    response = httpx.Response(201, json=body, request=httpx.Request("POST", "https://example.test/storage"))
    client = AsyncMock()
    client.post.return_value = response
    auth = MagicMock(get_headers=AsyncMock(return_value={}))
    errors = []
    with patch("pipeline.pipeline.httpx.AsyncClient") as factory, patch("pipeline.pipeline.get_db_admin_auth", return_value=auth), patch(
        "pipeline.pipeline.audit_log"
    ), patch("pipeline.dead_letter.write_dead_letter"):
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        factory.return_value.__aexit__ = AsyncMock(return_value=None)
        if target == "direct":
            saved = await pipeline._store([{"price": 10}, {"price": 20}], errors)
        else:
            saved = await pipeline._store_to_ingestion("test", "success", [{"price": 10}, {"price": 20}], "DiscountItem", None, 0, errors)
    assert saved == expected
    client.post.assert_awaited_once()
    if body.get("saved") is True or body.get("status") == "ok":
        assert any("acknowledgement" in error for error in errors)


@pytest.mark.asyncio
@pytest.mark.parametrize('saved', [0, 1])
async def test_source_partial_keeps_prior_rows_once_and_preserves_submission_status(saved):
    rows = [{'name': '이미 수집한 원문 상품', 'sale_price': 1200, 'source_record_key': 'retained-native'}]
    registry = _registry(rows)
    registry._registry['test_crawler']['config']['schedule']['retry_count'] = 3
    crawler = registry.get_crawler.return_value
    source_quality = {'source_stopped': True, 'source_stop_status': 429, 'source_stop_reason': 'http_access_denied'}
    crawler.crawl.return_value = CrawlResult(status=CrawlStatus.PARTIAL, crawler_name='test_crawler',
        items=rows, items_count=1, error_msg='HTTP 429; source run stopped', quality_details=source_quality)
    events = MagicMock(publish=AsyncMock())
    pipeline = CrawlPipeline(registry=registry, event_bus=events)
    with patch('pipeline.pipeline.enrich_items_with_matching_entries', side_effect=_matching_passthrough), patch.object(
        pipeline, '_store_to_ingestion', new_callable=AsyncMock, return_value=saved
    ) as store:
        result = await pipeline.run_crawler('test_crawler')
    crawler.crawl.assert_awaited_once()
    store.assert_awaited_once()
    assert store.await_args.kwargs['crawl_status'] == 'partial'
    assert store.await_args.kwargs['items'][0]['source_record_key'] == 'retained-native'
    assert result.status == ('partial_failure' if saved else 'failed')
    assert result.items_found == result.items_valid == 1 and result.items_saved == saved
    assert result.quality_details['source_collection'] == {'status': 'partial', 'error': 'HTTP 429; source run stopped'}
    assert result.quality_details['source_quality_details'] == source_quality
    assert result.quality_details['delivery']['target'] == 'pending_review'
    assert result.quality_details['delivery']['status'] == result.status
    assert 'source_collection_partial' in result.quality_details['alerts']
    assert any('partial source collection' in error for error in result.errors)


@pytest.mark.asyncio
@pytest.mark.parametrize('shape', ['strategy429', 'homeplus_structured', 'explicit_source_stop'])
async def test_failed_explicit_source_access_stop_is_not_a_whole_collector_retry(shape):
    registry = _registry([])
    registry._registry['test_crawler']['config']['schedule']['retry_count'] = 3
    quality = ({'fetch': {'source_distribution': {'access_stop': {'http_status': 429, 'reason': 'explicit_source_access_denial'}}}}
               if shape == 'homeplus_structured' else {'source_stopped': True, 'source_stop_status': 202} if shape == 'explicit_source_stop' else {})
    failures = [StrategyFailure(strategy_name='requests', error_type=ErrorType.HTTP_ERROR, error_msg='HTTP429', status_code=429)] if shape == 'strategy429' else []
    crawler = registry.get_crawler.return_value
    crawler.crawl.return_value = CrawlResult(status=CrawlStatus.FAILED, crawler_name='test_crawler',
        error_msg='explicit source stop', quality_details=quality, errors=failures)
    pipeline = CrawlPipeline(registry=registry, event_bus=MagicMock(publish=AsyncMock()))
    with patch.object(pipeline, '_store_to_ingestion', new_callable=AsyncMock) as store:
        result = await pipeline.run_crawler('test_crawler')
    crawler.crawl.assert_awaited_once()
    store.assert_not_awaited()
    assert result.status == 'failed' and result.items_saved == 0
    assert result.quality_details['source_quality_details'] == quality
    assert any('not retrying' in error for error in result.errors)
