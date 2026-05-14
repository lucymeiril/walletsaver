from __future__ import annotations

from core.product_units import normalize_unit_metadata, parse_package_quantity


def test_count_package_parser_handles_common_korean_non_weight_units() -> None:
    assert parse_package_quantity("황제 활 전복 특대 10마리") == {
        "raw_match": "10마리",
        "package_quantity": 10.0,
        "package_unit": "마리",
        "display_unit": "10마리",
    }
    assert parse_package_quantity("마스크팩 100매") == {
        "raw_match": "100매",
        "package_quantity": 100.0,
        "package_unit": "매",
        "display_unit": "100매",
    }
    assert parse_package_quantity("레몬즙 1박스 14포") == {
        "raw_match": "14포",
        "package_quantity": 14.0,
        "package_unit": "포",
        "display_unit": "14포",
    }


def test_count_package_parser_handles_parenthesized_single_count_units() -> None:
    assert parse_package_quantity("완도 전복(대) (마리)") == {
        "raw_match": "(마리)",
        "package_quantity": 1.0,
        "package_unit": "마리",
        "display_unit": "1마리",
    }
    assert parse_package_quantity("[농할할인가] 국내산 큰 양배추 (통)") == {
        "raw_match": "(통)",
        "package_quantity": 1.0,
        "package_unit": "통",
        "display_unit": "1통",
    }


def test_raw_unit_measure_is_used_when_title_has_no_package_but_reference_units_stay_display_only() -> None:
    parsed = normalize_unit_metadata(name="한글과자 초코맛 1봉지", raw_unit="10g", sale_price=1000)
    assert parsed["package_quantity"] == 1.0
    assert parsed["package_unit"] == "봉지"
    assert parsed["display_unit"] == "1봉지"

    parsed = normalize_unit_metadata(name="정육 1등급 윗등심살", raw_unit="100g", sale_price=4980)
    assert parsed["package_quantity"] is None
    assert parsed["package_unit"] is None
    assert parsed["display_unit"] is None

    parsed = normalize_unit_metadata(name="소용량 소스", raw_unit="80g", sale_price=1980)
    assert parsed["package_quantity"] == 80.0
    assert parsed["package_unit"] == "g"
    assert parsed["display_unit"] == "80g"


def test_measure_bundle_parser_prefers_total_packaging_over_trailing_count_units() -> None:
    parsed = normalize_unit_metadata(name="[기획] 모짜렐라 치즈볼 360g*2입", sale_price=8980)
    assert parsed["raw_match"] == "360g*2입"
    assert parsed["package_quantity"] == 360.0
    assert parsed["package_unit"] == "g"
    assert parsed["display_unit"] == "360g×2"
    assert parsed["bundle_count"] == 2
    assert parsed["price_per_100g"] == 1247.22

    parsed = normalize_unit_metadata(name="렌즈세정액 355ML*3", sale_price=12900)
    assert parsed["package_quantity"] == 355.0
    assert parsed["package_unit"] == "ml"
    assert parsed["display_unit"] == "355ml×3"
    assert parsed["bundle_count"] == 3


def test_measure_bundle_parser_does_not_treat_plus_formula_as_count_multiplier() -> None:
    parsed = normalize_unit_metadata(name="샴푸 100ml+100ml 기획", sale_price=3000)
    assert parsed["raw_match"] == "100ml"
    assert parsed["package_quantity"] == 100.0
    assert parsed["package_unit"] == "ml"
    assert "bundle_count" not in parsed


def test_korean_measure_words_parse_as_canonical_package_units() -> None:
    assert parse_package_quantity("처음보는 쌀과자 300그램") == {
        "raw_match": "300그램",
        "package_quantity": 300.0,
        "package_unit": "g",
        "display_unit": "300g",
    }

    parsed = normalize_unit_metadata(name="마트 PB 생수 2리터×6입", sale_price=3600)
    assert parsed["raw_match"] == "2리터×6입"
    assert parsed["package_quantity"] == 2.0
    assert parsed["package_unit"] == "L"
    assert parsed["display_unit"] == "2L×6"
    assert parsed["bundle_count"] == 6
