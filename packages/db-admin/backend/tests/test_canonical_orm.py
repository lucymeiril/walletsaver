"""
test_canonical_orm.py — SQLAlchemy 2.x canonical ORM 테스트.

테스트 전략:
  1) create_all: CanonicalBase.metadata로 인메모리 SQLite 생성
  2) insert + query: 각 모델 기본 CRUD
  3) cascade: CanonicalProduct 삭제 시 MartSkuAlias, PriceObservation 연쇄 삭제
  4) UNIQUE 제약 위반: MartSkuAlias (mart, mart_item_id) 중복 삽입
  5) 4사 fixture 통합 테스트: 실제 fixture → ORM insert → query

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
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, Session

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.canonical_models import (
    CanonicalBase,
    CanonicalProduct,
    CategoryNode,
    MartKindEnum,
    MartSkuAlias,
    PriceObservation,
    ProductReviewQueue,
    ReviewReasonEnum,
    UnitPriceBasisEnum,
    bootstrap_canonical_tables,
)

FIXTURE_BASE = (
    Path(__file__).parent.parent.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    bootstrap_canonical_tables(eng)
    return eng


@pytest.fixture
def session(engine) -> Session:
    SessionFactory = sessionmaker(bind=engine)
    with SessionFactory() as s:
        yield s


def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _payload_hash(payload: dict) -> str:
    return _sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _canonical_id(brand, name_core, pack_qty, pack_unit):
    raw = f"{brand or ''}|{name_core}|{pack_qty:.6f}|{pack_unit}"
    return _sha1(raw)


def _now():
    return datetime.now()


# ══════════════════════════════════════════════════════
# create_all
# ══════════════════════════════════════════════════════

def test_create_all_creates_all_tables(engine):
    """bootstrap_canonical_tables 가 모든 5개 테이블을 생성하는지 확인."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    expected = {
        "canonical_products",
        "canonical_category_nodes",
        "canonical_mart_sku_aliases",
        "canonical_price_observations",
        "canonical_product_review_queue",
    }
    assert expected.issubset(tables), f"누락된 테이블: {expected - tables}"


def test_bootstrap_idempotent(engine):
    """두 번 호출해도 오류 없이 동작 (CREATE TABLE IF NOT EXISTS)."""
    bootstrap_canonical_tables(engine)  # 두 번째 호출
    from sqlalchemy import inspect
    insp = inspect(engine)
    assert "canonical_products" in insp.get_table_names()


# ══════════════════════════════════════════════════════
# CanonicalProduct CRUD
# ══════════════════════════════════════════════════════

class TestCanonicalProductOrm:
    def test_insert_and_query(self, session):
        cid = _canonical_id(None, "양배추", 800.0, "g")
        product = CanonicalProduct(
            id=cid,
            brand=None,
            name_core="양배추",
            pack_quantity=800.0,
            pack_unit="g",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(product)
        session.commit()

        result = session.execute(
            select(CanonicalProduct).where(CanonicalProduct.id == cid)
        ).scalar_one()
        assert result.name_core == "양배추"
        assert result.brand is None
        assert result.pack_quantity == 800.0

    def test_nullable_fields(self, session):
        cid = _canonical_id(None, "굴비", 1.0, "개")
        product = CanonicalProduct(
            id=cid,
            name_core="굴비",
            pack_quantity=1.0,
            pack_unit="개",
            brand=None,
            category_path_internal_id=None,
            representative_image_url=None,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(product)
        session.commit()

        result = session.get(CanonicalProduct, cid)
        assert result is not None
        assert result.category_path_internal_id is None
        assert result.representative_image_url is None


# ══════════════════════════════════════════════════════
# CategoryNode
# ══════════════════════════════════════════════════════

class TestCategoryNodeOrm:
    def test_insert_parent_child(self, session):
        parent = CategoryNode(
            id="cat-meat",
            parent_id=None,
            name_kr="정육ㆍ계란",
            name_slug="meat-eggs",
            level=1,
            path="/정육ㆍ계란",
            display_order=1,
        )
        child = CategoryNode(
            id="cat-egg",
            parent_id="cat-meat",
            name_kr="계란ㆍ메추리알",
            name_slug="eggs",
            level=2,
            path="/정육ㆍ계란/계란ㆍ메추리알",
            display_order=1,
        )
        session.add(parent)
        session.add(child)
        session.commit()

        leaf = session.get(CategoryNode, "cat-egg")
        assert leaf.parent_id == "cat-meat"
        assert leaf.level == 2

    def test_path_unique_constraint(self, session):
        node1 = CategoryNode(
            id="cat-a",
            name_kr="채소",
            name_slug="vegetables",
            level=1,
            path="/채소",
        )
        node2 = CategoryNode(
            id="cat-b",
            name_kr="채소복사",
            name_slug="vegetables2",
            level=1,
            path="/채소",  # 동일 path
        )
        session.add(node1)
        session.commit()
        session.add(node2)
        with pytest.raises(IntegrityError):
            session.commit()


# ══════════════════════════════════════════════════════
# MartSkuAlias
# ══════════════════════════════════════════════════════

class TestMartSkuAliasOrm:
    def _create_product(self, session, name="두부", brand="풀무원"):
        cid = _canonical_id(brand, name, 340.0, "g")
        p = CanonicalProduct(
            id=cid,
            brand=brand,
            name_core=name,
            pack_quantity=340.0,
            pack_unit="g",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(p)
        session.commit()
        return cid

    def test_insert_and_query(self, session):
        cid = self._create_product(session)
        alias = MartSkuAlias(
            id="alias-001",
            canonical_id=cid,
            mart=MartKindEnum.EMART,
            mart_item_id="1000641687348",
            mart_item_name_raw="풀무원 국산 부침두부 (340G)",
            source_url="https://emart.ssg.com/item/itemView.ssg?itemId=1000641687348",
            first_seen_at=_now(),
            last_seen_at=_now(),
        )
        session.add(alias)
        session.commit()

        result = session.get(MartSkuAlias, "alias-001")
        assert result.mart == MartKindEnum.EMART
        assert result.mart_item_id == "1000641687348"

    def test_unique_constraint_violation(self, session):
        """같은 (mart, mart_item_id)를 두 번 삽입하면 IntegrityError."""
        cid = self._create_product(session)
        alias1 = MartSkuAlias(
            id="alias-dup-1",
            canonical_id=cid,
            mart=MartKindEnum.HOMEPLUS,
            mart_item_id="069483347",
            mart_item_name_raw="상품1",
            first_seen_at=_now(),
            last_seen_at=_now(),
        )
        alias2 = MartSkuAlias(
            id="alias-dup-2",
            canonical_id=cid,
            mart=MartKindEnum.HOMEPLUS,
            mart_item_id="069483347",  # 동일 mart + mart_item_id
            mart_item_name_raw="상품2",
            first_seen_at=_now(),
            last_seen_at=_now(),
        )
        session.add(alias1)
        session.commit()
        session.add(alias2)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_cascade_delete(self, session):
        """CanonicalProduct 삭제 시 MartSkuAlias도 삭제."""
        cid = self._create_product(session)
        alias = MartSkuAlias(
            id="alias-cascade",
            canonical_id=cid,
            mart=MartKindEnum.LOTTEMART,
            mart_item_id="OS001",
            mart_item_name_raw="캐스케이드 테스트",
            first_seen_at=_now(),
            last_seen_at=_now(),
        )
        session.add(alias)
        session.commit()

        product = session.get(CanonicalProduct, cid)
        session.delete(product)
        session.commit()

        alias_result = session.get(MartSkuAlias, "alias-cascade")
        assert alias_result is None


# ══════════════════════════════════════════════════════
# PriceObservation
# ══════════════════════════════════════════════════════

class TestPriceObservationOrm:
    def _create_product(self, session):
        cid = _canonical_id(None, "양배추", 800.0, "g")
        p = CanonicalProduct(
            id=cid,
            name_core="양배추",
            pack_quantity=800.0,
            pack_unit="g",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(p)
        session.commit()
        return cid

    def test_insert_and_query(self, session):
        cid = self._create_product(session)
        obs = PriceObservation(
            id="obs-001",
            canonical_id=cid,
            mart=MartKindEnum.EMART,
            regular_price=3480,
            sale_price=2784,
            on_sale=True,
            discount_rate=20,
            unit_price_basis=UnitPriceBasisEnum.PER_100G,
            observed_at=_now(),
            raw_payload_hash="a" * 40,
            event_labels=[],
        )
        session.add(obs)
        session.commit()

        result = session.get(PriceObservation, "obs-001")
        assert result.sale_price == 2784
        assert result.on_sale is True
        assert result.discount_rate == 20

    def test_cascade_delete_with_product(self, session):
        """CanonicalProduct 삭제 시 PriceObservation도 삭제."""
        cid = self._create_product(session)
        obs = PriceObservation(
            id="obs-cascade",
            canonical_id=cid,
            mart=MartKindEnum.HOMEPLUS,
            sale_price=9900,
            on_sale=False,
            unit_price_basis=UnitPriceBasisEnum.UNKNOWN,
            observed_at=_now(),
            raw_payload_hash="b" * 40,
        )
        session.add(obs)
        session.commit()

        product = session.get(CanonicalProduct, cid)
        session.delete(product)
        session.commit()

        obs_result = session.get(PriceObservation, "obs-cascade")
        assert obs_result is None

    def test_index_exists(self, engine):
        """composite index ix_price_obs_canonical_mart_time 가 생성됐는지 확인."""
        from sqlalchemy import inspect
        insp = inspect(engine)
        indexes = {ix["name"] for ix in insp.get_indexes("canonical_price_observations")}
        assert "ix_price_obs_canonical_mart_time" in indexes

    def test_nullable_regular_price(self, session):
        cid = self._create_product(session)
        obs = PriceObservation(
            id="obs-no-regular",
            canonical_id=cid,
            mart=MartKindEnum.COSTCO,
            regular_price=None,
            sale_price=35990,
            on_sale=False,
            discount_rate=None,
            unit_price_basis=UnitPriceBasisEnum.PER_100ML,
            observed_at=_now(),
            raw_payload_hash="c" * 40,
        )
        session.add(obs)
        session.commit()

        result = session.get(PriceObservation, "obs-no-regular")
        assert result.regular_price is None
        assert result.discount_rate is None


# ══════════════════════════════════════════════════════
# ProductReviewQueue
# ══════════════════════════════════════════════════════

class TestProductReviewQueueOrm:
    def test_insert_and_query(self, session):
        item = ProductReviewQueue(
            id="queue-001",
            raw_payload={"itemId": "xyz", "itemName": "테스트 상품"},
            source_mart=MartKindEnum.EMART,
            reason=ReviewReasonEnum.CATEGORY_UNKNOWN,
            suggested_canonical_id=None,
            created_at=_now(),
        )
        session.add(item)
        session.commit()

        result = session.get(ProductReviewQueue, "queue-001")
        assert result.reason == ReviewReasonEnum.CATEGORY_UNKNOWN
        assert result.resolved_at is None
        assert result.raw_payload["itemId"] == "xyz"

    def test_all_reasons(self, session):
        for i, reason in enumerate(ReviewReasonEnum):
            item = ProductReviewQueue(
                id=f"queue-reason-{i}",
                raw_payload={"test": True},
                source_mart=MartKindEnum.HOMEPLUS,
                reason=reason,
                created_at=_now(),
            )
            session.add(item)
        session.commit()

        results = session.execute(select(ProductReviewQueue)).scalars().all()
        assert len(results) == len(ReviewReasonEnum)


# ══════════════════════════════════════════════════════
# 4사 fixture 통합 ORM 테스트
# ══════════════════════════════════════════════════════

class TestEmartOrmIntegration:
    def test_emart_insert(self, session):
        fixture_path = FIXTURE_BASE / "emart" / "sale_listing_5cards.json"
        with open(fixture_path, encoding="utf-8") as f:
            raw = json.load(f)

        area_list = raw["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["areaList"]
        item = area_list[0]["dataList"][0]

        sale_price = int(item["finalPrice"].replace(",", ""))
        regular_price_str = item.get("strikeOutPrice", "")
        regular_price = int(regular_price_str.replace(",", "")) if regular_price_str else None
        discount_rate = int(item["discountRate"]) if item.get("discountRate") else None
        on_sale = regular_price is not None and regular_price > sale_price
        brand = item.get("brandName") or None
        if brand == "":
            brand = None

        cid = _canonical_id(brand, item["itemName"], 1.0, "개")
        product = CanonicalProduct(
            id=cid,
            brand=brand,
            name_core=item["itemName"],
            pack_quantity=1.0,
            pack_unit="개",
            representative_image_url=item.get("itemImgUrl"),
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(product)

        payload_hash = _payload_hash(item)
        obs = PriceObservation(
            id=f"emart-{item['itemId']}-test",
            canonical_id=cid,
            mart=MartKindEnum.EMART,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=discount_rate,
            unit_price_basis=UnitPriceBasisEnum.PER_EACH,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=[],
        )
        session.add(obs)
        session.commit()

        result = session.get(PriceObservation, f"emart-{item['itemId']}-test")
        assert result.sale_price == 2784
        assert result.on_sale is True


class TestHomeplusOrmIntegration:
    def test_homeplus_insert(self, session):
        fixture_path = FIXTURE_BASE / "homeplus" / "sale_listing_5items_dc_mixed.json"
        with open(fixture_path, encoding="utf-8") as f:
            raw = json.load(f)

        item = raw["data"]["dataList"][0]
        sale_price = item["dcPrice"] if item.get("dcPrice") is not None else item["salePrice"]
        regular_price = item["salePrice"]
        on_sale = item.get("dcPrice") is not None
        event_labels = [e["label"] for e in item.get("eventFlagList", [])]

        cid = _canonical_id(None, item["itemNm"], float(item.get("totalUnitQty") or 1.0), item.get("unitMeasure", "개"))
        product = CanonicalProduct(
            id=cid,
            name_core=item["itemNm"],
            pack_quantity=float(item.get("totalUnitQty") or 1.0),
            pack_unit=item.get("unitMeasure", "개"),
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(product)

        payload_hash = _payload_hash(item)
        obs = PriceObservation(
            id=f"homeplus-{item['itemNo']}-test",
            canonical_id=cid,
            mart=MartKindEnum.HOMEPLUS,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=item.get("dcRate"),
            unit_price_normalized=float(item["unitPrice"]) if item.get("unitPrice") else None,
            unit_price_basis=UnitPriceBasisEnum.PER_EACH,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=event_labels,
        )
        session.add(obs)
        session.commit()

        result = session.get(PriceObservation, f"homeplus-{item['itemNo']}-test")
        assert result.mart == MartKindEnum.HOMEPLUS
        assert result.sale_price == 4900


class TestLottemartOrmIntegration:
    def test_lottemart_insert(self, session):
        fixture_path = FIXTURE_BASE / "lottemart" / "hydrated_5cards.html"
        with open(fixture_path, encoding="utf-8") as f:
            content = f.read()

        start = content.index("window.__INITIAL_STATE__ = ") + len("window.__INITIAL_STATE__ = ")
        end = content.rindex("};") + 1
        state = json.loads(content[start:end])

        products_map = state["data"]["products"]["productEntities"]
        pid = next(iter(products_map))
        item = products_map[pid]

        price_current = item["price"]["current"]["amount"]
        price_original = item["price"].get("original", {})
        regular_price = price_original.get("amount") if price_original else None
        on_sale = regular_price is not None and regular_price > price_current
        offers = item.get("offers", [])
        event_labels = [o["description"] for o in offers]

        cid = _canonical_id(item.get("brand"), item["name"].strip(), 1.0, "개")
        product = CanonicalProduct(
            id=cid,
            brand=item.get("brand") or None,
            name_core=item["name"].strip(),
            pack_quantity=1.0,
            pack_unit="개",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(product)

        payload_hash = _payload_hash(item)
        obs = PriceObservation(
            id=f"lottemart-{pid[:8]}-test",
            canonical_id=cid,
            mart=MartKindEnum.LOTTEMART,
            regular_price=regular_price,
            sale_price=price_current,
            on_sale=on_sale,
            unit_price_basis=UnitPriceBasisEnum.PER_100G,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=event_labels,
        )
        session.add(obs)
        session.commit()

        result = session.get(PriceObservation, f"lottemart-{pid[:8]}-test")
        assert result.mart == MartKindEnum.LOTTEMART
        assert result.sale_price > 0


class TestCostcoOrmIntegration:
    def test_costco_insert(self, session):
        from bs4 import BeautifulSoup
        import re

        fixture_path = FIXTURE_BASE / "costco" / "special_offers_5cards.html"
        with open(fixture_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")

        items = soup.select("li.product-list-item")
        item_el = items[0]
        a = item_el.select_one("a.thumb")
        title = a["title"]
        href = a["href"]
        prod_id = href.rstrip("/").split("/p/")[-1]

        price_el = item_el.select_one(".product-price-amount")
        sale_price = int(price_el.get_text(strip=True).replace(",", "").replace("원", "").strip())

        orig_el = item_el.select_one(".original-price")
        orig_text = orig_el.get_text(strip=True).replace(",", "").replace("원", "").strip() if orig_el else ""
        regular_price = int(orig_text) if orig_text else None
        on_sale = regular_price is not None and regular_price > sale_price

        unit_el = item_el.select_one(".product-price-pre-unit-amount")
        unit_text = unit_el.get_text(strip=True) if unit_el else ""
        unit_price = None
        unit_basis = UnitPriceBasisEnum.UNKNOWN
        if unit_text:
            m = re.search(r"([\d,]+)원", unit_text)
            if m:
                unit_price = float(m.group(1).replace(",", ""))
            if "㎖" in unit_text:
                unit_basis = UnitPriceBasisEnum.PER_100ML
            elif "개" in unit_text:
                unit_basis = UnitPriceBasisEnum.PER_EACH

        raw = {"title": title, "href": href, "sale_price": sale_price}
        payload_hash = _payload_hash(raw)

        cid = _canonical_id(None, title, 1.0, "개")
        product = CanonicalProduct(
            id=cid,
            name_core=title,
            pack_quantity=1.0,
            pack_unit="개",
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(product)

        obs = PriceObservation(
            id=f"costco-{prod_id}-test",
            canonical_id=cid,
            mart=MartKindEnum.COSTCO,
            regular_price=regular_price,
            sale_price=sale_price,
            on_sale=on_sale,
            discount_rate=None,
            unit_price_normalized=unit_price,
            unit_price_basis=unit_basis,
            observed_at=_now(),
            raw_payload_hash=payload_hash,
            event_labels=[],
        )
        session.add(obs)
        session.commit()

        result = session.get(PriceObservation, f"costco-{prod_id}-test")
        assert result.mart == MartKindEnum.COSTCO
        assert result.sale_price == 35990
        assert result.on_sale is False
