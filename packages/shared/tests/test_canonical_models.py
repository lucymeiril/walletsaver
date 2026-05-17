"""
test_canonical_models.py — Pydantic v2 canonical 모델 테스트.

테스트 전략:
  1) 직렬화/역직렬화 (model → JSON → model)
  2) 해시 결정성 (같은 입력 → 항상 같은 id)
  3) 4사 fixture에서 추출한 실제 데이터로 모델 생성 (통합 테스트 1개씩)
  4) enum 유효성 검증
  5) nullable 필드 동작 확인

fixture 파일 경로: packages/crawler-admin/backend/tests/fixtures/
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# shared 패키지를 sys.path에 추가 (pytest pythonpath=. 와 호환)
SHARED_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(SHARED_ROOT))

from core.canonical_models import (
    CanonicalProduct,
    CategoryNodeSchema,
    MartKind,
    MartSkuAlias,
    PriceObservation,
    ProductReviewQueue,
    ReviewReason,
    UnitPriceBasis,
)

# fixture 기본 경로
FIXTURE_BASE = (
    Path(__file__).parent.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)


# ══════════════════════════════════════════════════════
# 헬퍼
# ══════════════════════════════════════════════════════

def _payload_hash(payload: dict) -> str:
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _now() -> datetime:
    return datetime.now()


# ══════════════════════════════════════════════════════
# CanonicalProduct — 기본 직렬화/역직렬화
# ══════════════════════════════════════════════════════

class TestCanonicalProductSerialize:
    def test_build_factory_sets_correct_id(self):
        p = CanonicalProduct.build(
            brand="풀무원",
            name_core="부침두부",
            pack_quantity=340.0,
            pack_unit="g",
        )
        expected = hashlib.sha1(
            "풀무원|부침두부|340.000000|g".encode("utf-8")
        ).hexdigest()
        assert p.id == expected

    def test_roundtrip_json(self):
        p = CanonicalProduct.build(
            brand="농심",
            name_core="신라면",
            pack_quantity=120.0,
            pack_unit="g",
        )
        json_str = p.model_dump_json()
        p2 = CanonicalProduct.model_validate_json(json_str)
        assert p.id == p2.id
        assert p.name_core == p2.name_core
        assert p.pack_quantity == p2.pack_quantity

    def test_nullable_brand(self):
        p = CanonicalProduct.build(
            brand=None,
            name_core="양배추",
            pack_quantity=800.0,
            pack_unit="g",
        )
        assert p.brand is None
        data = p.model_dump()
        p2 = CanonicalProduct(**data)
        assert p2.brand is None

    def test_nullable_category(self):
        p = CanonicalProduct.build(
            brand=None,
            name_core="굴비",
            pack_quantity=1.0,
            pack_unit="개",
        )
        assert p.category_path_internal is None

    def test_nullable_image_url(self):
        p = CanonicalProduct.build(
            brand=None,
            name_core="양말",
            pack_quantity=6.0,
            pack_unit="족",
        )
        assert p.representative_image_url is None


# ══════════════════════════════════════════════════════
# CanonicalProduct — 해시 결정성
# ══════════════════════════════════════════════════════

class TestCanonicalProductHashDeterminism:
    def test_same_inputs_same_id(self):
        id1 = CanonicalProduct.make_id("풀무원", "부침두부", 340.0, "g")
        id2 = CanonicalProduct.make_id("풀무원", "부침두부", 340.0, "g")
        assert id1 == id2

    def test_different_brand_different_id(self):
        id1 = CanonicalProduct.make_id("풀무원", "두부", 340.0, "g")
        id2 = CanonicalProduct.make_id("CJ", "두부", 340.0, "g")
        assert id1 != id2

    def test_none_brand_vs_empty_string_same_treatment(self):
        """None과 "" 브랜드는 같은 id를 생성해야 한다 (null 혼동 방지)."""
        id1 = CanonicalProduct.make_id(None, "두부", 340.0, "g")
        id2 = CanonicalProduct.make_id("", "두부", 340.0, "g")
        assert id1 == id2

    def test_different_pack_unit_different_id(self):
        id1 = CanonicalProduct.make_id("", "두부", 340.0, "g")
        id2 = CanonicalProduct.make_id("", "두부", 340.0, "개")
        assert id1 != id2

    def test_different_pack_qty_different_id(self):
        id1 = CanonicalProduct.make_id("", "두부", 340.0, "g")
        id2 = CanonicalProduct.make_id("", "두부", 300.0, "g")
        assert id1 != id2

    def test_id_is_40_char_hex(self):
        cid = CanonicalProduct.make_id("브랜드", "상품", 1.0, "개")
        assert len(cid) == 40
        assert all(c in "0123456789abcdef" for c in cid)


# ══════════════════════════════════════════════════════
# MartSkuAlias
# ══════════════════════════════════════════════════════

class TestMartSkuAlias:
    def test_roundtrip(self):
        alias = MartSkuAlias(
            id="alias-001",
            canonical_id="aabbcc" * 6 + "aabb",
            mart=MartKind.EMART,
            mart_item_id="1000641687348",
            mart_item_name_raw="[농할 20%쿠폰] 한끼 양배추 800g 통",
            source_url="https://emart.ssg.com/item/itemView.ssg?itemId=1000641687348",
            first_seen_at=_now(),
            last_seen_at=_now(),
        )
        data = alias.model_dump_json()
        alias2 = MartSkuAlias.model_validate_json(data)
        assert alias2.mart == MartKind.EMART
        assert alias2.mart_item_id == "1000641687348"

    def test_mart_enum_values(self):
        for mart in MartKind:
            alias = MartSkuAlias(
                id=f"alias-{mart.value}",
                canonical_id="a" * 40,
                mart=mart,
                mart_item_id="item001",
                mart_item_name_raw="테스트상품",
                first_seen_at=_now(),
                last_seen_at=_now(),
            )
            assert alias.mart == mart


# ══════════════════════════════════════════════════════
# PriceObservation
# ══════════════════════════════════════════════════════

class TestPriceObservation:
    def test_roundtrip(self):
        obs = PriceObservation(
            id="obs-001",
            canonical_id="a" * 40,
            mart=MartKind.HOMEPLUS,
            regular_price=10900,
            sale_price=4900,
            on_sale=True,
            discount_rate=55,
            unit_price_normalized=5.0,
            unit_price_basis=UnitPriceBasis.PER_EACH,
            observed_at=_now(),
            source_url=None,
            raw_payload_hash="b" * 40,
            event_labels=["상품할인"],
        )
        data = obs.model_dump_json()
        obs2 = PriceObservation.model_validate_json(data)
        assert obs2.sale_price == 4900
        assert obs2.on_sale is True
        assert obs2.discount_rate == 55

    def test_nullable_regular_price(self):
        """코스트코처럼 정가 미표시 상품은 regular_price=None."""
        obs = PriceObservation(
            id="obs-002",
            canonical_id="a" * 40,
            mart=MartKind.COSTCO,
            regular_price=None,
            sale_price=35990,
            on_sale=False,
            discount_rate=None,
            unit_price_normalized=3099.0,
            unit_price_basis=UnitPriceBasis.PER_100ML,
            observed_at=_now(),
            raw_payload_hash="c" * 40,
        )
        assert obs.regular_price is None
        assert obs.discount_rate is None

    def test_event_labels_default_empty(self):
        obs = PriceObservation(
            id="obs-003",
            canonical_id="a" * 40,
            mart=MartKind.LOTTEMART,
            sale_price=6990,
            on_sale=True,
            observed_at=_now(),
            raw_payload_hash="d" * 40,
        )
        assert obs.event_labels == []

    def test_unit_price_basis_default_unknown(self):
        obs = PriceObservation(
            id="obs-004",
            canonical_id="a" * 40,
            mart=MartKind.COUPANG,
            sale_price=5000,
            on_sale=False,
            observed_at=_now(),
            raw_payload_hash="e" * 40,
        )
        assert obs.unit_price_basis == UnitPriceBasis.UNKNOWN


# ══════════════════════════════════════════════════════
# ProductReviewQueue
# ══════════════════════════════════════════════════════

class TestProductReviewQueue:
    def test_roundtrip(self):
        item = ProductReviewQueue(
            id="queue-001",
            raw_payload={"itemId": "xyz", "itemName": "테스트"},
            source_mart=MartKind.EMART,
            reason=ReviewReason.CATEGORY_UNKNOWN,
            created_at=_now(),
        )
        data = item.model_dump_json()
        item2 = ProductReviewQueue.model_validate_json(data)
        assert item2.reason == ReviewReason.CATEGORY_UNKNOWN
        assert item2.resolved_at is None
        assert item2.resolver_user_id is None

    def test_all_review_reasons(self):
        for reason in ReviewReason:
            item = ProductReviewQueue(
                id=f"queue-{reason.value}",
                raw_payload={},
                source_mart=MartKind.HOMEPLUS,
                reason=reason,
                created_at=_now(),
            )
            assert item.reason == reason


# ══════════════════════════════════════════════════════
# CategoryNodeSchema
# ══════════════════════════════════════════════════════

class TestCategoryNodeSchema:
    def test_roundtrip(self):
        node = CategoryNodeSchema(
            id="cat-001",
            parent_id=None,
            name_kr="정육ㆍ계란",
            name_slug="meat-eggs",
            level=1,
            path="/정육ㆍ계란",
            display_order=1,
        )
        data = node.model_dump_json()
        node2 = CategoryNodeSchema.model_validate_json(data)
        assert node2.parent_id is None
        assert node2.level == 1


# ══════════════════════════════════════════════════════
# 4사 fixture 통합 테스트
# ══════════════════════════════════════════════════════

class TestEmartFixtureIntegration:
    """이마트 fixture에서 첫 번째 상품을 추출해 CanonicalProduct + PriceObservation 생성."""

    def test_emart_first_item(self):
        fixture_path = FIXTURE_BASE / "emart" / "sale_listing_5cards.json"
        with open(fixture_path, encoding="utf-8") as f:
            raw = json.load(f)

        area_list = raw["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["areaList"]
        item = area_list[0]["dataList"][0]

        # 이마트: finalPrice, strikeOutPrice는 "2,784" 형식 콤마 문자열
        sale_price = int(item["finalPrice"].replace(",", ""))
        regular_price_str = item.get("strikeOutPrice", "")
        regular_price = int(regular_price_str.replace(",", "")) if regular_price_str else None
        discount_rate = int(item["discountRate"]) if item.get("discountRate") else None
        on_sale = (regular_price is not None and regular_price > sale_price)

        name_raw = item["itemName"]
        brand = item.get("brandName") or None
        if brand == "":
            brand = None

        # CanonicalProduct 생성
        product = CanonicalProduct.build(
            brand=brand,
            name_core=name_raw,  # B4에서 정규화 예정
            pack_quantity=1.0,
            pack_unit="개",
            representative_image_url=item.get("itemImgUrl"),
        )
        assert product.id is not None
        assert len(product.id) == 40
        assert product.name_core == name_raw

        # PriceObservation 생성
        payload_hash = _payload_hash(item)
        obs = PriceObservation(
            id=f"emart-{item['itemId']}-{payload_hash[:8]}",
            canonical_id=product.id,
            mart=MartKind.EMART,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=discount_rate,
            source_url=item.get("itemUrl"),
            raw_payload_hash=payload_hash,
            event_labels=[],
            observed_at=_now(),
        )
        assert obs.sale_price == 2784
        assert obs.regular_price == 3480
        assert obs.on_sale is True
        assert obs.discount_rate == 20
        assert obs.mart == MartKind.EMART


class TestHomeplusFixtureIntegration:
    """홈플러스 fixture에서 첫 번째 상품을 추출해 모델 생성."""

    def test_homeplus_first_item(self):
        fixture_path = FIXTURE_BASE / "homeplus" / "sale_listing_5items_dc_mixed.json"
        with open(fixture_path, encoding="utf-8") as f:
            raw = json.load(f)

        item = raw["data"]["dataList"][0]

        sale_price = item["dcPrice"] if item.get("dcPrice") is not None else item["salePrice"]
        regular_price = item["salePrice"]
        dc_rate = item.get("dcRate")
        on_sale = item.get("dcPrice") is not None

        event_labels = [e["label"] for e in item.get("eventFlagList", [])]

        product = CanonicalProduct.build(
            brand=item.get("brandNm") or None,
            name_core=item["itemNm"],
            pack_quantity=float(item["totalUnitQty"]) if item.get("totalUnitQty") else 1.0,
            pack_unit=item.get("unitMeasure", "개"),
        )
        assert len(product.id) == 40

        payload_hash = _payload_hash(item)
        obs = PriceObservation(
            id=f"homeplus-{item['itemNo']}-{payload_hash[:8]}",
            canonical_id=product.id,
            mart=MartKind.HOMEPLUS,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=dc_rate,
            unit_price_normalized=float(item["unitPrice"]) if item.get("unitPrice") else None,
            unit_price_basis=UnitPriceBasis.PER_EACH,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=event_labels,
        )
        assert obs.mart == MartKind.HOMEPLUS
        assert obs.sale_price == 4900
        assert obs.discount_rate == 55
        assert "상품할인" in obs.event_labels


class TestLottemartFixtureIntegration:
    """롯데마트 fixture에서 첫 번째 상품을 추출해 모델 생성."""

    def test_lottemart_first_item(self):
        from bs4 import BeautifulSoup

        fixture_path = FIXTURE_BASE / "lottemart" / "hydrated_5cards.html"
        with open(fixture_path, encoding="utf-8") as f:
            content = f.read()

        # window.__INITIAL_STATE__ = {...}; 추출
        start = content.index("window.__INITIAL_STATE__ = ") + len("window.__INITIAL_STATE__ = ")
        end = content.rindex("};") + 1
        state = json.loads(content[start:end])

        products = state["data"]["products"]["productEntities"]
        pid = next(iter(products))
        item = products[pid]

        price_current = item["price"]["current"]["amount"]
        price_original = item["price"].get("original", {})
        regular_price = price_original.get("amount") if price_original else None
        on_sale = regular_price is not None and regular_price > price_current
        discount_rate = None
        if on_sale and regular_price:
            discount_rate = round((1 - price_current / regular_price) * 100)

        unit_label = item["price"].get("unit", {}).get("label", "")
        if "100gram" in unit_label:
            basis = UnitPriceBasis.PER_100G
        elif "each" in unit_label:
            basis = UnitPriceBasis.PER_EACH
        else:
            basis = UnitPriceBasis.UNKNOWN

        unit_current = item["price"].get("unit", {}).get("current", {})
        unit_price = float(unit_current["amount"]) if unit_current else None

        category_path = item.get("categoryPath", [])
        offers = item.get("offers", [])
        event_labels = [o["description"] for o in offers]

        product = CanonicalProduct.build(
            brand=item.get("brand") or None,
            name_core=item["name"].strip(),
            pack_quantity=1.0,
            pack_unit="개",
            representative_image_url=item.get("image", {}).get("src"),
        )
        assert len(product.id) == 40

        payload_hash = _payload_hash(item)
        obs = PriceObservation(
            id=f"lottemart-{pid[:8]}-{payload_hash[:8]}",
            canonical_id=product.id,
            mart=MartKind.LOTTEMART,
            regular_price=regular_price,
            sale_price=price_current,
            on_sale=on_sale,
            discount_rate=discount_rate,
            unit_price_normalized=unit_price,
            unit_price_basis=basis,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=event_labels,
        )
        assert obs.mart == MartKind.LOTTEMART
        assert obs.sale_price > 0


class TestCostcoFixtureIntegration:
    """코스트코 fixture에서 첫 번째 상품을 추출해 모델 생성."""

    def test_costco_first_item(self):
        from bs4 import BeautifulSoup
        import re

        fixture_path = FIXTURE_BASE / "costco" / "special_offers_5cards.html"
        with open(fixture_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        items = soup.select("li.product-list-item")
        assert len(items) > 0
        item = items[0]

        a = item.select_one("a.thumb")
        title = a["title"]
        href = a["href"]
        # href: /Category/SubCat/ProductName/p/{id}
        prod_id = href.rstrip("/").split("/p/")[-1]

        price_el = item.select_one(".product-price-amount")
        price_text = price_el.get_text(strip=True).replace(",", "").replace("원", "").strip()
        sale_price = int(price_text)

        orig_el = item.select_one(".original-price")
        orig_text = orig_el.get_text(strip=True).replace(",", "").replace("원", "").strip() if orig_el else ""
        regular_price = int(orig_text) if orig_text else None
        on_sale = (regular_price is not None and regular_price > sale_price)

        unit_el = item.select_one(".product-price-pre-unit-amount")
        unit_text = unit_el.get_text(strip=True) if unit_el else ""
        # "100㎖당 3,099원" or "한 개당 318원"
        unit_price = None
        unit_basis = UnitPriceBasis.UNKNOWN
        if unit_text:
            m = re.search(r"([\d,]+)원", unit_text)
            if m:
                unit_price = float(m.group(1).replace(",", ""))
            if "㎖" in unit_text or "ml" in unit_text.lower():
                unit_basis = UnitPriceBasis.PER_100ML
            elif "개" in unit_text:
                unit_basis = UnitPriceBasis.PER_EACH

        raw = {"title": title, "href": href, "sale_price": sale_price}
        payload_hash = _payload_hash(raw)

        product = CanonicalProduct.build(
            brand=None,
            name_core=title,
            pack_quantity=1.0,
            pack_unit="개",
        )
        assert len(product.id) == 40

        obs = PriceObservation(
            id=f"costco-{prod_id}-{payload_hash[:8]}",
            canonical_id=product.id,
            mart=MartKind.COSTCO,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=None,  # 코스트코는 할인율 미제공
            unit_price_normalized=unit_price,
            unit_price_basis=unit_basis,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=[],
        )
        assert obs.mart == MartKind.COSTCO
        assert obs.sale_price == 35990
        # 코스트코 첫 상품은 정가 = 현재가 (미할인)
        assert obs.on_sale is False
        assert obs.discount_rate is None
        assert obs.unit_price_normalized == 3099.0
        assert obs.unit_price_basis == UnitPriceBasis.PER_100ML
