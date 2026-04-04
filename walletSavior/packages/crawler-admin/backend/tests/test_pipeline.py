"""Pipeline run, validation, transformation 테스트."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, patch

import pytest

from pipeline.validator import (
    validate_items,
    validate_price_range,
    validate_urls,
    deduplicate,
    normalize_prices,
)
from pipeline.transformer import (
    to_discount_history,
    to_hotdeal_prices,
    to_delivery_items,
    enrich_with_category,
)
from pipeline.pipeline import CrawlPipeline, PipelineResult
from core.models import CrawlResult, CrawlStatus
from core.events import EventBus


# ── Validator tests ──────────────────────────────────────────


class TestValidateItems:
    def test_valid_items_pass(self):
        items = [{"name": "사과", "price": 3000}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 1
        assert len(invalid) == 0

    def test_missing_field_rejected(self):
        items = [{"name": "사과"}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "_validation_error" in invalid[0]

    def test_mixed_items(self):
        items = [
            {"name": "사과", "price": 3000},
            {"name": "배"},
            {"name": "포도", "price": 5000},
        ]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 2
        assert len(invalid) == 1

    def test_wrong_type_name_rejected(self):
        """name field must be str; integer name should be rejected."""
        items = [{"name": 12345, "price": 3000}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "expected" in invalid[0]["_validation_error"]

    def test_string_price_accepted(self):
        """Price as string is allowed (normalize_prices handles it later)."""
        items = [{"name": "사과", "price": "12,500원"}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 1

    def test_list_price_rejected(self):
        """Price as list should be rejected."""
        items = [{"name": "사과", "price": [1, 2, 3]}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(invalid) == 1

    def test_extra_fields_no_type_check(self):
        """Fields not in FIELD_TYPE_RULES should not be type-checked."""
        items = [{"name": "사과", "price": 3000, "custom_data": {"nested": True}}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 1


class TestValidatePriceRange:
    def test_in_range(self):
        items = [{"price": 5000}]
        valid, invalid = validate_price_range(items)
        assert len(valid) == 1

    def test_out_of_range(self):
        items = [{"price": -100}, {"price": 99999999}]
        valid, invalid = validate_price_range(items)
        assert len(valid) == 0
        assert len(invalid) == 2

    def test_none_price_passes(self):
        items = [{"price": None}]
        valid, invalid = validate_price_range(items)
        assert len(valid) == 1


class TestValidateUrls:
    def test_valid_url(self):
        items = [{"url": "https://example.com/page"}]
        valid, invalid = validate_urls(items)
        assert len(valid) == 1

    def test_invalid_url(self):
        items = [{"url": "not-a-url"}]
        valid, invalid = validate_urls(items)
        assert len(invalid) == 1

    def test_no_url_field(self):
        items = [{"name": "test"}]
        valid, invalid = validate_urls(items)
        assert len(valid) == 1


class TestDeduplicate:
    def test_removes_duplicates(self):
        items = [
            {"name": "사과", "price": 3000},
            {"name": "사과", "price": 3000},
            {"name": "배", "price": 5000},
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 2

    def test_keeps_different_prices(self):
        items = [
            {"name": "사과", "price": 3000},
            {"name": "사과", "price": 4000},
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 2

    def test_none_fields_not_collapsed(self):
        """Items with all-None key fields must not be falsely deduplicated."""
        items = [
            {"name": None, "price": None, "url": "https://a.com"},
            {"name": None, "price": None, "url": "https://b.com"},
            {"name": None, "price": None, "url": "https://c.com"},
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 3

    def test_partial_none_still_deduped(self):
        """Items sharing same name but None price should still dedup on (name, None)."""
        items = [
            {"name": "사과", "price": None},
            {"name": "사과", "price": None},
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 1  # same name, same None price → dedup

    def test_mixed_none_and_values(self):
        """Items with some None and some non-None key fields work correctly."""
        items = [
            {"name": "사과", "price": 3000},
            {"name": None, "price": None, "url": "https://a.com"},
            {"name": None, "price": None, "url": "https://b.com"},
            {"name": "사과", "price": 3000},  # duplicate of first
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 3  # first 사과 + 2 unique None items


class TestNormalizePrices:
    def test_string_with_won(self):
        items = [{"price": "12,500원"}]
        normalize_prices(items)
        assert items[0]["price"] == 12500

    def test_string_with_commas(self):
        items = [{"price": "1,000,000"}]
        normalize_prices(items)
        assert items[0]["price"] == 1000000

    def test_int_stays_int(self):
        items = [{"price": 5000}]
        normalize_prices(items)
        assert items[0]["price"] == 5000

    def test_none_stays_none(self):
        items = [{"price": None}]
        normalize_prices(items)
        assert items[0]["price"] is None

    def test_invalid_string(self):
        items = [{"price": "무료"}]
        normalize_prices(items)
        assert items[0]["price"] is None


# ── Transformer tests ───────────────────────────────────────


class TestToDiscountHistory:
    def test_basic_conversion(self):
        items = [
            {
                "name": "삼겹살 100g",
                "normalized_name": "삼겹살",
                "store": "이마트",
                "sale_price": 8900,
                "original_price": 12000,
                "discount_percent": 25.8,
                "detail_url": "https://emart.com/item/1",
            }
        ]
        records = to_discount_history(items, source="mart_discount")
        assert len(records) == 1
        assert records[0]["product_name"] == "삼겹살"
        assert records[0]["sale_price"] == 8900
        assert records[0]["source"] == "mart_discount"

    def test_empty_list(self):
        assert to_discount_history([]) == []


class TestToHotdealPrices:
    def test_basic_conversion(self):
        items = [{"title": "핫딜!", "url": "https://x.com", "price": 1000}]
        records = to_hotdeal_prices(items)
        assert len(records) == 1
        assert records[0]["title"] == "핫딜!"
        assert records[0]["source"] == "hotdeal"


class TestToDeliveryItems:
    def test_basic_conversion(self):
        items = [
            {"name": "치킨", "price": 18000, "platform": "배민"}
        ]
        records = to_delivery_items(items, platform="배민")
        assert len(records) == 1
        assert records[0]["platform"] == "배민"


class TestEnrichWithCategory:
    def test_auto_maps_known_keyword(self):
        items = [{"name": "국내산 삼겹살 500g"}]
        enrich_with_category(items)
        assert "삼겹살" in items[0]["category"]

    def test_keeps_existing_category(self):
        items = [{"name": "삼겹살", "category": "기존카테고리"}]
        enrich_with_category(items)
        assert items[0]["category"] == "기존카테고리"

    def test_no_match(self):
        items = [{"name": "알 수 없는 상품"}]
        enrich_with_category(items)
        assert items[0].get("category") is None or items[0].get("category") == ""


# ── Pipeline tests ──────────────────────────────────────────


class TestPipelineResult:
    def test_to_dict(self):
        r = PipelineResult(
            crawler_name="test",
            items_found=10,
            items_valid=8,
            items_saved=8,
            duration=1.234,
        )
        d = r.to_dict()
        assert d["crawler_name"] == "test"
        assert d["items_found"] == 10
        assert d["duration"] == 1.23


class TestCrawlPipeline:
    @pytest.fixture
    def mock_registry(self):
        reg = MagicMock()
        reg._registry = {
            "test_crawler": {
                "config": {
                    "name": "test_crawler",
                    "category": "mart",
                    "output": {
                        "model": "DiscountItem",
                        "required_fields": ["name", "price"],
                    },
                    "schedule": {"retry_count": 1},
                },
            }
        }
        reg.list_crawlers.return_value = [
            {"name": "test_crawler", "category": "mart", "schedule": "0 7 * * *"}
        ]
        return reg

    @pytest.fixture
    def mock_crawler(self):
        crawler = MagicMock()
        crawler.crawl = AsyncMock(
            return_value=CrawlResult(
                status=CrawlStatus.SUCCESS,
                crawler_name="test_crawler",
                items_count=2,
                items=[
                    {"name": "사과", "price": 3000},
                    {"name": "배", "price": 5000},
                ],
            )
        )
        return crawler

    @pytest.mark.asyncio
    async def test_run_crawler_success(self, mock_registry, mock_crawler):
        mock_registry.get_crawler.return_value = mock_crawler
        pipeline = CrawlPipeline(
            registry=mock_registry, db_api_url="http://fake:9999/api/prices/bulk"
        )
        with patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=2):
            result = await pipeline.run_crawler("test_crawler")
        assert result.status == "success"
        assert result.items_found == 2
        assert result.items_valid >= 1

    @pytest.mark.asyncio
    async def test_run_crawler_not_found(self):
        reg = MagicMock()
        reg.get_crawler.side_effect = KeyError("not found")
        reg._registry = {}
        pipeline = CrawlPipeline(registry=reg)
        result = await pipeline.run_crawler("missing")
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_run_batch(self, mock_registry, mock_crawler):
        mock_registry.get_crawler.return_value = mock_crawler
        pipeline = CrawlPipeline(
            registry=mock_registry, db_api_url="http://fake:9999/api/prices/bulk"
        )
        with patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=2):
            results = await pipeline.run_batch(["test_crawler"])
        assert len(results) == 1
        assert results[0].items_found == 2

    @pytest.mark.asyncio
    async def test_run_all_filters_category(self, mock_registry, mock_crawler):
        mock_registry.get_crawler.return_value = mock_crawler
        pipeline = CrawlPipeline(
            registry=mock_registry, db_api_url="http://fake:9999/api/prices/bulk"
        )
        with patch.object(pipeline, "_store_to_ingestion", new_callable=AsyncMock, return_value=2):
            results = await pipeline.run_all(category="mart")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_run_all_no_match(self, mock_registry, mock_crawler):
        mock_registry.get_crawler.return_value = mock_crawler
        pipeline = CrawlPipeline(
            registry=mock_registry, db_api_url="http://fake:9999/api/prices/bulk"
        )
        results = await pipeline.run_all(category="nonexistent")
        assert len(results) == 0
