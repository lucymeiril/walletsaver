from __future__ import annotations

from copy import deepcopy
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.match_key import build_match_key
from services.catalog_bundle import validate_bundle
from services.initial_catalog_seed import (
    build_initial_catalog_bundle,
    normalize_pending_ingestions,
    stable_id,
    validated_brand,
)
from storage.models import Base


CATEGORIES = [
    {"id": "food", "parent_id": None, "name_ko": "식품"},
    {"id": "food.dairy", "parent_id": "food", "name_ko": "유제품"},
    {"id": "food.dairy.milk", "parent_id": "food.dairy", "name_ko": "우유"},
    {"id": "food.dairy.milk.chocolate", "parent_id": "food.dairy.milk", "name_ko": "초코우유"},
]
LEAF = "food.dairy.milk.chocolate"


def item(**changes):
    row = {
        "name": "초코우유 120ml×24", "brand": "__no_brand__", "source": "homeplus",
        "sale_price": 19900, "original_price": 24000,
        "package_quantity": 120, "package_unit": "ml", "display_unit": "120ml×24",
        "unit": "120ml×24", "crawled_at": "2026-09-02T10:00:00+09:00",
        "detail_url": "https://example.test/item/123", "category": "축산/유제품",
        "event_name": "홈플러스 할인",
        "attributes": {"source_record_key": "123", "brand": "씨제이", "mart_native_category_path": "축산/유제품 > 유제품 > 우유 > 초코우유"},
    }
    row.update(changes)
    return row


def ingestion(identifier=1, rows=None, mart="homeplus"):
    return {"id": identifier, "crawler_name": mart, "items_json": json.dumps(rows or [item()], ensure_ascii=False)}


def assignment(**changes):
    value = {"unified_category_id": LEAF, "classification_confidence": 0.95, "review_status": "classified"}
    value.update(changes)
    return value


def build(ingestions=None, assignments=None):
    return build_initial_catalog_bundle(
        ingestions or [ingestion()], categories=CATEGORIES,
        assignments=assignments if assignments is not None else {("homeplus", "123"): assignment()},
        run_id="test-initial-catalog",
    )


def test_nested_brand_and_full_source_path_win_over_enrichment_placeholders():
    normalized = normalize_pending_ingestions([ingestion()])[0]
    assert normalized["brand"] == "CJ"
    assert normalized["source_category_path"] == ["축산/유제품", "유제품", "우유", "초코우유"]
    assert normalized["source_record_key"] == "123"
    assert normalized["package"]["bundle_count"] == 24
    assert normalized["crawled_at"] == "2026-09-02T01:00:00Z"
    assert normalized["raw_payload"]["brand"] == "__no_brand__"
    assert normalized["issues"] == []


@pytest.mark.parametrize("value", ["__no_brand__", "브랜드없음", "단독기획", "국내산", "미국산", ""])
def test_generic_brand_is_not_a_product_brand(value):
    assert validated_brand(value) is None


def test_emart_collection_is_not_inferred_to_be_a_brand_and_no_brand_is_real_brand():
    row = item(attributes={"source_record_key": "123", "collection": "백설", "category_path": ["식품", "소스"]})
    assert normalize_pending_ingestions([ingestion(rows=[row], mart="emart")])[0]["brand"] is None
    assert validated_brand("노브랜드") == "노브랜드"
    assert validated_brand("12Brix") is None
    assert validated_brand("국내산(제주)") is None


def test_display_unit_restores_explicit_multiplier_when_title_has_no_quantity():
    bundle = build([ingestion(1, [item(name="초코우유", sale_price=24000, original_price=None)])])
    assert bundle["variants"][0]["bundle_count"] == 24
    assert bundle["offers"][0]["standard_unit_price"] == pytest.approx(833.3333)


def test_display_and_title_multiplier_conflict_is_held():
    bundle = build([ingestion(1, [item(display_unit="120ml×12")])])
    assert "bundle_count_conflict" in bundle["unresolved"][0]["reasons"]


def test_legacy_comma_quantity_misparse_and_mixed_refill_are_held():
    for raw in [
        item(name="샴푸 1,050ml", package_quantity=50, display_unit="50ml"),
        item(name="샴푸 본품500ml+리필450ml", package_quantity=450, display_unit="450ml"),
    ]:
        bundle = build([ingestion(1, [raw])])
        assert "multiple_package_quantities" in bundle["unresolved"][0]["reasons"]


def test_generic_homeplus_badge_does_not_invent_conditional_benefit():
    bundle = build([ingestion(1, [item(event_name="행사상품")])])
    assert bundle["offers"][0]["price"] == 19900
    assert bundle["offers"][0]["promotion_type"] == "was_now_price"


def test_different_explicit_promotion_conditions_do_not_collapse():
    first = item(promo_type="checkout_discount")
    second = deepcopy(first)
    first["attributes"]["is_member_only"] = True
    second["attributes"]["is_member_only"] = False
    bundle = build([ingestion(1, [first]), ingestion(2, [second])])
    assert len(bundle["offers"]) == 2


def test_conditional_price_without_safe_semantics_is_not_comparable():
    row = item(original_price=None, coupon_required=True)
    bundle = build([ingestion(1, [row])])
    offer = bundle["offers"][0]
    assert offer["offer_state"] == "pending_review"
    assert offer["promotion_type"] == "unknown"
    assert offer["price"] == row["sale_price"]
    assert offer["standard_unit_price"] is None
    assert offer["price_per_100g"] is None
    assert bundle["offer_week_links"][0]["observed_min_price"] is None
    assert bundle["offer_week_links"][0]["observed_max_price"] is None
    assert bundle["products"][0]["is_active"] is False
    assert "promotion_conditions_unresolved" in offer["audit_provenance"]["review_reasons"]
    assert bundle["unresolved"] == []


def test_costco_only_can_use_explicitly_labelled_utc_batch_received_time_proxy():
    raw = item(crawled_at=None)
    batch = {**ingestion(1, [raw], "costco"), "crawled_at": "2026-09-02T01:02:03.123456"}
    bundle = build([batch], {("costco", "123"): assignment()})
    offer = bundle["offers"][0]
    assert offer["crawled_at"] == "2026-09-02T01:02:03.123456Z"
    assert offer["audit_provenance"]["timestamp_source"] == "ingestion_received_at"
    assert offer["audit_provenance"]["observed_time_precision"] == "batch"
    assert offer["raw_evidence"]["observations"][0]["raw_payload"]["crawled_at"] is None
    homeplus = build([{**batch, "crawler_name": "homeplus"}])
    assert "item_crawled_at_missing_or_invalid" in homeplus["unresolved"][0]["reasons"]


def test_exact_retry_collapses_offer_but_keeps_each_original_payload_and_id():
    first = ingestion(10)
    second = ingestion(11)
    bundle = build([first, second])
    assert len(bundle["source_listings"]) == 1
    assert len(bundle["offers"]) == 1
    offer = bundle["offers"][0]
    assert offer["audit_provenance"]["source_ingestion_ids"] == [10, 11]
    assert offer["audit_provenance"]["raw_record_ids"] == ["ingestion:10:0", "ingestion:11:0"]
    assert len(offer["raw_evidence"]["observations"]) == 2
    assert all(row["raw_payload"] == item() for row in offer["raw_evidence"]["observations"])
    assert bundle["build_report"]["exact_retry_observations_collapsed"] == 1
    assert bundle["build_report"]["source_observations"] == 2


def test_real_same_day_and_next_day_crawls_remain_distinct_offers():
    bundle = build([
        ingestion(1),
        ingestion(2, [item(crawled_at="2026-09-02T10:06:00+09:00")]),
        ingestion(3, [item(crawled_at="2026-09-03T10:00:00+09:00")]),
    ])
    assert len(bundle["source_listings"]) == 1
    assert len(bundle["offers"]) == 3
    assert len({row["crawled_at"] for row in bundle["offers"]}) == 3


def test_timezone_equivalent_retries_are_the_same_observation_time():
    bundle = build([ingestion(1), ingestion(2, [item(crawled_at="2026-09-02T01:00:00Z")])])
    assert len(bundle["offers"]) == 1


def test_costco_uses_checkout_sale_not_regular_price():
    row = item(source="costco", price=39990, sale_price=35990, original_price=None,
               promo_label="4,000원 할인", promo_type="checkout_discount", event_name="4,000원 할인")
    bundle = build([ingestion(1, [row], "costco")], {("costco", "123"): assignment()})
    offer = bundle["offers"][0]
    assert offer["price"] == 35990
    assert offer["original_price"] == 39990
    assert offer["promotion_type"] == "checkout_discount"
    assert bundle["offer_week_links"][0]["observed_min_price"] is None


def test_costco_nested_regular_price_is_preserved():
    row = item(source="costco", sale_price=35990, original_price=None, promo_label="4,000원 할인")
    row["attributes"].update(price=39990, sale_price=35990)
    bundle = build([ingestion(1, [row], "costco")], {("costco", "123"): assignment()})
    assert bundle["offers"][0]["original_price"] == 39990


@pytest.mark.parametrize("change,reason", [
    ({"package_unit": "mystery"}, "unit_unknown"),
    ({"package_quantity": None}, "unit_unresolved"),
    ({"crawled_at": None}, "item_crawled_at_missing_or_invalid"),
    ({"sale_price": 0}, "sale_price_missing_or_invalid"),
    ({"name": "초코우유 120ml+120ml 기획", "display_unit": "120ml"}, "mixed_package_unresolved"),
])
def test_ambiguous_source_is_held_with_complete_evidence(change, reason):
    raw = item(**change)
    bundle = build([ingestion(1, [raw])])
    assert bundle["offers"] == []
    assert reason in bundle["unresolved"][0]["reasons"]
    assert bundle["unresolved"][0]["raw_payload"] == raw
    assert bundle["observation_accounting"][0]["status"] == "unresolved"


def test_name_or_spec_change_on_same_listing_is_not_an_automatic_alias():
    changed = item(name="초코우유 새이름 140ml×12", package_quantity=140, display_unit="140ml×12")
    bundle = build([ingestion(1), ingestion(2, [changed])])
    assert not bundle["products"] and not bundle["source_listings"]
    assert len(bundle["unresolved"]) == 2
    assert all("source_title_changed" in row["reasons"] for row in bundle["unresolved"])
    assert all("source_specification_changed" in row["reasons"] for row in bundle["unresolved"])


def test_unassigned_internal_leaf_and_low_confidence_do_not_publish():
    assert "catalog_assignment_missing" in build(assignments={})["unresolved"][0]["reasons"]
    for decision in [assignment(unified_category_id="food.dairy"), assignment(classification_confidence=0.79)]:
        assert not build(assignments={("homeplus", "123"): decision})["offers"]
    approved = build(assignments={("homeplus", "123"): assignment(classification_confidence=0.79, review_status="approved")})
    assert len(approved["offers"]) == 1
    assert approved["match_rules"] == []


def test_same_unbranded_name_across_marts_does_not_merge_and_collision_rule_is_held():
    raw = item(brand="__no_brand__")
    raw["attributes"]["brand"] = "국내산"
    bundle = build([ingestion(1, [raw], "homeplus"), ingestion(2, [raw], "emart")], {
        ("homeplus", "123"): assignment(), ("emart", "123"): assignment(),
    })
    assert len(bundle["products"]) == 2
    assert len(bundle["variants"]) == 2
    assert len(bundle["source_listings"]) == 2
    assert all(product["brand"] is None for product in bundle["products"])
    assert bundle["match_rules"] == []
    assert bundle["review_issues"][0]["reason"] == "runtime_match_key_collision"


def test_reviewed_product_group_has_distinct_package_variants():
    small = item(name="초코우유 140ml×12", package_quantity=140, display_unit="140ml×12")
    decision = assignment(product_group_key="cj-chocolate-milk", canonical_name="초코우유", brand="CJ")
    bundle = build([ingestion(1), ingestion(2, [small], "emart")], {
        ("homeplus", "123"): decision, ("emart", "123"): decision,
    })
    assert len(bundle["products"]) == 1
    assert len(bundle["variants"]) == 2
    assert {(row["package_quantity"], row["bundle_count"]) for row in bundle["variants"]} == {(120, 24), (140, 12)}


def test_explicit_product_group_with_conflicting_fallback_brands_is_held():
    first, second = item(), item()
    first["attributes"]["brand"] = "Brand A"
    second["attributes"]["brand"] = "Brand B"
    decision = assignment(product_group_key="same", canonical_name="초코우유")
    bundle = build([ingestion(1, [first]), ingestion(2, [second], "emart")], {
        ("homeplus", "123"): decision, ("emart", "123"): decision,
    })
    assert bundle["products"] == []
    assert all("product_group_conflict" in row["reasons"] for row in bundle["unresolved"])


def test_classification_attributes_are_preserved_with_source_evidence_without_mutation():
    attributes = {"fat_content": "low_fat", "sterilized": False, "unknown_trait": None, "source_labels": ["저지방"]}
    assignments = {("homeplus", "123"): assignment(classification_attributes=attributes, classification_reason="explicit name token")}
    original = deepcopy(assignments)
    bundle = build(assignments=assignments)
    product_attributes = bundle["products"][0]["attributes"]
    assert product_attributes["classification_attributes"] == attributes
    assert product_attributes["classification_attribute_evidence"] == [{
        "source_name": "homeplus", "source_record_key": "123",
        "classification_attributes": attributes, "classification_reason": "explicit name token",
        "source_ingestion_ids": [1], "raw_record_ids": ["ingestion:1:0"],
    }]
    product_attributes["classification_attributes"]["source_labels"].append("changed output")
    assert assignments == original


def test_explicit_group_merges_compatible_known_attributes_but_none_is_not_false():
    common = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    bundle = build([ingestion(1), ingestion(2, [item()], "emart")], {
        ("homeplus", "123"): {**common, "classification_attributes": {"fat_content": None, "sterilized": False}},
        ("emart", "123"): {**common, "classification_attributes": {"fat_content": "low_fat", "sterilized": False}},
    })
    assert len(bundle["products"]) == 1
    attributes = bundle["products"][0]["attributes"]
    assert attributes["classification_attributes"] == {"fat_content": "low_fat", "sterilized": False}
    assert {row["source_name"] for row in attributes["classification_attribute_evidence"]} == {"homeplus", "emart"}
    assert any(row["classification_attributes"]["fat_content"] is None for row in attributes["classification_attribute_evidence"])
    assert bundle["build_report"]["classification_attribute_conflict_groups"] == 0


@pytest.mark.parametrize("first_value,second_value", [("low_fat", "fat_free"), (True, False), (False, 0)])
def test_explicit_group_attribute_conflicts_hold_all_members_and_preserve_candidates(first_value, second_value):
    common = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    decisions = {
        ("homeplus", "123"): {**common, "classification_attributes": {"trait": first_value}},
        ("emart", "123"): {**common, "classification_attributes": {"trait": second_value}},
    }
    sources = [ingestion(1), ingestion(2, [item()], "emart")]
    bundle = build(sources, decisions)
    assert bundle == build(list(reversed(sources)), dict(reversed(list(decisions.items()))))
    assert bundle["products"] == []
    assert bundle["variants"] == []
    assert bundle["source_listings"] == []
    assert bundle["offers"] == []
    assert bundle["match_rules"] == []
    assert len(bundle["unresolved"]) == 2
    assert all("product_group_classification_attribute_conflict" in row["reasons"] for row in bundle["unresolved"])
    assert bundle["unresolved"][0]["classification_attributes"] == {"trait": first_value}
    assert bundle["unresolved"][1]["classification_attributes"] == {"trait": second_value}
    issue = bundle["review_issues"][0]
    assert issue["reason"] == "product_group_classification_attribute_conflict"
    assert issue["raw_record_ids"] == ["ingestion:1:0", "ingestion:2:0"]
    assert len(issue["attribute_conflicts"]["trait"]) == 2
    assert {source["source_name"] for candidate in issue["attribute_conflicts"]["trait"] for source in candidate["sources"]} == {"homeplus", "emart"}
    assert all(row["status"] == "unresolved" for row in bundle["observation_accounting"])
    assert bundle["build_report"]["classification_attribute_conflict_groups"] == 1


def test_nested_classification_attributes_compare_values_not_object_key_order():
    common = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    bundle = build([ingestion(1), ingestion(2, [item()], "emart")], {
        ("homeplus", "123"): {**common, "classification_attributes": {"nutrition": {"fat": "low", "sugar": "none"}}},
        ("emart", "123"): {**common, "classification_attributes": {"nutrition": {"sugar": "none", "fat": "low"}}},
    })
    assert len(bundle["products"]) == 1
    assert bundle["products"][0]["attributes"]["classification_attributes"] == {"nutrition": {"fat": "low", "sugar": "none"}}


def test_classification_attribute_evidence_survives_an_unrelated_unit_blocker():
    bundle = build([ingestion(1, [item(package_unit="unknown-unit")])], {
        ("homeplus", "123"): assignment(classification_attributes={"fat_content": "low_fat"}),
    })
    assert bundle["products"] == []
    unresolved = bundle["unresolved"][0]
    assert unresolved["classification_attributes"] == {"fat_content": "low_fat"}
    assert unresolved["classification_attribute_evidence"]["raw_record_ids"] == ["ingestion:1:0"]
    assert "unit_unknown" in unresolved["reasons"]


def test_non_object_classification_attributes_are_held_not_silently_discarded():
    bundle = build(assignments={("homeplus", "123"): assignment(classification_attributes=["low_fat"])})
    assert bundle["products"] == []
    unresolved = bundle["unresolved"][0]
    assert "classification_attributes_invalid" in unresolved["reasons"]
    assert unresolved["classification_attributes"] == ["low_fat"]
    assert unresolved["classification_attribute_evidence"]["classification_attributes"] == ["low_fat"]


def test_report_separates_classification_from_safe_offer_coverage():
    bundle = build([ingestion(1, [item(promo_label="함께할인")])])
    assert bundle["build_report"]["classification_coverage"]["observations"] == 1
    assert bundle["build_report"]["included_observations"] == 1
    assert bundle["build_report"]["staged_observations"] == 1
    assert bundle["build_report"]["active_offer_observations"] == 0
    assert bundle["build_report"]["pending_promotion_observations"] == 1
    assert bundle["build_report"]["pending_promotion_offers"] == 1
    assert bundle["build_report"]["offer_coverage_by_mart"] == {"homeplus": 1}
    assert bundle["build_report"]["active_offer_coverage_by_mart"] == {}
    assert bundle["build_report"]["included_means"] == "staged_only_not_publicly_approved"
    assert bundle["build_report"]["public_approval"] is False
    assert bundle["observation_accounting"][0]["offer_state"] == "pending_review"
    assert bundle["observation_accounting"][0]["publication_status"] == "not_approved"


def test_promotion_only_retry_retains_all_raw_evidence_and_one_review_issue():
    raw = item(promo_label="함께할인")
    bundle = build([ingestion(1, [raw]), ingestion(2, [raw])])
    assert len(bundle["offers"]) == 1
    assert bundle["offers"][0]["offer_state"] == "pending_review"
    assert [row["raw_payload"] for row in bundle["offers"][0]["raw_evidence"]["observations"]] == [raw, raw]
    assert len(bundle["review_issues"]) == 1
    assert bundle["review_issues"][0]["reason"] == "promotion_pending_review"
    assert bundle["review_issues"][0]["raw_record_ids"] == ["ingestion:1:0", "ingestion:2:0"]
    assert bundle["build_report"]["runtime_match_key_collisions"] == 0
    assert bundle["build_report"]["pending_promotion_observations"] == 2


def test_promotion_plus_identity_problem_still_holds_entire_observation():
    bundle = build([ingestion(1, [item(promo_label="함께할인", package_unit="unknown-unit")])])
    assert bundle["offers"] == []
    assert "unit_unknown" in bundle["unresolved"][0]["reasons"]
    assert "promotion_unresolved" in bundle["unresolved"][0]["reasons"]


def test_group_is_active_if_any_listing_has_an_active_offer_regardless_of_order():
    decision = assignment(product_group_key="shared-milk", canonical_name="초코우유", brand="CJ")
    for first_pending in (True, False):
        homeplus = item(promo_label="함께할인") if first_pending else item()
        emart = item() if first_pending else item(promo_label="함께할인")
        bundle = build([ingestion(1, [homeplus]), ingestion(2, [emart], "emart")], {
            ("homeplus", "123"): decision, ("emart", "123"): decision,
        })
        assert len(bundle["products"]) == 1
        assert bundle["products"][0]["is_active"] is True
        assert {row["offer_state"] for row in bundle["offers"]} == {"active", "pending_review"}


def test_fixed_display_label_requires_exact_independent_price_match():
    exact = build([ingestion(1, [item(event_name="균일가 5,980원", sale_price=5980, original_price=None)])])
    assert exact["offers"][0]["offer_state"] == "active"
    assert exact["offers"][0]["promotion_type"] == "final_price"
    assert exact["offers"][0]["price"] == 5980
    mismatch = build([ingestion(1, [item(event_name="균일가 5,980원", sale_price=6980, original_price=None)])])
    assert mismatch["offers"][0]["offer_state"] == "pending_review"
    assert mismatch["offers"][0]["price"] == 6980


def test_runtime_miss_match_key_is_preserved_and_fallback_matches_shared_contract():
    runtime = item(match_key="__no_brand__|runtime full name|120.0|ml", matching_status="miss")
    assert build([ingestion(1, [runtime])])["match_rules"][0]["match_key"] == runtime["match_key"]
    assert build()["match_rules"][0]["match_key"] == build_match_key("__no_brand__", item()["name"], None, "120ml×24")


def test_ids_and_bundle_are_stable_under_ingestion_order_and_input_is_unchanged():
    ingestions = [ingestion(5), ingestion(6, [item(crawled_at="2026-09-03T10:00:00+09:00")])]
    original = deepcopy(ingestions)
    assert build(ingestions) == build(reversed(ingestions))
    assert ingestions == original
    assert stable_id("listing", "a|b", "c") != stable_id("listing", "a", "b|c")
    assert len(normalize_pending_ingestions([ingestions[0], ingestions[0]])) == 1


def test_generated_bundle_validates_against_current_v2_import_contract():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        result = validate_bundle(session, build(), "test-hash")
    assert result.ok, result.errors


def test_all_raw_rows_accounted_even_with_invalid_item_and_missing_source_key():
    missing = item(attributes={"brand": "CJ"})
    bundle = build([ingestion(1, [item(), missing, None])])
    assert bundle["build_report"]["source_observations"] == 3
    assert len(bundle["observation_accounting"]) == 3
    assert {row["raw_record_id"] for row in bundle["observation_accounting"]} == {"ingestion:1:0", "ingestion:1:1", "ingestion:1:2"}
    assert bundle["unresolved"][-1]["raw_payload"] is None
