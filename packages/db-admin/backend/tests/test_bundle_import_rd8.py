"""test_bundle_import_rd8.py — RD8 D phase 통합 테스트.

테스트 케이스:
  1. 멱등성: 같은 bundle 2회 import → product/baseline_prices 수 불변
  2. 4 마트 동일 상품 import → product 1개, baseline_prices 4개, source_marts 집합
  3. 단위 분류: g→weight, ml→volume, L→volume, 봉→pack, 개→count
  4. unit_price_normalized: 1200원/120g → 1000.0(원/100g)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, Category, MatchingEntry, Product, BaselinePrice
from services.unit_utils import classify_unit_kind, normalize_unit_price
from services.bundle_import import apply_products


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════

@pytest.fixture
def db_session():
    """인메모리 SQLite 세션. 매 테스트마다 새 DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def _add_matching_entry(
    session,
    match_key: str,
    brand: str | None,
    name_core: str | None,
    pack_qty: float | None,
    pack_unit: str | None,
) -> MatchingEntry:
    me = MatchingEntry(
        match_key=match_key,
        brand=brand,
        name_core=name_core,
        pack_qty=pack_qty,
        pack_unit=pack_unit,
        source="external-ai",
        confidence=1.0,
    )
    session.add(me)
    session.flush()
    return me


def _product_row(match_key: str, mart: str, price: float, dt: str) -> dict:
    return {
        "match_key": match_key,
        "mart": mart,
        "price": price,
        "captured_at": dt,
    }


# ═══════════════════════════════════════════════
# D3: 단위 분류 테스트
# ═══════════════════════════════════════════════

class TestClassifyUnitKind:
    def test_weight_g(self):
        assert classify_unit_kind("g") == "weight"

    def test_weight_kg(self):
        assert classify_unit_kind("kg") == "weight"

    def test_volume_ml(self):
        assert classify_unit_kind("ml") == "volume"

    def test_volume_L_upper(self):
        assert classify_unit_kind("L") == "volume"

    def test_volume_l_lower(self):
        assert classify_unit_kind("l") == "volume"

    def test_pack_봉(self):
        assert classify_unit_kind("봉") == "pack"

    def test_count_개(self):
        assert classify_unit_kind("개") == "count"

    def test_count_EA(self):
        assert classify_unit_kind("EA") == "count"

    def test_none_is_count(self):
        assert classify_unit_kind(None) == "count"

    def test_unknown_defaults_count(self):
        assert classify_unit_kind("미지정단위xyz") == "count"


# ═══════════════════════════════════════════════
# D3: 단위 정규화 테스트
# ═══════════════════════════════════════════════

class TestNormalizeUnitPrice:
    def test_신라면_120g_1200원(self):
        """1200원 / 120g → 1000.0 (원/100g)"""
        normalized, basis = normalize_unit_price(1200, 120, "g", "weight")
        assert normalized == 1000.0
        assert basis == "g"

    def test_weight_kg_변환(self):
        """1000원 / 1kg = 1000원/1000g → 100원/100g"""
        normalized, basis = normalize_unit_price(1000, 1, "kg", "weight")
        assert normalized == pytest.approx(100.0)
        assert basis == "g"

    def test_volume_ml(self):
        """2000원 / 500ml → 400.0 (원/100ml)"""
        normalized, basis = normalize_unit_price(2000, 500, "ml", "volume")
        assert normalized == pytest.approx(400.0)
        assert basis == "ml"

    def test_volume_L_변환(self):
        """1500원 / 1L = 1500원/1000ml → 150원/100ml"""
        normalized, basis = normalize_unit_price(1500, 1, "L", "volume")
        assert normalized == pytest.approx(150.0)
        assert basis == "ml"

    def test_count_returns_none(self):
        normalized, basis = normalize_unit_price(3000, 3, "개", "count")
        assert normalized is None
        assert basis is None

    def test_pack_returns_none(self):
        normalized, basis = normalize_unit_price(5000, 5, "봉", "pack")
        assert normalized is None
        assert basis is None

    def test_zero_qty_returns_none(self):
        normalized, basis = normalize_unit_price(1200, 0, "g", "weight")
        assert normalized is None


# ═══════════════════════════════════════════════
# D2: find_or_create 멱등성 테스트
# ═══════════════════════════════════════════════

class TestApplyProductsIdempotent:
    def test_same_bundle_twice_no_new_products(self, db_session):
        """같은 bundle 2회 import → product 수 변화 없음."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()

        rows = [_product_row("농심|신라면|120.000000|g", "emart", 1200, "2024-01-01T00:00:00")]

        apply_products(db_session, rows, mode="lenient")
        db_session.commit()
        count1 = db_session.query(Product).count()
        bp_count1 = db_session.query(BaselinePrice).count()

        apply_products(db_session, rows, mode="lenient")
        db_session.commit()
        count2 = db_session.query(Product).count()
        bp_count2 = db_session.query(BaselinePrice).count()

        assert count1 == count2, f"product 수 변화: {count1} → {count2}"
        assert bp_count1 == bp_count2, f"baseline 수 변화: {bp_count1} → {bp_count2}"

    def test_same_bundle_twice_product_count_is_1(self, db_session):
        """2회 import 후에도 product는 정확히 1개."""
        _add_matching_entry(
            db_session,
            match_key="CJ|햇반|210.000000|g",
            brand="CJ", name_core="햇반",
            pack_qty=210.0, pack_unit="g",
        )
        db_session.commit()

        rows = [_product_row("CJ|햇반|210.000000|g", "homeplus", 1800, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert db_session.query(Product).count() == 1
        assert db_session.query(BaselinePrice).count() == 1


# ═══════════════════════════════════════════════
# D2: 4 마트 동일 상품 테스트
# ═══════════════════════════════════════════════

class TestApplyProducts4Marts:
    def test_4marts_product_1_baseline_4(self, db_session):
        """4개 마트에서 동일 상품 import → product 1, baseline_prices 4."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()

        rows = [
            _product_row("농심|신라면|120.000000|g", "emart",     1200, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "homeplus",  1150, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "lottemart", 1100, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "costco",    1000, "2024-01-01T00:00:00"),
        ]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert db_session.query(Product).count() == 1
        assert db_session.query(BaselinePrice).count() == 4

    def test_4marts_source_marts_set(self, db_session):
        """4개 마트 import → source_marts에 4개 마트 코드 모두 포함."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()

        rows = [
            _product_row("농심|신라면|120.000000|g", "emart",     1200, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "homeplus",  1150, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "lottemart", 1100, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "costco",    1000, "2024-01-01T00:00:00"),
        ]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        product = db_session.query(Product).first()
        assert set(product.source_marts) == {"emart", "homeplus", "lottemart", "costco"}

    def test_4marts_idempotent(self, db_session):
        """4 마트 bundle 2회 import → product/baseline 수 불변."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()

        rows = [
            _product_row("농심|신라면|120.000000|g", "emart",     1200, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "homeplus",  1150, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "lottemart", 1100, "2024-01-01T00:00:00"),
            _product_row("농심|신라면|120.000000|g", "costco",    1000, "2024-01-01T00:00:00"),
        ]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()
        p1 = db_session.query(Product).count()
        b1 = db_session.query(BaselinePrice).count()

        apply_products(db_session, rows, mode="lenient")
        db_session.commit()
        p2 = db_session.query(Product).count()
        b2 = db_session.query(BaselinePrice).count()

        assert p1 == p2
        assert b1 == b2


# ═══════════════════════════════════════════════
# D2: Product 정규화 컬럼 검증
# ═══════════════════════════════════════════════

class TestProductNormalizedColumns:
    def test_product_unit_kind_set(self, db_session):
        """import 후 product.unit_kind가 'weight' (g 기준)."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()
        rows = [_product_row("농심|신라면|120.000000|g", "emart", 1200, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        p = db_session.query(Product).first()
        assert p.unit_kind == "weight"
        assert p.brand == "농심"
        assert p.name_core == "신라면"
        assert p.pack_qty == 120.0
        assert p.pack_unit == "g"

    def test_baseline_unit_price_normalized(self, db_session):
        """신라면 1200원/120g → unit_price_normalized = 1000.0, basis = 'g'."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()
        rows = [_product_row("농심|신라면|120.000000|g", "emart", 1200, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        bp = db_session.query(BaselinePrice).first()
        assert bp.mart_code == "emart"
        assert bp.unit_price_normalized == pytest.approx(1000.0)
        assert bp.unit_price_basis == "g"
        assert bp.pack_qty_snapshot == 120.0
        assert bp.pack_unit_snapshot == "g"

    def test_volume_product_normalized(self, db_session):
        """코카콜라 500ml 2000원 → unit_price_normalized = 400.0 원/100ml."""
        _add_matching_entry(
            db_session,
            match_key="코카콜라|콜라|500.000000|ml",
            brand="코카콜라", name_core="콜라",
            pack_qty=500.0, pack_unit="ml",
        )
        db_session.commit()
        rows = [_product_row("코카콜라|콜라|500.000000|ml", "emart", 2000, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        p = db_session.query(Product).first()
        assert p.unit_kind == "volume"
        bp = db_session.query(BaselinePrice).first()
        assert bp.unit_price_normalized == pytest.approx(400.0)
        assert bp.unit_price_basis == "ml"

    def test_pack_unit_no_normalize(self, db_session):
        """봉(pack) 상품은 unit_price_normalized = None."""
        _add_matching_entry(
            db_session,
            match_key="|김|5.000000|봉",
            brand=None, name_core="김",
            pack_qty=5.0, pack_unit="봉",
        )
        db_session.commit()
        rows = [_product_row("|김|5.000000|봉", "emart", 3000, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        bp = db_session.query(BaselinePrice).first()
        assert bp.unit_price_normalized is None
        p = db_session.query(Product).first()
        assert p.unit_kind == "pack"

    def test_count_unit_no_normalize(self, db_session):
        """개(count) 상품은 unit_price_normalized = None."""
        _add_matching_entry(
            db_session,
            match_key="|사과|3.000000|개",
            brand=None, name_core="사과",
            pack_qty=3.0, pack_unit="개",
        )
        db_session.commit()
        rows = [_product_row("|사과|3.000000|개", "emart", 6000, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        bp = db_session.query(BaselinePrice).first()
        assert bp.unit_price_normalized is None
        p = db_session.query(Product).first()
        assert p.unit_kind == "count"


# ═══════════════════════════════════════════════
# D4: alias 흡수 테스트
# ═══════════════════════════════════════════════

class TestAliasAccumulation:
    def test_different_raw_names_accumulated(self, db_session):
        """같은 (brand,name_core,qty,unit)에 다른 raw_name → aliases에 누적."""
        _add_matching_entry(
            db_session,
            match_key="농심|신라면|120.000000|g",
            brand="농심", name_core="신라면",
            pack_qty=120.0, pack_unit="g",
        )
        db_session.commit()

        rows_1 = [{
            "match_key": "농심|신라면|120.000000|g",
            "mart": "emart", "price": 1200,
            "captured_at": "2024-01-01T00:00:00",
            "raw_name": "[행사] 농심 신라면 120g",
        }]
        rows_2 = [{
            "match_key": "농심|신라면|120.000000|g",
            "mart": "homeplus", "price": 1150,
            "captured_at": "2024-01-01T00:00:00",
            "raw_name": "농심신라면120g",
        }]
        apply_products(db_session, rows_1, mode="lenient")
        apply_products(db_session, rows_2, mode="lenient")
        db_session.commit()

        p = db_session.query(Product).first()
        assert "[행사] 농심 신라면 120g" in (p.aliases or [])
        assert "농심신라면120g" in (p.aliases or [])
