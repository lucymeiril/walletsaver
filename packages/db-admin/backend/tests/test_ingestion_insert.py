"""Focused ingestion persistence contracts for the current DB-admin runtime.

This suite deliberately avoids the retired internal AI-admin publish workflow.
External classification import/matching behavior is covered separately by the
matching import tests.
"""
from __future__ import annotations

import os
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

import api.routes.ingestion as ingestion_routes
from api.routes.ingestion import (
    _insert_items,
    _retryable_lock_http_error,
    _with_sqlite_lock_retry,
)
from services.catalog_seed import seed_catalog_taxonomy
from storage.models import (
    Base,
    Category,
    DiscountHistory,
    PendingCategorization,
    Product,
)


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_sqlite_lock_retryable_error_payload_is_explicit():
    exc = OperationalError("database is locked", None, None)
    http_exc = _retryable_lock_http_error("bulk_approve_chunk", exc, {"ids": [1, 2]})

    assert isinstance(http_exc, HTTPException)
    assert http_exc.status_code == 503
    assert http_exc.detail["retryable"] is True
    assert http_exc.detail["operation"] == "bulk_approve_chunk"
    assert http_exc.detail["context"]["ids"] == [1, 2]


def test_sqlite_lock_retry_does_not_hide_final_lock(monkeypatch):
    monkeypatch.setattr(ingestion_routes.time, "sleep", lambda _seconds: None)
    attempts = 0

    def always_locked():
        nonlocal attempts
        attempts += 1
        raise OperationalError("database is locked", None, None)

    try:
        _with_sqlite_lock_retry(
            always_locked,
            operation_name="bulk_approve_chunk",
            context={"ids": [1]},
        )
    except OperationalError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected OperationalError")

    assert attempts == 7


def test_mart_discount_insert_preserves_package_and_unit_price_metadata():
    Session = _make_session_factory()

    with Session.begin() as session:
        saved = _insert_items(
            session,
            [
                {
                    "name": "[냉장] 한우 불고기1+등급300g",
                    "store": "이마트",
                    "source": "emart",
                    "sale_price": 14850,
                    "original_price": 19800,
                    "unit": "100g",
                },
                {
                    "name": "[냉동][베트남] 흰다리 새우살 (200g)",
                    "store": "이마트",
                    "source": "emart",
                    "sale_price": 4488,
                    "unit": "100g",
                },
            ],
            "DiscountItem",
        )

    with Session() as session:
        rows = session.execute(
            select(DiscountHistory).order_by(DiscountHistory.price.desc())
        ).scalars().all()

    assert saved == 2
    assert len(rows) == 2
    beef, shrimp = rows
    assert beef.price == 14850
    assert beef.raw_data["pack_price"] == 14850
    assert beef.raw_data["display_unit"] == "300g"
    assert beef.raw_data["package_quantity"] == 300
    assert beef.raw_data["package_unit"] == "g"
    assert beef.raw_data["price_per_100g"] == 4950
    assert beef.raw_data["attributes"]["storage_type"] == "chilled"
    assert shrimp.raw_data["display_unit"] == "200g"
    assert shrimp.raw_data["price_per_100g"] == 2244
    assert shrimp.raw_data["attributes"]["origin"] == "vietnam"


def test_plain_price_observation_does_not_invent_discount_metadata():
    Session = _make_session_factory()

    with Session.begin() as session:
        saved = _insert_items(
            session,
            [
                {
                    "name": "두부 300g",
                    "store": "이마트",
                    "source": "emart",
                    "sale_price": 1980,
                    "unit": "300g",
                }
            ],
            "DiscountItem",
        )

    with Session() as session:
        history = session.execute(select(DiscountHistory)).scalar_one()

    assert saved == 1
    assert history.price == 1980
    assert history.original_price is None
    assert history.discount_rate is None
    assert history.raw_data["claim_type"] == "price_observation"
    assert history.raw_data["discount_claim_status"] == "unknown"
    assert history.raw_data["has_discount_metadata"] is False
    assert history.raw_data["is_hotdeal_claim"] is False


def test_unknown_category_stays_pending_without_creating_fake_category():
    Session = _make_session_factory()

    with Session.begin() as session:
        saved = _insert_items(
            session,
            [
                {
                    "name": "분류 대기 상품 500g",
                    "store": "이마트",
                    "source": "emart",
                    "sale_price": 5000,
                    "unit": "500g",
                    "category_id": "external.suggested.unknown",
                }
            ],
            "DiscountItem",
        )

    with Session() as session:
        product = session.execute(
            select(Product).where(Product.name == "분류 대기 상품 500g")
        ).scalar_one()
        fake_category = session.get(Category, "external.suggested.unknown")
        pending = session.execute(
            select(PendingCategorization).where(
                PendingCategorization.product_id == product.id,
                PendingCategorization.suggested_category_id == "external.suggested.unknown",
            )
        ).scalar_one()

    assert saved == 1
    assert fake_category is None
    assert product.category_id is None
    assert pending.status == "pending"


def test_catalog_taxonomy_seed_is_idempotent_and_does_not_seed_products():
    Session = _make_session_factory()

    with Session.begin() as session:
        first = seed_catalog_taxonomy(session)
        second = seed_catalog_taxonomy(session)

    with Session() as session:
        product_count = session.query(Product).count()
        history_count = session.query(DiscountHistory).count()

    assert first["categories"] > 0
    assert first["keywords"] > 0
    assert second == {"categories": 0, "keywords": 0, "repaired_keywords": 0}
    assert product_count == 0
    assert history_count == 0
