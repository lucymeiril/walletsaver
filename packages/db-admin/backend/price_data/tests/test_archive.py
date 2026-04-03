"""test_archive — 아카이브 빌드·집계·비교 매트릭스 테스트 (12 tests)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from price_data.archive import (
    build_product_archive,
    aggregate_by_period,
    aggregate_by_store,
    generate_price_trend,
    build_comparison_matrix,
    build_full_archive,
)


def _make_records(product_id=1, days=30, stores=None):
    """테스트용 레코드 생성 헬퍼."""
    if stores is None:
        stores = ["emart", "homeplus"]
    now = datetime.now()
    records = []
    for d in range(days):
        for store in stores:
            records.append({
                "product_id": product_id,
                "price": 3000 + d * 10 + (hash(store) % 200),
                "source": store,
                "recorded_at": now - timedelta(days=days - d),
            })
    return records


class TestBuildProductArchive:
    def test_builds_archive(self):
        records = _make_records(product_id=1, days=10)
        archive = build_product_archive(records, product_id=1)
        assert archive["product_id"] == 1
        assert archive["total_records"] == 20  # 10 days × 2 stores
        assert archive["date_range"]["start"] is not None
        assert archive["date_range"]["end"] is not None
        assert len(archive["sources"]) == 2

    def test_empty_for_unknown_product(self):
        records = _make_records(product_id=1, days=5)
        archive = build_product_archive(records, product_id=999)
        assert archive["total_records"] == 0
        assert archive["records"] == []

    def test_records_are_sorted(self):
        records = _make_records(product_id=1, days=10)
        archive = build_product_archive(records, product_id=1)
        dates = [r["date"] for r in archive["records"]]
        assert dates == sorted(dates)


class TestAggregateByPeriod:
    def test_daily_aggregation(self):
        records = _make_records(product_id=1, days=7, stores=["emart", "homeplus"])
        daily = aggregate_by_period(records, product_id=1, period="daily")
        assert len(daily) == 7
        for d in daily:
            assert d["count"] == 2  # 2 stores per day

    def test_weekly_aggregation(self):
        records = _make_records(product_id=1, days=28)
        weekly = aggregate_by_period(records, product_id=1, period="weekly")
        assert len(weekly) >= 3  # ~4 weeks

    def test_monthly_aggregation(self):
        records = _make_records(product_id=1, days=60)
        monthly = aggregate_by_period(records, product_id=1, period="monthly")
        assert len(monthly) >= 2

    def test_invalid_period_raises(self):
        records = _make_records()
        with pytest.raises(ValueError):
            aggregate_by_period(records, product_id=1, period="yearly")

    def test_aggregation_has_stats(self):
        records = _make_records(product_id=1, days=5)
        daily = aggregate_by_period(records, product_id=1, period="daily")
        for d in daily:
            assert "avg_price" in d
            assert "min_price" in d
            assert "max_price" in d
            assert "count" in d
            assert d["min_price"] <= d["avg_price"] <= d["max_price"]


class TestAggregateByStore:
    def test_store_aggregation(self):
        records = _make_records(
            product_id=1, days=10, stores=["emart", "homeplus", "lottemart"],
        )
        by_store = aggregate_by_store(records, product_id=1)
        assert len(by_store) == 3
        store_names = [s["store"] for s in by_store]
        assert "emart" in store_names
        assert "homeplus" in store_names


class TestPriceTrend:
    def test_trend_structure(self):
        records = _make_records(product_id=1, days=30)
        trend = generate_price_trend(records, product_id=1, period="weekly")
        assert trend["product_id"] == 1
        assert trend["period"] == "weekly"
        assert "data_points" in trend
        assert "overall_change_pct" in trend

    def test_upward_trend_positive_change(self):
        now = datetime.now()
        records = []
        for d in range(60):
            records.append({
                "product_id": 1,
                "price": 2000 + d * 30,
                "source": "emart",
                "recorded_at": now - timedelta(days=60 - d),
            })
        trend = generate_price_trend(records, product_id=1, period="weekly")
        assert trend["overall_change_pct"] > 0


class TestComparisonMatrix:
    def test_matrix_structure(self):
        records = (
            _make_records(product_id=1, days=10, stores=["emart", "homeplus"])
            + _make_records(product_id=2, days=10, stores=["emart", "homeplus"])
        )
        matrix = build_comparison_matrix(records, product_ids=[1, 2])
        assert matrix["products"] == [1, 2]
        assert len(matrix["stores"]) == 2
        assert 1 in matrix["matrix"]
        assert 2 in matrix["matrix"]
        assert 1 in matrix["cheapest_store"]

    def test_cheapest_store_identified(self):
        now = datetime.now()
        records = [
            {"product_id": 1, "price": 3000, "source": "emart",
             "recorded_at": now},
            {"product_id": 1, "price": 3500, "source": "homeplus",
             "recorded_at": now},
        ]
        matrix = build_comparison_matrix(records, product_ids=[1])
        assert matrix["cheapest_store"][1] == "emart"


class TestFullArchive:
    def test_full_archive_structure(self):
        records = _make_records(product_id=1, days=10)
        archive = build_full_archive(records, product_ids=[1])
        assert "generated_at" in archive
        assert "total_records" in archive
        assert "products" in archive
        assert "comparison_matrix" in archive
        assert 1 in archive["products"]
        product_data = archive["products"][1]
        assert "archive" in product_data
        assert "daily" in product_data
        assert "weekly" in product_data
        assert "monthly" in product_data
        assert "by_store" in product_data
