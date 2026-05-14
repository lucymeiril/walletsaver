from pathlib import Path

from crawlers.registry.registry import CrawlerRegistry
from crawlers.source_coverage import build_source_coverage
from pipeline.quality import summarize_discount_run


def test_source_coverage_reports_registered_and_missing_one_shot_sources():
    crawlers_dir = Path(__file__).resolve().parents[1] / "crawlers"
    registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
    discovered = registry.discover()

    coverage = build_source_coverage(discovered)
    rows = {row["source_id"]: row for row in coverage["sources"]}

    assert rows["emart"]["status"] == "registered"
    assert rows["homeplus"]["status"] == "registered"
    assert rows["lottemart"]["status"] == "registered"
    assert rows["algumon"]["status"] == "registered"
    assert rows["arca_hotdeal"]["status"] == "registered"
    assert rows["opinet"]["status"] == "registered"
    assert rows["musinsa"]["status"] == "registered"
    assert rows["giordano"]["status"] == "registered"
    assert rows["uniqlo"]["status"] == "registered"

    for marketplace in ["coupang", "naver_store", "gmarket", "11st", "aliexpress"]:
        assert rows[marketplace]["status"] == "registered"
        assert rows[marketplace]["group"] == "marketplace"
        assert rows[marketplace]["registered_name"] == marketplace
        assert rows[marketplace]["collection_status"] == "registered_unverified"
        assert rows[marketplace]["can_claim_collecting"] is False
        assert rows[marketplace]["can_claim_live_ready"] is False
        assert rows[marketplace]["registration_metadata"]["live_ready"] is False
        assert rows[marketplace]["registration_metadata"]["fixture_contract"] == "marketplace_skeleton_fixture_contracts.v1"
        assert rows[marketplace]["registration_metadata"]["live_readiness"]["status"] == "skeleton_fixture_only"
        assert rows[marketplace]["live_readiness_gate"]["required"] is True
        assert rows[marketplace]["live_readiness_gate"]["passed"] is False
        assert rows[marketplace]["live_readiness_gate"]["safe_db_mutation_allowed"] is False
        assert rows[marketplace]["live_readiness_gate"]["downstream_flow"]["next_stage"] == "saved_fixture_diagnostics"
        assert any(
            "no-DB AI review" in action
            for action in rows[marketplace]["live_readiness_gate"]["operator_next_actions"]
        )
        assert "bounded_live_diagnostics_missing" in rows[marketplace]["live_readiness_gate"]["reasons"]
        assert rows[marketplace]["quality_evidence"]["has_quality_evidence"] is False
        diagnostic_codes = [diag["code"] for diag in rows[marketplace]["operator_diagnostics"]]
        assert diagnostic_codes == [
            "marketplace_live_readiness_gate_blocked",
            "live_collection_disabled",
            "dry_run_quality_missing",
        ]
        assert rows[marketplace]["operator_diagnostics"][0]["safe_db_mutation_allowed"] is False
        assert "saved-fixture dry-run diagnostics" in rows[marketplace]["next_action"]
        assert "no-DB AI review" in rows[marketplace]["next_action"]
        assert "fixture-only/registered_unverified" in rows[marketplace]["collection_status_reason"]

    assert "marketplace" not in coverage["missing_by_group"]
    assert "registered_unverified means the plugin exists" in coverage["collection_claim_policy"]
    assert "Marketplace skeletons additionally require the fixture contract plus bounded diagnostics evidence" in coverage["collection_claim_policy"]
    assert {
        rows[source_id]["registered_name"]
        for source_id in ["coupang", "naver_store", "gmarket", "11st", "aliexpress"]
    } == {
        "coupang",
        "naver_store",
        "gmarket",
        "11st",
        "aliexpress",
    }
    assert rows["emart"]["collection_status"] == "registered_unverified"
    assert rows["emart"]["operator_diagnostics"][0]["code"] == "dry_run_quality_missing"
    assert rows["emart"]["can_claim_collecting"] is False


def test_delivery_coupang_eats_does_not_satisfy_coupang_marketplace():
    coverage = build_source_coverage(
        {
            "coupangeats": {
                "config": {"name": "coupangeats", "category": "delivery"},
                "path": "crawlers/delivery/coupangeats",
                "module_path": "crawlers.delivery.coupangeats.crawler",
            }
        }
    )
    rows = {row["source_id"]: row for row in coverage["sources"]}

    assert rows["coupang"]["status"] == "missing"
    assert rows["coupang"]["registered_name"] is None


def test_source_coverage_distinguishes_registered_from_collecting_with_mock_quality():
    quality_by_source = {
        "emart": summarize_discount_run(
            [{"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"}],
            raw_count=1,
            source_raw_count=1,
        ),
        "homeplus": summarize_discount_run([], raw_count=0, source_raw_count=2),
    }

    coverage = build_source_coverage(
        {
            "emart": {"path": "crawlers/marts/emart", "module_path": "crawlers.marts.emart.crawler"},
            "homeplus": {"path": "crawlers/marts/homeplus", "module_path": "crawlers.marts.homeplus.crawler"},
        },
        quality_by_source=quality_by_source,
    )
    rows = {row["source_id"]: row for row in coverage["sources"]}

    assert coverage["registered_count"] == 2
    assert coverage["collecting_count"] == 1
    assert coverage["registered_not_collecting_count"] == 1
    assert rows["emart"]["collection_status"] == "collecting"
    assert rows["emart"]["can_claim_collecting"] is True
    assert rows["emart"]["quality_evidence"]["has_quality_evidence"] is True
    assert rows["emart"]["quality_evidence"]["counts"]["valid"] == 1
    assert "currently collecting" in rows["emart"]["next_action"]
    assert rows["homeplus"]["collection_status"] == "failing"
    assert rows["homeplus"]["operator_diagnostics"][0]["code"] == "parse_filtered_all_raw_rows"
    assert "parser drift" in rows["homeplus"]["next_action"]
    assert rows["homeplus"]["quality_evidence"]["zero_result_stage"] == "parse_filtered_all_raw_rows"


def test_marketplace_live_ready_true_without_required_gate_evidence_is_blocked():
    quality_by_source = {
        "coupang": summarize_discount_run(
            [{"name": "fixture", "sale_price": 1000, "detail_url": "https://example.test/item"}],
            raw_count=1,
            source_raw_count=1,
            strategy_used="bounded-diagnostic",
            live_enabled=True,
            fixture_available=True,
        )
    }

    coverage = build_source_coverage(
        {
            "coupang": {
                "config": {
                    "name": "coupang",
                    "source_group": "marketplace",
                    "live_ready": True,
                    "parser_contract": "marketplace_skeleton.v1",
                },
                "path": "crawlers/shopping/coupang",
                "module_path": "crawlers.shopping.coupang.crawler",
            }
        },
        quality_by_source=quality_by_source,
    )
    row = {row["source_id"]: row for row in coverage["sources"]}["coupang"]

    assert row["live_ready"] is True
    assert row["collection_status"] == "registered_unverified"
    assert row["can_claim_live_ready"] is False
    assert row["can_claim_collecting"] is False
    assert row["live_readiness_gate"]["passed"] is False
    assert "fixture_contract_missing" in row["live_readiness_gate"]["reasons"]
    assert "bounded_live_diagnostics_missing" in row["live_readiness_gate"]["reasons"]
    assert row["operator_diagnostics"][0]["code"] == "marketplace_live_readiness_gate_blocked"


def test_marketplace_live_ready_true_with_fixture_contract_but_no_bounded_evidence_is_blocked():
    quality_by_source = {
        "coupang": summarize_discount_run(
            [{"name": "fixture", "sale_price": 1000, "detail_url": "https://example.test/item"}],
            raw_count=1,
            source_raw_count=1,
            strategy_used="saved-fixture",
            live_enabled=False,
            fixture_available=True,
        )
    }

    coverage = build_source_coverage(
        {
            "coupang": {
                "config": {
                    "name": "coupang",
                    "source_group": "marketplace",
                    "live_ready": True,
                    "parser_contract": "marketplace_skeleton.v1",
                    "fixture_contract": "marketplace_skeleton_fixture_contracts.v1",
                    "live_readiness": {
                        "status": "skeleton_fixture_only",
                        "fixture_contract_status": "passed",
                    },
                },
                "path": "crawlers/shopping/coupang",
                "module_path": "crawlers.shopping.coupang.crawler",
            }
        },
        quality_by_source=quality_by_source,
    )
    row = {row["source_id"]: row for row in coverage["sources"]}["coupang"]

    assert row["collection_status"] == "registered_unverified"
    assert row["can_claim_live_ready"] is False
    assert row["can_claim_collecting"] is False
    assert "bounded_live_diagnostics_missing" in row["live_readiness_gate"]["reasons"]
    assert "operator_approval_missing" in row["live_readiness_gate"]["reasons"]


def test_marketplace_can_claim_collecting_only_after_full_readiness_gate_passes():
    quality_by_source = {
        "coupang": summarize_discount_run(
            [{"name": "fixture", "sale_price": 1000, "detail_url": "https://example.test/item"}],
            raw_count=1,
            source_raw_count=1,
            strategy_used="bounded-diagnostic",
            live_enabled=True,
            fixture_available=True,
        )
    }

    coverage = build_source_coverage(
        {
            "coupang": {
                "config": {
                    "name": "coupang",
                    "source_group": "marketplace",
                    "live_ready": True,
                    "parser_contract": "marketplace_skeleton.v1",
                    "fixture_contract": "marketplace_skeleton_fixture_contracts.v1",
                    "live_readiness": {
                        "status": "live_ready",
                        "fixture_contract_status": "passed",
                        "bounded_diagnostics": {
                            "status": "passed",
                            "evidence_id": "diagnostic-run-123",
                            "captured_at": "2025-01-01T00:00:00Z",
                            "run_limits": {
                                "max_requests": 3,
                                "max_pages": 1,
                                "timeout_seconds": 15,
                            },
                        },
                        "operator_approval": {"status": "approved"},
                    },
                },
                "path": "crawlers/shopping/coupang",
                "module_path": "crawlers.shopping.coupang.crawler",
            }
        },
        quality_by_source=quality_by_source,
    )
    row = {row["source_id"]: row for row in coverage["sources"]}["coupang"]

    assert row["live_readiness_gate"]["passed"] is True
    assert row["live_readiness_gate"]["safe_db_mutation_allowed"] is False
    assert row["live_readiness_gate"]["downstream_flow"] == {
        "current_stage": "live_ready",
        "next_stage": "no_db_ai_review",
        "db_mutation_allowed": False,
    }
    assert row["can_claim_live_ready"] is True
    assert row["collection_status"] == "collecting"
    assert row["can_claim_collecting"] is True
