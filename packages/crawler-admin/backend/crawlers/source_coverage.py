"""Crawler source coverage matrix for one-shot DB build planning.

This module is intentionally metadata-only. It does not crawl or probe external
sites; it tells operators which required sources are actually registered as
plugins and which are still backlog items.
"""
from __future__ import annotations

from typing import Any

from crawlers.source_health import build_source_health_row, summarize_source_health_rows


REQUIRED_ONE_SHOT_SOURCES: list[dict[str, Any]] = [
    {
        "source_id": "emart",
        "display_name": "이마트",
        "group": "mart",
        "required_for": "mart3",
        "plugin_aliases": ["emart"],
    },
    {
        "source_id": "homeplus",
        "display_name": "홈플러스",
        "group": "mart",
        "required_for": "mart3",
        "plugin_aliases": ["homeplus"],
    },
    {
        "source_id": "lottemart",
        "display_name": "롯데마트",
        "group": "mart",
        "required_for": "mart3",
        "plugin_aliases": ["lottemart"],
    },
    {
        "source_id": "coupang",
        "display_name": "쿠팡",
        "group": "marketplace",
        "required_for": "marketplace_price",
        "plugin_aliases": ["coupang"],
    },
    {
        "source_id": "naver_store",
        "display_name": "네이버스토어",
        "group": "marketplace",
        "required_for": "marketplace_price",
        "plugin_aliases": ["naver_store", "naverstore", "smartstore", "naver_smartstore"],
    },
    {
        "source_id": "gmarket",
        "display_name": "G마켓",
        "group": "marketplace",
        "required_for": "marketplace_price",
        "plugin_aliases": ["gmarket", "g마켓"],
    },
    {
        "source_id": "11st",
        "display_name": "11번가",
        "group": "marketplace",
        "required_for": "marketplace_price",
        "plugin_aliases": ["11st", "11번가", "elevenst"],
    },
    {
        "source_id": "aliexpress",
        "display_name": "알리익스프레스",
        "group": "marketplace",
        "required_for": "marketplace_price",
        "plugin_aliases": ["aliexpress", "ali_express", "ali"],
    },
    {
        "source_id": "algumon",
        "display_name": "알구몬",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["algumon"],
    },
    {
        "source_id": "arca_hotdeal",
        "display_name": "아카라이브 핫딜",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["arca", "아카라이브"],
    },
    {
        "source_id": "musinsa",
        "display_name": "무신사",
        "group": "fashion",
        "required_for": "fashion_price",
        "plugin_aliases": ["musinsa"],
    },
    {
        "source_id": "giordano",
        "display_name": "지오다노",
        "group": "fashion",
        "required_for": "fashion_price",
        "plugin_aliases": ["giordano"],
    },
    {
        "source_id": "uniqlo",
        "display_name": "유니클로",
        "group": "fashion",
        "required_for": "fashion_price",
        "plugin_aliases": ["uniqlo"],
    },
    {
        "source_id": "opinet",
        "display_name": "오피넷",
        "group": "government",
        "required_for": "gas_price",
        "plugin_aliases": ["opinet"],
    },
]

MARKETPLACE_FIXTURE_CONTRACT = "marketplace_skeleton_fixture_contracts.v1"
MARKETPLACE_PARSER_CONTRACT = "marketplace_skeleton.v1"
MARKETPLACE_REQUIRED_READINESS_EVIDENCE = [
    "fixture_contract_passed",
    "bounded_live_diagnostics_passed",
    "bounded_run_limits_recorded",
    "operator_approval_recorded",
]
MARKETPLACE_OPERATOR_NEXT_ACTIONS = [
    "Run saved-fixture diagnostics and confirm source_raw, parsed, valid, validation-drop, duplicate, and critical-field evidence.",
    "Prepare no-DB AI review output from bounded diagnostics only; do not write marketplace skeleton output to production tables.",
    "Record bounded live diagnostics run limits/evidence_id and explicit operator approval before live_ready=true or collecting claims.",
]


def build_source_coverage(
    registry: dict[str, dict[str, Any]],
    quality_by_source: dict[str, dict[str, Any]] | None = None,
    health_baseline_by_source: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return required-source coverage from a CrawlerRegistry registry dict.

    ``quality_by_source`` accepts dry-run/mock ``summarize_discount_run`` output
    keyed by source id, registered name, or plugin alias. It never performs live
    scraping; it only annotates metadata so operators can distinguish
    "registered" from "reliably collecting".
    """
    plugins_by_name = {
        str(name).lower(): {"registered_name": name, **info}
        for name, info in registry.items()
    }
    quality_by_source = quality_by_source or {}
    health_baseline_by_source = health_baseline_by_source or {}
    rows: list[dict[str, Any]] = []
    missing_by_group: dict[str, list[str]] = {}
    registered_count = 0
    collecting_count = 0

    for source in REQUIRED_ONE_SHOT_SOURCES:
        match = _find_plugin(source["plugin_aliases"], plugins_by_name)
        status = "registered" if match else "missing"
        quality = _find_quality(source, match, quality_by_source) if match else None
        live_ready = ((match or {}).get("config") or {}).get("live_ready") if match else None
        readiness_gate = _live_readiness_gate(source, match, quality)
        reliability = _collection_reliability(status, quality, live_ready, readiness_gate)
        source_health = build_source_health_row(
            source,
            match,
            quality,
            reliability,
            _find_health_baseline(source, match, health_baseline_by_source),
        )
        if reliability == "collecting":
            collecting_count += 1
        if match:
            registered_count += 1
        else:
            missing_by_group.setdefault(source["group"], []).append(source["source_id"])
        rows.append(
            {
                "source_id": source["source_id"],
                "display_name": source["display_name"],
                "group": source["group"],
                "required_for": source["required_for"],
                "status": status,
                "registration_status": status,
                "registered_name": match.get("registered_name") if match else None,
                "plugin_path": match.get("path") if match else None,
                "module_path": match.get("module_path") if match else None,
                "live_ready": live_ready,
                "parser_contract": ((match or {}).get("config") or {}).get("parser_contract") if match else None,
                "verification_status": reliability,
                "registration_metadata": _registration_metadata(match),
                "zero_result_diagnostics_required": True,
                "live_readiness_gate": readiness_gate,
                "can_claim_live_ready": readiness_gate["passed"] if readiness_gate["required"] else live_ready is True,
                "collection_status": reliability,
                "collection_status_reason": _collection_status_reason(status, reliability, quality, match),
                "can_claim_collecting": reliability == "collecting",
                "quality_evidence": _quality_evidence(quality),
                "quality_summary": _quality_summary(quality),
                "source_health": source_health,
                "operator_diagnostics": _coverage_diagnostics(source, status, reliability, quality, match, readiness_gate),
                "next_action": _next_action(source, status, reliability, quality, readiness_gate),
            }
        )

    return {
        "schema": "crawler_source_coverage.v1",
        "total_required": len(REQUIRED_ONE_SHOT_SOURCES),
        "registered_count": registered_count,
        "collecting_count": collecting_count,
        "registered_not_collecting_count": max(0, registered_count - collecting_count),
        "missing_count": len(REQUIRED_ONE_SHOT_SOURCES) - registered_count,
        "missing_by_group": missing_by_group,
        "collection_claim_policy": (
            "A source is collecting only when registered quality evidence reports status=collecting, live_ready is not false, "
            "and any required live_readiness_gate has passed. Marketplace skeletons additionally require the fixture "
            "contract plus bounded diagnostics evidence before any live_ready=true or collecting claim. "
            "registered_unverified means the plugin exists but live collection reliability has not been proven."
        ),
        "source_health_dashboard": summarize_source_health_rows(rows),
        "sources": rows,
    }


def _find_plugin(aliases: list[str], plugins_by_name: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for alias in aliases:
        match = plugins_by_name.get(str(alias).lower())
        if match:
            return match
    return None


def _find_quality(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    quality_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    keys = [source["source_id"], *source["plugin_aliases"]]
    if match:
        keys.append(str(match.get("registered_name", "")))
    for key in keys:
        quality = quality_by_source.get(str(key).lower()) or quality_by_source.get(str(key))
        if quality:
            return quality
    return None


def _find_health_baseline(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    health_baseline_by_source: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    keys = [source["source_id"], *source["plugin_aliases"]]
    if match:
        keys.append(str(match.get("registered_name", "")))
    for key in keys:
        baseline = health_baseline_by_source.get(str(key).lower()) or health_baseline_by_source.get(str(key))
        if baseline:
            return baseline
    return None


def _quality_summary(quality: dict[str, Any] | None) -> dict[str, Any] | None:
    if not quality:
        return None
    summary = quality.get("quality_summary") or {}
    return {
        "status": summary.get("status"),
        "score": quality.get("score"),
        "item_counts": quality.get("item_counts"),
        "alerts": quality.get("alerts", []),
        "zero_result_stage": summary.get("zero_result_stage"),
        "critical_field_coverage": summary.get("critical_field_coverage"),
        "low_critical_fields": summary.get("low_critical_fields", []),
        "next_actions": summary.get("next_actions", []) or quality.get("next_actions", []),
    }


def _registration_metadata(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match:
        return None
    config = match.get("config") or {}
    return {
        "live_ready": config.get("live_ready"),
        "source_group": config.get("source_group") or config.get("category"),
        "parser_contract": config.get("parser_contract"),
        "fixture_contract": config.get("fixture_contract"),
        "live_readiness": config.get("live_readiness"),
        "notes": config.get("notes"),
    }


def _quality_evidence(quality: dict[str, Any] | None) -> dict[str, Any]:
    if not quality:
        return {
            "has_quality_evidence": False,
            "evidence_type": None,
            "dry_run_safe": None,
            "counts": None,
            "zero_result_stage": None,
            "diagnostic_codes": [],
        }
    zero = quality.get("zero_result_diagnostic") or {}
    fetch = quality.get("fetch") or {}
    return {
        "has_quality_evidence": True,
        "evidence_type": fetch.get("strategy_used") or "quality_summary",
        "dry_run_safe": zero.get("dry_run_safe", True),
        "counts": {
            "source_raw": (quality.get("item_counts") or {}).get("source_raw"),
            "parsed": (quality.get("item_counts") or {}).get("parsed"),
            "valid": (quality.get("item_counts") or {}).get("valid"),
            "invalid_or_dropped": (quality.get("item_counts") or {}).get("invalid_or_dropped"),
            "duplicates_after_validation": (quality.get("item_counts") or {}).get("duplicates_after_validation"),
        },
        "zero_result_stage": zero.get("stage"),
        "diagnostic_codes": [diag.get("code") for diag in quality.get("operator_diagnostics", []) if diag.get("code")],
    }


def _live_readiness_gate(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    quality: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return live-readiness metadata without probing live sites."""
    required = source.get("group") == "marketplace"
    config = ((match or {}).get("config") or {}) if match else {}
    live_readiness = config.get("live_readiness") or {}
    if not required:
        return {
            "required": False,
            "passed": config.get("live_ready") is True,
            "status": live_readiness.get("status"),
            "reasons": [],
            "required_evidence": [],
            "bounded_diagnostics": live_readiness.get("bounded_diagnostics") or {},
            "operator_approval": live_readiness.get("operator_approval") or {},
        }

    bounded = live_readiness.get("bounded_diagnostics") or {}
    run_limits = bounded.get("run_limits") or {}
    approval = live_readiness.get("operator_approval") or {}
    reasons: list[str] = []

    if config.get("parser_contract") != MARKETPLACE_PARSER_CONTRACT:
        reasons.append("parser_contract_missing")
    if config.get("fixture_contract") != MARKETPLACE_FIXTURE_CONTRACT:
        reasons.append("fixture_contract_missing")
    if live_readiness.get("fixture_contract_status") not in {"passed", "verified"}:
        reasons.append("fixture_contract_not_passed")
    if bounded.get("status") not in {"passed", "verified"}:
        reasons.append("bounded_live_diagnostics_missing")
    if not bounded.get("evidence_id"):
        reasons.append("bounded_evidence_id_missing")
    if not bounded.get("captured_at"):
        reasons.append("bounded_capture_timestamp_missing")
    if not all(run_limits.get(key) for key in ("max_requests", "max_pages", "timeout_seconds")):
        reasons.append("bounded_run_limits_missing")
    if approval.get("status") not in {"approved", "verified"}:
        reasons.append("operator_approval_missing")
    if not quality:
        reasons.append("quality_evidence_missing")
    elif (quality.get("quality_summary") or {}).get("status") != "collecting":
        reasons.append("quality_not_collecting")

    return {
        "required": True,
        "passed": not reasons,
        "status": "passed" if not reasons else "blocked",
        "reasons": reasons,
        "required_evidence": MARKETPLACE_REQUIRED_READINESS_EVIDENCE,
        "fixture_contract": config.get("fixture_contract"),
        "parser_contract": config.get("parser_contract"),
        "bounded_diagnostics": bounded,
        "operator_approval": approval,
        "safe_db_mutation_allowed": False,
        "downstream_flow": {
            "current_stage": "live_ready" if not reasons else "fixture_diagnostics_only",
            "next_stage": "no_db_ai_review" if not reasons else "saved_fixture_diagnostics",
            "db_mutation_allowed": False,
        },
        "operator_next_actions": MARKETPLACE_OPERATOR_NEXT_ACTIONS,
    }


def _collection_reliability(
    status: str,
    quality: dict[str, Any] | None,
    live_ready: bool | None = True,
    readiness_gate: dict[str, Any] | None = None,
) -> str:
    if status != "registered":
        return "missing"
    if (readiness_gate or {}).get("required") and not (readiness_gate or {}).get("passed"):
        return "registered_unverified"
    if live_ready is False:
        return "registered_unverified"
    if not quality:
        return "registered_unverified"
    return (quality.get("quality_summary") or {}).get("status") or "registered_unverified"


def _collection_status_reason(
    status: str,
    reliability: str,
    quality: dict[str, Any] | None,
    match: dict[str, Any] | None,
) -> str:
    if status == "missing":
        return "Required source has no registered crawler plugin."
    gate = _live_readiness_gate({"group": ((match or {}).get("config") or {}).get("source_group")}, match, quality)
    if gate.get("required") and not gate.get("passed"):
        return (
            "Marketplace skeleton is fixture-only/registered_unverified. A live-ready or collecting claim requires "
            "the fixture contract, bounded live diagnostics with run limits, quality evidence, and operator approval."
        )
    if not quality:
        live_ready = ((match or {}).get("config") or {}).get("live_ready")
        if live_ready is False:
            return (
                "Crawler plugin is registered with live_ready=false; saved fixtures can prove parser shape, but this "
                "is not collecting evidence and remains registered_unverified until bounded live diagnostics are "
                "explicitly approved."
            )
        return "Crawler plugin is registered, but no dry-run/mock quality evidence was provided."
    if ((match or {}).get("config") or {}).get("live_ready") is False:
        return (
            "Saved-fixture quality evidence exists, but live_ready=false prevents a collecting claim until bounded live "
            "diagnostics are explicitly approved."
        )
    if reliability == "collecting":
        return "Dry-run/mock quality evidence has valid rows and required critical fields are covered."
    return "Dry-run/mock quality evidence exists but reports diagnostics that prevent a collecting claim."


def _coverage_diagnostics(
    source: dict[str, Any],
    status: str,
    reliability: str,
    quality: dict[str, Any] | None,
    match: dict[str, Any] | None = None,
    readiness_gate: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if status == "missing":
        return [
            {
                "code": "crawler_not_registered",
                "severity": "error",
                "message": f"{source['source_id']} is required for {source['required_for']} but has no registered plugin.",
                "next_action": _next_action(source, status, reliability, quality),
            }
        ]
    gate_diagnostics = _readiness_gate_diagnostics(source, readiness_gate)
    if not quality:
        diagnostics = [
            {
                "code": "dry_run_quality_missing",
                "severity": "warning",
                "message": f"{source['source_id']} is registered but has no dry-run/mock quality summary.",
                "next_action": _next_action(source, status, reliability, quality),
            }
        ]
        if ((match or {}).get("config") or {}).get("live_ready") is False:
            diagnostics.insert(
                0,
                {
                    "code": "live_collection_disabled",
                    "severity": "warning",
                    "message": (
                        f"{source['source_id']} is registered, but live collection is disabled; registration is not "
                        "collection evidence."
                    ),
                    "next_action": (
                        "Run a saved-fixture dry-run and review source_raw, parsed, valid, validation drops, critical "
                        "field coverage, and duplicate diagnostics before asking an admin to enable live collection."
                    ),
                },
            )
        return [*gate_diagnostics, *diagnostics]
    diagnostics = list(quality.get("operator_diagnostics") or [])
    if ((match or {}).get("config") or {}).get("live_ready") is False:
        diagnostics.insert(
            0,
            {
                "code": "live_ready_false_registered_unverified",
                "severity": "warning",
                "message": (
                    f"{source['source_id']} has saved-fixture evidence, but live_ready=false; do not treat this "
                    "skeleton as live production collection."
                ),
                "next_action": (
                    "Keep the source registered_unverified until bounded live diagnostics pass and an admin explicitly "
                    "changes live_ready."
                ),
            },
        )
    return [*gate_diagnostics, *diagnostics]


def _readiness_gate_diagnostics(
    source: dict[str, Any],
    readiness_gate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not readiness_gate or not readiness_gate.get("required") or readiness_gate.get("passed"):
        return []
    reasons = readiness_gate.get("reasons") or []
    return [
        {
            "code": "marketplace_live_readiness_gate_blocked",
            "severity": "warning",
            "message": (
                f"{source['source_id']} remains skeleton/fixture-only; live_ready=true or collecting claims are blocked "
                f"until required evidence is present: {', '.join(reasons)}."
            ),
            "next_action": (
                "Pass the marketplace fixture contract, attach bounded diagnostics with max_requests/max_pages/"
                "timeout_seconds and evidence_id, provide collecting quality evidence, complete no-DB AI review, "
                "then record operator approval before any safe DB mutation flow."
            ),
            "reasons": reasons,
            "required_evidence": readiness_gate.get("required_evidence", []),
            "operator_next_actions": readiness_gate.get("operator_next_actions", MARKETPLACE_OPERATOR_NEXT_ACTIONS),
            "safe_db_mutation_allowed": readiness_gate.get("safe_db_mutation_allowed", False),
        }
    ]


def _next_action(
    source: dict[str, Any],
    status: str,
    reliability: str = "registered_unverified",
    quality: dict[str, Any] | None = None,
    readiness_gate: dict[str, Any] | None = None,
) -> str:
    if status == "registered":
        if (readiness_gate or {}).get("required") and not (readiness_gate or {}).get("passed"):
            return (
                "Keep this marketplace crawler skeleton/fixture-only. Add or run saved-fixture dry-run diagnostics, "
                "then attach bounded live diagnostics with run limits, collecting quality evidence, and operator "
                "approval before enabling one-shot automation or live_ready=true; any later DB mutation must first "
                "go through no-DB AI review."
            )
        if reliability == "collecting":
            return "Keep parser drift fixtures and bounded diagnostics in CI; this registered crawler is currently collecting in dry-run/mock evidence."
        summary_actions = ((quality or {}).get("quality_summary") or {}).get("next_actions") or (quality or {}).get("next_actions")
        if summary_actions:
            return str(summary_actions[0])
        return (
            "Add or run saved-fixture dry-run diagnostics that report source_raw, parsed, valid, validation drops, "
            "critical field coverage, and parser drift before enabling one-shot automation."
        )
    return (
        f"Add a modular {source['source_id']} crawler plugin with parser tests, "
        "source metadata, per-stage counts, and zero-result diagnostics before one-shot coverage can be claimed."
    )
