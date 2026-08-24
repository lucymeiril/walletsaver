"""Focused regression tests for product application invariants."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
SHARED_ROOT = BACKEND_ROOT.parent.parent / "shared"
for path in (str(BACKEND_ROOT), str(SHARED_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from core.match_key import NO_BRAND_SENTINEL
from services.bundle_import import apply_products
from storage.models import Base, BaselinePrice, MatchingEntry, Product


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)
    with Session() as session:
        yield session
    engine.dispose()


def _add_entry(session, key: str, brand: str | None, name: str, qty: float, unit: str):
    entry = MatchingEntry(
        match_key=key,
        brand=brand,
        name_core=name,
        pack_qty=qty,
        pack_unit=unit,
        source="external-ai",
        confidence=1.0,
        hit_count=0,
    )
    session.add(entry)
    session.flush()
    return entry


def _row(key: str, mart: str | None, price: float, captured_at: str = "2026-08-24T00:00:00+00:00"):
    return {
        "match_key": key,
        "mart": mart,
        "price": price,
        "captured_at": captured_at,
    }


def test_second_apply_reuses_product_and_baseline(db_session):
    key = "농심|신라면|120.000000|g"
    _add_entry(db_session, key, "농심", "신라면", 120, "g")

    first = apply_products(db_session, [_row(key, "emart", 1200)], mode="lenient")
    db_session.flush()
    second = apply_products(db_session, [_row(key, "emart", 1200)], mode="lenient")

    assert first["created"] == 1
    assert first["baselines_upserted"] == 1
    assert second["created"] == 0
    assert second["matched"] == 1
    assert second["baselines_skipped"] == 1
    assert db_session.query(Product).count() == 1
    assert db_session.query(BaselinePrice).count() == 1


def test_equivalent_kg_and_g_entries_share_one_product(db_session):
    kg_key = "CJ|스팸|1.800000|kg"
    g_key = "CJ|스팸|1800.000000|g"
    _add_entry(db_session, kg_key, "CJ", "스팸", 1.8, "kg")
    _add_entry(db_session, g_key, "CJ", "스팸", 1800, "g")

    result = apply_products(
        db_session,
        [
            _row(kg_key, "emart", 5800),
            _row(g_key, "homeplus", 5700),
        ],
        mode="lenient",
    )
    db_session.flush()

    product = db_session.query(Product).one()
    assert result["processed"] == 2
    assert product.pack_qty == pytest.approx(1800.0)
    assert product.pack_unit == "g"
    assert set(product.source_marts or []) == {"emart", "homeplus"}
    assert db_session.query(BaselinePrice).count() == 2


@pytest.mark.parametrize("brand", [None, "", "no_brand", "브랜드없음", NO_BRAND_SENTINEL])
def test_brandless_aliases_use_stable_sentinel_not_mart_name(db_session, brand):
    key = f"legacy-brandless-{repr(brand)}|두부|300|g"
    entry = _add_entry(db_session, key, brand, "두부", 300, "g")

    result = apply_products(
        db_session,
        [
            _row(key, "emart", 1900),
            _row(key, "homeplus", 2000),
        ],
        mode="lenient",
    )
    db_session.flush()

    product = db_session.query(Product).one()
    assert result["created"] == 1
    assert result["matched"] == 1
    assert entry.brand == NO_BRAND_SENTINEL
    assert product.brand == NO_BRAND_SENTINEL
    assert set(product.source_marts or []) == {"emart", "homeplus"}


def test_real_brand_is_never_overridden_by_mart(db_session):
    key = "농심|신라면|120|g"
    _add_entry(db_session, key, "농심", "신라면", 120, "g")
    apply_products(db_session, [_row(key, "emart", 1200)], mode="strict")
    assert db_session.query(Product).one().brand == "농심"


def test_missing_mart_is_rejected_without_product(db_session):
    key = "농심|신라면|120|g"
    _add_entry(db_session, key, "농심", "신라면", 120, "g")

    result = apply_products(db_session, [_row(key, None, 1200)], mode="lenient")

    assert result["rejected"] == 1
    assert result["processed"] == 0
    assert db_session.query(Product).count() == 0


def test_missing_name_core_strictly_rejects_product(db_session):
    key = "broken|entry|1|ea"
    entry = MatchingEntry(
        match_key=key,
        brand="brand",
        name_core=None,
        pack_qty=1,
        pack_unit="ea",
        source="external-ai",
        confidence=1.0,
        hit_count=0,
    )
    db_session.add(entry)
    db_session.flush()

    with pytest.raises(ValueError, match="name_core"):
        apply_products(db_session, [_row(key, "emart", 1000)], mode="strict")
    assert db_session.query(Product).count() == 0
