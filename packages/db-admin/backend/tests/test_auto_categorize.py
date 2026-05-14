"""auto_categorize 모듈 종합 테스트.

실행: cd walletSavior && $env:PYTHONPATH = "packages\\shared;packages\\db-admin\\backend"
      py -m pytest packages/db-admin/backend/tests/test_auto_categorize.py -v
"""

from __future__ import annotations

import pytest
from services.auto_categorize import (
    auto_categorize,
    parse_product_name,
    match_category,
    disambiguate,
    extract_attributes,
    CategorizeResult,
    ParseResult,
    CategoryMatch,
    KNOWN_BRANDS,
    BRAND_CATEGORY_HINTS,
)


# ──────────────────────────────────────────────
# Test 1: 보먹돼 목심 100G/돼지고기(목살) → livestock.pork.neck
# ──────────────────────────────────────────────

class TestPorkNeck:
    def test_categorize(self):
        result = auto_categorize("보먹돼 목심 100G/돼지고기(목살)")
        assert result.category_id is not None
        assert result.category_id.startswith("livestock.pork")
        assert result.confidence >= 0.85

    def test_brand_extraction(self):
        result = auto_categorize("보먹돼 목심 100G/돼지고기(목살)")
        assert result.brand == "보먹돼"

    def test_keywords_contain_meat_terms(self):
        parsed = parse_product_name("보먹돼 목심 100G/돼지고기(목살)")
        assert any(kw in ("목심", "돼지고기", "목살") for kw in parsed.keywords)


# ──────────────────────────────────────────────
# Test 2: 한돈 YBD 황금돼지 삼겹살 100G/돼지고기
# ──────────────────────────────────────────────

class TestPorkBelly:
    def test_categorize(self):
        result = auto_categorize("한돈 YBD 황금돼지 삼겹살 100G/돼지고기")
        assert result.category_id is not None
        assert result.category_id.startswith("livestock.pork")
        assert result.confidence >= 0.85

    def test_brand(self):
        result = auto_categorize("한돈 YBD 황금돼지 삼겹살 100G/돼지고기")
        # 한돈, YBD, 황금돼지 are all known brands
        assert result.brand is not None


# ──────────────────────────────────────────────
# Test 3: [냉장] 앞다리살 보쌈/수육용 1kg → attributes
# ──────────────────────────────────────────────

class TestAttributeExtraction:
    def test_storage_and_weight(self):
        result = auto_categorize("[냉장] 앞다리살 보쌈/수육용 1kg")
        assert result.attributes.get("storage") == "냉장"
        assert result.attributes.get("weight_g") == 1000

    def test_category(self):
        result = auto_categorize("[냉장] 앞다리살 보쌈/수육용 1kg")
        assert result.category_id is not None
        assert "livestock" in result.category_id or "pork" in result.category_id

    def test_usage(self):
        result = auto_categorize("[냉장] 앞다리살 보쌈/수육용 1kg")
        assert result.attributes.get("usage") in ("보쌈", "수육")


# ──────────────────────────────────────────────
# Test 4: 드라이빗 뿌리볼륨 드라이 앞머리 미용실 → NOT livestock
# ──────────────────────────────────────────────

class TestDisambiguation:
    def test_not_livestock(self):
        result = auto_categorize("드라이빗 뿌리볼륨 드라이 앞머리 미용실 웨이브컬 롤빗 특가")
        if result.category_id:
            assert not result.category_id.startswith("livestock"), \
                f"Should not be livestock but got {result.category_id}"

    def test_brand_identified(self):
        result = auto_categorize("드라이빗 뿌리볼륨 드라이 앞머리 미용실 웨이브컬 롤빗 특가")
        assert result.brand == "드라이빗"


# ──────────────────────────────────────────────
# Test 5: 맥심 모카골드 커피믹스 100T 특가 → beverage.coffee
# ──────────────────────────────────────────────

class TestCoffeeMix:
    def test_categorize(self):
        result = auto_categorize("맥심 모카골드 커피믹스 100T 특가")
        assert result.category_id is not None
        assert "beverage.coffee" in result.category_id or "coffee" in result.category_id

    def test_count_attribute(self):
        result = auto_categorize("맥심 모카골드 커피믹스 100T 특가")
        assert result.attributes.get("count") == 100

    def test_brand(self):
        result = auto_categorize("맥심 모카골드 커피믹스 100T 특가")
        assert result.brand == "맥심"


# ──────────────────────────────────────────────
# Test 6: [GS25] 빙그레 바나나맛우유 240ml 2개 → dairy.milk
# ──────────────────────────────────────────────

class TestBananaMilk:
    def test_categorize(self):
        result = auto_categorize("[GS25] 빙그레 바나나맛우유 240ml 2개")
        assert result.category_id is not None
        assert result.category_id.startswith("dairy") or result.category_id.startswith("beverage")

    def test_brand(self):
        result = auto_categorize("[GS25] 빙그레 바나나맛우유 240ml 2개")
        assert result.brand == "빙그레"

    def test_weight(self):
        result = auto_categorize("[GS25] 빙그레 바나나맛우유 240ml 2개")
        assert result.attributes.get("weight_ml") == 240


# ──────────────────────────────────────────────
# Test 7: Empty string → None, confidence=0
# ──────────────────────────────────────────────

class TestEmpty:
    def test_empty_string(self):
        result = auto_categorize("")
        assert result.category_id is None
        assert result.confidence == 0.0

    def test_none_input(self):
        result = auto_categorize(None)
        assert result.category_id is None
        assert result.confidence == 0.0

    def test_whitespace_only(self):
        result = auto_categorize("   ")
        assert result.category_id is None
        assert result.confidence == 0.0


# ──────────────────────────────────────────────
# Test 8: ★행사★[제주직송][공육사] 제주돼지 앞다리살 500g [구이 용]
# ──────────────────────────────────────────────

class TestNoisyPork:
    def test_categorize(self):
        result = auto_categorize("★행사★[제주직송][공육사] 제주돼지 앞다리살 500g [구이 용]")
        assert result.category_id is not None
        assert result.category_id.startswith("livestock.pork")

    def test_origin(self):
        result = auto_categorize("★행사★[제주직송][공육사] 제주돼지 앞다리살 500g [구이 용]")
        assert result.attributes.get("origin") in ("제주", "제주직송", "제주산")

    def test_weight(self):
        result = auto_categorize("★행사★[제주직송][공육사] 제주돼지 앞다리살 500g [구이 용]")
        assert result.attributes.get("weight_g") == 500


# ──────────────────────────────────────────────
# Test 9: Brand extraction — 보먹돼 identified
# ──────────────────────────────────────────────

class TestBrandExtraction:
    def test_bomukdwae(self):
        assert "보먹돼" in KNOWN_BRANDS

    def test_brand_in_result(self):
        result = auto_categorize("보먹돼 삼겹살 100g")
        assert result.brand == "보먹돼"

    def test_known_brands_comprehensive(self):
        for brand in ("YBD", "피코크", "노브랜드", "빙그레", "하림", "드라이빗"):
            assert brand in KNOWN_BRANDS, f"{brand} should be in KNOWN_BRANDS"


# ──────────────────────────────────────────────
# Test 10: Never raises exception
# ──────────────────────────────────────────────

class TestNeverRaises:
    def test_garbage_input(self):
        result = auto_categorize("!@#$%^&*()_+{}|:<>?")
        assert isinstance(result, CategorizeResult)

    def test_very_long_input(self):
        result = auto_categorize("가" * 10000)
        assert isinstance(result, CategorizeResult)

    def test_numeric_input(self):
        result = auto_categorize("12345")
        assert isinstance(result, CategorizeResult)

    def test_mixed_unicode(self):
        result = auto_categorize("🔥💯삼겹살🎉 특가!!!")
        assert isinstance(result, CategorizeResult)

    def test_returns_categorize_result_always(self):
        inputs = [
            "", None, "   ", "???", "한글만", "English only",
            "12345", "★★★", "[](){}",
        ]
        for inp in inputs:
            result = auto_categorize(inp)
            assert isinstance(result, CategorizeResult), f"Failed for input: {inp!r}"


# ──────────────────────────────────────────────
# ParseResult detailed tests
# ──────────────────────────────────────────────

class TestParseProductName:
    def test_noise_removal(self):
        parsed = parse_product_name("★행사★ 삼겹살 특가")
        assert "★" not in parsed.cleaned_name
        assert "행사" not in " ".join(parsed.keywords)

    def test_bracket_extraction(self):
        parsed = parse_product_name("[냉장] 삼겹살 (목살)")
        assert "냉장" not in parsed.cleaned_name or parsed.attributes.get("storage") == "냉장"

    def test_separator_split(self):
        parsed = parse_product_name("100G/돼지고기")
        assert "돼지고기" in parsed.keywords

    def test_attribute_weight_kg(self):
        attrs = extract_attributes("삼겹살 1.5kg")
        assert attrs.get("weight_g") == 1500

    def test_attribute_ml(self):
        attrs = extract_attributes("우유 500ml")
        assert attrs.get("weight_ml") == 500

    def test_attribute_grade(self):
        attrs = extract_attributes("한우 1++ 등심")
        assert attrs.get("grade") == "1++"


# ──────────────────────────────────────────────
# CategoryMatch tests
# ──────────────────────────────────────────────

class TestMatchCategory:
    def test_exact_keyword_match(self):
        matches = match_category(["삼겹살"])
        cat_ids = [m.category_id for m in matches]
        assert any("livestock.pork.belly" in c for c in cat_ids)

    def test_synonym_match(self):
        matches = match_category(["돼지목살"])
        cat_ids = [m.category_id for m in matches]
        assert any("livestock.pork" in c for c in cat_ids)

    def test_mapping_match(self):
        matches = match_category(["커피믹스"])
        cat_ids = [m.category_id for m in matches]
        assert any("beverage.coffee" in c for c in cat_ids)

    def test_empty_keywords(self):
        matches = match_category([])
        assert matches == []


# ──────────────────────────────────────────────
# Brand category hints
# ──────────────────────────────────────────────

class TestBrandCategoryHints:
    def test_binggrae_dairy(self):
        assert BRAND_CATEGORY_HINTS.get("빙그레") == "dairy"

    def test_harim_chicken(self):
        assert BRAND_CATEGORY_HINTS.get("하림") == "livestock.chicken"

    def test_dongwon_seafood(self):
        assert BRAND_CATEGORY_HINTS.get("동원") == "seafood"


# ──────────────────────────────────────────────
# Confidence and auto_assigned
# ──────────────────────────────────────────────

class TestConfidence:
    def test_confidence_capped_at_1(self):
        result = auto_categorize("삼겹살 돼지고기 돼지삼겹살 구이용삼겹살 삼겹")
        assert result.confidence <= 1.0

    def test_auto_assigned_high_confidence(self):
        result = auto_categorize("보먹돼 목심 100G/돼지고기(목살)")
        if result.confidence >= 0.85:
            assert result.auto_assigned is True

    def test_candidates_top5(self):
        result = auto_categorize("삼겹살 돼지고기")
        assert len(result.candidates) <= 5


# ──────────────────────────────────────────────
# Source context
# ──────────────────────────────────────────────

class TestSourceContext:
    def test_emart_food_bonus(self):
        result_no_source = auto_categorize("삼겹살")
        result_emart = auto_categorize("삼겹살", source="emart")
        # emart source should give food categories a bonus
        assert result_emart.confidence >= result_no_source.confidence
