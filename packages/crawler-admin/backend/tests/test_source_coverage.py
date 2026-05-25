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
    assert rows["ppomppu"]["status"] == "registered"
    assert rows["fmkorea"]["status"] == "registered"
    assert rows["clien"]["status"] == "registered"
    assert rows["quasarzone"]["status"] == "registered"
    assert rows["cocodal"]["status"] == "registered"
    assert rows["opinet"]["status"] == "registered"
    for community in ["algumon", "arca_hotdeal", "ppomppu", "fmkorea", "clien", "quasarzone"]:
        assert rows[community]["readiness_status"] == "registered-unverified"
    assert rows["cocodal"]["readiness_status"] == "blocked-by-key/service"
    assert rows["opinet"]["readiness_status"] == "blocked-by-key/service"
    assert rows["musinsa"]["status"] == "registered"
    assert rows["giordano"]["status"] == "registered"
    assert rows["uniqlo"]["status"] == "registered"
    assert rows["baemin"]["status"] == "registered"
    assert rows["coupangeats"]["status"] == "registered"
    assert rows["yogiyo"]["status"] == "registered"
    assert rows["naver_place"]["status"] == "registered"

    for marketplace in ["coupang", "naver_store", "gmarket", "11st", "aliexpress"]:
        assert rows[marketplace]["status"] == "registered"
        assert rows[marketplace]["group"] == "marketplace"
        assert rows[marketplace]["registered_name"] == marketplace
        assert rows[marketplace]["readiness_status"] == "skeleton-only"
        assert rows[marketplace]["gap_classification"] == "skeleton_only"
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
        assert rows[marketplace]["source_readiness"]["stage"] == "skeleton_only"
        assert rows[marketplace]["source_completion_gate"]["stage"] == "skeleton_only"
        assert rows[marketplace]["source_completion_gate"]["passed"] is False
        assert rows[marketplace]["source_completion_gate"]["blocks_completion_claim"] is True
        assert rows[marketplace]["source_completion_gate"]["required_evidence"] == [
            "fixture_contract_passed",
            "bounded_live_diagnostics_passed",
            "bounded_run_limits_recorded",
            "operator_approval_recorded",
        ]
        assert "bounded_live_diagnostics_missing" in rows[marketplace]["source_completion_gate"]["missing_evidence"]
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
    assert coverage["gap_classification_counts"]["skeleton_only"] == 5
    assert coverage["gap_classification_counts"]["blocked_by_external_key/service"] >= 5
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
    assert rows["emart"]["gap_classification"] == "registered_unverified"
    assert rows["emart"]["source_readiness"]["stage"] == "registered_unverified"
    assert rows["emart"]["source_completion_gate"]["classification"] == "registered_unverified"
    assert rows["emart"]["source_completion_gate"]["blocks_completion_claim"] is True
    assert "quality_evidence_missing" in rows["emart"]["source_completion_gate"]["missing_evidence"]
    assert rows["emart"]["live_readiness_gate"]["required"] is True
    assert rows["emart"]["can_claim_live_ready"] is False
    assert rows["emart"]["operator_diagnostics"][0]["code"] == "mart3_live_readiness_gate_blocked"
    assert "dry_run_quality_missing" in [diag["code"] for diag in rows["emart"]["operator_diagnostics"]]
    assert "live_collection_disabled" in [diag["code"] for diag in rows["emart"]["operator_diagnostics"]]
    assert rows["emart"]["mart3_source_collection_readiness"]["status"] == "source_collection_blocked"
    assert "source_collection_diagnostics_missing" in rows["emart"]["mart3_source_collection_readiness"]["blockers"]
    assert rows["emart"]["source_map_manifest"]["schema"] == "mart3_source_map_manifest.v1"
    assert rows["emart"]["source_map_manifest"]["breadth_plan"]["planned_request_count"] == 39
    assert "eggs" in rows["emart"]["source_map_manifest"]["breadth_plan"]["missing_product_classes"]
    assert rows["homeplus"]["source_map_manifest"]["collection_surfaces"]["bounded_limits"]["max_items"] == 300
    # lottemart 는 plugin.yaml live_readiness.status=ready 로 전환됨 — WAF 202 회복 완료.
    # 더 이상 live_blocker 가 부착되면 안 된다 (사용자 헌법: 안전 타령 금지, 1급 워크밴치 인정).
    assert rows["lottemart"]["source_map_manifest"].get("live_blocker") in (None, {})
    audit = coverage["mart3_source_collection_audit"]
    assert audit["schema"] == "mart3_source_collection_audit.v1"
    assert audit["can_realistically_cover_live_service_product_data"] is False
    assert audit["counts_by_source"]["emart"]["counts_recorded"] is False
    # lottemart 는 더 이상 blocked_sources 에 포함되지 않는다.
    blocked_source_ids = {b["source_id"] for b in audit["blocked_sources"]}
    assert "lottemart" not in blocked_source_ids, (
        f"lottemart 가 여전히 blocked_sources 에 있음: {blocked_source_ids}"
    )
    assert "WAF/access-control/CAPTCHA bypass is not allowed" in audit["safe_collection_policy"]
    assert rows["emart"]["can_claim_collecting"] is False
    assert rows["opinet"]["gap_classification"] == "blocked_by_external_key/service"
    assert rows["opinet"]["source_readiness"]["stage"] == "blocked_by_external_key/service"
    assert rows["opinet"]["source_completion_gate"]["classification"] == "blocked_by_external_key/service"
    assert rows["opinet"]["source_completion_gate"]["blocks_completion_claim"] is True
    assert "external_key_service_or_location_prerequisite_missing" in rows["opinet"]["source_completion_gate"]["missing_evidence"]
    for service_source in ["baemin", "coupangeats", "yogiyo", "naver_place"]:
        assert rows[service_source]["gap_classification"] == "blocked_by_external_key/service"


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
    assert coverage["collecting_count"] == 0
    assert coverage["registered_not_collecting_count"] == 2
    assert rows["emart"]["collection_status"] == "registered_unverified"
    assert rows["emart"]["can_claim_collecting"] is False
    assert rows["emart"]["quality_evidence"]["has_quality_evidence"] is True
    assert rows["emart"]["quality_evidence"]["counts"]["valid"] == 1
    assert rows["emart"]["mart3_source_collection_readiness"]["status"] == "fixture_diagnostics_ready"
    assert "live_ready=true" in rows["emart"]["next_action"]
    assert rows["homeplus"]["collection_status"] == "failing"
    assert "parse_filtered_all_raw_rows" in [diag["code"] for diag in rows["homeplus"]["operator_diagnostics"]]
    assert "parser drift" in rows["homeplus"]["next_action"]
    assert rows["homeplus"]["quality_evidence"]["zero_result_stage"] == "parse_filtered_all_raw_rows"


def test_mart3_readiness_separates_fixture_diagnostics_from_live_service_ready():
    quality = summarize_discount_run(
        [{"name": "양파 1kg", "sale_price": 3980, "detail_url": "https://emart.example/a"}],
        raw_count=1,
        source_raw_count=1,
        strategy_used="bounded-fixture",
        live_enabled=False,
        fixture_available=True,
    )
    coverage = build_source_coverage(
        {
            "emart": {
                "config": {
                    "name": "emart",
                    "category": "mart",
                    "live_ready": False,
                    "live_readiness": {
                        "bounded_diagnostics": {
                            "status": "required_before_live_ready",
                            "run_limits": {"max_requests": 3, "max_pages": 1, "timeout_seconds": 20},
                        }
                    },
                },
                "path": "crawlers/marts/emart",
                "module_path": "crawlers.marts.emart.crawler",
            }
        },
        quality_by_source={"emart": quality},
    )

    readiness = {row["source_id"]: row for row in coverage["sources"]}["emart"]["mart3_source_collection_readiness"]
    assert readiness["schema"] == "mart3_source_collection_readiness.v1"
    assert readiness["status"] == "fixture_diagnostics_ready"
    assert readiness["fixture_diagnostics_passed"] is True
    assert readiness["bounded_diagnostic_ready"] is False
    assert readiness["live_ready"] is False
    assert readiness["live_service_ready"] is False
    assert readiness["required_evidence_fields"] == [
        "name",
        "sale_price",
        "detail_url",
        "source_url",
        "image_url",
        "period",
        "unit",
        "category_hint",
    ]
    assert readiness["field_coverage"]["source_url"] == 1.0
    assert readiness["field_coverage"]["period"] == 0
    assert "live_ready_not_approved" in readiness["blockers"]
    assert "bounded_live_diagnostics_missing" in readiness["blockers"]
    assert "bounded_evidence_id_missing" in readiness["blockers"]
    assert "operator_approval_missing" in readiness["blockers"]
    assert "fixture passing does not equal live-service readiness" in readiness["claim_policy"]


def test_mart3_readiness_distinguishes_bounded_diagnostic_ready_from_live_ready():
    quality = summarize_discount_run(
        [{
            "name": "양파 1kg",
            "sale_price": 3980,
            "detail_url": "https://emart.example/a",
            "image_url": "https://emart.example/a.jpg",
            "unit": "1kg",
            "category": "채소",
        }],
        raw_count=1,
        source_raw_count=1,
        strategy_used="bounded-diagnostic",
        live_enabled=False,
        fixture_available=True,
    )
    base_plugin = {
        "config": {
            "name": "emart",
            "category": "mart",
            "live_ready": False,
            "live_readiness": {
                "fixture_contract_status": "passed",
                "bounded_diagnostics": {
                    "status": "passed",
                    "evidence_id": "bounded:emart:2025-01-01",
                    "captured_at": "2025-01-01T00:00:00Z",
                    "run_limits": {"max_requests": 3, "max_pages": 1, "timeout_seconds": 20},
                },
            },
        },
        "path": "crawlers/marts/emart",
        "module_path": "crawlers.marts.emart.crawler",
    }

    bounded = build_source_coverage({"emart": base_plugin}, quality_by_source={"emart": quality})
    bounded_row = {row["source_id"]: row for row in bounded["sources"]}["emart"]
    bounded_readiness = bounded_row["mart3_source_collection_readiness"]

    assert bounded_row["can_claim_live_ready"] is False
    assert bounded_readiness["status"] == "bounded_diagnostic_ready"
    assert bounded_readiness["bounded_diagnostic_ready"] is True
    assert bounded_readiness["live_ready"] is False
    assert "live_ready_not_approved" in bounded_readiness["blockers"]
    assert "operator_approval_missing" in bounded_readiness["blockers"]

    live_plugin = {
        **base_plugin,
        "config": {
            **base_plugin["config"],
            "live_ready": True,
            "live_readiness": {
                **base_plugin["config"]["live_readiness"],
                "operator_approval": {"status": "approved"},
            },
        },
    }
    live = build_source_coverage({"emart": live_plugin}, quality_by_source={"emart": quality})
    live_row = {row["source_id"]: row for row in live["sources"]}["emart"]
    live_readiness = live_row["mart3_source_collection_readiness"]

    assert live_row["live_readiness_gate"]["passed"] is True
    assert live_row["can_claim_live_ready"] is True
    assert live_readiness["status"] == "live_ready"
    assert live_readiness["live_ready"] is True
    assert live_readiness["blockers"] == []


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
    assert row["source_completion_gate"]["passed"] is False
    assert "no_db_ai_review_missing" in row["source_completion_gate"]["missing_evidence"]


def test_source_completion_requires_no_db_ai_review_after_live_readiness_gate():
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
                        "no_db_ai_review": {
                            "status": "completed",
                            "artifact_id": "no-db-ai-review-123",
                        },
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
    assert row["source_completion_gate"]["passed"] is True
    assert row["source_completion_gate"]["can_claim_source_complete"] is True
