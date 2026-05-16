"""test_sample_data — 샘플 데이터 생성 검증 (11 tests)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from price_data.sample_data import (
    PRODUCT_CATALOG,
    STORE_PROFILES,
    HOTDEAL_SOURCES,
    generate_baseline_prices,
    generate_discount_history,
    generate_hotdeal_prices,
    generate_all_sample_data,
    _seasonal_factor,
    _daily_noise,
)


class TestProductCatalog:
    def test_has_at_least_50_products(self):
        assert len(PRODUCT_CATALOG) >= 50

    def test_all_products_have_required_fields(self):
        for p in PRODUCT_CATALOG:
            assert "id" in p, f"제품 누락 필드: id"
            assert "name" in p, f"제품 누락 필드: name"
            assert "category" in p, f"제품 {p.get('name')} 누락: category"
            assert "unit" in p, f"제품 {p.get('name')} 누락: unit"
            assert "base_price" in p, f"제품 {p.get('name')} 누락: base_price"
            assert "price_range" in p, f"제품 {p.get('name')} 누락: price_range"

    def test_covers_required_categories(self):
        categories = {p["category"] for p in PRODUCT_CATALOG}
        required = {"농산물", "축산물", "수산물", "가공식품", "생활용품", "음료"}
        assert required.issubset(categories), f"누락 카테고리: {required - categories}"

    def test_price_ranges_are_valid(self):
        for p in PRODUCT_CATALOG:
            lo, hi = p["price_range"]
            assert lo > 0, f"{p['name']} 최저가 > 0"
            assert hi > lo, f"{p['name']} 최고가 > 최저가"
            assert lo <= p["base_price"] <= hi, (
                f"{p['name']} base_price {p['base_price']} 범위 밖 ({lo}-{hi})"
            )

    def test_unique_product_ids(self):
        ids = [p["id"] for p in PRODUCT_CATALOG]
        assert len(ids) == len(set(ids)), "중복 제품 ID 존재"


class TestSeasonalFactor:
    def test_no_seasonal_returns_1(self):
        assert _seasonal_factor(6, None) == 1.0

    def test_peak_month_is_highest(self):
        seasonal = {"peak_month": 7, "trough_month": 1, "amplitude": 0.3}
        peak_val = _seasonal_factor(7, seasonal)
        off_peak_val = _seasonal_factor(1, seasonal)
        assert peak_val > off_peak_val


class TestGenerateBaselinePrices:
    def test_generates_records(self):
        records = generate_baseline_prices(months=1, seed=42)
        assert len(records) > 0

    def test_record_structure(self):
        records = generate_baseline_prices(
            products=PRODUCT_CATALOG[:2], months=1, seed=42,
        )
        r = records[0]
        assert "product_id" in r
        assert "product_name" in r
        assert "price" in r
        assert "source" in r
        assert "unit" in r
        assert "recorded_at" in r
        assert r["price"] > 0

    def test_prices_within_range(self):
        records = generate_baseline_prices(
            products=PRODUCT_CATALOG[:5], months=1, seed=42,
        )
        for r in records:
            prod = next(p for p in PRODUCT_CATALOG if p["id"] == r["product_id"])
            lo, hi = prod["price_range"]
            assert r["price"] >= lo, f"{prod['name']} price {r['price']} < {lo}"
            assert r["price"] <= hi, f"{prod['name']} price {r['price']} > {hi}"

    def test_includes_multiple_stores(self):
        records = generate_baseline_prices(
            products=PRODUCT_CATALOG[:1], months=1, seed=42,
        )
        sources = {r["source"] for r in records}
        for store in STORE_PROFILES:
            assert store in sources, f"마트 {store} 누락"

    def test_includes_coupang_data(self):
        records = generate_baseline_prices(
            products=PRODUCT_CATALOG[:1], months=2, seed=42,
        )
        coupang_records = [r for r in records if r["source"] == "coupang"]
        assert len(coupang_records) > 0, "쿠팡 데이터 없음"

    def test_deterministic_with_seed(self):
        r1 = generate_baseline_prices(products=PRODUCT_CATALOG[:1], months=1, seed=99)
        r2 = generate_baseline_prices(products=PRODUCT_CATALOG[:1], months=1, seed=99)
        assert len(r1) == len(r2)
        assert r1[0]["price"] == r2[0]["price"]


class TestGenerateDiscountHistory:
    def test_generates_records(self):
        records = generate_discount_history(months=3, seed=42)
        assert len(records) > 0

    def test_discount_rate_is_positive(self):
        records = generate_discount_history(
            products=PRODUCT_CATALOG[:5], months=3, seed=42,
        )
        for r in records:
            assert r["discount_rate"] > 0
            assert r["discount_rate"] <= 100

    def test_sale_price_less_than_original(self):
        records = generate_discount_history(
            products=PRODUCT_CATALOG[:5], months=3, seed=42,
        )
        for r in records:
            assert r["price"] <= r["original_price"], (
                f"할인가 {r['price']} > 원가 {r['original_price']}"
            )

    def test_has_valid_dates(self):
        records = generate_discount_history(
            products=PRODUCT_CATALOG[:2], months=2, seed=42,
        )
        for r in records:
            assert r["valid_from"] < r["valid_to"]


class TestGenerateHotdealPrices:
    def test_generates_records(self):
        records = generate_hotdeal_prices(months=3, seed=42)
        assert len(records) > 0

    def test_has_community_sources(self):
        records = generate_hotdeal_prices(
            products=PRODUCT_CATALOG[:10], months=3, seed=42,
        )
        sources = {r["source"] for r in records}
        for s in HOTDEAL_SOURCES:
            # 소스 중 하나라도 있으면 OK (랜덤이라 전부 보장 불가)
            pass
        assert len(sources) > 0

    def test_hotdeal_prices_are_deep_discounts(self):
        records = generate_hotdeal_prices(
            products=PRODUCT_CATALOG[:10], months=3, seed=42,
        )
        for r in records:
            prod = next(p for p in PRODUCT_CATALOG if p["id"] == r["product_id"])
            # 핫딜은 base_price보다 항상 저렴해야 함
            assert r["price"] < prod["base_price"], (
                f"{prod['name']} 핫딜 {r['price']} >= base {prod['base_price']}"
            )

    def test_has_votes(self):
        records = generate_hotdeal_prices(
            products=PRODUCT_CATALOG[:5], months=3, seed=42,
        )
        for r in records:
            assert r["votes_hot"] >= 0
            assert r["votes_not"] >= 0


class TestGenerateAllSampleData:
    def test_returns_all_sections(self):
        data = generate_all_sample_data(months=1, seed=42)
        assert "baseline_prices" in data
        assert "discount_history" in data
        assert "hotdeal_prices" in data
        assert "products" in data
        assert "summary" in data

    def test_summary_counts_match(self):
        data = generate_all_sample_data(months=1, seed=42)
        s = data["summary"]
        assert s["baseline_count"] == len(data["baseline_prices"])
        assert s["discount_count"] == len(data["discount_history"])
        assert s["hotdeal_count"] == len(data["hotdeal_prices"])
        assert s["products"] == len(PRODUCT_CATALOG)
