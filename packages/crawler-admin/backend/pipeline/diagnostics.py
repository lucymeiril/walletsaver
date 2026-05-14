"""Bounded crawler diagnostics runner for safe fixture-based quality evidence."""

from __future__ import annotations

import inspect
from typing import Any

from crawlers.source_coverage import build_source_coverage
from pipeline.quality import CRITICAL_FIELD_THRESHOLDS, summarize_discount_run

DIAGNOSTICS_SCHEMA = "bounded_crawler_diagnostics.v1"
LIVE_DIAGNOSTICS_PLAN_SCHEMA = "bounded_live_diagnostics_plan.v1"
DEFAULT_LIVE_DIAGNOSTIC_RUN_LIMITS = {
    "max_requests": 3,
    "max_pages": 1,
    "timeout_seconds": 15,
}


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "dict"):
        return item.dict()
    return {k: v for k, v in vars(item).items() if not k.startswith("_")}


def _fixture_for(crawler_id: str, info: dict[str, Any], fixtures: dict[str, str]) -> str | None:
    config = info.get("config") or {}
    keys = [crawler_id, config.get("name"), config.get("source_id"), *(config.get("plugin_aliases") or [])]
    lowered = {str(key).lower(): value for key, value in fixtures.items()}
    for key in keys:
        if key is None:
            continue
        if str(key) in fixtures:
            return fixtures[str(key)]
        if str(key).lower() in lowered:
            return lowered[str(key).lower()]
    return None


def _fixture_missing_summary(crawler_id: str, live_enabled: bool) -> dict[str, Any]:
    if live_enabled:
        return summarize_discount_run(
            [],
            raw_count=0,
            source_raw_count=0,
            live_enabled=True,
            fixture_available=False,
            errors=[f"{crawler_id} bounded diagnostics received no fixture/raw input."],
        )
    return summarize_discount_run(
        [],
        raw_count=0,
        source_raw_count=0,
        live_enabled=False,
        fixture_available=False,
        errors=[
            f"{crawler_id} live crawling is disabled for bounded diagnostics and no saved fixture/raw input was provided."
        ],
    )


def _registry_dict(registry: Any) -> dict[str, dict[str, Any]]:
    return getattr(registry, "_registry", registry)


def _fixture_snapshot_for(
    source_id: str,
    row: dict[str, Any],
    fixture_snapshots: dict[str, Any],
) -> dict[str, Any]:
    snapshot = fixture_snapshots.get(source_id) or fixture_snapshots.get(str(row.get("registered_name")))
    if isinstance(snapshot, dict):
        return {
            "path": snapshot.get("path"),
            "status": snapshot.get("status") or ("available" if snapshot.get("path") else "missing"),
        }
    if isinstance(snapshot, str):
        return {"path": snapshot, "status": "available"}

    if row.get("group") == "marketplace" and (row.get("registration_metadata") or {}).get("fixture_contract"):
        return {
            "path": f"packages\\crawler-admin\\backend\\tests\\fixtures\\marketplace_skeleton\\{source_id}.html",
            "status": "contract_fixture_available",
        }
    return {"path": None, "status": "missing"}


def _configured_run_limits(row: dict[str, Any], requested_limits: dict[str, int] | None) -> dict[str, int]:
    configured = ((row.get("live_readiness_gate") or {}).get("bounded_diagnostics") or {}).get("run_limits") or {}
    merged = {**DEFAULT_LIVE_DIAGNOSTIC_RUN_LIMITS, **(requested_limits or {})}
    for src, dst in (("max_pages", "max_pages"), ("timeout_seconds", "timeout_seconds"), ("timeout", "timeout_seconds")):
        if configured.get(src):
            merged[dst] = int(configured[src])
    if configured.get("max_requests"):
        merged["max_requests"] = int(configured["max_requests"])
    return merged


def _plan_blockers(row: dict[str, Any], fixture_snapshot: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if row.get("registration_status") != "registered":
        blockers.append("crawler_not_registered")
    if fixture_snapshot.get("status") == "missing":
        blockers.append("fixture_snapshot_missing")

    gate = row.get("live_readiness_gate") or {}
    if gate.get("required") and not gate.get("passed"):
        blockers.extend(f"marketplace_gate:{reason}" for reason in gate.get("reasons", []))

    if row.get("collection_status") != "collecting":
        blockers.append(f"current_collection_status:{row.get('collection_status')}")
    return blockers


def build_bounded_live_diagnostics_plan(
    registry: Any,
    *,
    quality_by_source: dict[str, dict[str, Any]] | None = None,
    health_baseline_by_source: dict[str, dict[str, Any]] | None = None,
    fixture_snapshots: dict[str, Any] | None = None,
    allow_live: bool = False,
    run_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build a source-by-source live diagnostics plan without running live network."""
    registry_data = _registry_dict(registry)
    coverage = build_source_coverage(
        registry_data,
        quality_by_source=quality_by_source,
        health_baseline_by_source=health_baseline_by_source,
    )
    fixture_snapshots = fixture_snapshots or {}
    plans: list[dict[str, Any]] = []

    for row in coverage["sources"]:
        source_id = row["source_id"]
        limits = _configured_run_limits(row, run_limits)
        fixture_snapshot = _fixture_snapshot_for(source_id, row, fixture_snapshots)
        blockers = _plan_blockers(row, fixture_snapshot)
        gate = row.get("live_readiness_gate") or {}
        evidence_id = (
            (gate.get("bounded_diagnostics") or {}).get("evidence_id")
            or f"pending:{source_id}:bounded-live-diagnostics"
        )
        allowed_live = bool(allow_live and not blockers)
        approval_needed = not allowed_live or bool(gate.get("required") and not gate.get("passed"))

        plans.append(
            {
                "source_id": source_id,
                "collection_status": row.get("collection_status"),
                "current_collection_status": row.get("collection_status"),
                "required_run_limits": limits,
                "fixture_snapshot": fixture_snapshot,
                "fixture_snapshot_path": fixture_snapshot.get("path"),
                "fixture_snapshot_status": fixture_snapshot.get("status"),
                "allowed_live": allowed_live,
                "max_requests": limits["max_requests"],
                "max_pages": limits["max_pages"],
                "timeout": limits["timeout_seconds"],
                "timeout_seconds": limits["timeout_seconds"],
                "evidence_id": evidence_id,
                "approval_needed": approval_needed,
                "blockers": blockers,
            }
        )

    return {
        "schema": LIVE_DIAGNOSTICS_PLAN_SCHEMA,
        "live_network_default": "disabled",
        "live_enabled": bool(allow_live),
        "plan_policy": (
            "This artifact only plans bounded live diagnostics. It never runs live crawling, and registered_unverified "
            "sources remain non-collecting until fixture snapshots, bounded run limits, evidence, gates, and approval pass."
        ),
        "default_run_limits": DEFAULT_LIVE_DIAGNOSTIC_RUN_LIMITS,
        "source_coverage": coverage,
        "sources": plans,
    }


def _safe_collection_status(quality: dict[str, Any], *, live_ready: bool | None, has_quality_evidence: bool) -> str:
    if not has_quality_evidence:
        return "registered_unverified"
    if live_ready is False:
        return "registered_unverified"
    return (quality.get("quality_summary") or {}).get("status") or "registered_unverified"


def _source_drift_readiness(quality: dict[str, Any], *, fixture_available: bool) -> dict[str, Any]:
    counts = quality.get("item_counts") or {}
    summary = quality.get("quality_summary") or {}
    zero_stage = summary.get("zero_result_stage")
    low_critical = summary.get("low_critical_fields") or []
    parsed = counts.get("parsed") or 0
    source_raw = counts.get("source_raw") or 0
    valid = counts.get("valid") or 0

    if not fixture_available:
        status = "not_ready"
        reason = "No saved fixture/raw input was supplied, so parser drift cannot be checked safely."
    elif source_raw > 0 and parsed == 0:
        status = "drift_detected"
        reason = "Source candidates exist but parser emitted zero rows."
    elif parsed > 0 and valid == 0:
        status = "validation_blocked"
        reason = "Parser emitted rows but validation rejected all of them."
    elif low_critical:
        status = "warning"
        reason = "Fixture parses, but customer-visible critical field coverage is below threshold."
    elif valid > 0:
        status = "ready"
        reason = "Fixture has source candidates, parsed rows, valid rows, and critical fields at threshold."
    else:
        status = "not_ready"
        reason = zero_stage or "No valid diagnostic evidence was produced."

    return {
        "status": status,
        "ready": status == "ready",
        "reason": reason,
        "fixture_available": fixture_available,
        "counts": {
            "source_raw": source_raw,
            "parsed": parsed,
            "valid": valid,
            "invalid_or_dropped": counts.get("invalid_or_dropped") or 0,
        },
        "critical_field_coverage": summary.get("critical_field_coverage") or {},
        "low_critical_fields": low_critical,
        "zero_result_stage": zero_stage,
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _diagnose_fixture(crawler: Any, fixture: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    source_raw_count = 0
    try:
        if hasattr(crawler, "count_raw_candidates"):
            source_raw_count = int(crawler.count_raw_candidates(fixture))
        elif hasattr(crawler, "_count_raw_candidates"):
            source_raw_count = int(crawler._count_raw_candidates(fixture))
        elif fixture.strip():
            source_raw_count = 1
    except Exception as exc:
        errors.append(f"source_raw_count: {exc}")

    parsed_items: list[Any] = []
    try:
        parsed_items = list(await _maybe_await(crawler.parse(fixture)))
    except Exception as exc:
        errors.append(f"parse: {exc}")

    valid_items = parsed_items
    if parsed_items and hasattr(crawler, "validate"):
        try:
            valid_items = list(await _maybe_await(crawler.validate(parsed_items)))
        except Exception as exc:
            errors.append(f"validate: {exc}")
            valid_items = []

    valid_dicts = [_item_to_dict(item) for item in valid_items]
    quality = summarize_discount_run(
        valid_dicts,
        raw_count=len(parsed_items),
        source_raw_count=source_raw_count,
        invalid_count=max(0, len(parsed_items) - len(valid_items)),
        errors=errors,
        strategy_used="bounded-fixture",
        live_enabled=False,
        fixture_available=True,
    )
    return quality, errors


def _report_from_quality(
    crawler_id: str,
    info: dict[str, Any],
    quality: dict[str, Any],
    *,
    fixture_available: bool,
) -> dict[str, Any]:
    config = info.get("config") or {}
    live_ready = config.get("live_ready")
    counts = quality.get("item_counts") or {}
    has_quality_evidence = fixture_available and (counts.get("source_raw") or counts.get("parsed") or counts.get("valid")) > 0
    collection_status = _safe_collection_status(
        quality,
        live_ready=live_ready,
        has_quality_evidence=has_quality_evidence,
    )
    readiness = _source_drift_readiness(quality, fixture_available=fixture_available)
    operator_diagnostics = list(quality.get("operator_diagnostics", []))
    if live_ready is False and has_quality_evidence:
        operator_diagnostics.insert(
            0,
            {
                "code": "live_ready_false_registered_unverified",
                "severity": "warning",
                "message": (
                    f"{crawler_id} has saved-fixture evidence, but live_ready=false; keep it registered_unverified."
                ),
                "next_action": (
                    "Attach this fixture diagnostic as parser-shape evidence, then request an explicitly approved "
                    "bounded no-DB live diagnostic before any live_ready or collecting claim."
                ),
            },
        )
    return {
        "crawler_id": crawler_id,
        "registration_status": "registered",
        "registered_name": config.get("name", crawler_id),
        "module_path": info.get("module_path"),
        "parser_contract": config.get("parser_contract"),
        "live_ready": live_ready,
        "fixture": {
            "available": fixture_available,
            "live_enabled": False,
            "mode": "saved_fixture" if fixture_available else "live_disabled_no_fixture",
        },
        "quality_evidence": {
            "has_quality_evidence": has_quality_evidence,
            "can_claim_collecting": collection_status == "collecting",
            "collection_status": collection_status,
            "counts": {
                "source_raw": counts.get("source_raw"),
                "parsed": counts.get("parsed"),
                "valid": counts.get("valid"),
                "invalid_or_dropped": counts.get("invalid_or_dropped"),
                "duplicates_after_validation": counts.get("duplicates_after_validation"),
            },
            "critical_field_coverage": (quality.get("quality_summary") or {}).get("critical_field_coverage") or {},
            "critical_field_thresholds": CRITICAL_FIELD_THRESHOLDS,
            "diagnostic_codes": [d.get("code") for d in quality.get("operator_diagnostics", []) if d.get("code")],
        },
        "source_drift_readiness": readiness,
        "operator_diagnostics": operator_diagnostics,
        "next_actions": quality.get("next_actions", []),
        "quality_details": quality,
    }


async def run_bounded_crawler_diagnostics(
    registry: Any,
    *,
    fixture_by_source: dict[str, str] | None = None,
    crawler_ids: list[str] | None = None,
    health_baseline_by_source: dict[str, dict[str, Any]] | None = None,
    live_enabled: bool = False,
) -> dict[str, Any]:
    """Run safe, bounded fixture diagnostics for registered crawlers only.

    Live crawling is disabled by default. Without a fixture this function reports
    a diagnostic gap instead of calling ``crawl()`` or making network requests.
    """
    fixture_by_source = fixture_by_source or {}
    registry_dict: dict[str, dict[str, Any]] = _registry_dict(registry)
    selected = crawler_ids or list(registry_dict.keys())
    reports: list[dict[str, Any]] = []
    quality_by_source: dict[str, dict[str, Any]] = {}

    for crawler_id in selected:
        info = registry_dict.get(crawler_id)
        if not info:
            reports.append(
                {
                    "crawler_id": crawler_id,
                    "registration_status": "missing",
                    "quality_evidence": {"has_quality_evidence": False, "can_claim_collecting": False},
                    "operator_diagnostics": [
                        {
                            "code": "crawler_not_registered",
                            "severity": "error",
                            "message": f"{crawler_id} is not registered; diagnostics cannot run.",
                        }
                    ],
                }
            )
            continue

        fixture = _fixture_for(crawler_id, info, fixture_by_source)
        if fixture is None:
            quality = _fixture_missing_summary(crawler_id, live_enabled)
            report = _report_from_quality(crawler_id, info, quality, fixture_available=False)
            reports.append(report)
            continue

        try:
            crawler = registry.get_crawler(crawler_id) if hasattr(registry, "get_crawler") else info["crawler"]
            quality, _ = await _diagnose_fixture(crawler, fixture)
        except Exception as exc:
            quality = summarize_discount_run(
                [],
                raw_count=0,
                source_raw_count=0,
                errors=[f"diagnostics: {exc}"],
                strategy_used="bounded-fixture",
                live_enabled=False,
                fixture_available=True,
            )
        report = _report_from_quality(crawler_id, info, quality, fixture_available=True)
        reports.append(report)
        if report["quality_evidence"]["has_quality_evidence"]:
            quality_by_source[crawler_id] = quality

    collecting_count = sum(1 for report in reports if report.get("quality_evidence", {}).get("can_claim_collecting"))
    return {
        "schema": DIAGNOSTICS_SCHEMA,
        "live_network_default": "disabled",
        "live_enabled": live_enabled,
        "registered_count": sum(1 for report in reports if report.get("registration_status") == "registered"),
        "diagnosed_count": len(reports),
        "quality_evidence_count": len(quality_by_source),
        "collecting_count": collecting_count,
        "collection_claim_policy": (
            "Registered crawlers cannot claim collecting unless bounded diagnostics produce quality evidence with valid "
            "rows, critical customer-visible field coverage, and no blocking live_ready=false state."
        ),
        "quality_by_source": quality_by_source,
        "source_coverage": build_source_coverage(
            registry_dict,
            quality_by_source=quality_by_source,
            health_baseline_by_source=health_baseline_by_source,
        ),
        "crawlers": reports,
    }
