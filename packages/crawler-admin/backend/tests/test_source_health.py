from crawlers.source_coverage import build_source_coverage
from pipeline.quality import summarize_discount_run


def test_mart_source_health_includes_calendar_baseline_and_field_dashboard():
    coverage = build_source_coverage(
        {
            "emart": {
                "config": {
                    "name": "emart",
                    "category": "mart",
                    "schedule": {"cron": "0 7 * * *", "retry_count": 3, "retry_delay": 300},
                    "output": {"required_fields": ["name", "sale_price"]},
                },
                "path": "crawlers\\marts\\emart",
                "module_path": "crawlers.marts.emart.crawler",
            }
        },
        quality_by_source={
            "emart": summarize_discount_run(
                [
                    {"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"},
                    {"name": "두부", "sale_price": 1980, "detail_url": "https://example.test/b"},
                ],
                raw_count=2,
                source_raw_count=2,
            )
        },
    )
    emart = {row["source_id"]: row for row in coverage["sources"]}["emart"]
    health = emart["source_health"]

    assert health["schema"] == "crawler_source_health.v1"
    assert health["status"] == "collecting"
    assert health["calendar"]["expected_event_cadence"] == "daily_price_event"
    assert health["calendar"]["expression"] == "0 7 * * *"
    assert health["calendar"]["freshness_sla_hours"] == 36
    assert health["completeness"]["status"] == "meets_baseline"
    assert health["completeness_baseline"]["expected_counts"] == {"source_raw": 1, "parsed": 1, "valid": 1}
    assert health["field_coverage_dashboard"]["status"] == "ok"
    assert health["next_action_state"]["state"] == "monitor"
    assert coverage["source_health_dashboard"]["status_counts"]["collecting"] == 1


def test_marketplace_registered_unverified_health_keeps_live_disabled():
    coverage = build_source_coverage(
        {
            "coupang": {
                "config": {
                    "name": "coupang",
                    "source_group": "marketplace",
                    "live_ready": False,
                    "parser_contract": "marketplace_skeleton.v1",
                    "fixture_contract": "marketplace_skeleton_fixture_contracts.v1",
                    "live_readiness": {
                        "status": "skeleton_fixture_only",
                        "fixture_contract_status": "passed",
                        "bounded_diagnostics": {"status": "required_before_live_ready"},
                        "operator_approval": {"status": "required_before_live_ready"},
                    },
                    "schedule": "manual",
                },
                "path": "crawlers\\shopping\\coupang",
                "module_path": "crawlers.shopping.coupang.crawler",
            }
        }
    )
    coupang = {row["source_id"]: row for row in coverage["sources"]}["coupang"]
    health = coupang["source_health"]

    assert coupang["collection_status"] == "registered_unverified"
    assert health["status"] == "registered_unverified"
    assert health["calendar"]["expected_event_cadence"] == "manual_fixture_until_verified"
    assert health["calendar"]["trigger"] == "manual"
    assert health["completeness"]["status"] == "not_measured"
    assert health["count_drop"]["status"] == "not_measured"
    assert health["live_network_default"] == "disabled"
    assert health["next_action_state"]["state"] == "attach_fixture_and_run_bounded_diagnostics"


def test_source_health_flags_failing_count_drop_against_baseline():
    coverage = build_source_coverage(
        {
            "emart": {
                "config": {"name": "emart", "category": "mart", "schedule": {"cron": "0 7 * * *"}},
                "path": "crawlers\\marts\\emart",
                "module_path": "crawlers.marts.emart.crawler",
            }
        },
        quality_by_source={
            "emart": summarize_discount_run(
                [
                    {"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"},
                    {"name": "두부", "sale_price": 1980, "detail_url": "https://example.test/b"},
                ],
                raw_count=2,
                source_raw_count=2,
            )
        },
        health_baseline_by_source={
            "emart": {
                "expected_counts": {"source_raw": 10, "parsed": 10, "valid": 10},
                "count_drop_threshold": 0.5,
                "baseline_source": "fixture_contract:emart:previous_good",
            }
        },
    )
    health = {row["source_id"]: row for row in coverage["sources"]}["emart"]["source_health"]

    assert health["status"] == "failing"
    assert health["completeness"]["status"] == "below_baseline"
    assert health["count_drop"]["status"] == "drop_detected"
    assert {alert["code"] for alert in health["count_drop"]["alerts"]} == {
        "source_raw_count_drop",
        "parsed_count_drop",
        "valid_count_drop",
    }
    assert health["next_action_state"]["state"] == "investigate_count_drop"


def test_source_health_dashboard_aggregates_multiple_sources_alerts_and_fields():
    coverage = build_source_coverage(
        {
            "emart": {
                "config": {"name": "emart", "category": "mart", "schedule": {"cron": "0 7 * * *"}},
                "path": "crawlers\\marts\\emart",
                "module_path": "crawlers.marts.emart.crawler",
            },
            "homeplus": {
                "config": {"name": "homeplus", "category": "mart", "schedule": {"cron": "30 7 * * *"}},
                "path": "crawlers\\marts\\homeplus",
                "module_path": "crawlers.marts.homeplus.crawler",
            },
        },
        quality_by_source={
            "emart": summarize_discount_run(
                [{"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"}],
                raw_count=1,
                source_raw_count=1,
            ),
            "homeplus": summarize_discount_run(
                [{"name": "두부", "sale_price": 1980}],
                raw_count=1,
                source_raw_count=1,
            ),
        },
        health_baseline_by_source={
            "homeplus": {
                "expected_counts": {"source_raw": 4, "parsed": 4, "valid": 4},
                "count_drop_threshold": 0.75,
            }
        },
    )
    rows = {row["source_id"]: row for row in coverage["sources"]}
    dashboard = coverage["source_health_dashboard"]

    assert rows["emart"]["source_health"]["calendar"]["source_calendar"] == "emart_daily_morning_price_snapshot.v1"
    assert rows["homeplus"]["source_health"]["status"] == "failing"
    assert dashboard["status_counts"]["collecting"] == 1
    assert dashboard["status_counts"]["failing"] == 1
    assert dashboard["field_coverage_dashboard"]["detail_url"]["low"] >= 1
    assert {alert["metric"] for alert in dashboard["count_drop_alerts"]} == {"source_raw", "parsed", "valid"}
    assert dashboard["sources_needing_action"][0]["source_id"] == "homeplus"


def test_source_health_reports_missing_count_baseline_without_count_drop_alerts():
    coverage = build_source_coverage(
        {
            "emart": {
                "config": {"name": "emart", "category": "mart"},
                "path": "crawlers\\marts\\emart",
                "module_path": "crawlers.marts.emart.crawler",
            }
        },
        quality_by_source={
            "emart": summarize_discount_run(
                [{"name": "양파", "sale_price": 3980, "detail_url": "https://example.test/a"}],
                raw_count=1,
                source_raw_count=1,
            )
        },
        health_baseline_by_source={"emart": {"expected_counts": {"source_raw": 1}}},
    )
    health = {row["source_id"]: row for row in coverage["sources"]}["emart"]["source_health"]

    assert health["completeness"]["status"] == "baseline_missing"
    assert health["completeness"]["missing_expected_count_keys"] == ["parsed", "valid"]
    assert health["count_drop"]["alerts"] == []
    assert health["next_action_state"]["state"] == "define_completeness_baseline"


def test_source_health_prioritizes_parser_drift_zero_result_action():
    coverage = build_source_coverage(
        {
            "homeplus": {
                "config": {"name": "homeplus", "category": "mart"},
                "path": "crawlers\\marts\\homeplus",
                "module_path": "crawlers.marts.homeplus.crawler",
            }
        },
        quality_by_source={"homeplus": summarize_discount_run([], raw_count=0, source_raw_count=3)},
        health_baseline_by_source={"homeplus": {"expected_counts": {"source_raw": 3, "parsed": 3, "valid": 3}}},
    )
    health = {row["source_id"]: row for row in coverage["sources"]}["homeplus"]["source_health"]

    assert health["status"] == "failing"
    assert health["completeness"]["zero_result_stage"] == "parse_filtered_all_raw_rows"
    assert {alert["metric"] for alert in health["count_drop"]["alerts"]} == {"parsed", "valid"}
    assert health["next_action_state"]["state"] == "triage_zero_result_parser_drift"
