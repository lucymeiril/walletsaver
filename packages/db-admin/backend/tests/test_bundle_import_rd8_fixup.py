"""test_bundle_import_rd8_fixup.py — RD8 D-fixup 재검증 테스트.

검증 항목:
  Fix-1 (D-VERIFY-002): BundleResult 카운터 의미 분리
    - products_processed vs products_created 올바르게 구분
    - 멱등 2회: created=0, matched>0

  Fix-3 (D-VERIFY-004): kg↔g canonicalize → 같은 Product 1개로 흡수
    - 1.8kg 행 + 1800g 행 → Product 1개, BaselinePrice 2개(마트 다를 때) 또는 1개(같은 마트/날짜)

  Fix-4 (자기검열 #2): brand=None/"브랜드없음"/"no_brand"/"" → mart_code 로 fallback
    - product.brand == mart_code

  Fix-5 (자기검열 #3): mart_code 없음 → INSERT 거부, rejected 카운터 증가
    - result["rejected"] > 0, product 수 = 0
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, Category, MatchingEntry, Product, BaselinePrice
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


def _add_me(
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


def _row(match_key: str, mart: str, price: float, dt: str = "2024-01-01T00:00:00") -> dict:
    return {"match_key": match_key, "mart": mart, "price": price, "captured_at": dt}


# ═══════════════════════════════════════════════
# Fix-1: 카운터 의미 분리 (D-VERIFY-002)
# ═══════════════════════════════════════════════

class TestProductsCounter:
    """products_created / products_matched / products_processed 의미 검증."""

    def test_first_import_creates(self, db_session):
        """처음 import: created=1, matched=0, processed=1."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        r = apply_products(
            db_session,
            [_row("농심|신라면|120.000000|g", "emart", 1200)],
            mode="lenient",
        )
        assert r["created"] == 1
        assert r["matched"] == 0
        assert r["processed"] == 1
        assert r["rejected"] == 0

    def test_second_import_matches(self, db_session):
        """2회 import: 2번째는 created=0, matched=1."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [_row("농심|신라면|120.000000|g", "emart", 1200)]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        # 날짜가 같은 동일 행 → baselines_skipped (price 갱신만)
        r2 = apply_products(db_session, rows, mode="lenient")
        assert r2["created"] == 0
        assert r2["matched"] == 1
        assert r2["baselines_skipped"] == 1
        assert r2["baselines_upserted"] == 0

    def test_processed_equals_created_plus_matched(self, db_session):
        """processed = created + matched."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        _add_me(db_session, "CJ|햇반|210.000000|g", "CJ", "햇반", 210.0, "g")
        db_session.commit()

        rows = [
            _row("농심|신라면|120.000000|g", "emart", 1200),
            _row("CJ|햇반|210.000000|g", "emart", 1800),
        ]
        # 첫 import
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()
        # 두 번째: 모두 matched
        r = apply_products(db_session, rows, mode="lenient")
        assert r["processed"] == r["created"] + r["matched"]
        assert r["matched"] == 2


# ═══════════════════════════════════════════════
# Fix-3: kg↔g canonicalize (D-VERIFY-004)
# ═══════════════════════════════════════════════

class TestUnitCanonicalize:
    """1.8kg / 1800g → 동일 Product 1개로 흡수."""

    def _setup_both_me(self, db_session):
        """1.8kg MatchingEntry + 1800g MatchingEntry (같은 canon product)."""
        _add_me(db_session, "CJ|스팸|1.800000|kg", "CJ", "스팸", 1.8, "kg")
        _add_me(db_session, "CJ|스팸|1800.000000|g", "CJ", "스팸", 1800.0, "g")
        db_session.commit()

    def test_kg_and_g_same_product(self, db_session):
        """1.8kg 행 + 1800g 행 → Product 1개 (canonicalize_pack이 둘 다 1800g으로 변환)."""
        self._setup_both_me(db_session)

        rows = [
            _row("CJ|스팸|1.800000|kg",   "emart",    5800, "2024-01-01T00:00:00"),
            _row("CJ|스팸|1800.000000|g", "homeplus", 5700, "2024-01-01T00:00:00"),
        ]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        products = db_session.query(Product).all()
        assert len(products) == 1, f"Product가 {len(products)}개 생성됨 (기대: 1)"
        p = products[0]
        assert p.pack_unit == "g"
        assert p.pack_qty == pytest.approx(1800.0)

    def test_kg_and_g_two_baselines(self, db_session):
        """마트가 다르고 날짜가 같으면 BaselinePrice는 2개여야 함."""
        self._setup_both_me(db_session)

        rows = [
            _row("CJ|스팸|1.800000|kg",   "emart",    5800, "2024-01-01T00:00:00"),
            _row("CJ|스팸|1800.000000|g", "homeplus", 5700, "2024-01-01T00:00:00"),
        ]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert db_session.query(BaselinePrice).count() == 2

    def test_same_mart_same_date_kg_then_g_idempotent(self, db_session):
        """같은 마트/날짜에서 1.8kg → 1800g 두 번 import → BaselinePrice 1개."""
        self._setup_both_me(db_session)

        rows_kg = [_row("CJ|스팸|1.800000|kg",   "emart", 5800, "2024-01-01T00:00:00")]
        rows_g  = [_row("CJ|스팸|1800.000000|g", "emart", 5800, "2024-01-01T00:00:00")]

        apply_products(db_session, rows_kg, mode="lenient")
        db_session.commit()
        apply_products(db_session, rows_g, mode="lenient")
        db_session.commit()

        # 같은 (product_id, mart, date) → UNIQUE → 1개
        assert db_session.query(BaselinePrice).count() == 1

    def test_unit_price_normalized_kg_input(self, db_session):
        """1.8kg 행으로 import → unit_price_normalized는 1800g 기준으로 계산."""
        _add_me(db_session, "CJ|스팸|1.800000|kg", "CJ", "스팸", 1.8, "kg")
        db_session.commit()

        rows = [_row("CJ|스팸|1.800000|kg", "emart", 1800, "2024-01-01T00:00:00")]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        bp = db_session.query(BaselinePrice).first()
        # 1800원 / 1800g → 100원/100g
        assert bp.unit_price_normalized == pytest.approx(100.0)
        assert bp.unit_price_basis == "g"


# ═══════════════════════════════════════════════
# Fix-4: brand fallback (자기검열 #2)
# ═══════════════════════════════════════════════

class TestBrandFallback:
    """brand=None / "브랜드없음" / "no_brand" / "" → mart_code fallback."""

    @pytest.mark.parametrize("brand_val", [None, "브랜드없음", "no_brand", ""])
    def test_brand_fallback_to_mart(self, db_session, brand_val):
        mk = f"{'(none)' if brand_val is None else brand_val}|김|5.000000|봉"
        _add_me(db_session, mk, brand_val, "김", 5.0, "봉")
        db_session.commit()

        rows = [_row(mk, "emart", 3000)]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        p = db_session.query(Product).first()
        assert p is not None, "Product가 생성되지 않음"
        assert p.brand == "emart", f"brand가 '{p.brand}'이어야 'emart'"

    def test_non_null_brand_not_overridden(self, db_session):
        """brand='농심'은 그대로 유지 (fallback 없어야 함)."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [_row("농심|신라면|120.000000|g", "emart", 1200)]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        p = db_session.query(Product).first()
        assert p.brand == "농심"

    def test_brand_fallback_idempotent(self, db_session):
        """fallback brand로 두 번 import → Product 1개 (idempotent)."""
        _add_me(db_session, "|사과|3.000000|개", None, "사과", 3.0, "개")
        db_session.commit()

        rows = [_row("|사과|3.000000|개", "costco", 6000)]
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()
        apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert db_session.query(Product).count() == 1


# ═══════════════════════════════════════════════
# Fix-5: mart_code=None/공백 → 거부 (자기검열 #3)
# ═══════════════════════════════════════════════

class TestMartCodeRejection:
    """mart_code 없는 row는 INSERT 거부, products_rejected 카운터 증가."""

    def test_empty_mart_rejected(self, db_session):
        """mart='' → rejected=1, Product 없음."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [{"match_key": "농심|신라면|120.000000|g", "mart": "", "price": 1200, "captured_at": "2024-01-01T00:00:00"}]
        r = apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert r["rejected"] == 1
        assert db_session.query(Product).count() == 0
        assert len(r["failures"]) >= 1

    def test_none_mart_rejected(self, db_session):
        """mart=None → rejected=1, Product 없음."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [{"match_key": "농심|신라면|120.000000|g", "mart": None, "price": 1200, "captured_at": "2024-01-01T00:00:00"}]
        r = apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert r["rejected"] == 1
        assert db_session.query(Product).count() == 0

    def test_missing_mart_key_rejected(self, db_session):
        """mart 키 없음 → rejected=1."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [{"match_key": "농심|신라면|120.000000|g", "price": 1200, "captured_at": "2024-01-01T00:00:00"}]
        r = apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert r["rejected"] == 1

    def test_strict_mode_raises_on_missing_mart(self, db_session):
        """strict mode에서 mart 없으면 ValueError 발생."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [{"match_key": "농심|신라면|120.000000|g", "mart": "", "price": 1200, "captured_at": "2024-01-01T00:00:00"}]
        with pytest.raises(ValueError, match="mart_code"):
            apply_products(db_session, rows, mode="strict")

    def test_valid_row_after_rejected_still_processes(self, db_session):
        """거부된 row 다음에 유효한 row가 있으면 정상 처리."""
        _add_me(db_session, "농심|신라면|120.000000|g", "농심", "신라면", 120.0, "g")
        db_session.commit()

        rows = [
            {"match_key": "농심|신라면|120.000000|g", "mart": "", "price": 1200, "captured_at": "2024-01-01T00:00:00"},
            _row("농심|신라면|120.000000|g", "emart", 1200),
        ]
        r = apply_products(db_session, rows, mode="lenient")
        db_session.commit()

        assert r["rejected"] == 1
        assert r["created"] == 1
        assert db_session.query(Product).count() == 1
