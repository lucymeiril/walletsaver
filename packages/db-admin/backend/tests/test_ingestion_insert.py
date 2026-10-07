"""Focused ingestion persistence contracts for the current DB-admin runtime.

This suite deliberately avoids the retired internal publish workflow.
External classification import/matching behavior is covered separately by the
matching import tests.
"""
from __future__ import annotations

import os
import sys
import pytest

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
    UnifiedCategory,
    NormalizedCanonicalProduct,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedOfferEvent,
)


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _reviewed_new_row(name="농심 신라면120g*5", native="fixture-1"):
    return {"name": name, "source_title": name, "source": "emart", "sale_price": 4150,
            "source_record_key": native,
            "source_url": f"https://emart.ssg.com/item/itemView.ssg?itemId={native}",
            "unified_category_id": "food.meals.noodles.bag_ramen",
            "crawled_at": "2026-10-07T08:00:00Z"}


def _seed_reviewed_leaf(session):
    session.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
    session.add(UnifiedCategory(id="food.meals.noodles.bag_ramen", parent_id="food",
                               slug="bag_ramen", name_ko="봉지라면", level=1))
    session.flush()


@pytest.mark.parametrize("name", ["농심 신라면120g*5", "신라면5입600g(120gx5입)"])
def test_approved_new_leaf_retains_exact_bundle_once_and_source_identity(name):
    Session = _make_session_factory()
    with Session.begin() as session:
        _seed_reviewed_leaf(session)
        item = _reviewed_new_row(name)
        assert _insert_items(session, [item], "DiscountItem") == 1
        assert _insert_items(session, [{**item, "source_record_key": "fixture-2",
            "source_url": "https://emart.ssg.com/item/itemView.ssg?itemId=fixture-2"}], "DiscountItem") == 1
    with Session() as session:
        products = session.execute(select(NormalizedCanonicalProduct)).scalars().all()
        variants = session.execute(select(NormalizedProductVariant)).scalars().all()
        histories = session.execute(select(DiscountHistory)).scalars().all()
        assert len(products) == len(variants) == 2
        assert len({p.public_product_id for p in products}) == 2
        assert all(p.unified_category_id == item["unified_category_id"] and not p.public_product_id.startswith("prod-unclassified") for p in products)
        assert all((v.package_quantity, v.package_unit, v.bundle_count) == (120, "g", 5) for v in variants)
        assert all(h.price == 4150 and h.raw_data["bundle_count"] == 5 for h in histories)
        assert all(h.raw_data["normalized_publication"]["publication_status"] == "published" for h in histories)
        assert all(h.raw_data["price_per_100g"] == 691.67 for h in histories)
        assert session.execute(select(Product)).scalar_one().is_active is True


@pytest.mark.parametrize("changes,reason", [
    ({"unified_category_id": None, "category_id": "legacy-only"}, "unified_category_review_required"),
    ({"unified_category_id": "missing"}, "unified_category_review_required"),
    ({"unified_category_id": "food"}, "unified_category_leaf_required"),
    ({"name": "농심 신라면120g 5입", "source_title": "농심 신라면120g 5입"}, "measured_inner_scope_unresolved"),
    ({"name": "농심 신라면120g(5입)", "source_title": "농심 신라면120g(5입)"}, "measured_inner_scope_unresolved"),
])
def test_unresolved_new_row_preserves_raw_history_without_public_fallback(tmp_path, changes, reason):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from services import public_snapshot_v2
    Session = _make_session_factory()
    with Session.begin() as session:
        _seed_reviewed_leaf(session)
        session.add(Category(id="legacy-only", name="legacy", depth=0))
        assert _insert_items(session, [{**_reviewed_new_row(), **changes}], "DiscountItem") == 1
        history = session.execute(select(DiscountHistory)).scalar_one()
        assert history.price == 4150
        assert history.raw_data["normalized_publication"]["publication_status"] == "pending_review"
        assert reason in history.raw_data["normalized_publication"]["review_reasons"]
        assert session.execute(select(NormalizedCanonicalProduct)).scalars().all() == []
        assert session.execute(select(Product)).scalar_one().is_active is False
    snapshot = tmp_path / "public.sqlite"
    with Session.kw["bind"].connect() as connection:
        public_snapshot_v2._write_snapshot_file(snapshot, connection, revision=1)
    source = Path(__file__).resolve().parents[3] / "web-api/backend/services/catalog_storage.py"
    spec = spec_from_file_location("review_fixture_catalog_storage", source)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog = module.PublicCatalogStore(snapshot)
    assert catalog.has_normalized_catalog() is False
    assert catalog.search_products("") == []  # Actual legacy fallback store excludes the new held row.


def test_existing_legacy_status_survives_unresolved_new_observation():
    Session = _make_session_factory()
    with Session.begin() as session:
        item = _reviewed_new_row()
        session.add(Product(name=item["name"], is_active=True, attributes={"kept": True}))
        session.flush()
        assert _insert_items(session, [item], "DiscountItem") == 1
        product = session.execute(select(Product)).scalar_one()
        assert product.is_active is True and product.attributes["kept"] is True
        assert session.execute(select(DiscountHistory)).scalar_one().price == 4150


def test_new_leaf_uses_explicit_native_quantity_fields_without_title_guess():
    Session = _make_session_factory()
    with Session.begin() as session:
        _seed_reviewed_leaf(session)
        item = {**_reviewed_new_row("출처 선언 상품"), "pack_qty": 250, "pack_unit": "g"}
        assert _insert_items(session, [item], "DiscountItem") == 1
        variant = session.execute(select(NormalizedProductVariant)).scalar_one()
        assert (variant.package_quantity, variant.package_unit, variant.bundle_count) == (250, "g", 1)


@pytest.mark.parametrize("source_bundle", [None, 1])
def test_explicit_whole600_field_never_multiplies_parser_bundle_twice(source_bundle):
    Session = _make_session_factory()
    with Session.begin() as session:
        _seed_reviewed_leaf(session)
        item = {**_reviewed_new_row("신라면5입600g(120gx5입)"), "package_quantity": 600, "package_unit": "g"}
        if source_bundle is not None:
            item["bundle_count"] = source_bundle
        assert _insert_items(session, [item], "DiscountItem") == 1
        history = session.execute(select(DiscountHistory)).scalar_one()
        assert history.raw_data["published_item"]["package_quantity"] == 600
        assert (history.raw_data["package_quantity"], history.raw_data["bundle_count"]) == (600, 1)
        assert history.price == 4150
        variants = session.execute(select(NormalizedProductVariant)).scalars().all()
        if source_bundle is None:
            assert len(variants) == 1
            assert (variants[0].package_quantity, variants[0].bundle_count) == (120, 5)
            assert variants[0].package_quantity * variants[0].bundle_count == 600
        else:
            assert variants == []
            assert "bundle_count_conflict" in history.raw_data["normalized_publication"]["review_reasons"]


def test_known_native_without_matched_tuple_is_held_instead_of_moved():
    Session = _make_session_factory()
    with Session.begin() as session:
        _seed_reviewed_leaf(session)
        item = _reviewed_new_row()
        assert _insert_items(session, [item], "DiscountItem") == 1
        listing = session.execute(select(NormalizedSourceListing)).scalar_one()
        original = (listing.public_source_listing_id, listing.public_variant_id)
        assert _insert_items(session, [{**item, "sale_price": 4300,
            "name": "변경된 표시명120g*5", "source_title": "변경된 표시명120g*5"}], "DiscountItem") == 1
        assert session.execute(select(NormalizedCanonicalProduct)).scalar_one()
        assert session.execute(select(NormalizedOfferEvent)).scalar_one().price == 4150
        assert (listing.public_source_listing_id, listing.public_variant_id) == original
        history = session.execute(select(DiscountHistory).where(DiscountHistory.price == 4300)).scalar_one()
        assert "existing_source_identity_requires_match" in history.raw_data["normalized_publication"]["review_reasons"]


def test_new_source_scoped_publication_replays_and_appends_without_identity_changes():
    Session = _make_session_factory()
    with Session.begin() as session:
        _seed_reviewed_leaf(session)
        item = _reviewed_new_row()
        assert _insert_items(session, [item], "DiscountItem") == 1
        first = session.execute(select(NormalizedOfferEvent)).scalar_one().public_offer_event_id
        assert _insert_items(session, [item], "DiscountItem") == 1
        assert session.execute(select(NormalizedOfferEvent)).scalar_one().public_offer_event_id == first
        assert _insert_items(session, [{**item, "sale_price": 4300,
            "crawled_at": "2026-10-08T08:00:00Z"}], "DiscountItem") == 1
        assert len(session.execute(select(NormalizedOfferEvent)).scalars().all()) == 2
        assert session.execute(select(NormalizedCanonicalProduct)).scalar_one()
        assert session.execute(select(NormalizedProductVariant)).scalar_one().bundle_count == 5
        assert session.execute(select(NormalizedSourceListing)).scalar_one().source_record_key == item["source_record_key"]


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


def test_approved_hotdeal_uses_external_post_and_preserves_identity_on_update():
    from storage.models import HotdealPost, HotdealPrice
    Session = _make_session_factory()
    item = {"title": "[스팀] 파이널판타지 16 컴플리트에디션 31920원",
            "source_url": "https://bbs.ruliweb.com/market/board/1020/read/107813",
            "source_record_key": "ruliweb:post:107813", "price": 31920,
            "source_community": "루리웹", "tags": ["currency:KRW", "price_basis:community_quote"],
            "crawled_at": "2026-10-06T10:15:17+00:00"}
    with Session.begin() as session:
        assert _insert_items(session, [item], "HotdealPost") == 1
        identity = session.execute(select(HotdealPost)).scalar_one().id
        assert _insert_items(session, [item], "HotdealPost") == 1
        assert _insert_items(session, [{**item, "price": 31000, "crawled_at": "2026-10-06T10:16:17+00:00"}], "HotdealPost") == 1
        assert _insert_items(session, [item], "HotdealPost") == 1  # Earlier receipt cannot overwrite newer quote.
        row = session.execute(select(HotdealPost)).scalar_one()
        assert row.id == identity and row.price == 31000 and row.original_price is None
        assert row.source_native_id == "ruliweb:post:107813" and row.tags == item['tags']
        assert session.query(Product).count() == session.query(HotdealPrice).count() == 0
        assert _insert_items(session, [{**item, "price": True}], "HotdealPost") == 0
