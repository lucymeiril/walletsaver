"""test_collector — 데이터 수집·임포트·검증 테스트 (14 tests)."""

from __future__ import annotations

from datetime import datetime

import pytest

from price_data.collector import (
    PriceRecord,
    ValidationResult,
    validate_price_record,
    import_from_csv,
    import_from_json,
    aggregate_mart_prices,
    batch_import,
    build_price_history,
)


class TestPriceRecord:
    def test_create_valid_record(self):
        r = PriceRecord(
            product_id=1, product_name="배추", price=3200,
            source="emart", unit="1포기",
        )
        assert r.is_valid()
        assert r.product_name == "배추"
        assert r.price == 3200

    def test_to_dict(self):
        r = PriceRecord(
            product_id=1, product_name="배추", price=3200,
            source="emart", unit="1포기",
        )
        d = r.to_dict()
        assert d["product_id"] == 1
        assert d["price"] == 3200
        assert "recorded_at" in d

    def test_invalid_when_no_name(self):
        r = PriceRecord(product_id=1, product_name="", price=3200, source="emart")
        assert not r.is_valid()

    def test_invalid_when_zero_price(self):
        r = PriceRecord(product_id=1, product_name="배추", price=0, source="emart")
        assert not r.is_valid()

    def test_invalid_when_no_source(self):
        r = PriceRecord(product_id=1, product_name="배추", price=3200, source="")
        assert not r.is_valid()


class TestValidation:
    def test_valid_record(self):
        rec, errors = validate_price_record({
            "product_id": 1, "product_name": "배추",
            "price": 3200, "source": "emart",
        })
        assert rec is not None
        assert len(errors) == 0

    def test_missing_product_id(self):
        rec, errors = validate_price_record({
            "product_name": "배추", "price": 3200, "source": "emart",
        })
        assert rec is None
        assert any("product_id" in e for e in errors)

    def test_negative_price(self):
        rec, errors = validate_price_record({
            "product_id": 1, "product_name": "배추",
            "price": -100, "source": "emart",
        })
        assert rec is None
        assert any("0보다" in e for e in errors)

    def test_missing_source(self):
        rec, errors = validate_price_record({
            "product_id": 1, "product_name": "배추", "price": 3200,
        })
        assert rec is None
        assert any("source" in e for e in errors)


class TestCSVImport:
    def test_valid_csv(self):
        csv = "product_id,product_name,price,source\n1,배추,3200,emart\n2,양파,2350,homeplus"
        result = import_from_csv(csv)
        assert result.valid_count == 2
        assert result.invalid_count == 0
        assert result.total == 2

    def test_csv_with_invalid_row(self):
        csv = "product_id,product_name,price,source\n1,배추,3200,emart\n,양파,,homeplus"
        result = import_from_csv(csv)
        assert result.valid_count == 1
        assert result.invalid_count == 1

    def test_csv_default_source(self):
        csv = "product_id,product_name,price\n1,배추,3200"
        result = import_from_csv(csv, source="manual")
        assert result.valid_count == 1
        assert result.valid[0].source == "manual"


class TestJSONImport:
    def test_valid_json(self):
        json_str = '[{"product_id": 1, "product_name": "배추", "price": 3200, "source": "emart"}]'
        result = import_from_json(json_str)
        assert result.valid_count == 1
        assert result.invalid_count == 0

    def test_invalid_json_syntax(self):
        result = import_from_json("{invalid json")
        assert result.invalid_count > 0

    def test_json_default_source(self):
        json_str = '[{"product_id": 1, "product_name": "배추", "price": 3200}]'
        result = import_from_json(json_str, source="api")
        assert result.valid[0].source == "api"


class TestCollectedQuantilePath:
    @pytest.mark.skip(reason="TODO: 마트4사+쿠팡 N개월 분위수 기준가 경로 테스트를 보강해야 합니다.")
    def test_quantile_baseline_path_todo(self):
        assert False


class TestMartAggregation:
    def test_aggregate_crawl_results(self):
        crawl = [
            {"name": "배추", "price": 3200, "product_id": 1, "unit": "1포기"},
            {"name": "양파", "price": 2350, "product_id": 2, "unit": "1kg"},
        ]
        records = aggregate_mart_prices(crawl, "emart")
        assert len(records) == 2
        assert all(r.source == "emart" for r in records)

    def test_skip_invalid_prices(self):
        crawl = [
            {"name": "배추", "price": -100, "product_id": 1},
            {"name": "", "price": 3200, "product_id": 2},
        ]
        records = aggregate_mart_prices(crawl, "emart")
        assert len(records) == 0


class TestBatchImport:
    def test_batch_import(self):
        data = [
            {"product_id": 1, "product_name": "배추", "price": 3200, "source": "emart"},
            {"product_id": 2, "product_name": "양파", "price": 2350, "source": "homeplus"},
        ]
        result = batch_import(data)
        assert result.valid_count == 2


class TestBuildPriceHistory:
    def test_builds_sorted_history(self):
        records = [
            {"product_id": 1, "price": 3200, "source": "emart",
             "recorded_at": datetime(2024, 1, 15)},
            {"product_id": 1, "price": 3100, "source": "emart",
             "recorded_at": datetime(2024, 1, 10)},
            {"product_id": 2, "price": 2350, "source": "emart",
             "recorded_at": datetime(2024, 1, 12)},
        ]
        history = build_price_history(records, product_id=1)
        assert len(history) == 2
        assert history[0]["date"] == "2024-01-10"
        assert history[1]["date"] == "2024-01-15"
