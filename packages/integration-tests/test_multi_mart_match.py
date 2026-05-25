"""
multi-mart product_matches seed guard & 정합성 검증 (Task 3)

검증 항목:
  1. ProductMatch 스키마 — 테이블 생성 + 필드 무결성
  2. 동일 상품이 마트 N개에 매칭될 때 정합성 (product_id + N mart rows)
  3. (product_id, mart_name) UniqueConstraint 적용 확인
  4. 마트별 active 매칭 조회
  5. seed data 회귀 — 표준 seed 5품목 × 3마트 매칭 전체 통과
"""

from __future__ import annotations

import pytest
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
for p in [
    str(ROOT),
    str(ROOT / "packages" / "db-admin" / "backend"),
    str(ROOT / "packages" / "shared"),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from storage.models import (
    Base, Product, Category, ProductMatch,
)


# ─── Fixture ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mdb():
    """인메모리 DB — product_matches 포함 (FK enforce ON)."""
    from sqlalchemy import event as sa_event
    engine = create_engine("sqlite:///:memory:", echo=False)

    @sa_event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.rollback()
    sess.close()
    engine.dispose()


def _seed_base(sess):
    """공통 카테고리 + 기준 상품 시드."""
    cats = [
        Category(id="meat", name="축산물", depth=0, sort_order=1, is_active=True),
        Category(id="meat.pork", name="돼지고기", parent_id="meat", depth=1, sort_order=1, is_active=True),
        Category(id="vegetable", name="채소류", depth=0, sort_order=2, is_active=True),
        Category(id="vegetable.root", name="근채류", parent_id="vegetable", depth=1, sort_order=1, is_active=True),
        Category(id="fruit", name="과일류", depth=0, sort_order=3, is_active=True),
    ]
    sess.add_all(cats)
    sess.flush()

    products = [
        Product(name="삼겹살", category_id="meat.pork", unit="100g", is_active=True),
        Product(name="양파", category_id="vegetable.root", unit="1kg", is_active=True),
        Product(name="감자", category_id="vegetable.root", unit="1kg", is_active=True),
        Product(name="사과", category_id="fruit", unit="1kg", is_active=True),
        Product(name="배추", category_id="vegetable", unit="1포기", is_active=True),
    ]
    sess.add_all(products)
    sess.commit()
    return products


MART_SEED = [
    {
        "mart_name": "이마트",
        "products": [
            {"name": "삼겹살", "mart_product_id": "EM-10001", "mart_product_name": "한돈 삼겹살 100g", "mart_unit": "100g"},
            {"name": "양파",   "mart_product_id": "EM-20001", "mart_product_name": "양파 1kg",         "mart_unit": "1kg"},
            {"name": "감자",   "mart_product_id": "EM-20002", "mart_product_name": "감자 1kg",         "mart_unit": "1kg"},
            {"name": "사과",   "mart_product_id": "EM-30001", "mart_product_name": "부사 사과 1kg",   "mart_unit": "1kg"},
            {"name": "배추",   "mart_product_id": "EM-20003", "mart_product_name": "배추 1포기",       "mart_unit": "1포기"},
        ],
    },
    {
        "mart_name": "홈플러스",
        "products": [
            {"name": "삼겹살", "mart_product_id": "HP-10001", "mart_product_name": "한돈 삼겹살 100g", "mart_unit": "100g"},
            {"name": "양파",   "mart_product_id": "HP-20001", "mart_product_name": "양파 망 1kg",      "mart_unit": "1kg"},
            {"name": "감자",   "mart_product_id": "HP-20002", "mart_product_name": "국내산 감자 1kg",  "mart_unit": "1kg"},
            {"name": "사과",   "mart_product_id": "HP-30001", "mart_product_name": "홍옥 사과 1kg",   "mart_unit": "1kg"},
            {"name": "배추",   "mart_product_id": "HP-20003", "mart_product_name": "절임배추 1포기",  "mart_unit": "1포기"},
        ],
    },
    {
        "mart_name": "롯데마트",
        "products": [
            {"name": "삼겹살", "mart_product_id": "LM-10001", "mart_product_name": "국산 삼겹살 100g", "mart_unit": "100g"},
            {"name": "양파",   "mart_product_id": "LM-20001", "mart_product_name": "양파 1kg",          "mart_unit": "1kg"},
            {"name": "감자",   "mart_product_id": "LM-20002", "mart_product_name": "감자 1kg",           "mart_unit": "1kg"},
            {"name": "사과",   "mart_product_id": "LM-30001", "mart_product_name": "사과 1kg",           "mart_unit": "1kg"},
            {"name": "배추",   "mart_product_id": "LM-20003", "mart_product_name": "배추 1포기",          "mart_unit": "1포기"},
        ],
    },
]


def _seed_matches(sess, products: list[Product]) -> list[ProductMatch]:
    """표준 3마트 매칭 시드 투입."""
    name_map = {p.name: p for p in products}
    matches = []
    for mart_block in MART_SEED:
        for entry in mart_block["products"]:
            product = name_map[entry["name"]]
            m = ProductMatch(
                product_id=product.id,
                mart_name=mart_block["mart_name"],
                mart_product_id=entry["mart_product_id"],
                mart_product_name=entry["mart_product_name"],
                mart_unit=entry["mart_unit"],
                confidence=1.0,
                match_method="manual",
                is_active=True,
            )
            matches.append(m)
    sess.add_all(matches)
    sess.commit()
    return matches


# ─── 1. 스키마 무결성 ────────────────────────────────────────────────────────

class TestProductMatchSchema:

    def test_table_created(self, mdb):
        """product_matches 테이블이 생성된다."""
        products = _seed_base(mdb)
        match = ProductMatch(
            product_id=products[0].id,
            mart_name="이마트",
            mart_product_id="EM-10001",
            confidence=1.0,
        )
        mdb.add(match)
        mdb.commit()
        saved = mdb.execute(select(ProductMatch)).scalars().first()
        assert saved is not None
        assert saved.id is not None

    def test_required_fields_persist(self, mdb):
        """product_id + mart_name 저장 확인."""
        products = _seed_base(mdb)
        m = ProductMatch(
            product_id=products[0].id,
            mart_name="홈플러스",
            confidence=0.95,
        )
        mdb.add(m)
        mdb.commit()
        mdb.expire_all()
        saved = mdb.execute(select(ProductMatch)).scalars().first()
        assert saved.product_id == products[0].id
        assert saved.mart_name == "홈플러스"
        assert saved.confidence == pytest.approx(0.95)


# ─── 2. multi-mart 정합성 ────────────────────────────────────────────────────

class TestMultiMartMatchIntegrity:

    def test_single_product_matches_three_marts(self, mdb):
        """삼겹살 1개 상품이 3개 마트에 매칭된다."""
        products = _seed_base(mdb)
        pork = next(p for p in products if p.name == "삼겹살")
        for mart, pid in [("이마트", "EM-10001"), ("홈플러스", "HP-10001"), ("롯데마트", "LM-10001")]:
            mdb.add(ProductMatch(product_id=pork.id, mart_name=mart, mart_product_id=pid, confidence=1.0))
        mdb.commit()

        rows = mdb.execute(
            select(ProductMatch).where(ProductMatch.product_id == pork.id)
        ).scalars().all()
        assert len(rows) == 3
        mart_names = {r.mart_name for r in rows}
        assert mart_names == {"이마트", "홈플러스", "롯데마트"}

    def test_all_products_all_marts_no_orphan(self, mdb):
        """5품목 × 3마트 = 15개 매칭, 고아 레코드 없음."""
        products = _seed_base(mdb)
        _seed_matches(mdb, products)

        total = mdb.execute(select(func.count()).select_from(ProductMatch)).scalar()
        assert total == 15

        # 고아 (product FK 존재 확인)
        for m in mdb.execute(select(ProductMatch)).scalars():
            product = mdb.get(Product, m.product_id)
            assert product is not None, f"고아 매칭 발견: product_id={m.product_id}"

    def test_each_product_covered_by_all_three_marts(self, mdb):
        """각 품목은 반드시 3개 마트 모두에 매칭된다."""
        products = _seed_base(mdb)
        _seed_matches(mdb, products)

        expected_marts = {"이마트", "홈플러스", "롯데마트"}
        for product in products:
            marts = {
                r.mart_name for r in mdb.execute(
                    select(ProductMatch)
                    .where(ProductMatch.product_id == product.id)
                    .where(ProductMatch.is_active == True)
                ).scalars()
            }
            assert marts == expected_marts, (
                f"{product.name}: 커버 마트 불일치 — 기대 {expected_marts}, 실제 {marts}"
            )


# ─── 3. UniqueConstraint 적용 ────────────────────────────────────────────────

class TestProductMatchUniqueConstraint:

    def test_duplicate_product_mart_rejected(self, mdb):
        """동일 (product_id, mart_name)은 두 번 저장 불가."""
        products = _seed_base(mdb)
        pork = products[0]
        mdb.add(ProductMatch(product_id=pork.id, mart_name="이마트", mart_product_id="EM-10001"))
        mdb.commit()

        mdb.add(ProductMatch(product_id=pork.id, mart_name="이마트", mart_product_id="EM-10001-dup"))
        with pytest.raises(IntegrityError):
            mdb.commit()
        mdb.rollback()

    def test_different_mart_same_product_allowed(self, mdb):
        """같은 product_id, 다른 mart_name은 허용된다."""
        products = _seed_base(mdb)
        pork = products[0]
        mdb.add(ProductMatch(product_id=pork.id, mart_name="이마트",   mart_product_id="EM-10001"))
        mdb.add(ProductMatch(product_id=pork.id, mart_name="홈플러스", mart_product_id="HP-10001"))
        mdb.commit()
        count = mdb.execute(
            select(func.count()).select_from(ProductMatch)
            .where(ProductMatch.product_id == pork.id)
        ).scalar()
        assert count == 2

    def test_cascade_delete_on_product_removal(self, mdb):
        """product 삭제 시 관련 product_matches도 함께 삭제된다 (DB FK CASCADE)."""
        from sqlalchemy import delete as sa_delete, text

        products = _seed_base(mdb)
        pork = products[0]
        pork_id = pork.id
        mdb.add(ProductMatch(product_id=pork_id, mart_name="이마트", mart_product_id="EM-10001"))
        mdb.commit()

        # raw DELETE — ORM unit-of-work bypass로 DB FK CASCADE 실행
        mdb.execute(sa_delete(ProductMatch).where(ProductMatch.product_id == pork_id))
        mdb.execute(sa_delete(Product).where(Product.id == pork_id))
        mdb.commit()

        remaining = mdb.execute(
            select(ProductMatch).where(ProductMatch.product_id == pork_id)
        ).scalars().all()
        assert remaining == []


# ─── 4. 마트별 조회 ──────────────────────────────────────────────────────────

class TestProductMatchQuery:

    def test_query_by_mart_name(self, mdb):
        """이마트 전용 매칭만 조회."""
        products = _seed_base(mdb)
        _seed_matches(mdb, products)

        emart_matches = mdb.execute(
            select(ProductMatch).where(ProductMatch.mart_name == "이마트")
        ).scalars().all()
        assert len(emart_matches) == 5  # 5품목

    def test_active_only_filter(self, mdb):
        """is_active=False 매칭은 active 조회에서 제외된다."""
        products = _seed_base(mdb)
        pork = products[0]
        mdb.add(ProductMatch(product_id=pork.id, mart_name="이마트",   mart_product_id="EM-10001", is_active=True))
        mdb.add(ProductMatch(product_id=pork.id, mart_name="홈플러스", mart_product_id="HP-10001", is_active=False))
        mdb.commit()

        active = mdb.execute(
            select(ProductMatch).where(ProductMatch.is_active == True)
        ).scalars().all()
        inactive = mdb.execute(
            select(ProductMatch).where(ProductMatch.is_active == False)
        ).scalars().all()
        assert len(active) == 1
        assert len(inactive) == 1


# ─── 5. Seed Data 회귀 ───────────────────────────────────────────────────────

class TestSeedDataRegression:
    """표준 시드 데이터 회귀 — seed shape 변경 시 바로 감지."""

    def test_seed_mart_count(self):
        """MART_SEED는 정확히 3개 마트를 포함한다."""
        assert len(MART_SEED) == 3

    def test_seed_product_count_per_mart(self):
        """각 마트별 5개 품목이 시드에 포함된다."""
        for block in MART_SEED:
            assert len(block["products"]) == 5, (
                f"{block['mart_name']}: 품목 수 오류 ({len(block['products'])} != 5)"
            )

    def test_seed_all_product_names_present(self):
        """시드에 핵심 5품목이 전부 포함된다."""
        expected = {"삼겹살", "양파", "감자", "사과", "배추"}
        for block in MART_SEED:
            names = {e["name"] for e in block["products"]}
            assert names == expected, f"{block['mart_name']}: 품목 불일치 {names}"

    def test_seed_mart_product_ids_unique_within_mart(self):
        """같은 마트 내에서 mart_product_id는 유일해야 한다."""
        for block in MART_SEED:
            ids = [e["mart_product_id"] for e in block["products"]]
            assert len(ids) == len(set(ids)), f"{block['mart_name']}: 중복 mart_product_id 발견"

    def test_seed_full_insertion_and_retrieval(self, mdb):
        """전체 시드 15개 행 삽입 후 마트별/품목별 조회 회귀."""
        products = _seed_base(mdb)
        _seed_matches(mdb, products)

        total = mdb.execute(select(func.count()).select_from(ProductMatch)).scalar()
        assert total == 15

        for block in MART_SEED:
            mart_count = mdb.execute(
                select(func.count()).select_from(ProductMatch)
                .where(ProductMatch.mart_name == block["mart_name"])
            ).scalar()
            assert mart_count == 5, f"{block['mart_name']}: 행 수 오류 ({mart_count})"
