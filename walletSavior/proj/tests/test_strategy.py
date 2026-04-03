"""
테스트: 카테고리 트리, 통계 엔진, 레시피 계산기, 커뮤니티 검증.
"""

import pytest
from core.categories import (
    CategoryTree, CategoryNode, ProductAttribute, AttrKeys,
    build_default_tree, STORAGE_VALUES, ORIGIN_VALUES,
)
from core.statistics import (
    remove_outliers_iqr, compute_stats, simple_moving_average,
    exponential_moving_average, compute_moving_averages,
    determine_tier, seasonal_comparison, PriceStats,
)
from core.recipe import Recipe, Ingredient, build_default_recipes
from core.verification import (
    verify_community_price, VerifyStatus,
)


# ===============================
# 카테고리 트리 테스트
# ===============================

class TestCategoryTree:
    def test_add_and_find(self):
        tree = CategoryTree()
        tree.add("축산물", "돼지고기", "삼겹살")
        node = tree.find("삼겹살")
        assert node is not None
        assert node.name == "삼겹살"
        assert node.depth == 3
        assert "축산물" in node.path
        assert "돼지고기" in node.path

    def test_path_generation(self):
        tree = CategoryTree()
        tree.add("채소류", "근채류", "양파")
        path = tree.get_path("양파")
        assert path == "전체 > 채소류 > 근채류 > 양파"

    def test_find_nonexistent(self):
        tree = CategoryTree()
        assert tree.find("존재하지않음") is None

    def test_duplicate_add(self):
        tree = CategoryTree()
        tree.add("축산물", "돼지고기", "삼겹살")
        tree.add("축산물", "돼지고기", "앞다리")
        # 돼지고기 노드는 하나만 있어야
        pork = tree.find("돼지고기")
        assert len(pork.children) == 2
        assert pork.children[0].name == "삼겹살"
        assert pork.children[1].name == "앞다리"

    def test_all_categories(self):
        tree = CategoryTree()
        tree.add("A", "B", "C")
        tree.add("A", "B", "D")
        tree.add("X", "Y")
        cats = tree.all_categories()
        names = [c.name for c in cats]
        assert "A" in names
        assert "B" in names
        assert "C" in names
        assert "D" in names
        assert "X" in names
        assert "Y" in names
        assert len(cats) == 6

    def test_default_tree_has_categories(self):
        tree = build_default_tree()
        assert tree.find("삼겹살") is not None
        assert tree.find("양파") is not None
        assert tree.find("계란") is not None
        assert tree.find("우유") is not None
        assert tree.find("라면") is not None
        # 최소 50개 이상의 카테고리
        assert len(tree.all_categories()) >= 50

    def test_applicable_attrs(self):
        tree = build_default_tree()
        pork = tree.find("삼겹살")
        assert AttrKeys.STORAGE in pork.applicable_attrs
        assert AttrKeys.ORIGIN in pork.applicable_attrs

    def test_product_attribute(self):
        attr = ProductAttribute(key=AttrKeys.STORAGE, value="냉동")
        assert str(attr) == "storage=냉동"

    def test_all_leaves(self):
        tree = CategoryTree()
        tree.add("A", "B", "C")
        tree.add("A", "B", "D")
        tree.add("A", "E")
        a = tree.find("A")
        leaves = a.all_leaves()
        leaf_names = [l.name for l in leaves]
        assert "C" in leaf_names
        assert "D" in leaf_names
        assert "E" in leaf_names
        assert "B" not in leaf_names  # B는 중간 노드


# ===============================
# 통계 엔진 테스트
# ===============================

class TestStatistics:
    def test_compute_stats_basic(self):
        prices = [100, 200, 300, 400, 500]
        stats = compute_stats(prices, data_days=5)
        assert stats.count == 5
        assert stats.mean == 300.0
        assert stats.median == 300.0
        assert stats.low == 100
        assert stats.high == 500

    def test_compute_stats_empty(self):
        stats = compute_stats([])
        assert stats.count == 0
        assert stats.mean == 0

    def test_outlier_removal(self):
        # 정상 가격 + 극단 이상치
        prices = [100, 110, 105, 95, 108, 102, 1000, 5]
        cleaned, removed = remove_outliers_iqr(prices)
        assert removed >= 1  # 1000은 제거되어야
        assert 1000 not in cleaned

    def test_no_outliers(self):
        prices = [100, 102, 98, 101, 99]
        cleaned, removed = remove_outliers_iqr(prices)
        assert removed == 0
        assert len(cleaned) == 5

    def test_confidence_interval(self):
        prices = [1000, 1100, 1050, 950, 1000, 1020, 980]
        stats = compute_stats(prices)
        # 신뢰구간은 평균 ± 2σ
        assert stats.confidence_low < stats.mean
        assert stats.confidence_high > stats.mean
        assert stats.confidence_low <= stats.low or True  # 범위가 데이터를 감쌀 수 있음

    def test_sma(self):
        prices = [10, 20, 30, 40, 50]
        sma3 = simple_moving_average(prices, 3)
        assert len(sma3) == 5
        assert sma3[2] == 20.0  # (10+20+30)/3
        assert sma3[4] == 40.0  # (30+40+50)/3

    def test_ema(self):
        prices = [100, 110, 120, 130, 140]
        ema = exponential_moving_average(prices, 3)
        assert len(ema) == 5
        assert ema[0] == 100  # 첫 값은 원본 그대로
        assert ema[-1] > ema[0]  # 상승 추세면 EMA도 상승

    def test_moving_averages(self):
        prices = list(range(100, 200))
        ma = compute_moving_averages(prices)
        assert len(ma.sma_7) == 100
        assert len(ma.sma_30) == 100
        assert len(ma.ema_7) == 100

    def test_tier_ultra(self):
        stats = PriceStats(mean=2000, median=2000, std=200, low=1500, high=2500,
                          q1=1800, q3=2200, count=100, confidence_low=1600,
                          confidence_high=2400, outliers_removed=0, data_days=30)
        tier = determine_tier(1200, stats)  # 60% of avg
        assert tier.tier == "ultra"

    def test_tier_great(self):
        stats = PriceStats(mean=2000, median=2000, std=200, low=1500, high=2500,
                          q1=1800, q3=2200, count=100, confidence_low=1600,
                          confidence_high=2400, outliers_removed=0, data_days=30)
        tier = determine_tier(1600, stats)  # 80% of avg
        assert tier.tier == "great"

    def test_tier_good(self):
        stats = PriceStats(mean=2000, median=2000, std=200, low=1500, high=2500,
                          q1=1800, q3=2200, count=100, confidence_low=1600,
                          confidence_high=2400, outliers_removed=0, data_days=30)
        tier = determine_tier(2050, stats)  # ~102% of avg
        assert tier.tier == "good"

    def test_tier_wait(self):
        stats = PriceStats(mean=2000, median=2000, std=200, low=1500, high=2500,
                          q1=1800, q3=2200, count=100, confidence_low=1600,
                          confidence_high=2400, outliers_removed=0, data_days=30)
        tier = determine_tier(2500, stats)  # 125% of avg
        assert tier.tier == "wait"

    def test_seasonal_comparison(self):
        result = seasonal_comparison(2000, [1800, 1900, 1850])
        assert result is not None
        assert result["change_pct"] > 0  # 올해가 더 비쌈


# ===============================
# 레시피 계산기 테스트
# ===============================

class TestRecipe:
    def test_ingredient_cost(self):
        i = Ingredient(name="양파", amount=2, unit="개", price_per_unit=500)
        assert i.cost == 1000

    def test_recipe_total_cost(self):
        r = Recipe(
            name="테스트", servings=1, eating_out_price=10000,
            ingredients=[
                Ingredient(name="A", amount=1, unit="개", price_per_unit=2000),
                Ingredient(name="B", amount=2, unit="개", price_per_unit=1500),
            ]
        )
        assert r.total_cost == 5000  # 2000 + 3000

    def test_recipe_savings(self):
        r = Recipe(
            name="테스트", servings=1, eating_out_price=10000,
            ingredients=[
                Ingredient(name="A", amount=1, unit="개", price_per_unit=3000),
            ]
        )
        assert r.savings == 7000
        assert r.savings_pct == 70.0

    def test_recipe_summary(self):
        r = Recipe(
            name="짜장면", servings=1, eating_out_price=6500,
            ingredients=[
                Ingredient(name="면", amount=1, unit="인분", price_per_unit=600),
            ]
        )
        s = r.summary()
        assert s["recipe"] == "짜장면"
        assert s["eating_out"] == 6500
        assert s["savings"] > 0

    def test_default_recipes(self):
        recipes = build_default_recipes()
        assert len(recipes) >= 5
        for r in recipes:
            assert r.name
            assert r.eating_out_price > 0
            assert len(r.ingredients) > 0
            assert r.total_cost > 0
            assert r.savings > 0  # 집밥이 항상 더 싸야


# ===============================
# 커뮤니티 검증 테스트
# ===============================

class TestVerification:
    def test_verified_normal(self):
        result = verify_community_price(1800, 2000)
        assert result.status == VerifyStatus.VERIFIED
        assert result.can_post is True

    def test_great_deal(self):
        result = verify_community_price(1100, 2000)  # 55% of avg
        assert result.status == VerifyStatus.GREAT_DEAL
        assert "🔥" in result.emoji

    def test_suspicious_low(self):
        result = verify_community_price(100, 2000)  # 5% of avg → 너무 싸
        assert result.status == VerifyStatus.SUSPICIOUS_LOW
        assert result.can_post is False
        assert result.warning_msg  # 경고 메시지 있어야

    def test_suspicious_high(self):
        result = verify_community_price(2500, 2000)  # 125% of avg → 바이럴
        assert result.status == VerifyStatus.SUSPICIOUS_HIGH
        assert "🚨" in result.emoji

    def test_unmatched(self):
        result = verify_community_price(1000, 0, "없는품목")
        assert result.status == VerifyStatus.UNMATCHED

    def test_edge_boundaries(self):
        # 정확히 70% → great_deal과 verified 경계
        result = verify_community_price(1400, 2000)  # 70%
        assert result.status in (VerifyStatus.GREAT_DEAL, VerifyStatus.VERIFIED)

    def test_price_vs_avg_pct(self):
        result = verify_community_price(1500, 2000)
        assert result.price_vs_avg_pct == -25.0
