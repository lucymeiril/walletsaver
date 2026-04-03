"""test_report — 리포트 생성·내보내기 테스트 (10 tests)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from price_data.report import (
    generate_product_report,
    generate_category_summary,
    generate_full_report,
    export_report_to_json,
    _determine_best_time,
)
from price_data.sample_data import PRODUCT_CATALOG, generate_all_sample_data


def _sample_records(product_id=1, days=30):
    """테스트용 간단한 레코드 세트."""
    now = datetime.now()
    baseline = [
        {"product_id": product_id, "price": 3000 + i * 10,
         "source": "emart", "recorded_at": now - timedelta(days=days - i)}
        for i in range(days)
    ]
    discount = [
        {"product_id": product_id, "price": 2500,
         "source": "homeplus", "recorded_at": now - timedelta(days=15)},
        {"product_id": product_id, "price": 2700,
         "source": "lottemart", "recorded_at": now - timedelta(days=10)},
    ]
    return baseline, discount


class TestProductReport:
    def test_report_structure(self):
        baseline, discount = _sample_records(product_id=1, days=30)
        report = generate_product_report(
            baseline, discount, product_id=1,
            product_name="배추", product_unit="1포기",
        )
        assert report["product_id"] == 1
        assert report["product_name"] == "배추"
        assert "baseline" in report
        assert "trend" in report
        assert "seasonal" in report
        assert "confidence" in report
        assert "price_tiers" in report
        assert "best_time_to_buy" in report
        assert "store_comparison" in report
        assert "price_trend" in report

    def test_baseline_has_recommended(self):
        baseline, discount = _sample_records()
        report = generate_product_report(
            baseline, discount, product_id=1, product_name="배추",
        )
        assert report["baseline"]["recommended"] > 0

    def test_confidence_score_present(self):
        baseline, discount = _sample_records()
        report = generate_product_report(
            baseline, discount, product_id=1, product_name="배추",
        )
        assert "score" in report["confidence"]
        assert "grade" in report["confidence"]

    def test_store_comparison_populated(self):
        baseline, discount = _sample_records()
        report = generate_product_report(
            baseline, discount, product_id=1, product_name="배추",
        )
        assert len(report["store_comparison"]) >= 1


class TestCategorySummary:
    def test_category_summary_structure(self):
        data = generate_all_sample_data(months=1, seed=42)
        all_records = data["baseline_prices"] + data["discount_history"]
        summary = generate_category_summary(all_records, PRODUCT_CATALOG, "농산물")
        assert summary["category"] == "농산물"
        assert summary["product_count"] > 0
        assert "overall_trend" in summary
        assert "products_summary" in summary

    def test_empty_category(self):
        summary = generate_category_summary([], PRODUCT_CATALOG, "존재하지않는카테고리")
        assert summary["product_count"] == 0

    def test_cheapest_and_most_expensive(self):
        data = generate_all_sample_data(months=1, seed=42)
        all_records = data["baseline_prices"] + data["discount_history"]
        summary = generate_category_summary(all_records, PRODUCT_CATALOG, "농산물")
        assert len(summary["cheapest_products"]) > 0
        assert len(summary["most_expensive_products"]) > 0


class TestFullReport:
    def test_full_report_structure(self):
        data = generate_all_sample_data(months=1, seed=42)
        report = generate_full_report(
            baseline_records=data["baseline_prices"],
            discount_records=data["discount_history"],
            products=PRODUCT_CATALOG[:5],
        )
        assert "generated_at" in report
        assert "total_products" in report
        assert "product_reports" in report
        assert "category_summaries" in report
        assert "overall_stats" in report
        assert report["total_products"] == 5


class TestExportJSON:
    def test_export_valid_json(self):
        baseline, discount = _sample_records()
        report = generate_product_report(
            baseline, discount, product_id=1, product_name="배추",
        )
        json_str = export_report_to_json(report)
        parsed = json.loads(json_str)
        assert parsed["product_name"] == "배추"

    def test_export_handles_datetime(self):
        report = {"generated_at": datetime.now(), "data": "test"}
        json_str = export_report_to_json(report)
        parsed = json.loads(json_str)
        assert "generated_at" in parsed


class TestBestTime:
    def test_determine_best_time_up_trend(self):
        extended = {
            "trend": {"direction": "up"},
            "seasonal": {"best_month": 10},
            "confidence": {"score": 60},
        }
        result = _determine_best_time(extended, "배추")
        assert "상승" in result
        assert "10월" in result

    def test_determine_best_time_low_confidence(self):
        extended = {
            "trend": {"direction": "stable"},
            "seasonal": {"best_month": None},
            "confidence": {"score": 5},
        }
        result = _determine_best_time(extended, "배추")
        assert "데이터 부족" in result
