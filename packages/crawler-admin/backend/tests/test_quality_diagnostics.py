from pathlib import Path

from crawlers.registry.registry import CrawlerRegistry
from pipeline.quality import summarize_discount_run
from pipeline.diagnostics import build_bounded_live_diagnostics_plan, run_bounded_crawler_diagnostics


NON_MARKETPLACE_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "non_marketplace_crawlers"
MARKETPLACE_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "marketplace_skeleton"


def _run(coro):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


class _DiagnosticsCrawler:
    def __init__(self, mode: str, source_raw_count: int | None = None):
        self.mode = mode
        self.source_raw_count = source_raw_count

    def count_raw_candidates(self, raw_data: str) -> int:
        if self.source_raw_count is not None:
            return self.source_raw_count
        return len(_items_for_mode(self.mode))

    async def parse(self, raw_data: str):
        if self.mode == "drift":
            return []
        return _items_for_mode(self.mode)

    async def validate(self, items):
        if self.mode == "drop":
            return []
        return items


class _DiagnosticsRegistry:
    def __init__(self):
        self._registry = {
            "ok": {"config": {"name": "ok", "live_ready": True}, "module_path": "tests.ok"},
            "skeleton": {
                "config": {"name": "skeleton", "live_ready": False, "parser_contract": "skeleton.v1"},
                "module_path": "tests.skeleton",
            },
            "drift": {"config": {"name": "drift", "live_ready": True}, "module_path": "tests.drift"},
            "drop": {"config": {"name": "drop", "live_ready": True}, "module_path": "tests.drop"},
            "dupe": {"config": {"name": "dupe", "live_ready": True}, "module_path": "tests.dupe"},
        }
        self._crawlers = {
            "ok": _DiagnosticsCrawler("ok"),
            "drift": _DiagnosticsCrawler("drift", source_raw_count=2),
            "drop": _DiagnosticsCrawler("drop", source_raw_count=2),
            "dupe": _DiagnosticsCrawler("dupe", source_raw_count=3),
        }

    def get_crawler(self, name: str):
        return self._crawlers[name]


def _items_for_mode(mode: str):
    if mode == "ok":
        return [
            {"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"name": "두부", "sale_price": 1980, "detail_url": "https://example.test/b"},
        ]
    if mode == "drop":
        return [{"name": "가격 없음"}, {"name": "가격 없음 2"}]
    if mode == "dupe":
        return [
            {"store": "fixture", "name": "라면", "sale_price": 4980, "detail_url": "https://example.test/a"},
            {"store": "fixture", "name": "라면", "sale_price": 4980, "detail_url": "https://example.test/a"},
            {"store": "fixture", "name": "만두", "sale_price": 7980},
        ]
    return []


def test_zero_source_rows_include_operator_next_action():
    summary = summarize_discount_run([], raw_count=0, source_raw_count=0)

    diagnostic = summary["zero_result_diagnostic"]
    assert diagnostic["stage"] == "source_zero_raw_rows"
    assert diagnostic["dry_run_safe"] is True
    assert "source_zero_raw_rows" == summary["operator_diagnostics"][0]["code"]
    assert "found zero source candidate rows" in diagnostic["next_action"]
    assert summary["quality_summary"]["status"] == "failing"
    assert summary["quality_summary"]["zero_result_stage"] == "source_zero_raw_rows"


def test_live_disabled_without_fixture_is_not_reported_as_empty_source():
    summary = summarize_discount_run(
        [],
        raw_count=0,
        source_raw_count=0,
        live_enabled=False,
        fixture_available=False,
        errors=["marketplace skeleton has no configured safe fixture/input; live crawling is intentionally disabled."],
    )

    diagnostic = summary["zero_result_diagnostic"]
    assert diagnostic["stage"] == "live_disabled_no_fixture"
    assert diagnostic["live_enabled"] is False
    assert diagnostic["fixture_available"] is False
    assert "registration cannot be treated as collection evidence" in diagnostic["message"]
    assert "Attach a recent approved fixture or raw_data sample" in diagnostic["next_action"]
    assert summary["operator_diagnostics"][0]["code"] == "live_disabled_no_fixture"
    assert "live_collection_disabled" in summary["alerts"]
    assert "fixture_or_raw_missing" in summary["alerts"]


def test_missing_fixture_or_raw_input_has_specific_next_action():
    summary = summarize_discount_run([], raw_count=0, source_raw_count=0, fixture_available=False)

    diagnostic = summary["zero_result_diagnostic"]
    assert diagnostic["stage"] == "fixture_or_raw_missing"
    assert "did not receive saved fixture/raw input" in diagnostic["message"]
    assert "Provide a saved fixture or raw_data sample" in diagnostic["next_action"]
    assert "without input there is no evidence" in diagnostic["next_action"]


def test_parser_drift_and_validation_zero_results_are_actionable():
    parser_drift = summarize_discount_run([], raw_count=0, source_raw_count=3)
    validation_drop = summarize_discount_run([], raw_count=3, source_raw_count=3, invalid_count=3)

    assert parser_drift["zero_result_diagnostic"]["stage"] == "parse_filtered_all_raw_rows"
    assert "parser drift regression fixture" in parser_drift["zero_result_diagnostic"]["next_action"]
    assert validation_drop["zero_result_diagnostic"]["stage"] == "validation_rejected_all_rows"
    assert "validation/normalization rules" in validation_drop["zero_result_diagnostic"]["next_action"]


def test_low_critical_field_coverage_blocks_collecting_status():
    summary = summarize_discount_run(
        [
            {"name": "양파 1kg", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"name": "두부 300g", "sale_price": 1980},
        ],
        raw_count=2,
        source_raw_count=2,
    )

    assert summary["quality_summary"]["status"] == "warning"
    assert "low_critical_field_coverage" == summary["operator_diagnostics"][0]["code"]
    assert summary["quality_summary"]["low_critical_fields"][0]["field"] == "detail_url"
    assert "Fix parser field mapping" in summary["next_actions"][0]


def test_quality_summary_collecting_when_critical_fields_are_covered():
    summary = summarize_discount_run(
        [
            {"name": "양파 1kg", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"name": "두부 300g", "sale_price": 1980, "detail_url": "https://example.test/b"},
        ],
        raw_count=2,
        source_raw_count=2,
    )

    assert summary["quality_summary"]["status"] == "collecting"
    assert summary["operator_diagnostics"] == []
    assert summary["quality_summary"]["critical_field_coverage"] == {
        "name": 1.0,
        "sale_price": 1.0,
        "detail_url": 1.0,
    }


def test_lottemart_like_bounded_artifact_shape_reports_image_and_unit_coverage():
    summary = summarize_discount_run(
        [
            {
                "name": "[농할할인가 6,990원] 행복생생란 (특란, 30입) (1.8KG)",
                "sale_price": 6990,
                "detail_url": "https://lottemartzetta.com/products/a",
                "image_url": "https://lottemartzetta.com/images-v3/a/300x300.jpg",
                "display_unit": "1.8kg",
                "package_quantity": 1.8,
                "package_unit": "kg",
            },
            {
                "name": "오늘좋은 미네랄워터 (2L*6입)",
                "current_price": 2000,
                "detail_url": "https://lottemartzetta.com/products/b",
                "image_url": "https://lottemartzetta.com/images-v3/b/300x300.jpg",
                "package_unit": "입",
            },
        ],
        raw_count=2,
        source_raw_count=2,
    )

    assert summary["quality_summary"]["status"] == "collecting"
    assert summary["operator_diagnostics"] == []
    assert summary["quality_summary"]["critical_field_coverage"] == {
        "name": 1.0,
        "sale_price": 1.0,
        "detail_url": 1.0,
    }
    assert summary["coverage"]["image_url"] == 1.0
    assert summary["coverage"]["unit"] == 1.0


def test_duplicate_heavy_output_has_operator_diagnostic_and_next_action():
    summary = summarize_discount_run(
        [
            {"store": "emart", "name": "양파 1kg", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"store": "emart", "name": "양파 1kg", "sale_price": 3980, "detail_url": "https://example.test/a"},
            {"store": "emart", "name": "두부 300g", "sale_price": 1980, "detail_url": "https://example.test/b"},
        ],
        raw_count=3,
        source_raw_count=3,
    )

    duplicate_diag = next(diag for diag in summary["operator_diagnostics"] if diag["code"] == "duplicate_heavy_output")
    assert summary["quality_summary"]["status"] == "warning"
    assert duplicate_diag["duplicate_count"] == 1
    assert duplicate_diag["duplicate_ratio"] == 0.333
    assert "fix parser pagination/card selectors or dedupe keys" in duplicate_diag["next_action"]


def test_bounded_diagnostics_runner_reports_fixture_success_and_negative_states():
    registry = _DiagnosticsRegistry()

    result = _run(
        run_bounded_crawler_diagnostics(
            registry,
            fixture_by_source={
                "ok": "<fixture>ok</fixture>",
                "drift": "<fixture>drift</fixture>",
                "drop": "<fixture>drop</fixture>",
                "dupe": "<fixture>dupe</fixture>",
            },
            crawler_ids=["ok", "skeleton", "drift", "drop", "dupe"],
        )
    )
    rows = {row["crawler_id"]: row for row in result["crawlers"]}

    assert result["schema"] == "bounded_crawler_diagnostics.v1"
    assert result["live_network_default"] == "disabled"
    assert rows["ok"]["quality_evidence"]["counts"] == {
        "source_raw": 2,
        "parsed": 2,
        "valid": 2,
        "invalid_or_dropped": 0,
        "duplicates_after_validation": 0,
    }
    assert rows["ok"]["quality_evidence"]["collection_status"] == "collecting"
    assert rows["ok"]["source_drift_readiness"]["status"] == "ready"

    assert rows["skeleton"]["fixture"]["available"] is False
    assert rows["skeleton"]["fixture"]["mode"] == "live_disabled_no_fixture"
    assert rows["skeleton"]["quality_evidence"]["has_quality_evidence"] is False
    assert rows["skeleton"]["quality_evidence"]["can_claim_collecting"] is False
    assert rows["skeleton"]["operator_diagnostics"][0]["code"] == "live_disabled_no_fixture"
    assert rows["skeleton"]["source_drift_readiness"]["status"] == "not_ready"

    assert rows["drift"]["quality_evidence"]["counts"]["source_raw"] == 2
    assert rows["drift"]["quality_evidence"]["counts"]["parsed"] == 0
    assert rows["drift"]["operator_diagnostics"][0]["code"] == "parse_filtered_all_raw_rows"
    assert rows["drift"]["source_drift_readiness"]["status"] == "drift_detected"

    assert rows["drop"]["quality_evidence"]["counts"]["invalid_or_dropped"] == 2
    assert rows["drop"]["operator_diagnostics"][0]["code"] == "validation_rejected_all_rows"
    assert rows["drop"]["source_drift_readiness"]["status"] == "validation_blocked"

    dupe_codes = rows["dupe"]["quality_evidence"]["diagnostic_codes"]
    assert "duplicate_heavy_output" in dupe_codes
    assert "low_critical_field_coverage" in dupe_codes
    assert rows["dupe"]["quality_evidence"]["counts"]["duplicates_after_validation"] == 1
    assert rows["dupe"]["quality_evidence"]["critical_field_coverage"]["detail_url"] == 0.667
    assert rows["dupe"]["quality_evidence"]["can_claim_collecting"] is False


def test_bounded_diagnostics_does_not_feed_missing_fixture_as_collecting_evidence():
    registry = _DiagnosticsRegistry()

    result = _run(run_bounded_crawler_diagnostics(registry, crawler_ids=["skeleton"]))
    row = result["crawlers"][0]

    assert result["quality_evidence_count"] == 0
    assert result["collecting_count"] == 0
    assert row["quality_evidence"]["has_quality_evidence"] is False
    assert row["quality_evidence"]["can_claim_collecting"] is False
    assert result["source_coverage"]["collecting_count"] == 0


def test_bounded_diagnostics_attaches_source_health_count_drop_evidence():
    crawlers_dir = Path(__file__).resolve().parents[1] / "crawlers"
    registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
    registry.discover()
    fixture = (NON_MARKETPLACE_FIXTURE_DIR / "emart.html").read_text(encoding="utf-8")

    result = _run(
        run_bounded_crawler_diagnostics(
            registry,
            fixture_by_source={"emart": fixture},
            crawler_ids=["emart"],
            health_baseline_by_source={
                "emart": {
                    "expected_counts": {"source_raw": 10, "parsed": 10, "valid": 10},
                    "count_drop_threshold": 0.75,
                    "baseline_source": "fixture_contract:emart:previous_good",
                }
            },
        )
    )
    report = result["crawlers"][0]
    coverage = {row["source_id"]: row for row in result["source_coverage"]["sources"]}["emart"]
    health = report["source_health_evidence"]

    assert health["counts"]["source_raw"] == report["quality_evidence"]["counts"]["source_raw"]
    assert health["counts"]["parsed"] == report["quality_evidence"]["counts"]["parsed"]
    assert health["counts"]["valid"] == report["quality_evidence"]["counts"]["valid"]
    assert health["baseline"]["baseline_source"] == "fixture_contract:emart:previous_good"
    assert health["count_drop"]["status"] == "drop_detected"
    assert {alert["metric"] for alert in health["count_drop"]["alerts"]} == {"source_raw", "parsed", "valid"}
    assert health["next_action_state"]["state"] == "investigate_count_drop"
    assert coverage["source_health"]["status"] == "failing"
    assert coverage["source_health"]["next_action_state"]["state"] == "investigate_count_drop"


def test_bounded_live_diagnostics_plan_is_artifact_only_and_keeps_unverified_non_collecting():
    registry = _DiagnosticsRegistry()

    result = build_bounded_live_diagnostics_plan(
        registry,
        fixture_snapshots={"ok": {"path": "fixtures\\ok.html", "status": "available"}},
        run_limits={"max_requests": 2, "max_pages": 1, "timeout_seconds": 10},
    )
    rows = {row["source_id"]: row for row in result["sources"]}

    assert result["schema"] == "bounded_live_diagnostics_plan.v1"
    assert result["live_network_default"] == "disabled"
    assert rows["emart"]["allowed_live"] is False
    assert rows["emart"]["collection_status"] == "missing"
    assert rows["coupang"]["allowed_live"] is False
    assert rows["coupang"]["current_collection_status"] == "missing"

    # A registered source with a plan remains registered_unverified without collecting quality evidence.
    plan = build_bounded_live_diagnostics_plan(
        {
            "emart": {
                "config": {"name": "emart", "source_id": "emart", "live_ready": True},
                "path": "crawlers\\marts\\emart",
                "module_path": "crawlers.marts.emart.crawler",
            }
        },
        fixture_snapshots={"emart": "fixtures\\emart.html"},
    )
    emart = {row["source_id"]: row for row in plan["sources"]}["emart"]

    assert emart["fixture_snapshot_status"] == "available"
    assert emart["current_collection_status"] == "registered_unverified"
    assert emart["allowed_live"] is False
    assert "current_collection_status:registered_unverified" in emart["blockers"]
    assert plan["source_coverage"]["collecting_count"] == 0


def test_high_priority_non_marketplace_fixtures_produce_bounded_quality_evidence():
    crawlers_dir = Path(__file__).resolve().parents[1] / "crawlers"
    registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
    registry.discover()
    fixture_by_source = {
        source_id: (NON_MARKETPLACE_FIXTURE_DIR / f"{source_id}.html").read_text(encoding="utf-8")
        for source_id in ("emart", "homeplus", "algumon")
    }

    result = _run(
        run_bounded_crawler_diagnostics(
            registry,
            fixture_by_source=fixture_by_source,
            crawler_ids=["emart", "homeplus", "algumon"],
        )
    )
    rows = {row["crawler_id"]: row for row in result["crawlers"]}

    assert result["live_network_default"] == "disabled"
    assert result["live_enabled"] is False
    assert result["quality_evidence_count"] == 3
    for source_id in ("emart", "algumon"):
        row = rows[source_id]
        counts = row["quality_evidence"]["counts"]
        coverage = row["quality_evidence"]["critical_field_coverage"]
        health = row["source_health_evidence"]

        assert row["fixture"] == {
            "available": True,
            "live_enabled": False,
            "mode": "saved_fixture",
        }
        assert row["quality_evidence"]["collection_status"] == "collecting"
        assert row["quality_evidence"]["has_quality_evidence"] is True
        assert counts["source_raw"] > 0
        assert counts["parsed"] > 0
        assert counts["valid"] > 0
        assert coverage["name"] == 1.0
        assert coverage["sale_price"] == 1.0
        assert coverage["detail_url"] == 1.0
        assert row["operator_diagnostics"] == []
        assert row["source_drift_readiness"]["ready"] is True
        assert row["fixture"]["live_enabled"] is False
        assert health["counts"]["source_raw"] == counts["source_raw"]
        assert health["counts"]["parsed"] == counts["parsed"]
        assert health["counts"]["valid"] == counts["valid"]
        assert health["expected_counts"] == {"source_raw": 1, "parsed": 1, "valid": 1}
        assert health["critical_field_coverage"] == coverage
        assert health["field_coverage_dashboard"]["status"] == "ok"
        assert health["count_drop"]["status"] == "within_baseline"
        assert health["next_action_state"]["state"] == "monitor"
        assert health["live_network_default"] == "disabled"

    homeplus = rows["homeplus"]
    homeplus_counts = homeplus["quality_evidence"]["counts"]
    homeplus_coverage = homeplus["quality_evidence"]["critical_field_coverage"]
    homeplus_health = homeplus["source_health_evidence"]

    assert homeplus["fixture"] == {
        "available": True,
        "live_enabled": False,
        "mode": "saved_fixture",
    }
    assert homeplus["quality_evidence"]["has_quality_evidence"] is True
    assert homeplus["quality_evidence"]["collection_status"] == "registered_unverified"
    assert homeplus["quality_evidence"]["can_claim_collecting"] is False
    assert homeplus_counts["source_raw"] > 0
    assert homeplus_counts["parsed"] > 0
    assert homeplus_counts["valid"] > 0
    assert homeplus_coverage["name"] == 1.0
    assert homeplus_coverage["sale_price"] == 1.0
    assert homeplus_coverage["detail_url"] == 1.0
    assert homeplus["source_drift_readiness"]["ready"] is True
    assert homeplus["operator_diagnostics"][0]["code"] == "live_ready_false_registered_unverified"
    assert "bounded no-DB live diagnostic" in homeplus["operator_diagnostics"][0]["next_action"]
    assert homeplus_health["counts"]["source_raw"] == homeplus_counts["source_raw"]
    assert homeplus_health["critical_field_coverage"] == homeplus_coverage
    assert homeplus_health["count_drop"]["status"] == "within_baseline"
    assert homeplus_health["next_action_state"]["state"] == "await_bounded_live_diagnostics_approval"

    plan = build_bounded_live_diagnostics_plan(
        registry,
        quality_by_source={"homeplus": homeplus["quality_details"]},
        fixture_snapshots={
            "homeplus": "tests\\fixtures\\non_marketplace_crawlers\\homeplus.html",
        },
    )
    homeplus_plan = {row["source_id"]: row for row in plan["sources"]}["homeplus"]

    assert homeplus_plan["fixture_snapshot_status"] == "available"
    assert homeplus_plan["allowed_live"] is False
    assert homeplus_plan["approval_needed"] is True
    assert homeplus_plan["max_requests"] == 1
    assert homeplus_plan["max_pages"] == 1
    assert homeplus_plan["timeout_seconds"] == 20
    assert "current_collection_status:registered_unverified" in homeplus_plan["blockers"]


def test_marketplace_skeleton_fixtures_are_diagnostics_ready_but_not_db_mutation_ready():
    crawlers_dir = Path(__file__).resolve().parents[1] / "crawlers"
    registry = CrawlerRegistry(crawlers_dir=crawlers_dir)
    registry.discover()
    marketplace_sources = ["coupang", "naver_store", "gmarket", "11st", "aliexpress"]
    fixture_by_source = {
        source_id: (MARKETPLACE_FIXTURE_DIR / f"{source_id}.html").read_text(encoding="utf-8")
        for source_id in marketplace_sources
    }

    result = _run(
        run_bounded_crawler_diagnostics(
            registry,
            fixture_by_source=fixture_by_source,
            crawler_ids=marketplace_sources,
        )
    )
    reports = {row["crawler_id"]: row for row in result["crawlers"]}
    coverage_rows = {row["source_id"]: row for row in result["source_coverage"]["sources"]}

    assert result["live_network_default"] == "disabled"
    assert result["live_enabled"] is False
    assert result["quality_evidence_count"] == len(marketplace_sources)
    assert result["collecting_count"] == 0
    assert result["source_coverage"]["collecting_count"] == 0

    for source_id in marketplace_sources:
        report = reports[source_id]
        coverage = coverage_rows[source_id]

        assert report["fixture"]["mode"] == "saved_fixture"
        assert report["quality_evidence"]["has_quality_evidence"] is True
        assert report["quality_evidence"]["collection_status"] == "registered_unverified"
        assert report["quality_evidence"]["can_claim_collecting"] is False
        assert report["source_drift_readiness"]["status"] == "ready"
        assert report["quality_evidence"]["counts"]["source_raw"] > 0
        assert report["quality_evidence"]["counts"]["parsed"] > 0
        assert report["quality_evidence"]["counts"]["valid"] > 0
        assert report["operator_diagnostics"][0]["code"] == "live_ready_false_registered_unverified"
        assert "bounded no-DB live diagnostic" in report["operator_diagnostics"][0]["next_action"]
        assert report["source_health_evidence"]["counts"]["source_raw"] == report["quality_evidence"]["counts"]["source_raw"]
        assert report["source_health_evidence"]["counts"]["parsed"] == report["quality_evidence"]["counts"]["parsed"]
        assert report["source_health_evidence"]["counts"]["valid"] == report["quality_evidence"]["counts"]["valid"]
        assert report["source_health_evidence"]["critical_field_coverage"] == report["quality_evidence"]["critical_field_coverage"]
        assert report["source_health_evidence"]["field_coverage_dashboard"]["status"] == "ok"
        assert report["source_health_evidence"]["count_drop"]["status"] == "within_baseline"
        assert report["source_health_evidence"]["next_action_state"]["state"] == "await_bounded_live_diagnostics_approval"
        assert report["source_health_evidence"]["live_network_default"] == "disabled"

        assert coverage["collection_status"] == "registered_unverified"
        assert coverage["can_claim_collecting"] is False
        assert coverage["live_readiness_gate"]["passed"] is False
        assert coverage["live_readiness_gate"]["safe_db_mutation_allowed"] is False
        assert coverage["live_readiness_gate"]["downstream_flow"]["next_stage"] == "saved_fixture_diagnostics"
        assert coverage["source_health"]["count_drop"]["status"] == "within_baseline"
        assert coverage["source_health"]["next_action_state"]["state"] == "await_bounded_live_diagnostics_approval"
        assert "marketplace_live_readiness_gate_blocked" in [
            diag["code"] for diag in coverage["operator_diagnostics"]
        ]
