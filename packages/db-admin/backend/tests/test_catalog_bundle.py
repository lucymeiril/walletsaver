from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from services.catalog_bundle import SCHEMA_VERSION, apply_bundle, parse_bundle, validate_bundle
from storage.models import (
    Base,
    MatchingEntry,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedProductVariant,
    UnifiedCategory,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _bundle():
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": "run-2026-08-30",
        "categories": [
            {"id": "food", "parent_id": None, "name_ko": "식품"},
            {"id": "food.dairy", "parent_id": "food", "name_ko": "유제품"},
            {"id": "food.dairy.milk", "parent_id": "food.dairy", "name_ko": "우유"},
            {"id": "food.dairy.milk.chocolate", "parent_id": "food.dairy.milk", "name_ko": "초코우유"},
        ],
        "products": [{
            "public_product_id": "prod-chocoemong",
            "unified_category_id": "food.dairy.milk.chocolate",
            "canonical_name": "초코에몽",
            "classification_confidence": 0.95,
        }],
        "variants": [{
            "public_variant_id": "var-chocoemong-120ml-24",
            "public_product_id": "prod-chocoemong",
            "variant_name": "초코에몽 120ml 24개",
            "package_quantity": 120,
            "package_unit": "ml",
            "bundle_count": 24,
        }],
        "source_listings": [{
            "public_source_listing_id": "listing-emart-1",
            "public_variant_id": "var-chocoemong-120ml-24",
            "source_name": "emart",
            "source_record_key": "1",
            "source_title": "초코에몽 120ml*24",
            "source_url": "https://example.test/1",
        }],
        "offers": [{
            "public_offer_event_id": "offer-emart-1-20260830",
            "public_source_listing_id": "listing-emart-1",
            "price_state": "normal",
            "promotion_type": "was_now_price",
            "price": 19900,
            "original_price": 24000,
            "crawled_at": "2026-08-30T00:00:00Z",
        }],
        "week_buckets": [{
            "public_week_bucket_id": "week-20260824",
            "week_start": "2026-08-24T00:00:00Z",
            "week_end": "2026-08-31T00:00:00Z",
        }],
        "offer_week_links": [{
            "public_offer_event_id": "offer-emart-1-20260830",
            "public_week_bucket_id": "week-20260824",
            "observed_min_price": 19900,
            "observed_max_price": 19900,
        }],
        "match_rules": [{
            "match_key": "남양|초코에몽|120.000000|ml",
            "public_product_id": "prod-chocoemong",
            "public_variant_id": "var-chocoemong-120ml-24",
            "confidence": 0.98,
        }],
        "mart_category_mappings": [{
            "mart": "emart",
            "mart_native_id": "dairy/milk/choco",
            "mart_native_path": "유제품 > 우유 > 초코우유",
            "unified_category_id": "food.dairy.milk.chocolate",
            "trust": "external-ai",
            "confidence": 0.95,
        }],
        "unresolved": [],
    }


def test_catalog_bundle_apply_is_atomic_shape_and_idempotent():
    session = _session()
    bundle = _bundle()
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()

    validation = validate_bundle(session, bundle, digest)
    assert validation.ok, validation.errors
    first = apply_bundle(session, bundle, digest, user="tester")
    session.commit()
    second = apply_bundle(session, bundle, digest, user="tester")

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert session.query(UnifiedCategory).count() == 4
    assert session.query(NormalizedCanonicalProduct).count() == 1
    assert session.query(NormalizedProductVariant).count() == 1
    assert session.query(NormalizedOfferEvent).count() == 1
    assert [row.level for row in session.execute(select(UnifiedCategory).order_by(UnifiedCategory.level)).scalars()] == [0, 1, 2, 3]
    rule = session.execute(select(MatchingEntry)).scalar_one()
    assert rule.public_product_id == "prod-chocoemong"
    assert rule.public_variant_id == "var-chocoemong-120ml-24"


def test_category_cycle_and_fifth_level_are_rejected():
    session = _session()
    cycle = _bundle()
    cycle["categories"][0]["parent_id"] = "food.dairy.milk.chocolate"
    assert not validate_bundle(session, cycle, "cycle").ok

    too_deep = _bundle()
    too_deep["categories"].append({
        "id": "food.dairy.milk.chocolate.small",
        "parent_id": "food.dairy.milk.chocolate",
        "name_ko": "소용량",
    })
    assert any("4단계를 초과" in error for error in validate_bundle(session, too_deep, "deep").errors)


def test_product_must_use_leaf_and_low_confidence_requires_approval():
    session = _session()
    internal = _bundle()
    internal["products"][0]["unified_category_id"] = "food.dairy.milk"
    assert any("리프" in error for error in validate_bundle(session, internal, "internal").errors)

    low = _bundle()
    low["products"][0]["classification_confidence"] = 0.79
    assert any("approved" in error for error in validate_bundle(session, low, "low").errors)
    low["products"][0]["review_status"] = "approved"
    approved = validate_bundle(session, low, "approved")
    assert approved.ok
    assert approved.review_counts["low_confidence_approved"] == 1


def test_json_parser_populates_optional_entities():
    content = json.dumps({"schema_version": SCHEMA_VERSION, "run_id": "x"}).encode()
    bundle, digest = parse_bundle(content)
    assert digest == hashlib.sha256(content).hexdigest()
    assert bundle["products"] == []


def test_imported_category_level_is_derived_from_parent_tree():
    session = _session()
    bundle = _bundle()
    for row in bundle["categories"]:
        row["level"] = 0
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()

    apply_bundle(session, bundle, digest, user="tester")
    session.flush()

    levels = {
        row.id: row.level
        for row in session.execute(select(UnifiedCategory)).scalars()
    }
    assert levels["food"] == 0
    assert levels["food.dairy.milk.chocolate"] == 3
