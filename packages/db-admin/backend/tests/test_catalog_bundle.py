from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from services.catalog_bundle import SCHEMA_VERSION, apply_bundle, parse_bundle, validate_bundle
from storage.models import (
    Base,
    Keyword,
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
        "keywords": [{
            "word": "초코우유",
            "synonyms": ["초콜릿우유", "chocolate milk"],
            "unified_category_id": "food.dairy.milk.chocolate",
        }],
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


def test_reimport_same_offer_from_new_ingestion_preserves_both_raw_observations():
    session = _session()
    bundle = _bundle()
    offer = bundle["offers"][0]
    for ingestion in (10, 11):
        raw_id = f"ingestion:{ingestion}:0"
        offer["raw_record_id"] = raw_id
        offer["raw_evidence"] = {"observations": [{"raw_record_id": raw_id, "raw_payload": {"price": 19900}}]}
        offer["audit_provenance"] = {"raw_record_ids": [raw_id], "source_ingestion_ids": [ingestion], "observation_count": 1}
        apply_bundle(session, bundle, f"hash-{ingestion}", user="tester")
        session.commit()
    stored = session.get(NormalizedOfferEvent, offer["public_offer_event_id"])
    assert session.query(NormalizedOfferEvent).count() == 1
    assert stored.raw_record_id == "ingestion:10:0"
    assert stored.audit_provenance["source_ingestion_ids"] == [10, 11]
    assert stored.audit_provenance["observation_count"] == 2
    assert len(stored.raw_evidence["observations"]) == 2


def test_manifest_rejects_dropped_original_observation():
    session = _session()
    bundle = _bundle()
    bundle["source_manifest"] = {"source_ingestions": [{"id": 1, "items_count": 1}], "observation_count": 1}
    bundle["observation_accounting"] = []
    validation = validate_bundle(session, bundle, "hash")
    assert not validation.ok
    assert any("원본 행" in error for error in validation.errors)


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
    assert session.query(Keyword).count() == 1
    assert session.query(NormalizedCanonicalProduct).count() == 1
    assert session.query(NormalizedProductVariant).count() == 1
    assert session.query(NormalizedOfferEvent).count() == 1
    assert [row.level for row in session.execute(select(UnifiedCategory).order_by(UnifiedCategory.level)).scalars()] == [0, 1, 2, 3]
    rule = session.execute(select(MatchingEntry)).scalar_one()
    assert rule.public_product_id == "prod-chocoemong"
    assert rule.public_variant_id == "var-chocoemong-120ml-24"
    keyword = session.execute(select(Keyword)).scalar_one()
    assert keyword.unified_category_id == "food.dairy.milk.chocolate"
    assert keyword.category_id is None
    assert keyword.synonyms == ["초콜릿우유", "chocolate milk"]


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
    assert bundle["keywords"] == []
    assert bundle["products"] == []


def test_keyword_definitions_require_unified_category_and_clean_unique_terms():
    session = _session()

    missing_category = _bundle()
    missing_category["keywords"][0]["unified_category_id"] = "missing"
    result = validate_bundle(session, missing_category, "missing-category")
    assert any("없는 통합 카테고리" in error for error in result.errors)

    duplicate_synonym = _bundle()
    duplicate_synonym["keywords"][0]["synonyms"] = ["초코우유"]
    result = validate_bundle(session, duplicate_synonym, "duplicate-synonym")
    assert any("중복 synonym" in error for error in result.errors)

    duplicate_word = _bundle()
    duplicate_word["keywords"].append({**duplicate_word["keywords"][0]})
    result = validate_bundle(session, duplicate_word, "duplicate-word")
    assert any("중복 word" in error for error in result.errors)


def test_keyword_definition_upsert_preserves_search_count():
    session = _session()
    keyword = Keyword(
        word="초코우유",
        synonyms=["old"],
        category_id=None,
        search_count=17,
        is_active=False,
    )
    session.add(keyword)
    session.commit()

    bundle = _bundle()
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
    apply_bundle(session, bundle, digest, user="tester")
    session.commit()

    session.refresh(keyword)
    assert keyword.search_count == 17
    assert keyword.is_active is True
    assert keyword.synonyms == ["초콜릿우유", "chocolate milk"]
    assert keyword.unified_category_id == "food.dairy.milk.chocolate"


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


def test_old_bundle_without_optional_keywords_still_validates_directly():
    bundle = _bundle()
    del bundle["keywords"]
    assert validate_bundle(_session(), bundle, "old").ok


def test_duplicate_listing_keys_and_equivalent_variant_specs_are_rejected():
    bundle = _bundle()
    bundle["source_listings"].append({
        **bundle["source_listings"][0], "public_source_listing_id": "duplicate-listing",
    })
    bundle["variants"].append({
        **bundle["variants"][0], "public_variant_id": "duplicate-variant",
        "package_quantity": 0.12, "package_unit": "L",
    })
    errors = validate_bundle(_session(), bundle, "duplicates").errors
    assert any("중복 마트 원본 ID" in error for error in errors)
    assert any("중복 variant" in error for error in errors)


def test_match_key_collision_and_wrong_variant_parent_are_rejected():
    bundle = _bundle()
    bundle["products"].append({**bundle["products"][0], "public_product_id": "other-product"})
    bundle["match_rules"].append({**bundle["match_rules"][0], "public_product_id": "other-product"})
    errors = validate_bundle(_session(), bundle, "wrong-target").errors
    assert any("중복 match_key" in error for error in errors)
    assert any("상품군에 속하지" in error for error in errors)


def test_malformed_package_and_entity_shapes_return_validation_errors():
    bundle = _bundle()
    bundle["variants"][0]["bundle_count"] = "not-a-number"
    assert not validate_bundle(_session(), bundle, "bad-count").ok
    bundle["products"] = [None]
    assert not validate_bundle(_session(), bundle, "bad-shape").ok


def test_unparsed_variant_unit_is_not_imported_as_public_variant():
    bundle = _bundle()
    bundle["variants"][0]["package_unit"] = "mystery"
    assert not validate_bundle(_session(), bundle, "unknown-unit").ok


def test_offer_timestamp_is_normalized_to_utc_on_import():
    session = _session()
    bundle = _bundle()
    bundle["offers"][0]["crawled_at"] = "2026-09-03T09:00:00+09:00"
    apply_bundle(session, bundle, "timezone", user="tester")
    offer = session.execute(select(NormalizedOfferEvent)).scalar_one()
    assert offer.crawled_at.isoformat() == "2026-09-03T00:00:00"
