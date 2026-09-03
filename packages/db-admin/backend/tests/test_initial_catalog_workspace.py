from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest

from services.initial_catalog_workspace import merge_review_decisions, prepare_assignments, prepare_workspace, prune_unused_categories, read_pending_source, rehearse_import, render_review


def categories():
    return [{"id": "food", "name_ko": "식품", "parent_id": None},
            {"id": "food.milk", "name_ko": "우유", "parent_id": "food"},
            {"id": "food.other", "name_ko": "미사용", "parent_id": "food"}]


def classification(_):
    return {"unified_category_id": "food.milk", "classification_confidence": 0.95,
            "review_status": "classified", "classification_reason": "fixture source path"}


def source(tmp_path):
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE pending_ingestions (id INTEGER PRIMARY KEY, crawler_name TEXT, crawled_at TEXT, items_json TEXT, items_count INTEGER, status TEXT)")
        for index, mart in enumerate(("emart", "homeplus", "lottemart", "costco"), 1):
            payload = {"name": "검증우유 200ml", "source_record_key": str(index), "crawled_at": "2026-09-02T12:00:00+09:00",
                       "package_quantity": 200, "package_unit": "ml", "sale_price": 1000,
                       "attributes": {"mart_native_category_path": ["식품", "우유"]}}
            db.execute("INSERT INTO pending_ingestions VALUES (?, ?, ?, ?, 1, 'PENDING')",
                       (index, mart, "2026-09-02T03:01:00", json.dumps([payload], ensure_ascii=False)))
    return path


def test_workspace_reads_source_without_mutation_and_imports_twice(tmp_path):
    database = source(tmp_path)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = prepare_workspace(database, tmp_path / "review", run_id="fixture-review",
                               categories=categories(), classifier=classification, keywords=[])
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert result["build_report"]["source_observations"] == 4
    assert result["build_report"]["included_observations"] == 4
    assert result["rehearsal"]["applied"] is True
    assert result["rehearsal"]["second_idempotent"] is True
    assert result["rehearsal"]["foreign_key_violations"] == 0
    assert result["source_read_only"] and not result["public_approval"]
    assert result["category_count"] == 2
    assert result["cross_mart_candidate_groups"] == 1
    assert result["build_report"]["entity_counts"]["products"] == 4  # no unreviewed cross-mart merge
    report = (tmp_path / "review" / "review.html").read_text(encoding="utf-8")
    assert all(f"ingestion:{i}:0" in report for i in range(1, 5))


def test_existing_workspace_is_not_overwritten(tmp_path):
    database = source(tmp_path)
    output = tmp_path / "review"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("evidence")
    with pytest.raises(FileExistsError):
        prepare_workspace(database, output, run_id="review", categories=categories(), classifier=classification, keywords=[])
    assert marker.read_text() == "evidence"


def test_all_four_marts_and_consistent_counts_required(tmp_path):
    database = source(tmp_path)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE pending_ingestions SET items_count=2 WHERE id=1")
    with pytest.raises(ValueError, match="JSON/count"):
        read_pending_source(database)
    with sqlite3.connect(database) as db:
        db.execute("DELETE FROM pending_ingestions WHERE id=1")
    with pytest.raises(ValueError, match="all four"):
        read_pending_source(database)


def test_one_conflicting_or_weak_observation_holds_listing():
    rows = [{"raw_record_id": str(i), "source_name": "homeplus", "source_record_key": "one", "tag": i} for i in range(2)]
    def weak(row):
        return {**classification(row), "classification_confidence": 0.6 if row["tag"] else 0.95}
    assert prepare_assignments(rows, weak)[0] == {}
    def conflict(row):
        return {**classification(row), "unified_category_id": "food.other" if row["tag"] else "food.milk"}
    assert prepare_assignments(rows, conflict)[0] == {}
    def attribute_conflict(row):
        return {**classification(row), "classification_attributes": {"sterilized": bool(row["tag"])}}
    assert prepare_assignments(rows, attribute_conflict)[0] == {}


def test_pruning_never_makes_internal_assignment_valid():
    bundle = {"categories": categories(), "products": [{"unified_category_id": "food"}], "keywords": []}
    with pytest.raises(ValueError, match="internal"):
        prune_unused_categories(bundle)


def test_html_report_escapes_raw_source_text():
    row = {"raw_record_id": "one", "source_name": "emart", "source_title": "<script>unsafe</script>", "price": 1, "package": None, "source_category_path": []}
    bundle = {"categories": [], "observation_accounting": [{"raw_record_id": "one", "status": "unresolved"}]}
    report = render_review([row], [{"classification_reason": "<img>"}], bundle)
    assert "<script>unsafe</script>" not in report
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in report
    assert "&lt;img&gt;" in report


def test_html_report_exposes_actual_merged_identity_and_reviewed_package():
    row = {"raw_record_id": "one", "source_name": "emart", "source_title": "원본 이름", "price": 1, "package": {"package_quantity": 200}, "source_category_path": []}
    bundle = {"categories": [], "observation_accounting": [{"raw_record_id": "one", "status": "included", "public_source_listing_id": "listing-one", "offer_state": "pending_review"}],
              "source_listings": [{"public_source_listing_id": "listing-one", "public_variant_id": "var-one"}],
              "variants": [{"public_variant_id": "var-one", "public_product_id": "merged-family", "package_quantity": 500, "package_unit": "ml", "bundle_count": 2}],
              "products": [{"public_product_id": "merged-family", "canonical_name": "검토 대표명", "brand": "검토 브랜드", "attributes": {"identity_basis": "reviewed_product_group"}}]}
    report = render_review([row], [{}], bundle)
    for value in ("200", "500", "검토 대표명", "검토 브랜드", "merged-family", "reviewed_product_group", "pending_review"):
        assert value in report


def test_explicit_review_decisions_are_pinned_to_all_raw_evidence():
    rows = [{"source_name": "emart", "source_record_key": "one", "raw_record_id": "ingestion:1:0", "raw_payload_sha256": "raw-hash"}]
    document = {"schema_version": "walletsaver-initial-review-v1", "status": "reviewed_draft", "reviewed_by": "test-reviewer",
                "source_sha256": "snapshot-hash", "decisions": [{
                    "source_name": "emart", "source_record_key": "one", "unified_category_id": "food.milk",
                    "classification_confidence": 0.95, "reason": "Explicit type and exact pack verified",
                    "expected_observations": [{"raw_record_id": "ingestion:1:0", "raw_payload_sha256": "raw-hash"}],
                    "review_status": "approved", "offer_state": "active",  # cannot bypass approval/offer checks
                }]}
    result, context = merge_review_decisions(rows, {}, document, "snapshot-hash")
    assert result[("emart", "one")]["review_status"] == "classified"
    assert "offer_state" not in result[("emart", "one")]
    assert context["public_approval"] is False
    with pytest.raises(ValueError, match="snapshot changed"):
        merge_review_decisions(rows, {}, document, "different")
    stale = deepcopy(document)
    stale["decisions"][0]["expected_observations"][0]["raw_payload_sha256"] = "changed"
    with pytest.raises(ValueError, match="raw evidence changed"):
        merge_review_decisions(rows, {}, stale, "snapshot-hash")
    proposal = {**document, "status": "proposal_only"}
    with pytest.raises(ValueError, match="unreviewed proposal"):
        merge_review_decisions(rows, {}, proposal, "snapshot-hash")
