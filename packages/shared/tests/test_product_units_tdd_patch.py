"""Test improvements for robust unit normalization supporting Korean and typo variants."""
from __future__ import annotations

import pytest
from core.product_units import (
    parse_package_quantity,
    quantity_to_grams,
    quantity_to_standard_total,
    extract_product_attributes,
    normalize_unit_metadata,
)


class TestUnitNormalizationWithKoreanVariants:
    """Tests for Korean language unit handling in normalize_unit()."""

    def test_korean_liter_variants_normalize_to_uppercase_L(self) -> None:
        # Korean: 리터 should map to L (used in quantity_to_standard_total)
        result = quantity_to_standard_total(2.0, "리터", bundle_count=1)
        assert result == (2.0, "L"), "Korean 리터 should normalize to L"

    def test_korean_milliliter_variants_normalize_to_lowercase_ml(self) -> None:
        # Korean: 미리리터 should map to ml
        result = quantity_to_standard_total(500.0, "미리리터", bundle_count=1)
        assert result == (0.5, "L"), "Korean 미리리터 should normalize to ml then convert to L"

    def test_korean_gram_variants_normalize_to_lowercase_g(self) -> None:
        # Korean: 그램 should map to g
        result = quantity_to_grams(100.0, "그램")
        assert result == 100.0, "Korean 그램 should normalize to g"

    def test_korean_kilogram_variants_normalize_to_lowercase_kg(self) -> None:
        # Korean: 킬로그램 should map to kg
        result = quantity_to_grams(1.5, "킬로그램")
        assert result == 1500.0, "Korean 킬로그램 should normalize to kg"


class TestUnitNormalizationWithEnglishVariants:
    """Tests for full English unit names."""

    def test_english_liter_normalizes_to_uppercase_L(self) -> None:
        result = quantity_to_standard_total(1.0, "liter", bundle_count=1)
        assert result == (1.0, "L"), "'liter' should normalize to L"

    def test_english_milliliter_normalizes_to_lowercase_ml(self) -> None:
        result = quantity_to_standard_total(250.0, "milliliter", bundle_count=1)
        assert result == (0.25, "L"), "'milliliter' should normalize to ml"

    def test_english_gram_normalizes_to_lowercase_g(self) -> None:
        result = quantity_to_grams(50.0, "gram")
        assert result == 50.0, "'gram' should normalize to g"

    def test_english_kilogram_normalizes_to_lowercase_kg(self) -> None:
        result = quantity_to_grams(2.0, "kilogram")
        assert result == 2000.0, "'kilogram' should normalize to kg"


class TestUnitNormalizationWithCommonTypos:
    """Tests for defensive handling of keyboard typos."""

    def test_double_lowercase_l_typo_normalizes_to_uppercase_L(self) -> None:
        # ll (two lowercase L) is a common typo
        result = quantity_to_standard_total(1.0, "ll", bundle_count=1)
        assert result == (1.0, "L"), "Typo 'll' should normalize to L"

    def test_uppercase_LL_typo_normalizes_to_uppercase_L(self) -> None:
        # LL (uppercase) is a less common but possible typo
        result = quantity_to_standard_total(1.0, "LL", bundle_count=1)
        assert result == (1.0, "L"), "Typo 'LL' should normalize to L"

    def test_mml_typo_normalizes_to_ml(self) -> None:
        # mml is a keyboard typo (m pressed twice)
        result = quantity_to_standard_total(100.0, "mml", bundle_count=1)
        assert result == (0.1, "L"), "Typo 'mml' should normalize to ml"


class TestExtractProductAttributesWithMoreStorageVariants:
    """Tests for storage attribute detection."""

    def test_common_ambient_produce_detected(self) -> None:
        result = extract_product_attributes("고산지 사과 1.3kg 봉")
        assert result["storage_type"] == "ambient"
        assert result["storage_label"] == "상온"

    def test_chilled_storage_preserved(self) -> None:
        result = extract_product_attributes("냉장 소시지 300g")
        assert result["storage_type"] == "chilled"
        assert result["storage_label"] == "냉장"

    def test_frozen_storage_preserved(self) -> None:
        result = extract_product_attributes("냉동 만두 500g")
        assert result["storage_type"] == "frozen"
        assert result["storage_label"] == "냉동"


class TestExtractProductAttributesWithMoreCutVariants:
    """Tests for expanded meat cut detection."""

    def test_standard_cuts_detected(self) -> None:
        result = extract_product_attributes("불고기 300g")
        assert result.get("cut") == "bulgogi"
        
        result = extract_product_attributes("돼지고기 등심 500g")
        assert result.get("cut") == "sirloin"
        
        result = extract_product_attributes("삼겹살 구이용 400g")
        assert result.get("cut") == "pork_belly"

    def test_unknown_cuts_not_detected(self) -> None:
        # Should not falsely detect cuts not in the hints
        result = extract_product_attributes("소고기 반찬")
        assert result.get("cut") is None


class TestPackageQuantityParsingUnchanged:
    """Ensure existing regex-based parsing still works after normalization changes."""

    def test_weight_units_still_parse_correctly(self) -> None:
        # Original functionality must not break
        assert parse_package_quantity("300g") == {
            "raw_match": "300g",
            "package_quantity": 300.0,
            "package_unit": "g",
            "display_unit": "300g",
        }
        
        assert parse_package_quantity("(200g)") == {
            "raw_match": "(200g)",
            "package_quantity": 200.0,
            "package_unit": "g",
            "display_unit": "200g",
        }
        
        assert parse_package_quantity("1.5L") == {
            "raw_match": "1.5L",
            "package_quantity": 1.5,
            "package_unit": "L",
            "display_unit": "1.5L",
        }

    def test_count_units_still_parse_correctly(self) -> None:
        # Count packages should not be affected
        assert parse_package_quantity("10마리") == {
            "raw_match": "10마리",
            "package_quantity": 10.0,
            "package_unit": "마리",
            "display_unit": "10마리",
        }


class TestUnitNormalizationRobustness:
    """Integration tests for full normalize_unit_metadata flow."""

    def test_korean_units_in_raw_unit_field(self) -> None:
        parsed = normalize_unit_metadata(
            name="소시지",
            sale_price=5000,
            raw_unit="그램"
        )
        # raw_unit with Korean term should not crash
        assert "package_quantity" in parsed
        assert "package_unit" in parsed or parsed["package_quantity"] is None

    def test_mixed_typo_units_handled(self) -> None:
        parsed = normalize_unit_metadata(
            name="우유 1L",
            sale_price=3000,
            raw_unit="ll"  # Typo
        )
        # Should not crash, should handle gracefully
        assert isinstance(parsed, dict)
        assert "attributes" in parsed


@pytest.mark.parametrize("unit_string,expected_normalized", [
    # Korean variants
    ("리터", "L"),
    ("미리리터", "ml"),
    ("그램", "g"),
    ("킬로그램", "kg"),
    # English variants  
    ("liter", "L"),
    ("litre", "L"),
    ("milliliter", "ml"),
    ("millilitre", "ml"),
    ("gram", "g"),
    ("kilogram", "kg"),
    # Typos
    ("ll", "L"),
    ("LL", "L"),
    ("mml", "ml"),
    # Standard cases (unchanged)
    ("L", "L"),
    ("ml", "ml"),
    ("g", "g"),
    ("kg", "kg"),
])
def test_normalize_unit_comprehensive(unit_string: str, expected_normalized: str) -> None:
    """Comprehensive parametrized test for all unit normalization cases."""
    # Use quantity_to_grams as proxy to test _normalize_unit indirectly
    if expected_normalized in ("g", "kg"):
        result = quantity_to_grams(100.0, unit_string)
        if expected_normalized == "g":
            assert result == 100.0, f"Failed for {unit_string}"
        else:  # kg
            assert result == 100000.0, f"Failed for {unit_string}"
    else:
        result = quantity_to_standard_total(100.0, unit_string)
        if expected_normalized == "L":
            assert result == (100.0, "L"), f"Failed for {unit_string}"
        else:  # ml
            assert result == (0.1, "L"), f"Failed for {unit_string}"
