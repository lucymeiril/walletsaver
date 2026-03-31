"""test_baseline — 통계·이상치·계절·추세·신뢰도 테스트 (15 tests)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from price_data.baseline import (
    remove_outliers_iqr,
    calculate_mean,
    calculate_median,
    calculate_mode,
    calculate_std,
    calculate_percentile,
    full_statistics,
    get_seasonal_factor,
    adjust_for_season,
    calculate_seasonal_baseline,
    analyze_trend,
    calculate_confidence,
    calculate_extended_baseline,
    SEASONAL_INDICES,
)


class TestBasicStatistics:
    def test_mean(self):
        assert calculate_mean([10, 20, 30]) == 20.0

    def test_mean_empty(self):
        assert calculate_mean([]) == 0.0

    def test_median_odd(self):
        assert calculate_median([1, 3, 5]) == 3

    def test_median_even(self):
        assert calculate_median([1, 3, 5, 7]) == 4.0

    def test_median_empty(self):
        assert calculate_median([]) == 0.0

    def test_mode(self):
        result = calculate_mode([100, 200, 200, 300])
        assert result == 200

    def test_std_single_value(self):
        assert calculate_std([5]) == 0.0

    def test_percentile_50(self):
        values = list(range(1, 101))
        p50 = calculate_percentile(values, 50)
        assert 49 <= p50 <= 51


class TestOutlierDetection:
    def test_remove_outliers_normal(self):
        prices = [100, 102, 98, 105, 95, 103, 500, 10]
        cleaned, outliers = remove_outliers_iqr(prices)
        assert 500 in outliers or 10 in outliers
        assert len(cleaned) < len(prices)

    def test_no_outliers_in_tight_data(self):
        prices = [100, 101, 99, 102, 98]
        cleaned, outliers = remove_outliers_iqr(prices)
        assert len(outliers) == 0
        assert len(cleaned) == len(prices)

    def test_small_dataset_no_removal(self):
        prices = [100, 500, 10]
        cleaned, outliers = remove_outliers_iqr(prices)
        assert len(cleaned) == 3
        assert len(outliers) == 0


class TestFullStatistics:
    def test_full_stats_structure(self):
        prices = [3000, 3100, 3200, 3300, 3400, 3200, 3150, 3250]
        stats = full_statistics(prices)
        assert "count" in stats
        assert "mean" in stats
        assert "median" in stats
        assert "std" in stats
        assert "q1" in stats
        assert "q3" in stats
        assert "iqr" in stats
        assert "cv" in stats
        assert "skewness" in stats

    def test_empty_prices(self):
        stats = full_statistics([])
        assert stats["count"] == 0
        assert stats["mean"] == 0

    def test_realistic_prices(self):
        # 배추 가격 시뮬레이션
        prices = [3200, 3100, 3300, 3250, 3150, 3400, 3000, 2900, 3500, 3200]
        stats = full_statistics(prices)
        assert 2800 <= stats["mean"] <= 3600
        assert stats["std"] > 0
        assert stats["min"] <= stats["mean"] <= stats["max"]
        assert stats["q1"] <= stats["median"] <= stats["q3"]


class TestSeasonalAdjustment:
    def test_known_product_factor(self):
        # 배추는 10월 전후 가장 저렴해야 함
        factor_spring = get_seasonal_factor("배추", 3)
        factor_fall = get_seasonal_factor("배추", 10)
        assert factor_spring > factor_fall  # 봄에 더 비쌈

    def test_unknown_product_returns_1(self):
        assert get_seasonal_factor("알수없는제품", 6) == 1.0

    def test_invalid_month_returns_1(self):
        assert get_seasonal_factor("배추", 0) == 1.0
        assert get_seasonal_factor("배추", 13) == 1.0

    def test_adjust_for_season_lowers_expensive(self):
        # 배추가 비싼 계절에 보정하면 가격이 낮아져야 함
        price = 5000
        factor_spring = get_seasonal_factor("배추", 3)
        assert factor_spring > 1.0  # 봄은 비싼 계절
        adjusted = adjust_for_season(price, "배추", 3)
        assert adjusted < price  # 보정 후 더 낮아야

    def test_seasonal_baseline(self):
        records = [
            {"price": 4000, "recorded_at": datetime(2024, 3, 15)},
            {"price": 3000, "recorded_at": datetime(2024, 3, 20)},
            {"price": 2500, "recorded_at": datetime(2024, 10, 15)},
            {"price": 2200, "recorded_at": datetime(2024, 10, 20)},
        ]
        result = calculate_seasonal_baseline(records, "배추")
        assert result["raw_mean"] > 0
        assert result["adjusted_mean"] > 0
        assert result["best_month"] is not None
        assert result["worst_month"] is not None


class TestTrendAnalysis:
    def test_upward_trend(self):
        now = datetime.now()
        records = []
        for i in range(60):
            records.append({
                "price": 3000 + i * 20,  # 지속 상승
                "recorded_at": now - timedelta(days=60 - i),
            })
        result = analyze_trend(records, window_days=30)
        assert result["direction"] == "up"

    def test_downward_trend(self):
        now = datetime.now()
        records = []
        for i in range(60):
            records.append({
                "price": 5000 - i * 20,  # 지속 하락
                "recorded_at": now - timedelta(days=60 - i),
            })
        result = analyze_trend(records, window_days=30)
        assert result["direction"] == "down"

    def test_stable_trend(self):
        now = datetime.now()
        records = []
        for i in range(60):
            records.append({
                "price": 3000 + (i % 3) * 10,  # 미세 변동
                "recorded_at": now - timedelta(days=60 - i),
            })
        result = analyze_trend(records, window_days=30)
        assert result["direction"] == "stable"

    def test_empty_data(self):
        result = analyze_trend([])
        assert result["direction"] == "stable"
        assert result["label"] == "데이터 부족"


class TestConfidenceScore:
    def test_high_confidence(self):
        now = datetime.now()
        records = [
            {"price": 3200, "source": src, "recorded_at": now - timedelta(days=d)}
            for d in range(30)
            for src in ["emart", "homeplus", "lottemart", "kamis"]
        ]
        result = calculate_confidence(records)
        assert result["score"] >= 60
        assert result["grade"] in ("A", "B")

    def test_low_confidence_few_records(self):
        result = calculate_confidence([
            {"price": 3200, "source": "emart", "recorded_at": datetime.now()},
        ])
        assert result["score"] < 60

    def test_no_data(self):
        result = calculate_confidence([])
        assert result["score"] == 0
        assert result["grade"] == "F"


class TestExtendedBaseline:
    def test_calculates_all_sections(self):
        now = datetime.now()
        baseline = [
            {"product_id": 1, "price": 3000 + i * 10, "source": "emart",
             "recorded_at": now - timedelta(days=30 - i)}
            for i in range(30)
        ]
        discount = [
            {"product_id": 1, "price": 2500, "source": "emart",
             "recorded_at": now - timedelta(days=15)},
        ]
        result = calculate_extended_baseline(baseline, discount, product_name="배추")
        assert "statistics" in result
        assert "seasonal" in result
        assert "trend" in result
        assert "confidence" in result
        assert "recommended_baseline" in result
        assert "price_tiers" in result
        assert result["recommended_baseline"] > 0
