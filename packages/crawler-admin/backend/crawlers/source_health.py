"""Fixture-safe source health foundations for crawler operators.

This module is intentionally metadata/quality-summary only. It does not crawl,
probe, or enable live network access.
"""
from __future__ import annotations

from typing import Any

from pipeline.quality import CRITICAL_FIELD_THRESHOLDS

SOURCE_HEALTH_SCHEMA = "crawler_source_health.v1"

DEFAULT_CADENCE_BY_GROUP: dict[str, dict[str, Any]] = {
    "mart": {
        "expected_event_cadence": "daily_price_event",
        "freshness_sla_hours": 36,
        "collection_window": "morning_local",
        "timezone": "Asia/Seoul",
        "event_family": "retail_price_snapshot",
        "evidence_mode": "fixture_or_bounded_diagnostic",
    },
    "marketplace": {
        "expected_event_cadence": "manual_fixture_until_verified",
        "freshness_sla_hours": None,
        "collection_window": "disabled_until_live_readiness_gate_passes",
        "timezone": "Asia/Seoul",
        "event_family": "marketplace_price_snapshot",
        "evidence_mode": "saved_fixture_then_bounded_no_db_live_diagnostic",
    },
    "hotdeal": {
        "expected_event_cadence": "frequent_hotdeal_event",
        "freshness_sla_hours": 12,
        "collection_window": "bounded_fixture_or_approved_run",
    },
    "fashion": {
        "expected_event_cadence": "daily_price_event",
        "freshness_sla_hours": 48,
        "collection_window": "bounded_fixture_or_approved_run",
    },
    "government": {
        "expected_event_cadence": "daily_public_data_event",
        "freshness_sla_hours": 48,
        "collection_window": "bounded_fixture_or_approved_run",
    },
}

SOURCE_CALENDAR_BY_ID: dict[str, dict[str, Any]] = {
    "emart": {
        "source_calendar": "emart_daily_morning_price_snapshot.v1",
        "collection_window": "07:00-10:00 Asia/Seoul",
        "freshness_sla_hours": 36,
    },
    "homeplus": {
        "source_calendar": "homeplus_daily_morning_price_snapshot.v1",
        "collection_window": "07:00-10:00 Asia/Seoul",
        "freshness_sla_hours": 36,
    },
    "lottemart": {
        "source_calendar": "lottemart_daily_morning_price_snapshot.v1",
        "collection_window": "07:00-10:00 Asia/Seoul",
        "freshness_sla_hours": 36,
    },
    "coupang": {
        "source_calendar": "marketplace_fixture_gate_price_snapshot.v1",
        "expected_event_cadence": "manual_fixture_until_verified",
        "collection_window": "disabled_until_live_readiness_gate_passes",
        "freshness_sla_hours": None,
    },
    "naver_store": {
        "source_calendar": "marketplace_fixture_gate_price_snapshot.v1",
        "expected_event_cadence": "manual_fixture_until_verified",
        "collection_window": "disabled_until_live_readiness_gate_passes",
        "freshness_sla_hours": None,
    },
    "gmarket": {
        "source_calendar": "marketplace_fixture_gate_price_snapshot.v1",
        "expected_event_cadence": "manual_fixture_until_verified",
        "collection_window": "disabled_until_live_readiness_gate_passes",
        "freshness_sla_hours": None,
    },
    "11st": {
        "source_calendar": "marketplace_fixture_gate_price_snapshot.v1",
        "expected_event_cadence": "manual_fixture_until_verified",
        "collection_window": "disabled_until_live_readiness_gate_passes",
        "freshness_sla_hours": None,
    },
    "aliexpress": {
        "source_calendar": "marketplace_fixture_gate_price_snapshot.v1",
        "expected_event_cadence": "manual_fixture_until_verified",
        "collection_window": "disabled_until_live_readiness_gate_passes",
        "freshness_sla_hours": None,
    },
}

DEFAULT_COUNT_DROP_THRESHOLD = 0.5

DEFAULT_BASELINE_BY_GROUP: dict[str, dict[str, Any]] = {
    "mart": {
        "expected_counts": {"source_raw": 1, "parsed": 1, "valid": 1},
        "baseline_source": "mart_fixture_minimum.v1",
    },
    "marketplace": {
        "expected_counts": {"source_raw": 1, "parsed": 1, "valid": 1},
        "baseline_source": "marketplace_fixture_contract_minimum.v1",
    },
}

SOURCE_BASELINE_BY_ID: dict[str, dict[str, Any]] = {
    "emart": {"baseline_source": "emart_fixture_contract_minimum.v1"},
    "homeplus": {"baseline_source": "homeplus_fixture_contract_minimum.v1"},
    "lottemart": {"baseline_source": "lottemart_fixture_contract_minimum.v1"},
    "coupang": {"baseline_source": "coupang_marketplace_skeleton_fixture_minimum.v1"},
    "naver_store": {"baseline_source": "naver_store_marketplace_skeleton_fixture_minimum.v1"},
    "gmarket": {"baseline_source": "gmarket_marketplace_skeleton_fixture_minimum.v1"},
    "11st": {"baseline_source": "11st_marketplace_skeleton_fixture_minimum.v1"},
    "aliexpress": {"baseline_source": "aliexpress_marketplace_skeleton_fixture_minimum.v1"},
}


def build_source_health_row(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    quality: dict[str, Any] | None,
    collection_status: str,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a per-source health foundation from registry metadata and bounded quality evidence."""
    config = (match or {}).get("config") or {}
    baseline = _merge_baselines(_default_baseline(source, config), config.get("health_baseline"), baseline)
    cadence = _cadence_for(source, config)
    completeness = _completeness_status(quality, baseline)
    count_drop = _count_drop_status(quality, baseline)
    field_dashboard = _field_coverage_dashboard(quality, baseline)
    status = _health_status(collection_status, completeness, count_drop, field_dashboard)
    next_state = _next_action_state(collection_status, status, completeness, count_drop, field_dashboard)

    return {
        "schema": SOURCE_HEALTH_SCHEMA,
        "source_id": source["source_id"],
        "status": status,
        "collection_status": collection_status,
        "calendar": cadence,
        "completeness_baseline": baseline,
        "completeness": completeness,
        "count_drop": count_drop,
        "field_coverage_dashboard": field_dashboard,
        "next_action_state": next_state,
        "live_network_default": "disabled",
    }


def summarize_source_health_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    health_rows = [row.get("source_health") for row in rows if row.get("source_health")]
    by_status: dict[str, int] = {}
    next_actions: dict[str, int] = {}
    completeness: dict[str, int] = {}
    field_statuses: dict[str, dict[str, int]] = {}
    count_drop_alerts: list[dict[str, Any]] = []
    sources_needing_action: list[dict[str, Any]] = []
    for health in health_rows:
        by_status[health["status"]] = by_status.get(health["status"], 0) + 1
        state = health["next_action_state"]["state"]
        next_actions[state] = next_actions.get(state, 0) + 1
        completeness_status = health["completeness"]["status"]
        completeness[completeness_status] = completeness.get(completeness_status, 0) + 1
        count_drop_alerts.extend(
            {"source_id": health["source_id"], **alert} for alert in health["count_drop"].get("alerts", [])
        )
        for field in health["field_coverage_dashboard"].get("fields", []):
            field_name = field["field"]
            status = field["status"]
            field_statuses.setdefault(field_name, {})
            field_statuses[field_name][status] = field_statuses[field_name].get(status, 0) + 1
        if health["next_action_state"]["state"] != "monitor":
            sources_needing_action.append(
                {
                    "source_id": health["source_id"],
                    "state": health["next_action_state"]["state"],
                    "severity": health["next_action_state"]["severity"],
                    "status": health["status"],
                }
            )
    return {
        "schema": SOURCE_HEALTH_SCHEMA,
        "total_sources": len(health_rows),
        "status_counts": by_status,
        "completeness_counts": completeness,
        "next_action_state_counts": next_actions,
        "count_drop_alerts": count_drop_alerts,
        "field_coverage_dashboard": field_statuses,
        "sources_needing_action": sources_needing_action,
        "live_network_default": "disabled",
        "policy": (
            "Source health uses registry metadata, fixture/bounded quality summaries, and configured baselines only; "
            "it never performs live marketplace crawling by default."
        ),
    }


def _default_baseline(source: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    output = config.get("output") if isinstance(config.get("output"), dict) else {}
    configured_required = list(output.get("required_fields") or [])
    required_fields = list(dict.fromkeys([*configured_required, *CRITICAL_FIELD_THRESHOLDS.keys()]))
    group_baseline = DEFAULT_BASELINE_BY_GROUP.get(source.get("group"), {})
    source_baseline = SOURCE_BASELINE_BY_ID.get(source["source_id"], {})
    return _merge_baselines(
        {
            "required_fields": required_fields,
            "critical_field_thresholds": CRITICAL_FIELD_THRESHOLDS,
            "expected_counts": {
                "source_raw": 1,
                "parsed": 1,
                "valid": 1,
            },
            "count_drop_threshold": DEFAULT_COUNT_DROP_THRESHOLD,
            "baseline_source": "registry_default_fixture_baseline",
            "group": source.get("group"),
            "baseline_required": True,
        },
        group_baseline,
        source_baseline,
    )


def _merge_baselines(*baselines: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for baseline in baselines:
        if not baseline:
            continue
        for key, value in baseline.items():
            if key != "expected_counts" and isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    return merged


def _cadence_for(source: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    schedule = config.get("schedule", "manual")
    if isinstance(schedule, dict):
        trigger = "cron" if schedule.get("cron") else "manual"
        expression = schedule.get("cron") or "manual"
        retry_count = schedule.get("retry_count")
        retry_delay_seconds = schedule.get("retry_delay")
    else:
        trigger = "manual" if not schedule or schedule == "manual" else "schedule"
        expression = schedule or "manual"
        retry_count = None
        retry_delay_seconds = None
    defaults = DEFAULT_CADENCE_BY_GROUP.get(source.get("group"), DEFAULT_CADENCE_BY_GROUP["fashion"])
    source_defaults = SOURCE_CALENDAR_BY_ID.get(source["source_id"], {})
    return {
        **defaults,
        **source_defaults,
        **(config.get("source_health_calendar") or {}),
        "source_id": source["source_id"],
        "trigger": trigger,
        "expression": expression,
        "retry_count": retry_count,
        "retry_delay_seconds": retry_delay_seconds,
    }


def _counts(quality: dict[str, Any] | None) -> dict[str, int]:
    raw = (quality or {}).get("item_counts") or {}
    return {
        "source_raw": int(raw.get("source_raw") or 0),
        "parsed": int(raw.get("parsed") or 0),
        "valid": int(raw.get("valid") or 0),
        "invalid_or_dropped": int(raw.get("invalid_or_dropped") or 0),
        "duplicates_after_validation": int(raw.get("duplicates_after_validation") or 0),
    }


def _completeness_status(quality: dict[str, Any] | None, baseline: dict[str, Any]) -> dict[str, Any]:
    counts = _counts(quality)
    expected = baseline.get("expected_counts") or {}
    zero_stage = ((quality or {}).get("zero_result_diagnostic") or {}).get("stage")
    missing_baselines = [name for name in ("source_raw", "parsed", "valid") if name not in expected]
    below_expected = [
        name for name in ("source_raw", "parsed", "valid") if name in expected and counts[name] < int(expected.get(name) or 0)
    ]
    if not quality:
        status = "not_measured"
    elif missing_baselines:
        status = "baseline_missing"
    elif below_expected:
        status = "below_baseline"
    else:
        status = "meets_baseline"
    return {
        "status": status,
        "counts": counts,
        "expected_counts": expected,
        "missing_count_baselines": missing_baselines,
        "below_expected_counts": below_expected,
        "missing_expected_count_keys": missing_baselines,
        "zero_result_stage": zero_stage,
    }


def _count_drop_status(quality: dict[str, Any] | None, baseline: dict[str, Any]) -> dict[str, Any]:
    counts = _counts(quality)
    expected = baseline.get("expected_counts") or {}
    threshold = float(baseline.get("count_drop_threshold", DEFAULT_COUNT_DROP_THRESHOLD))
    alerts: list[dict[str, Any]] = []
    for name in ("source_raw", "parsed", "valid"):
        expected_count = int(expected.get(name) or 0)
        if not quality or expected_count <= 0:
            continue
        ratio = round(counts[name] / expected_count, 3)
        if ratio < threshold:
            alerts.append(
                {
                    "code": f"{name}_count_drop",
                    "severity": "error" if name == "valid" else "warning",
                    "metric": name,
                    "current": counts[name],
                    "baseline": expected_count,
                    "ratio": ratio,
                    "threshold": threshold,
                }
            )
    return {
        "status": "drop_detected" if alerts else ("not_measured" if not quality else "within_baseline"),
        "alerts": alerts,
    }


def _field_coverage_dashboard(quality: dict[str, Any] | None, baseline: dict[str, Any]) -> dict[str, Any]:
    thresholds = baseline.get("critical_field_thresholds") or CRITICAL_FIELD_THRESHOLDS
    coverage = ((quality or {}).get("quality_summary") or {}).get("critical_field_coverage") or {}
    fields = []
    for field, threshold in thresholds.items():
        value = coverage.get(field)
        fields.append(
            {
                "field": field,
                "coverage": value,
                "threshold": threshold,
                "status": "not_measured" if value is None else ("ok" if value >= threshold else "low"),
            }
        )
    if not quality:
        status = "not_measured"
    elif any(field["status"] == "low" for field in fields):
        status = "low_coverage"
    else:
        status = "ok"
    return {"status": status, "fields": fields}


def _health_status(
    collection_status: str,
    completeness: dict[str, Any],
    count_drop: dict[str, Any],
    field_dashboard: dict[str, Any],
) -> str:
    if count_drop["status"] == "drop_detected":
        return "failing"
    if collection_status == "failing" or completeness["status"] in {"below_baseline", "baseline_missing"}:
        return "failing"
    if collection_status == "registered_unverified":
        return "registered_unverified"
    if field_dashboard["status"] == "low_coverage":
        return "warning"
    if collection_status == "collecting":
        return "collecting"
    return collection_status


def _next_action_state(
    collection_status: str,
    health_status: str,
    completeness: dict[str, Any],
    count_drop: dict[str, Any],
    field_dashboard: dict[str, Any],
) -> dict[str, Any]:
    zero_stage = completeness.get("zero_result_stage")
    if zero_stage in {"parse_filtered_all_raw_rows", "validation_rejected_all_rows", "source_zero_raw_rows"}:
        return {
            "state": "triage_zero_result_parser_drift",
            "severity": "error",
            "message": "Zero-result diagnostics indicate parser drift or validation rejection; replay fixtures before live changes.",
        }
    if completeness["status"] == "baseline_missing":
        return {
            "state": "define_completeness_baseline",
            "severity": "error",
            "message": "Source health cannot evaluate completeness until source_raw, parsed, and valid baselines are defined.",
        }
    if count_drop["alerts"]:
        return {
            "state": "investigate_count_drop",
            "severity": "error",
            "message": "Current bounded counts dropped below the source baseline; replay fixture evidence before live changes.",
        }
    if health_status == "failing" or completeness["status"] == "below_baseline":
        return {
            "state": "repair_parser_or_fixture",
            "severity": "error",
            "message": "Bounded diagnostics do not meet completeness baseline; fix parser, validation, or fixture contract.",
        }
    if collection_status == "registered_unverified":
        if completeness["status"] == "meets_baseline":
            return {
                "state": "await_bounded_live_diagnostics_approval",
                "severity": "warning",
                "message": (
                    "Fixture/bounded evidence meets source health baselines, but live/collecting claims remain disabled "
                    "until bounded diagnostics gates and explicit operator approval pass."
                ),
            }
        return {
            "state": "attach_fixture_and_run_bounded_diagnostics",
            "severity": "warning",
            "message": "Source is registered but not collecting; keep live crawling disabled and add fixture evidence.",
        }
    if field_dashboard["status"] == "low_coverage":
        return {
            "state": "improve_field_coverage",
            "severity": "warning",
            "message": "Critical fields are below threshold; update fixture-backed parser field mapping.",
        }
    return {
        "state": "monitor",
        "severity": "info",
        "message": "Maintain fixture/bounded diagnostics and watch cadence, completeness, and field coverage.",
    }
