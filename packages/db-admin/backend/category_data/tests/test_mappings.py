"""상품-카테고리 매핑 테스트."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from category_data.mappings import (
    PRODUCT_MAPPINGS,
    UNITS,
    get_categories_for_product,
    get_products_for_category,
    get_price_range,
    get_unit,
)


class TestProductMappingData:
    """상품 매핑 데이터 무결성."""

    def test_mapping_count(self):
        """충분한 매핑이 있어야 한다."""
        assert len(PRODUCT_MAPPINGS) >= 50

    def test_all_have_required_fields(self):
        """필수 필드 검증."""
        for pm in PRODUCT_MAPPINGS:
            assert "name" in pm
            assert "categories" in pm
            assert "unit" in pm
            assert isinstance(pm["categories"], list)
            assert len(pm["categories"]) > 0

    def test_units_valid(self):
        """모든 상품 단위가 UNITS 목록에 포함되어야 한다."""
        for pm in PRODUCT_MAPPINGS:
            assert pm["unit"] in UNITS, f"{pm['name']}: '{pm['unit']}' 이 UNITS에 없음"

    def test_price_range_valid(self):
        """가격 범위가 유효해야 한다 (min <= max)."""
        for pm in PRODUCT_MAPPINGS:
            if pm["min_price"] > 0 and pm["max_price"] > 0:
                assert pm["min_price"] <= pm["max_price"], \
                    f"{pm['name']}: min={pm['min_price']} > max={pm['max_price']}"


class TestProductCategoryLookup:
    """상품 → 카테고리 매핑 조회."""

    def test_samgyeopsal_category(self):
        """삼겹살의 카테고리."""
        cats = get_categories_for_product("삼겹살")
        assert "livestock.pork.belly" in cats

    def test_gyeran_category(self):
        """계란의 카테고리."""
        cats = get_categories_for_product("계란")
        assert "livestock.egg" in cats

    def test_kimchijjigae_multi_category(self):
        """김치찌개는 다중 카테고리."""
        cats = get_categories_for_product("김치찌개")
        assert len(cats) >= 2

    def test_alias_lookup(self):
        """alias 로도 조회 가능."""
        cats = get_categories_for_product("달걀")
        assert len(cats) > 0

    def test_unknown_product(self):
        """알 수 없는 상품은 빈 리스트."""
        cats = get_categories_for_product("존재하지않는상품xyz")
        assert cats == []


class TestCategoryProductLookup:
    """카테고리 → 상품 매핑 조회."""

    def test_pork_belly_products(self):
        """돼지삼겹살 카테고리의 상품."""
        products = get_products_for_category("livestock.pork.belly")
        names = [p["name"] for p in products]
        assert "삼겹살" in names

    def test_dairy_products(self):
        """유제품 카테고리 상품."""
        products = get_products_for_category("dairy.milk.plain")
        names = [p["name"] for p in products]
        assert "우유" in names


class TestPriceRange:
    """가격 범위 조회."""

    def test_samgyeopsal_price_range(self):
        """삼겹살 가격 범위."""
        pr = get_price_range("삼겹살")
        assert pr is not None
        assert pr["min_price"] > 0
        assert pr["max_price"] > pr["min_price"]
        assert pr["unit"] == "g"

    def test_unknown_price_range(self):
        """알 수 없는 상품의 가격 범위는 None."""
        assert get_price_range("존재하지않는상품") is None

    def test_get_unit(self):
        """상품 단위 조회."""
        assert get_unit("계란") == "구"
        assert get_unit("우유") == "mL"
        assert get_unit("쌀") == "kg"
