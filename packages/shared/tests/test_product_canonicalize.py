"""
B4 product_canonicalize.py TDD 테스트.

4사 fixture에서 각 5건씩 → 총 20건 canonicalize.
검증 항목:
  - 모든 행이 CanonicalizationResult 반환 (None 아님)
  - 4사 합쳐 unique canonical_id 개수 = 20
  - 멱등성: 같은 raw 두 번 통과 → 같은 canonical_id
  - 표기 변형 회귀 (340G / 340g / 340 g)
  - 머리표 변형 회귀 ([프로모] 유무)
  - 이마트 5건 → queue_entry에 EMART_NO_CATEGORY 포함, canonical 생성
  - 코스트코 메가롤 단위 정책 (ROLL, qty=60) 회귀
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from core.canonical_models import MartKind, ReviewReason
from core.product_canonicalize import (
    CanonicalizationResult,
    canonicalize_costco,
    canonicalize_emart,
    canonicalize_homeplus,
    canonicalize_lottemart,
    derive_canonical_key,
    extract_quantity_token,
    merge_into_canonical,
    parse_costco_cards_from_html,
    parse_product_name,
    strip_promo_brackets,
)
from core.units import UnitKind

# ─────────────────────────────────────────────────────────────────────────────
# Fixture 경로
# ─────────────────────────────────────────────────────────────────────────────

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "crawler-admin" / "backend" / "tests" / "fixtures"
_EMART_FIXTURE = _FIXTURE_DIR / "emart" / "sale_listing_5cards.json"
_HOMEPLUS_FIXTURE = _FIXTURE_DIR / "homeplus" / "sale_listing_5items_dc_mixed.json"
_LOTTEMART_FIXTURE = _FIXTURE_DIR / "lottemart" / "hydrated_5cards.html"
_COSTCO_FIXTURE = _FIXTURE_DIR / "costco" / "special_offers_5cards.html"

NOW = datetime(2025, 7, 1, 0, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture 로더
# ─────────────────────────────────────────────────────────────────────────────

def _load_emart_items() -> list[dict]:
    with open(_EMART_FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    return (
        data["props"]["pageProps"]["dehydratedState"]
        ["queries"][0]["state"]["data"]["areaList"][0]["dataList"]
    )


def _load_homeplus_items() -> list[dict]:
    with open(_HOMEPLUS_FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    return data["data"]["dataList"]


def _load_lottemart_items() -> list[dict]:
    with open(_LOTTEMART_FIXTURE, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", content, re.DOTALL)
    assert m, "INITIAL_STATE not found in lottemart fixture"
    data = json.loads(m.group(1))
    entities = data["data"]["products"]["productEntities"]
    return list(entities.values())


def _load_costco_items() -> list[dict]:
    with open(_COSTCO_FIXTURE, encoding="utf-8") as f:
        content = f.read()
    return parse_costco_cards_from_html(content)


# ─────────────────────────────────────────────────────────────────────────────
# 이름 파서 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestStripPromoBrackets:
    def test_removes_leading_bracket(self):
        result = strip_promo_brackets("[농할 20%쿠폰 상세 다운] 한끼 양배추 800g 통")
        assert result == "한끼 양배추 800g 통"

    def test_removes_refrigeration_bracket(self):
        result = strip_promo_brackets("[냉장] 언양식 소불고기 500g")
        assert result == "언양식 소불고기 500g"

    def test_removes_price_bracket(self):
        result = strip_promo_brackets("[농할할인가 6,990원]  행복생생란 (특란, 30입) (1.8KG)")
        assert result.startswith("행복생생란")

    def test_no_bracket_unchanged(self):
        result = strip_promo_brackets("철원 오대쌀 10kg")
        assert result == "철원 오대쌀 10kg"


class TestExtractQuantityToken:
    def test_gram_inline(self):
        qty, unit, cleaned = extract_quantity_token("언양식 소불고기 500g")
        assert qty == 500.0
        assert unit == UnitKind.GRAM

    def test_kilogram_inline(self):
        qty, unit, cleaned = extract_quantity_token("철원 오대쌀 10kg")
        assert qty == 10.0
        assert unit == UnitKind.KILOGRAM

    def test_gram_paren_end(self):
        qty, unit, cleaned = extract_quantity_token("국산 부침두부 (340G)")
        assert qty == 340.0
        assert unit == UnitKind.GRAM

    def test_piece_paren(self):
        qty, unit, cleaned = extract_quantity_token("행복생생란 (특란, 30입) (1.8KG)")
        # PIECE 우선 — 계란은 개수가 primary
        assert qty == 30.0
        assert unit == UnitKind.PIECE

    def test_each_ea_paren(self):
        qty, unit, cleaned = extract_quantity_token("골드키위 (EA)")
        assert qty == 1.0
        assert unit == UnitKind.EACH

    def test_each_개_paren(self):
        qty, unit, cleaned = extract_quantity_token("파프리카 (개)")
        assert qty == 1.0
        assert unit == UnitKind.EACH

    def test_double_multiply_sheet_roll(self):
        """잘풀리는집 키친타월 150매*6롤 → 900 SHEET"""
        qty, unit, cleaned = extract_quantity_token("키친타월 150매*6롤")
        assert qty == pytest.approx(900.0)
        assert unit == UnitKind.SHEET

    def test_triple_multiply_meter_roll(self):
        """크리넥스 메가롤 40m x 30롤 x 2 → 60 ROLL (단위 정책)"""
        qty, unit, cleaned = extract_quantity_token("순수소프트 메가롤 40m x 30롤 x 2")
        assert qty == pytest.approx(60.0)
        assert unit == UnitKind.ROLL

    def test_double_multiply_ml_count(self):
        """500ml x 2입 → 1000 ML"""
        qty, unit, cleaned = extract_quantity_token("아토덤 울트라 크림 500ml x 2입")
        assert qty == pytest.approx(1000.0)
        assert unit == UnitKind.MILLILITER

    def test_tablet_정(self):
        """84정 → PIECE"""
        qty, unit, cleaned = extract_quantity_token("임팩타뮨 84정")
        assert qty == pytest.approx(84.0)
        assert unit == UnitKind.PIECE

    def test_bundle_봉_paren(self):
        """(봉) → BUNDLE 1개 → 실제로 이름에서 fallback UNKNOWN 후 tail 제거"""
        qty, unit, cleaned = extract_quantity_token("씨없는 아삭 파프리카(봉)")
        # 봉 is BUNDLE
        assert unit == UnitKind.BUNDLE
        assert qty == 1.0

    def test_gram_case_insensitive(self):
        """340G == 340g == 340 g → 같은 canonical_id"""
        q1, u1, _ = extract_quantity_token("부침두부 (340G)")
        q2, u2, _ = extract_quantity_token("부침두부 (340g)")
        assert q1 == q2
        assert u1 == u2


class TestParseProductName:
    def test_emart_양배추(self):
        parsed = parse_product_name("[농할 20%쿠폰 상세 다운] 한끼 양배추 800g 통")
        assert parsed.brand is None
        assert "양배추" in parsed.name_core
        assert parsed.pack_quantity == pytest.approx(800.0)
        assert parsed.pack_unit == UnitKind.GRAM

    def test_emart_소고기(self):
        parsed = parse_product_name("[냉장] 언양식 소불고기 500g")
        assert parsed.brand is None
        assert "소불고기" in parsed.name_core
        assert parsed.pack_quantity == pytest.approx(500.0)
        assert parsed.pack_unit == UnitKind.GRAM

    def test_homeplus_키친타월_brand(self):
        parsed = parse_product_name("잘풀리는집 천연펄프 2겹 키친타월 150매*6롤")
        assert parsed.brand == "잘풀리는집"
        assert "키친타월" in parsed.name_core
        assert parsed.pack_quantity == pytest.approx(900.0)
        assert parsed.pack_unit == UnitKind.SHEET

    def test_homeplus_믹스넛_brand(self):
        parsed = parse_product_name("머거본 믹스파티 프렌즈 800G(통)")
        assert parsed.brand == "머거본"
        assert parsed.pack_quantity == pytest.approx(800.0)
        assert parsed.pack_unit == UnitKind.GRAM

    def test_lottemart_두부_brand(self):
        parsed = parse_product_name("풀무원 국산 부침두부 (340G)")
        assert parsed.brand == "풀무원"
        assert "부침두부" in parsed.name_core
        assert parsed.pack_quantity == pytest.approx(340.0)
        assert parsed.pack_unit == UnitKind.GRAM

    def test_lottemart_CJ짬뽕(self):
        parsed = parse_product_name("CJ 고메 중화짬뽕 (2인분) (652G)")
        assert parsed.brand == "CJ"
        assert parsed.pack_quantity == pytest.approx(652.0)
        assert parsed.pack_unit == UnitKind.GRAM

    def test_costco_bioderma(self):
        parsed = parse_product_name("바이오더마 아토덤 울트라 크림 500ml x 2입")
        assert parsed.brand == "바이오더마"
        assert parsed.pack_quantity == pytest.approx(1000.0)
        assert parsed.pack_unit == UnitKind.MILLILITER

    def test_costco_크리넥스_메가롤(self):
        parsed = parse_product_name("크리넥스 순수소프트 메가롤 40m x 30롤 x 2")
        assert parsed.brand == "크리넥스"
        assert parsed.pack_quantity == pytest.approx(60.0)
        assert parsed.pack_unit == UnitKind.ROLL

    def test_costco_대웅제약(self):
        parsed = parse_product_name("대웅제약 임팩타뮨 84정")
        assert parsed.brand == "대웅제약"
        assert parsed.pack_quantity == pytest.approx(84.0)
        assert parsed.pack_unit == UnitKind.PIECE

    def test_costco_스탠리(self):
        parsed = parse_product_name("스탠리 폴딩 핸드트럭 (2 IN 1)")
        assert parsed.brand == "스탠리"
        # qty 파싱 불가 → UNKNOWN (fallback 은 canonicalize 단계에서)
        # name_core는 비어있지 않아야 함
        assert len(parsed.name_core) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 표기 변형 회귀 테스트 (canonical_id 동일성)
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalIdVariants:
    """같은 상품의 다른 표기가 같은 canonical_id를 생성해야 한다."""

    def test_gram_case_variants(self):
        """'340G' vs '340g' vs '340 g' → 같은 canonical_id"""
        ids = []
        for variant in ["풀무원 국산 부침두부 (340G)", "풀무원 국산 부침두부 (340g)", "풀무원 국산 부침두부 (340 g)"]:
            parsed = parse_product_name(variant)
            cid = derive_canonical_key(
                parsed.brand, parsed.name_core, parsed.pack_quantity, parsed.pack_unit
            )
            ids.append(cid)
        assert ids[0] == ids[1] == ids[2], f"ID mismatch: {ids}"

    def test_promo_bracket_variants(self):
        """'[농할 20%] 한끼 양배추 800g 통' vs '한끼 양배추 800g 통' → 같은 canonical_id"""
        p1 = parse_product_name("[농할 20%] 한끼 양배추 800g 통")
        p2 = parse_product_name("한끼 양배추 800g 통")
        cid1 = derive_canonical_key(p1.brand, p1.name_core, p1.pack_quantity, p1.pack_unit)
        cid2 = derive_canonical_key(p2.brand, p2.name_core, p2.pack_quantity, p2.pack_unit)
        assert cid1 == cid2, f"Promo bracket variant mismatch: {cid1} != {cid2}"

    def test_refrigeration_bracket_variant(self):
        """'[냉장] 언양식 소불고기 500g' vs '언양식 소불고기 500g' → 같은 canonical_id"""
        p1 = parse_product_name("[냉장] 언양식 소불고기 500g")
        p2 = parse_product_name("언양식 소불고기 500g")
        cid1 = derive_canonical_key(p1.brand, p1.name_core, p1.pack_quantity, p1.pack_unit)
        cid2 = derive_canonical_key(p2.brand, p2.name_core, p2.pack_quantity, p2.pack_unit)
        assert cid1 == cid2

    def test_idempotency_same_raw(self):
        """같은 raw를 두 번 통과 → 같은 canonical_id"""
        emart_items = _load_emart_items()
        r1 = canonicalize_emart(emart_items[0], NOW)
        r2 = canonicalize_emart(emart_items[0], NOW)
        assert r1.canonical is not None
        assert r2.canonical is not None
        assert r1.canonical.id == r2.canonical.id


# ─────────────────────────────────────────────────────────────────────────────
# 단위 정책 회귀
# ─────────────────────────────────────────────────────────────────────────────

class TestMegaRollPolicy:
    """코스트코 메가롤 단위 정책 회귀: qty=60 ROLL"""

    def test_megaroll_unit_is_roll(self):
        parsed = parse_product_name("크리넥스 순수소프트 메가롤 40m x 30롤 x 2")
        assert parsed.pack_unit == UnitKind.ROLL
        assert parsed.pack_quantity == pytest.approx(60.0)

    def test_deco_soft_unit_is_roll(self):
        parsed = parse_product_name("크리넥스 데코&소프트 3겹 화장지 40m x 30롤 x 2")
        assert parsed.pack_unit == UnitKind.ROLL
        assert parsed.pack_quantity == pytest.approx(60.0)


# ─────────────────────────────────────────────────────────────────────────────
# 이마트 5건 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalizeEmart:
    @pytest.fixture
    def emart_results(self) -> list[CanonicalizationResult]:
        items = _load_emart_items()
        return [canonicalize_emart(item, NOW) for item in items]

    def test_returns_5_results(self, emart_results):
        assert len(emart_results) == 5

    def test_all_results_not_none(self, emart_results):
        for r in emart_results:
            assert r is not None, "CanonicalizationResult must never be None"

    def test_all_have_canonical(self, emart_results):
        """이마트 5건 모두 canonical 생성 (EMART_NO_CATEGORY 는 canonical 차단 안 함)"""
        for r in emart_results:
            assert r.canonical is not None, f"Canonical should not be None. reasons={r.reasons}"

    def test_all_have_queue_entry(self, emart_results):
        """이마트 5건 모두 queue_entry 생성 (EMART_NO_CATEGORY)"""
        for r in emart_results:
            assert r.queue_entry is not None, "Queue entry expected for EMART_NO_CATEGORY"

    def test_all_have_emart_no_category_reason(self, emart_results):
        for r in emart_results:
            assert "EMART_NO_CATEGORY" in r.reasons, f"Expected EMART_NO_CATEGORY in {r.reasons}"

    def test_queue_reason_is_category_unknown(self, emart_results):
        for r in emart_results:
            assert r.queue_entry.reason == ReviewReason.CATEGORY_UNKNOWN

    def test_5_unique_canonical_ids(self, emart_results):
        ids = {r.canonical.id for r in emart_results}
        assert len(ids) == 5, f"Expected 5 unique IDs, got {len(ids)}: {ids}"

    def test_mart_kind_is_emart(self, emart_results):
        for r in emart_results:
            assert r.sku_alias.mart == MartKind.EMART

    def test_prices_extracted(self, emart_results):
        for r in emart_results:
            assert r.price_obs is not None
            assert r.price_obs.sale_price > 0

    def test_양배추_parsed(self, emart_results):
        # 첫 번째 item: "[농할 20%쿠폰 상세 다운] 한끼 양배추 800g 통"
        r = emart_results[0]
        assert r.canonical is not None
        assert "양배추" in r.canonical.name_core
        assert r.canonical.pack_quantity == pytest.approx(800.0)
        assert r.canonical.pack_unit == UnitKind.GRAM.value

    def test_소불고기_parsed(self, emart_results):
        # 네 번째 item: "[냉장] 언양식 소불고기 500g"
        r = emart_results[3]
        assert "소불고기" in r.canonical.name_core
        assert r.canonical.pack_quantity == pytest.approx(500.0)


# ─────────────────────────────────────────────────────────────────────────────
# 홈플러스 5건 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalizeHomeplus:
    @pytest.fixture
    def hp_results(self) -> list[CanonicalizationResult]:
        items = _load_homeplus_items()
        return [canonicalize_homeplus(item, NOW) for item in items]

    def test_returns_5_results(self, hp_results):
        assert len(hp_results) == 5

    def test_all_results_not_none(self, hp_results):
        for r in hp_results:
            assert r is not None

    def test_all_have_canonical(self, hp_results):
        for r in hp_results:
            assert r.canonical is not None, f"reasons={r.reasons}"

    def test_5_unique_canonical_ids(self, hp_results):
        ids = {r.canonical.id for r in hp_results}
        assert len(ids) == 5

    def test_키친타월_brand_and_qty(self, hp_results):
        r = hp_results[0]  # "잘풀리는집 천연펄프 2겹 키친타월 150매*6롤"
        assert r.canonical.brand == "잘풀리는집"
        assert "키친타월" in r.canonical.name_core
        assert r.canonical.pack_quantity == pytest.approx(900.0)
        assert r.canonical.pack_unit == UnitKind.SHEET.value

    def test_믹스넛_brand(self, hp_results):
        r = hp_results[1]  # "머거본 믹스파티 프렌즈 800G(통)"
        assert r.canonical.brand == "머거본"
        assert r.canonical.pack_quantity == pytest.approx(800.0)

    def test_all_category_mapped(self, hp_results):
        """홈플러스 5건 모두 카테고리 매핑 성공"""
        for r in hp_results:
            assert "CATEGORY_UNMAPPED" not in r.reasons, f"Category unmapped: {r.reasons}"

    def test_sale_prices(self, hp_results):
        for r in hp_results:
            assert r.price_obs.sale_price > 0

    def test_on_sale_item(self, hp_results):
        # 첫 번째 item은 dcPrice 있음 → on_sale
        r = hp_results[0]
        assert r.price_obs.on_sale is True


# ─────────────────────────────────────────────────────────────────────────────
# 롯데마트 5건 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalizeLottemart:
    @pytest.fixture
    def lm_results(self) -> list[CanonicalizationResult]:
        items = _load_lottemart_items()
        return [canonicalize_lottemart(item, NOW) for item in items]

    def test_returns_5_results(self, lm_results):
        assert len(lm_results) == 5

    def test_all_results_not_none(self, lm_results):
        for r in lm_results:
            assert r is not None

    def test_all_have_canonical(self, lm_results):
        for r in lm_results:
            assert r.canonical is not None, f"reasons={r.reasons}"

    def test_5_unique_canonical_ids(self, lm_results):
        ids = {r.canonical.id for r in lm_results}
        assert len(ids) == 5

    def test_두부_brand_qty(self, lm_results):
        # "풀무원 국산 부침두부 (340G)"
        r = next(r for r in lm_results if r.sku_alias.mart_item_id == "OS8801114119426")
        assert r.canonical.brand == "풀무원"
        assert r.canonical.pack_quantity == pytest.approx(340.0)
        assert r.canonical.pack_unit == UnitKind.GRAM.value

    def test_CJ짬뽕_brand(self, lm_results):
        # "CJ 고메 중화짬뽕 (2인분) (652G)"
        r = next(r for r in lm_results if r.sku_alias.mart_item_id == "OS8801007761350")
        assert r.canonical.brand == "CJ"
        assert r.canonical.pack_quantity == pytest.approx(652.0)

    def test_계란_qty_piece(self, lm_results):
        # "행복생생란 (특란, 30입) (1.8KG)" → 30 PIECE
        r = next(r for r in lm_results if r.sku_alias.mart_item_id == "OS8809214203632")
        assert r.canonical.pack_quantity == pytest.approx(30.0)
        assert r.canonical.pack_unit == UnitKind.PIECE.value

    def test_all_category_mapped(self, lm_results):
        for r in lm_results:
            assert "CATEGORY_UNMAPPED" not in r.reasons

    def test_mart_kind_is_lottemart(self, lm_results):
        for r in lm_results:
            assert r.sku_alias.mart == MartKind.LOTTEMART


# ─────────────────────────────────────────────────────────────────────────────
# 코스트코 5건 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestCanonicalizeCostco:
    @pytest.fixture
    def cc_results(self) -> list[CanonicalizationResult]:
        items = _load_costco_items()
        return [canonicalize_costco(item, NOW) for item in items]

    def test_fixture_has_5_cards(self):
        items = _load_costco_items()
        assert len(items) == 5

    def test_returns_5_results(self, cc_results):
        assert len(cc_results) == 5

    def test_all_results_not_none(self, cc_results):
        for r in cc_results:
            assert r is not None

    def test_all_have_canonical(self, cc_results):
        for r in cc_results:
            assert r.canonical is not None, f"reasons={r.reasons}"

    def test_5_unique_canonical_ids(self, cc_results):
        ids = {r.canonical.id for r in cc_results}
        assert len(ids) == 5, f"Expected 5 unique IDs, got {len(ids)}"

    def test_bioderma_brand_qty(self, cc_results):
        r = cc_results[0]  # "바이오더마 아토덤 울트라 크림 500ml x 2입"
        assert r.canonical.brand == "바이오더마"
        assert r.canonical.pack_quantity == pytest.approx(1000.0)
        assert r.canonical.pack_unit == UnitKind.MILLILITER.value

    def test_megaroll_unit_policy(self, cc_results):
        """메가롤 정책: qty=60 ROLL (30롤 x 2)"""
        r = cc_results[3]  # "크리넥스 순수소프트 메가롤 40m x 30롤 x 2"
        assert r.canonical.pack_quantity == pytest.approx(60.0)
        assert r.canonical.pack_unit == UnitKind.ROLL.value

    def test_크리넥스_brand(self, cc_results):
        r = cc_results[3]
        assert r.canonical.brand == "크리넥스"

    def test_all_on_sale(self, cc_results):
        """특가 페이지 = 모두 on_sale"""
        for r in cc_results:
            assert r.price_obs.on_sale is True

    def test_all_category_mapped(self, cc_results):
        for r in cc_results:
            assert "CATEGORY_UNMAPPED" not in r.reasons, f"Category unmapped: {r.reasons}"

    def test_대웅제약_84정(self, cc_results):
        r = cc_results[1]  # "대웅제약 임팩타뮨 84정"
        assert r.canonical.brand == "대웅제약"
        assert r.canonical.pack_quantity == pytest.approx(84.0)
        assert r.canonical.pack_unit == UnitKind.PIECE.value


# ─────────────────────────────────────────────────────────────────────────────
# 20건 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestAll20Items:
    @pytest.fixture
    def all_results(self) -> list[CanonicalizationResult]:
        emart = [canonicalize_emart(i, NOW) for i in _load_emart_items()]
        hp = [canonicalize_homeplus(i, NOW) for i in _load_homeplus_items()]
        lm = [canonicalize_lottemart(i, NOW) for i in _load_lottemart_items()]
        cc = [canonicalize_costco(i, NOW) for i in _load_costco_items()]
        return emart + hp + lm + cc

    def test_total_20_results(self, all_results):
        assert len(all_results) == 20

    def test_all_results_not_none(self, all_results):
        for r in all_results:
            assert r is not None

    def test_all_have_canonical(self, all_results):
        for r in all_results:
            assert r.canonical is not None, f"Canonical is None: reasons={r.reasons}"

    def test_20_unique_canonical_ids(self, all_results):
        """4사 fixture의 모든 상품이 서로 다른 canonical_id를 가져야 한다."""
        ids = [r.canonical.id for r in all_results]
        unique_ids = set(ids)
        assert len(unique_ids) == 20, (
            f"Expected 20 unique IDs, got {len(unique_ids)}. Duplicates: "
            + str([cid for cid in unique_ids if ids.count(cid) > 1])
        )

    def test_all_have_price_obs(self, all_results):
        for r in all_results:
            assert r.price_obs is not None

    def test_all_sale_prices_positive(self, all_results):
        for r in all_results:
            assert r.price_obs.sale_price > 0, f"sale_price=0 for {r.sku_alias.mart_item_name_raw}"

    def test_merge_into_canonical_20_groups(self, all_results):
        groups = merge_into_canonical(all_results)
        assert len(groups) == 20

    def test_emart_always_has_queue_entry(self, all_results):
        emart_results = [r for r in all_results if r.sku_alias.mart == MartKind.EMART]
        for r in emart_results:
            assert r.queue_entry is not None
            assert "EMART_NO_CATEGORY" in r.reasons

    def test_payload_hash_not_empty(self, all_results):
        for r in all_results:
            assert r.price_obs.raw_payload_hash, "raw_payload_hash should not be empty"

    def test_sku_alias_canonical_id_matches(self, all_results):
        for r in all_results:
            assert r.sku_alias.canonical_id == r.canonical.id


# ─────────────────────────────────────────────────────────────────────────────
# derive_canonical_key / merge_into_canonical 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestDeriveCanonicalKey:
    def test_deterministic(self):
        k1 = derive_canonical_key("풀무원", "국산 부침두부", 340.0, UnitKind.GRAM)
        k2 = derive_canonical_key("풀무원", "국산 부침두부", 340.0, UnitKind.GRAM)
        assert k1 == k2

    def test_brand_none_vs_empty_same(self):
        """brand=None 과 brand="" 는 동일하게 처리 (CanonicalProduct.make_id 스펙)"""
        k1 = derive_canonical_key(None, "두부", 340.0, UnitKind.GRAM)
        k2 = derive_canonical_key("", "두부", 340.0, UnitKind.GRAM)
        # make_id: brand or '' → "" 동일하게 처리
        assert k1 == k2

    def test_different_brand_different_id(self):
        k1 = derive_canonical_key("풀무원", "두부", 340.0, UnitKind.GRAM)
        k2 = derive_canonical_key("CJ", "두부", 340.0, UnitKind.GRAM)
        assert k1 != k2

    def test_different_unit_different_id(self):
        k1 = derive_canonical_key(None, "쌀", 10.0, UnitKind.KILOGRAM)
        k2 = derive_canonical_key(None, "쌀", 10.0, UnitKind.GRAM)
        assert k1 != k2


class TestMergeIntoCanonical:
    def test_groups_by_canonical_id(self):
        emart_results = [canonicalize_emart(i, NOW) for i in _load_emart_items()]
        groups = merge_into_canonical(emart_results)
        # 5개 아이템 → 5개 그룹
        assert len(groups) == 5

    def test_none_canonical_excluded(self):
        """canonical=None 인 항목은 그루핑에서 제외"""
        dummy = CanonicalizationResult(
            canonical=None, sku_alias=None, price_obs=None,
            queue_entry=None, confidence=0.0, reasons=["UNIT_UNKNOWN"]
        )
        emart_results = [canonicalize_emart(i, NOW) for i in _load_emart_items()]
        groups = merge_into_canonical(emart_results + [dummy])
        assert len(groups) == 5  # dummy excluded
