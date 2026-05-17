"""4사 + 쿠팡 단위 파서 회귀 테스트.

모든 케이스는 실측 fixture 값 기반:
  - 이마트:    packages/crawler-admin/backend/tests/fixtures/emart/sale_listing_5cards.json
  - 홈플러스:  packages/crawler-admin/backend/tests/fixtures/homeplus/sale_listing_5items_dc_mixed.json
               packages/crawler-admin/backend/tests/fixtures/homeplus/sale_listing_3items.json
  - 롯데마트:  packages/crawler-admin/backend/tests/fixtures/live_probe/lottemart_hydrated_productEntities_sample.json
  - 코스트코:  packages/crawler-admin/backend/tests/fixtures/costco/special_offers_5cards.html
"""
from __future__ import annotations

import pytest

from core.units import (
    NormalizedUnit,
    UnitKind,
    parse_costco_unit_text,
    parse_emart_capacity,
    parse_generic_korean,
    parse_homeplus_unit,
    parse_lottemart_unit_label,
    to_standard_basis,
    unit_price,
)


# ─────────────────────────────────────────────────────────────────────────────
# 이마트 (sellUnitCapacity)
# 실측 fixture: emart/sale_listing_5cards.json → areas[0].dataList
# ─────────────────────────────────────────────────────────────────────────────

class TestEmartCapacity:
    def test_gram_100(self) -> None:
        """감자 1.5kg 박스 → sellUnitCapacity="100g" (100g당 532원)"""
        r = parse_emart_capacity("100g")
        assert r is not None
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 100.0
        assert r.basis == "per_100g"

    def test_kilogram_1(self) -> None:
        """철원 오대쌀 10kg → sellUnitCapacity="1kg" (1kg당 4,498원)"""
        r = parse_emart_capacity("1kg")
        assert r is not None
        assert r.kind == UnitKind.KILOGRAM
        assert r.quantity == 1.0
        assert r.basis == "per_1kg"

    def test_each_1(self) -> None:
        """한끼 양배추 800g 통 → sellUnitCapacity="1개" (1개당 2,784원)"""
        r = parse_emart_capacity("1개")
        assert r is not None
        assert r.kind == UnitKind.EACH
        assert r.quantity == 1.0
        assert r.basis == "per_each"

    def test_none_returns_none(self) -> None:
        """sellUnitCapacity 필드 자체가 없는 상품 (파프리카봉) → None"""
        assert parse_emart_capacity(None) is None

    def test_empty_string_returns_unknown(self) -> None:
        """빈 문자열 → UNKNOWN (값 있지만 파싱 불가)"""
        r = parse_emart_capacity("")
        assert r is not None
        assert r.kind == UnitKind.UNKNOWN

    def test_bundle_1(self) -> None:
        """sellUnitCapacity="1봉" — 봉지 단위 상품"""
        r = parse_emart_capacity("1봉")
        assert r is not None
        assert r.kind == UnitKind.BUNDLE
        assert r.quantity == 1.0
        assert r.basis == "per_1봉"

    def test_pack_1(self) -> None:
        """sellUnitCapacity="1팩" — 팩 단위 상품 (PACK, EACH 와 다른 kind)"""
        r = parse_emart_capacity("1팩")
        assert r is not None
        assert r.kind == UnitKind.PACK
        assert r.quantity == 1.0
        assert r.basis == "per_1팩"

    def test_gram_100_with_whitespace(self) -> None:
        """공백 변형 허용: "100 g" """
        r = parse_emart_capacity("100 g")
        assert r is not None
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 100.0

    def test_noise_character_stripped(self) -> None:
        """≒ 노이즈 문자 제거 후 파싱"""
        r = parse_emart_capacity("≒100g")
        assert r is not None
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# 홈플러스 (unitMeasure / unitQty / totalUnitQty)
# 실측 fixture: homeplus/sale_listing_5items_dc_mixed.json + sale_listing_3items.json
# ─────────────────────────────────────────────────────────────────────────────

class TestHomeplusUnit:
    def test_sheet_매_900(self) -> None:
        """잘풀리는집 키친타월 150매*6롤 → unitMeasure="매", unitQty=1, totalUnitQty=900"""
        r = parse_homeplus_unit("매", 1, 900)
        assert r.kind == UnitKind.SHEET
        assert r.quantity == 900.0
        assert r.basis == "per_1매"

    def test_gram_G_800(self) -> None:
        """머거본 믹스파티 800G → unitMeasure="G", unitQty=100, totalUnitQty=800"""
        r = parse_homeplus_unit("G", 100, 800)
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 800.0
        assert r.basis == "per_100g"

    def test_gram_G_600(self) -> None:
        """호주청정우 불고기 600G → unitMeasure="G", unitQty=100, totalUnitQty=600"""
        r = parse_homeplus_unit("G", 100, 600)
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 600.0
        assert r.basis == "per_100g"

    def test_each_개_1(self) -> None:
        """영광 참굴비 (마리 아닌 개 단위 표기) → unitMeasure="개", unitQty=1, totalUnitQty=1"""
        r = parse_homeplus_unit("개", 1, 1)
        assert r.kind == UnitKind.EACH
        assert r.quantity == 1.0
        assert r.basis == "per_each"

    def test_milliliter_ML_1000(self) -> None:
        """simplus 엑스트라버진 올리브유 1L → unitMeasure="ML", unitQty=100, totalUnitQty=1000"""
        r = parse_homeplus_unit("ML", 100, 1000)
        assert r.kind == UnitKind.MILLILITER
        assert r.quantity == 1000.0
        assert r.basis == "per_100ml"

    def test_gram_G_520(self) -> None:
        """simplus 숯불닭꼬치 520G → unitMeasure="G", unitQty=100, totalUnitQty=520"""
        r = parse_homeplus_unit("G", 100, 520)
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 520.0
        assert r.basis == "per_100g"

    def test_gram_G_224_unitQty10(self) -> None:
        """허쉬 크림파이 224G → unitMeasure="G", unitQty=10, totalUnitQty=224 (10g 기준 비교)"""
        r = parse_homeplus_unit("G", 10, 224)
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 224.0
        assert r.basis == "per_10g"

    def test_none_unitQty_safe(self) -> None:
        """unitQty=None (unitDispYn="N" 상품) → qty=1 로 안전 처리"""
        r = parse_homeplus_unit("개", None, 0)  # type: ignore[arg-type]
        assert r.kind == UnitKind.EACH
        assert r.basis == "per_each"


# ─────────────────────────────────────────────────────────────────────────────
# 롯데마트 (price.unit.label)
# 실측 fixture: live_probe/lottemart_hydrated_productEntities_sample.json
# ─────────────────────────────────────────────────────────────────────────────

class TestLottemartUnitLabel:
    def test_per_100gram_egg(self) -> None:
        """행복생생란 (특란 30입) → label="fop.price.per.100gram", amount=389"""
        r = parse_lottemart_unit_label("fop.price.per.100gram", 389)
        assert r.kind == UnitKind.GRAM
        assert r.basis == "per_100g"

    def test_per_each_kiwi(self) -> None:
        """제스프리 골드키위 → label="fop.price.per.each", amount=1110"""
        r = parse_lottemart_unit_label("fop.price.per.each", 1110)
        assert r.kind == UnitKind.EACH
        assert r.basis == "per_each"

    def test_per_each_paprika(self) -> None:
        """국내산 파프리카 → label="fop.price.per.each", amount=1100"""
        r = parse_lottemart_unit_label("fop.price.per.each", 1100)
        assert r.kind == UnitKind.EACH
        assert r.basis == "per_each"

    def test_per_100gram_item4(self) -> None:
        """4번째 상품 → label="fop.price.per.100gram", amount=1468"""
        r = parse_lottemart_unit_label("fop.price.per.100gram", 1468)
        assert r.kind == UnitKind.GRAM
        assert r.basis == "per_100g"
        assert r.quantity == 100.0

    def test_per_100gram_item5(self) -> None:
        """5번째 상품 → label="fop.price.per.100gram", amount=1531"""
        r = parse_lottemart_unit_label("fop.price.per.100gram", 1531)
        assert r.kind == UnitKind.GRAM
        assert r.basis == "per_100g"

    def test_unknown_label_preserved(self) -> None:
        """알 수 없는 레이블 → UNKNOWN 반환, raw_text 보존"""
        r = parse_lottemart_unit_label("fop.price.per.newunit", 999)
        assert r.kind == UnitKind.UNKNOWN
        assert "fop.price.per.newunit" in r.raw_text

    def test_raw_text_preserved(self) -> None:
        """raw_text 는 항상 원본 label 문자열"""
        r = parse_lottemart_unit_label("fop.price.per.100gram", 389)
        assert r.raw_text == "fop.price.per.100gram"


# ─────────────────────────────────────────────────────────────────────────────
# 코스트코 (단위가격 문자열)
# 실측 fixture: costco/special_offers_5cards.html
# ─────────────────────────────────────────────────────────────────────────────

class TestCostcoUnitText:
    def test_milliliter_100(self) -> None:
        """바이오더마 아토덤 크림 500ml x 2 → 100㎖당 3,099원"""
        r = parse_costco_unit_text("100㎖당 3,099원")
        assert r.kind == UnitKind.MILLILITER
        assert r.quantity == 100.0
        assert r.basis == "per_100ml"

    def test_each_한개(self) -> None:
        """대웅제약 임팩타뮨 84정 → 한 개당 318원 (한국어 수사)"""
        r = parse_costco_unit_text("한 개당 318원")
        assert r.kind == UnitKind.EACH
        assert r.quantity == 1.0
        assert r.basis == "per_each"

    def test_meter_10_kleenex1(self) -> None:
        """크리넥스 순수소프트 40m x 30롤 x 2 → 10미터당 162원"""
        r = parse_costco_unit_text("10미터당 162원")
        assert r.kind == UnitKind.METER
        assert r.quantity == 10.0
        assert r.basis == "per_10m"

    def test_meter_10_kleenex2(self) -> None:
        """크리넥스 데코&소프트 → 10미터당 237원"""
        r = parse_costco_unit_text("10미터당 237원")
        assert r.kind == UnitKind.METER
        assert r.quantity == 10.0
        assert r.basis == "per_10m"

    def test_no_unit_text_returns_unknown(self) -> None:
        """단위가격 텍스트 없는 상품 (스탠리 핸드트럭) → UNKNOWN"""
        r = parse_costco_unit_text("93,900원")
        assert r.kind == UnitKind.UNKNOWN

    def test_empty_string(self) -> None:
        r = parse_costco_unit_text("")
        assert r.kind == UnitKind.UNKNOWN

    def test_raw_text_preserved(self) -> None:
        r = parse_costco_unit_text("100㎖당 3,099원")
        assert r.raw_text == "100㎖당 3,099원"


# ─────────────────────────────────────────────────────────────────────────────
# to_standard_basis
# ─────────────────────────────────────────────────────────────────────────────

class TestToStandardBasis:
    def test_gram_800_category_gram(self) -> None:
        """GRAM 800g 상품 + 카테고리 육류(GRAM) → per_100g 기준으로 basis 설정"""
        u = NormalizedUnit(kind=UnitKind.GRAM, quantity=800.0, basis="per_100g", raw_text="800g")
        result = to_standard_basis(u, UnitKind.GRAM)
        assert result.kind == UnitKind.GRAM
        assert result.quantity == 800.0
        assert result.basis == "per_100g"

    def test_kilogram_1_5_category_gram(self) -> None:
        """KILOGRAM 1.5kg → GRAM 1500g 변환 + per_100g basis"""
        u = NormalizedUnit(kind=UnitKind.KILOGRAM, quantity=1.5, basis="per_1kg", raw_text="1.5kg")
        result = to_standard_basis(u, UnitKind.GRAM)
        assert result.kind == UnitKind.GRAM
        assert result.quantity == pytest.approx(1500.0)
        assert result.basis == "per_100g"

    def test_kilogram_1_category_gram(self) -> None:
        """KILOGRAM 1.0kg → GRAM 1000g"""
        u = NormalizedUnit(kind=UnitKind.KILOGRAM, quantity=1.0, basis="per_1kg", raw_text="1kg")
        result = to_standard_basis(u, UnitKind.GRAM)
        assert result.kind == UnitKind.GRAM
        assert result.quantity == pytest.approx(1000.0)
        assert result.basis == "per_100g"

    def test_each_category_each(self) -> None:
        """EACH 1개 + 카테고리 계란(EACH) → per_each"""
        u = NormalizedUnit(kind=UnitKind.EACH, quantity=1.0, basis="per_each", raw_text="1개")
        result = to_standard_basis(u, UnitKind.EACH)
        assert result.kind == UnitKind.EACH
        assert result.basis == "per_each"

    def test_liter_to_milliliter(self) -> None:
        """LITER 1L + 카테고리 음료(MILLILITER) → MILLILITER 1000ml, per_100ml"""
        u = NormalizedUnit(kind=UnitKind.LITER, quantity=1.0, basis="per_1l", raw_text="1L")
        result = to_standard_basis(u, UnitKind.MILLILITER)
        assert result.kind == UnitKind.MILLILITER
        assert result.quantity == pytest.approx(1000.0)
        assert result.basis == "per_100ml"

    def test_raw_text_unchanged(self) -> None:
        """raw_text 는 변환 후에도 원본 유지"""
        u = NormalizedUnit(kind=UnitKind.GRAM, quantity=800.0, basis="per_100g", raw_text="orig")
        result = to_standard_basis(u, UnitKind.GRAM)
        assert result.raw_text == "orig"


# ─────────────────────────────────────────────────────────────────────────────
# unit_price
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitPrice:
    def test_gram_9980_800g(self) -> None:
        """9980원 / 800g → 100g당 1247.5원"""
        u = NormalizedUnit(kind=UnitKind.GRAM, quantity=800.0, basis="per_100g", raw_text="800g")
        assert unit_price(9980, u) == pytest.approx(1247.5)

    def test_each_30000_1each(self) -> None:
        """굴비 30,000원 / 1개 → 1개당 30,000원"""
        u = NormalizedUnit(kind=UnitKind.EACH, quantity=1.0, basis="per_each", raw_text="1개")
        assert unit_price(30000, u) == pytest.approx(30000.0)

    def test_sheet_10900_900sheets(self) -> None:
        """키친타월 10,900원 / 900매 → 1매당 ≈ 12.11원"""
        u = NormalizedUnit(kind=UnitKind.SHEET, quantity=900.0, basis="per_1매", raw_text="900매")
        assert unit_price(10900, u) == pytest.approx(10900 / 900)

    def test_meter_49990_2400m(self) -> None:
        """화장지 49,990원 / 2400m → 10m당 ≈ 208.3원"""
        u = NormalizedUnit(kind=UnitKind.METER, quantity=2400.0, basis="per_10m", raw_text="2400m")
        assert unit_price(49990, u) == pytest.approx(49990 * 10 / 2400)

    def test_zero_quantity_raises(self) -> None:
        """quantity=0 이면 ValueError"""
        u = NormalizedUnit(kind=UnitKind.GRAM, quantity=0.0, basis="per_100g", raw_text="")
        with pytest.raises(ValueError):
            unit_price(1000, u)

    def test_gram_after_standard_basis(self) -> None:
        """to_standard_basis 후 unit_price: 1.5kg 상품 총가 15000원 → 100g당 1000원"""
        raw_unit = NormalizedUnit(kind=UnitKind.KILOGRAM, quantity=1.5, basis="per_1kg", raw_text="1.5kg")
        std = to_standard_basis(raw_unit, UnitKind.GRAM)  # → GRAM 1500, per_100g
        assert unit_price(15000, std) == pytest.approx(15000 * 100 / 1500)


# ─────────────────────────────────────────────────────────────────────────────
# parse_generic_korean (쿠팡 fallback)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseGenericKorean:
    def test_emart_style_gram(self) -> None:
        """이마트 스타일 "100g" → GRAM"""
        r = parse_generic_korean("100g")
        assert r.kind == UnitKind.GRAM
        assert r.quantity == 100.0

    def test_costco_style_당(self) -> None:
        """코스트코 스타일 "10미터당 162원" → METER"""
        r = parse_generic_korean("10미터당 162원")
        assert r.kind == UnitKind.METER
        assert r.basis == "per_10m"

    def test_empty_returns_unknown(self) -> None:
        r = parse_generic_korean("")
        assert r.kind == UnitKind.UNKNOWN

    def test_unparseable_returns_unknown(self) -> None:
        """파싱 불가 노이즈 → UNKNOWN + raw_text 보존"""
        r = parse_generic_korean("≒한자漢字")
        assert r.kind == UnitKind.UNKNOWN
        assert r.raw_text == "≒한자漢字"

    def test_each_1개(self) -> None:
        r = parse_generic_korean("1개")
        assert r.kind == UnitKind.EACH


# ─────────────────────────────────────────────────────────────────────────────
# 엣지 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_emart_only_number_no_unit(self) -> None:
        """숫자만 있고 단위 없음 → UNKNOWN"""
        r = parse_emart_capacity("100")
        assert r is not None
        assert r.kind == UnitKind.UNKNOWN

    def test_emart_unknown_unit_string(self) -> None:
        """사전에 없는 단위어 → UNKNOWN + raw_text 보존"""
        r = parse_emart_capacity("1홉")  # 홉 = 미지원 단위
        assert r is not None
        assert r.kind == UnitKind.UNKNOWN
        assert r.raw_text == "1홉"

    def test_homeplus_unknown_measure(self) -> None:
        """사전에 없는 unitMeasure → UNKNOWN kind"""
        r = parse_homeplus_unit("홉", 1, 5)
        assert r.kind == UnitKind.UNKNOWN

    def test_costco_korean_number_두(self) -> None:
        """'두 개당' → EACH, quantity=2"""
        r = parse_costco_unit_text("두 개당 500원")
        assert r.kind == UnitKind.EACH
        assert r.quantity == 2.0

    def test_emart_decimal_quantity(self) -> None:
        """소수점 수량: "1.5kg" → KILOGRAM 1.5"""
        r = parse_emart_capacity("1.5kg")
        assert r is not None
        assert r.kind == UnitKind.KILOGRAM
        assert r.quantity == 1.5

    def test_lottemart_no_fop_prefix(self) -> None:
        """prefix 없이 직접 suffix → 동일하게 파싱 가능"""
        r = parse_lottemart_unit_label("100gram", 500)
        assert r.kind == UnitKind.GRAM
        assert r.basis == "per_100g"

    def test_unit_price_basis_1kg(self) -> None:
        """per_1kg basis → 전체가 / 수량kg × 1"""
        u = NormalizedUnit(kind=UnitKind.KILOGRAM, quantity=10.0, basis="per_1kg", raw_text="10kg")
        assert unit_price(44980, u) == pytest.approx(44980 / 10)
