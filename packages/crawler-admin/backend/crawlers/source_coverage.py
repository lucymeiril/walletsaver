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
        "source_id": "cocodalin",
        "display_name": "코코달인 (코스트코)",
        "group": "mart",
        "required_for": "mart_connector_inventory",
        "plugin_aliases": ["cocodalin"],
    },
    {
        "source_id": "coupang",
        "display_name": "쿠팡",
        "group": "marketplace",
        "required_for": "commerce_marketplace",
        "plugin_aliases": ["coupang"],
    },
    {
        "source_id": "naver_store",
        "display_name": "네이버스토어",
        "group": "marketplace",
        "required_for": "commerce_marketplace",
        "plugin_aliases": ["naver_store", "naverstore", "smartstore", "naver_smartstore"],
    },
    {
        "source_id": "gmarket",
        "display_name": "G마켓",
        "group": "marketplace",
        "required_for": "commerce_marketplace",
        "plugin_aliases": ["gmarket", "g마켓"],
    },
    {
        "source_id": "11st",
        "display_name": "11번가",
        "group": "marketplace",
        "required_for": "commerce_marketplace",
        "plugin_aliases": ["11st", "11번가", "elevenst"],
    },
    {
        "source_id": "aliexpress",
        "display_name": "알리익스프레스",
        "group": "marketplace",
        "required_for": "commerce_marketplace",
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
        "source_id": "ppomppu",
        "display_name": "뽐뿌",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["ppomppu", "뽐뿌"],
    },
    {
        "source_id": "fmkorea",
        "display_name": "FM코리아",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["fmkorea", "FM코리아"],
    },
    {
        "source_id": "clien",
        "display_name": "클리앙",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["clien", "클리앙"],
    },
    {
        "source_id": "arca_hotdeal",
        "display_name": "아카라이브 핫딜",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["arca", "아카라이브"],
    },
    {
        "source_id": "quasarzone",
        "display_name": "퀘이사존",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["quasarzone", "퀘이사존"],
    },
    {
        "source_id": "cocodal",
        "display_name": "코코달",
        "group": "hotdeal",
        "required_for": "community_hotdeal",
        "plugin_aliases": ["cocodal", "코코달"],
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
        "required_for": "fuel_price",
        "plugin_aliases": ["opinet"],
        "external_dependency": "opinet_api_key_or_public_site",
    },
    {
        "source_id": "baemin",
        "display_name": "배달의민족",
        "group": "delivery",
        "required_for": "delivery_location",
        "plugin_aliases": ["baemin"],
        "external_dependency": "location_or_service_state",
    },
    {
        "source_id": "coupangeats",
        "display_name": "쿠팡이츠",
        "group": "delivery",
        "required_for": "delivery_location",
        "plugin_aliases": ["coupangeats"],
        "external_dependency": "location_or_service_state",
    },
    {
        "source_id": "yogiyo",
        "display_name": "요기요",
        "group": "delivery",
        "required_for": "delivery_location",
        "plugin_aliases": ["yogiyo"],
        "external_dependency": "location_or_service_state",
    },
    {
        "source_id": "naver_place",
        "display_name": "네이버 플레이스",
        "group": "location",
        "required_for": "delivery_location",
        "plugin_aliases": ["naver_place"],
        "external_dependency": "location_or_service_state",
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
MART3_REQUIRED_READINESS_EVIDENCE = [
    "saved_fixture_or_raw_snapshot_passed",
    "source_raw_parsed_valid_counts_recorded",
    "critical_field_coverage_recorded",
    "source_url_or_detail_url_coverage_recorded",
    "image_url_coverage_recorded",
    "period_coverage_recorded",
    "unit_coverage_recorded",
    "category_hint_coverage_recorded",
    "bounded_live_diagnostics_with_run_limits",
    "operator_approval_before_live_ready_or_db_handoff",
]
MART3_OPERATOR_NEXT_ACTIONS = [
    "Attach saved fixture/raw diagnostics for each mart showing source_raw, parsed, valid, validation-drop, duplicate, and critical-field evidence.",
    "Record source URL/detail URL, image, period, unit, and category-hint coverage; gaps must stay visible instead of being treated as live readiness.",
    "Run an explicitly approved bounded no-DB live diagnostic with max_requests/max_pages/timeout_seconds, evidence_id, and captured_at before live_ready=true.",
    "Record operator approval only after bounded diagnostics pass; fixture diagnostics alone cannot enable one-shot AI/DB handoff.",
]
MART3_EVIDENCE_FIELD_KEYS = [
    "name",
    "sale_price",
    "detail_url",
    "source_url",
    "image_url",
    "period",
    "unit",
    "category_hint",
]
REGISTERED_UNVERIFIED_REQUIRED_READINESS_EVIDENCE = [
    "saved_fixture_or_bounded_quality_summary",
    "source_raw_parsed_valid_counts_recorded",
    "critical_field_coverage_recorded",
    "bounded_diagnostics_required_before_live_ready",
    "operator_approval_before_live_ready_or_collecting_claim",
]
EXTERNAL_BLOCKER_REQUIRED_READINESS_EVIDENCE = [
    "external_key_service_or_location_prerequisite_recorded",
    "saved_fixture_or_raw_snapshot_passed",
    "bounded_diagnostic_run_limits_recorded",
    "operator_approval_after_service_prerequisite_verified",
]
FIXTURE_PASSING_REQUIRED_READINESS_EVIDENCE = [
    "bounded_live_diagnostics_passed",
    "bounded_run_limits_recorded",
    "operator_approval_recorded",
    "live_ready_true_only_after_bounded_evidence",
]
BOUNDED_DIAGNOSTIC_READY_REQUIRED_READINESS_EVIDENCE = [
    "operator_approval_recorded",
    "live_ready_true_recorded_for_live_service_claim",
    "no_db_ai_review_completed_before_db_mutation",
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
    gap_classification_counts: dict[str, int] = {}
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
        source_readiness = _source_readiness_dimension(source, match, status, reliability, quality, readiness_gate, source_health)
        mart3_readiness = _mart3_source_collection_readiness(source, match, quality, source_health, readiness_gate)
        gap_classification = _gap_classification(source, status, reliability, quality, match, source_readiness)
        completion_gate = _source_completion_gate(
            source,
            status,
            reliability,
            quality,
            match,
            readiness_gate,
            source_readiness,
            gap_classification,
        )
        gap_classification_counts[gap_classification["classification"]] = (
            gap_classification_counts.get(gap_classification["classification"], 0) + 1
        )
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
                "readiness_status": _readiness_status(source, status, reliability, quality, readiness_gate, match, source_health),
                "can_claim_collecting": reliability == "collecting",
                "quality_evidence": _quality_evidence(quality),
                "quality_summary": _quality_summary(quality),
                "source_health": source_health,
                "source_readiness": source_readiness,
                "source_completion_gate": completion_gate,
                "mart3_source_collection_readiness": mart3_readiness,
                "gap_classification": gap_classification["classification"],
                "gap_classification_reason": gap_classification["reason"],
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
        "gap_classification_counts": gap_classification_counts,
        "collection_claim_policy": (
            "A source is collecting only when registered quality evidence reports status=collecting, live_ready is not false, "
            "and any required live_readiness_gate has passed. Marketplace skeletons additionally require the fixture "
            "contract plus bounded diagnostics evidence before any live_ready=true or collecting claim. "
            "registered_unverified means the plugin exists but live collection reliability has not been proven."
        ),
        "source_health_dashboard": summarize_source_health_rows(rows),
        "sources": rows,
    }


def _gap_classification(
    source: dict[str, Any],
    status: str,
    reliability: str,
    quality: dict[str, Any] | None,
    match: dict[str, Any] | None,
    source_readiness: dict[str, Any],
) -> dict[str, str]:
    """Map a source to the operator-facing gap class without probing a service."""
    if status != "registered":
        return {
            "classification": "missing",
            "reason": "No registered crawler plugin matched this source id or alias.",
        }

    config = (match or {}).get("config") or {}
    if source_readiness.get("stage") == "live_approved" or reliability == "collecting":
        return {
            "classification": "implemented_live_bounded",
            "reason": "Registered connector has bounded quality evidence that currently permits a collecting claim.",
        }
    if source_readiness.get("fixture_passed"):
        return {
            "classification": "fixture_passing",
            "reason": "Saved fixture or bounded diagnostic evidence passes parser/field baselines, but live collection is not approved.",
        }
    if _is_skeleton_source(config):
        return {
            "classification": "skeleton_only",
            "reason": "Registered connector is a skeleton/fixture contract and has no approved live collection evidence.",
        }
    if _is_external_service_blocked(source, config):
        return {
            "classification": "blocked_by_external_key/service",
            "reason": "Registered connector depends on external service state, location context, browser runtime, or configured key evidence.",
        }
    if not quality:
        return {
            "classification": "registered_unverified",
            "reason": "Registered connector exists, but no saved fixture or bounded quality summary was attached.",
        }
    return {
        "classification": "registered_unverified",
        "reason": "Quality evidence exists but does not currently permit a collecting claim.",
    }


def _is_skeleton_source(config: dict[str, Any]) -> bool:
    return bool(
        config.get("parser_contract") == MARKETPLACE_PARSER_CONTRACT
        or config.get("fixture_contract") == MARKETPLACE_FIXTURE_CONTRACT
        or config.get("difficulty") == "skeleton"
    )


def _is_external_service_blocked(source: dict[str, Any], config: dict[str, Any]) -> bool:
    if source.get("external_dependency"):
        return True
    notes = " ".join(
        str(config.get(key) or "")
        for key in ("notes", "note", "description")
    ).lower()
    return any(
        marker in notes
        for marker in (
            "api key",
            "api 키",
            "인증",
            "주소 설정",
            "location",
            "playwright 필수",
            "selenium/playwright",
            "spa",
            "접속 불가",
            "inactive",
        )
    )


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
            "critical_field_coverage": None,
            "field_coverage": None,
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
        "critical_field_coverage": (quality.get("quality_summary") or {}).get("critical_field_coverage") or {},
        "field_coverage": quality.get("coverage") or {},
        "zero_result_stage": zero.get("stage"),
        "diagnostic_codes": [diag.get("code") for diag in quality.get("operator_diagnostics", []) if diag.get("code")],
    }


def _source_readiness_dimension(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    status: str,
    reliability: str,
    quality: dict[str, Any] | None,
    readiness_gate: dict[str, Any],
    source_health: dict[str, Any],
) -> dict[str, Any]:
    """Classify source readiness from registry metadata and bounded evidence only."""
    completeness = source_health.get("completeness") or {}
    count_drop = source_health.get("count_drop") or {}
    field_dashboard = source_health.get("field_coverage_dashboard") or {}
    bounded = readiness_gate.get("bounded_diagnostics") or {}
    run_limits = bounded.get("run_limits") or {}
    quality_status = (quality.get("quality_summary") or {}).get("status") if quality else None
    config = ((match or {}).get("config") or {}) if match else {}
    metadata_status = str((config.get("live_readiness") or {}).get("status") or config.get("connector_status") or "")

    blockers: list[str] = []
    if status != "registered":
        blockers.append("crawler_not_registered")
    if not quality:
        blockers.append("quality_evidence_missing")
    if completeness.get("status") == "baseline_missing":
        blockers.append("completeness_baseline_missing")
    if completeness.get("status") == "below_baseline":
        blockers.extend(f"below_baseline:{name}" for name in completeness.get("below_expected_counts", []))
    if count_drop.get("status") == "drop_detected":
        blockers.extend(f"count_drop:{alert.get('metric')}" for alert in count_drop.get("alerts", []))
    if field_dashboard.get("status") == "low_coverage":
        blockers.extend(
            f"critical_field_low:{field.get('field')}"
            for field in field_dashboard.get("fields", [])
            if field.get("status") == "low"
        )
    if quality and quality_status != "collecting":
        blockers.append(f"quality_status:{quality_status}")

    fixture_passed = bool(
        quality
        and quality_status == "collecting"
        and completeness.get("status") == "meets_baseline"
        and count_drop.get("status") in {"within_baseline", None}
        and field_dashboard.get("status") == "ok"
    )
    bounded_ready = bool(
        fixture_passed
        and readiness_gate.get("required")
        and bounded.get("status") in {"passed", "verified"}
        and bounded.get("evidence_id")
        and bounded.get("captured_at")
        and all(run_limits.get(key) for key in ("max_requests", "max_pages", "timeout_seconds"))
    )

    blocked_by_external = bool(
        status == "registered"
        and (
            metadata_status in {"blocked_by_key_or_service", "blocked-by-key/service"}
            or (not quality and _is_external_service_blocked(source, config))
        )
    )
    if status != "registered":
        stage = "registered_only"
    elif blocked_by_external and not fixture_passed:
        stage = "blocked_by_external_key/service"
    elif not quality and _is_skeleton_source(config):
        stage = "skeleton_only"
    elif not quality:
        stage = "registered_unverified"
    elif not fixture_passed:
        stage = "registered_only"
    elif readiness_gate.get("passed"):
        stage = "live_approved"
    elif bounded_ready:
        stage = "bounded_diagnostic_ready"
    else:
        stage = "fixture_passing"

    if readiness_gate.get("required") and not readiness_gate.get("passed"):
        blockers.extend(f"live_readiness_gate:{reason}" for reason in readiness_gate.get("reasons", []))

    return {
        "stage": stage,
        "status": _readiness_status_from_stage(stage, status, reliability, match=None, quality=quality),
        "fixture_passed": fixture_passed,
        "bounded_diagnostic_ready": bounded_ready,
        "live_approved": stage == "live_approved",
        "evidence_basis": "registry_metadata_and_saved_fixture_or_bounded_diagnostic_summary",
        "live_network_default": "disabled",
        "claim_policy": (
            "Readiness is derived from registry metadata, saved fixtures, and bounded diagnostic summaries only; "
            "it does not assert that live collection ran."
        ),
        "blockers": list(dict.fromkeys(blockers)),
        "completeness_status": completeness.get("status"),
        "count_drop_status": count_drop.get("status"),
        "field_coverage_status": field_dashboard.get("status"),
    }


def _source_completion_gate(
    source: dict[str, Any],
    status: str,
    reliability: str,
    quality: dict[str, Any] | None,
    match: dict[str, Any] | None,
    readiness_gate: dict[str, Any],
    source_readiness: dict[str, Any],
    gap_classification: dict[str, str],
) -> dict[str, Any]:
    """Make every non-live source state an executable completion gate."""
    config = ((match or {}).get("config") or {}) if match else {}
    live_readiness = config.get("live_readiness") or {}
    stage = source_readiness.get("stage")
    classification = gap_classification["classification"]
    bounded = live_readiness.get("bounded_diagnostics") or readiness_gate.get("bounded_diagnostics") or {}
    run_limits = bounded.get("run_limits") or {}
    approval = live_readiness.get("operator_approval") or readiness_gate.get("operator_approval") or {}
    no_db_ai_review = live_readiness.get("no_db_ai_review") or config.get("no_db_ai_review") or {}
    no_db_ai_review_completed = no_db_ai_review.get("status") in {"completed", "passed", "verified"}

    if stage == "blocked_by_external_key/service" or classification == "blocked_by_external_key/service":
        required_evidence = EXTERNAL_BLOCKER_REQUIRED_READINESS_EVIDENCE
        operator_requirements = [
            "Record the external key, provider service, browser, address, or location prerequisite that unblocks the source.",
            "Attach saved fixture/raw snapshot evidence proving source_raw, parsed, valid, and critical-field counts.",
            "Run bounded diagnostics with max_requests/max_pages/timeout_seconds before any live-ready claim.",
            "Record operator approval after the prerequisite and bounded evidence are verified.",
        ]
        missing = ["external_key_service_or_location_prerequisite_missing"]
    elif stage == "skeleton_only" or classification == "skeleton_only":
        required_evidence = MARKETPLACE_REQUIRED_READINESS_EVIDENCE
        operator_requirements = MARKETPLACE_OPERATOR_NEXT_ACTIONS
        missing = list(readiness_gate.get("reasons") or ["fixture_contract_or_bounded_diagnostics_missing"])
    elif stage == "bounded_diagnostic_ready":
        required_evidence = BOUNDED_DIAGNOSTIC_READY_REQUIRED_READINESS_EVIDENCE
        operator_requirements = [
            "Complete operator approval for the bounded diagnostic evidence.",
            "Keep DB mutation disabled until no-DB AI review is complete.",
        ]
        missing = []
    elif stage == "live_approved":
        required_evidence = BOUNDED_DIAGNOSTIC_READY_REQUIRED_READINESS_EVIDENCE
        operator_requirements = [
            "Keep collecting evidence current and rerun no-DB AI review before any DB mutation.",
            "Only claim source completion when no-DB AI review evidence is recorded for this bounded source snapshot.",
        ]
        missing = []
    elif stage == "fixture_passing" or classification == "fixture_passing":
        if source.get("required_for") == "mart3":
            required_evidence = MART3_REQUIRED_READINESS_EVIDENCE
            operator_requirements = MART3_OPERATOR_NEXT_ACTIONS
        else:
            required_evidence = FIXTURE_PASSING_REQUIRED_READINESS_EVIDENCE
            operator_requirements = [
                "Keep the fixture parser contract in CI, but do not call it live-ready.",
                "Attach bounded live diagnostics with evidence_id, captured_at, and run limits.",
                "Record explicit operator approval before live_ready=true, collecting, or one-shot completion claims.",
            ]
        missing = []
    elif stage == "registered_unverified" or classification == "registered_unverified":
        required_evidence = REGISTERED_UNVERIFIED_REQUIRED_READINESS_EVIDENCE
        operator_requirements = [
            "Attach a saved fixture or bounded quality summary before claiming implementation completion.",
            "Record source_raw, parsed, valid, invalid/drop, duplicate, and critical-field evidence.",
            "Require bounded diagnostics and operator approval before any live-ready or collecting claim.",
        ]
        missing = ["quality_evidence_missing"] if not quality else []
    else:
        required_evidence = ["registered_plugin", "quality_evidence_collecting", "operator_claim_review"]
        operator_requirements = ["Maintain collecting evidence and parser drift fixtures in CI."]
        missing = []

    if not quality and "quality_evidence_missing" not in missing and classification != "missing":
        missing.append("quality_evidence_missing")
    if stage in {"fixture_passing", "bounded_diagnostic_ready"}:
        if bounded.get("status") not in {"passed", "verified"}:
            missing.append("bounded_live_diagnostics_missing")
        if not bounded.get("evidence_id"):
            missing.append("bounded_evidence_id_missing")
        if not bounded.get("captured_at"):
            missing.append("bounded_capture_timestamp_missing")
        if not all(run_limits.get(key) for key in ("max_requests", "max_pages", "timeout_seconds")):
            missing.append("bounded_run_limits_missing")
        if approval.get("status") not in {"approved", "verified"}:
            missing.append("operator_approval_missing")
    if stage in {"bounded_diagnostic_ready", "live_approved"} and not no_db_ai_review_completed:
        missing.append("no_db_ai_review_missing")
    missing.extend(source_readiness.get("blockers") or [])
    if readiness_gate.get("required") and not readiness_gate.get("passed"):
        missing.extend(f"live_readiness_gate:{reason}" for reason in readiness_gate.get("reasons", []))

    passed = bool(
        status == "registered"
        and reliability == "collecting"
        and stage == "live_approved"
        and not list(dict.fromkeys(missing))
    )
    return {
        "schema": "source_completion_gate.v1",
        "stage": stage,
        "classification": classification,
        "passed": passed,
        "blocks_completion_claim": not passed,
        "can_claim_source_complete": passed,
        "can_claim_live_ready": passed,
        "can_claim_collecting": passed,
        "safe_db_mutation_allowed": False,
        "required_evidence": required_evidence,
        "missing_evidence": list(dict.fromkeys(missing)),
        "operator_requirements": operator_requirements,
        "executable_check": (
            "build_source_coverage(...)[source]['source_completion_gate']['passed'] must be true before "
            "claiming source completion."
        ),
    }


def _mart3_source_collection_readiness(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    quality: dict[str, Any] | None,
    source_health: dict[str, Any],
    readiness_gate: dict[str, Any],
) -> dict[str, Any] | None:
    if source.get("required_for") != "mart3":
        return None

    config = ((match or {}).get("config") or {}) if match else {}
    completeness = source_health.get("completeness") or {}
    field_dashboard = source_health.get("field_coverage_dashboard") or {}
    bounded = (config.get("live_readiness") or {}).get("bounded_diagnostics") or {}
    run_limits = bounded.get("run_limits") or {}
    approval = (config.get("live_readiness") or {}).get("operator_approval") or {}
    quality_status = (quality.get("quality_summary") or {}).get("status") if quality else None
    field_coverage = (quality or {}).get("coverage") or {}
    critical_field_coverage = (quality or {}).get("quality_summary", {}).get("critical_field_coverage") or {}

    blockers: list[str] = []
    if not match:
        blockers.append("crawler_not_registered")
    if not quality:
        blockers.append("source_collection_diagnostics_missing")
    if quality and quality_status != "collecting":
        blockers.append(f"quality_status:{quality_status}")
    if completeness.get("status") != "meets_baseline":
        blockers.append(f"completeness:{completeness.get('status')}")
    if field_dashboard.get("status") != "ok":
        blockers.append(f"field_coverage:{field_dashboard.get('status')}")
    if config.get("live_ready") is not True:
        blockers.append("live_ready_not_approved")
    if bounded.get("status") not in {"passed", "verified"}:
        blockers.append("bounded_live_diagnostics_missing")
    if not bounded.get("evidence_id"):
        blockers.append("bounded_evidence_id_missing")
    if not bounded.get("captured_at"):
        blockers.append("bounded_capture_timestamp_missing")
    if not all(run_limits.get(key) for key in ("max_requests", "max_pages", "timeout_seconds")):
        blockers.append("bounded_run_limits_missing")
    if approval.get("status") not in {"approved", "verified"}:
        blockers.append("operator_approval_missing")

    fixture_passed = bool(
        quality
        and quality_status == "collecting"
        and completeness.get("status") == "meets_baseline"
        and field_dashboard.get("status") == "ok"
    )
    bounded_ready = bool(
        fixture_passed
        and bounded.get("status") in {"passed", "verified"}
        and bounded.get("evidence_id")
        and bounded.get("captured_at")
        and all(run_limits.get(key) for key in ("max_requests", "max_pages", "timeout_seconds"))
    )
    live_ready = fixture_passed and not blockers
    if live_ready:
        status = "live_ready"
        next_action = "Monitor source collection diagnostics and freshness before one-shot AI/DB handoff."
    elif bounded_ready:
        status = "bounded_diagnostic_ready"
        next_action = (
            "Bounded diagnostics evidence exists; record operator approval and live_ready=true before any live service "
            "readiness or one-shot AI/DB handoff claim."
        )
    elif fixture_passed:
        status = "fixture_diagnostics_ready"
        next_action = (
            "Run explicitly approved bounded live source collection diagnostics with recorded run limits before "
            "claiming live service readiness or enabling one-shot AI/DB handoff."
        )
    else:
        status = "source_collection_blocked"
        next_action = (
            "Attach source fixture/raw evidence and repair parser diagnostics until source_raw, parsed, valid, "
            "and critical fields pass."
        )

    return {
        "schema": "mart3_source_collection_readiness.v1",
        "status": status,
        "fixture_diagnostics_passed": fixture_passed,
        "bounded_diagnostic_ready": bounded_ready,
        "live_ready": live_ready,
        "live_service_ready": live_ready,
        "required_evidence": MART3_REQUIRED_READINESS_EVIDENCE,
        "required_evidence_fields": MART3_EVIDENCE_FIELD_KEYS,
        "blockers": list(dict.fromkeys(blockers)),
        "quality_status": quality_status,
        "counts": completeness.get("counts"),
        "critical_field_coverage": critical_field_coverage,
        "field_coverage": {key: field_coverage.get(key, 0) for key in MART3_EVIDENCE_FIELD_KEYS},
        "field_coverage_status": field_dashboard.get("status"),
        "live_network_default": "disabled",
        "claim_policy": (
            "Mart3 source collection readiness is diagnostics-only unless bounded live diagnostics and operator "
            "approval are recorded; fixture passing does not equal live-service readiness."
        ),
        "next_action": next_action,
        "live_readiness_gate": readiness_gate,
    }


def _readiness_status(
    source: dict[str, Any],
    status: str,
    reliability: str,
    quality: dict[str, Any] | None,
    readiness_gate: dict[str, Any],
    match: dict[str, Any] | None,
    source_health: dict[str, Any],
) -> str:
    """Normalize operator-facing connector readiness into a compact state."""
    if status != "registered":
        return "missing"
    config = (match or {}).get("config") or {}
    live_readiness = config.get("live_readiness") or {}
    metadata_status = str(live_readiness.get("status") or config.get("connector_status") or "")
    if metadata_status in {"blocked_by_key_or_service", "blocked-by-key/service"}:
        return "blocked-by-key/service"
    if not quality and _is_external_service_blocked(source, config):
        return "blocked-by-key/service"
    if source.get("group") == "marketplace" and readiness_gate.get("required") and not readiness_gate.get("passed"):
        return "skeleton-only"
    if reliability == "collecting":
        bounded = readiness_gate.get("bounded_diagnostics") or {}
        if bounded.get("status") in {"passed", "verified"}:
            return "live-bounded"
        return "fixture-passing" if quality else "registered-unverified"
    completeness = (source_health.get("completeness") or {}).get("status")
    fields = (source_health.get("field_coverage_dashboard") or {}).get("status")
    if quality and completeness == "meets_baseline" and fields == "ok":
        return "fixture-passing"
    return "registered-unverified"


def _readiness_status_from_stage(
    stage: str,
    status: str,
    reliability: str,
    match: dict[str, Any] | None,
    quality: dict[str, Any] | None,
) -> str:
    if status != "registered":
        return "missing"
    if stage == "live_approved":
        return "live-bounded"
    if stage == "blocked_by_external_key/service":
        return "blocked-by-key/service"
    if stage == "skeleton_only":
        return "skeleton-only"
    if stage == "bounded_diagnostic_ready":
        return "bounded-diagnostic-ready"
    if stage == "fixture_passing":
        return "fixture-passing"
    if reliability == "collecting" and quality:
        return "fixture-passing"
    return "registered-unverified"


def _live_readiness_gate(
    source: dict[str, Any],
    match: dict[str, Any] | None,
    quality: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return live-readiness metadata without probing live sites."""
    config = ((match or {}).get("config") or {}) if match else {}
    live_readiness = config.get("live_readiness") or {}
    is_marketplace = source.get("group") == "marketplace"
    is_mart3 = source.get("required_for") == "mart3"
    required = is_marketplace or is_mart3
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

    if config.get("live_ready") is not True:
        reasons.append("live_ready_not_approved")
    if is_marketplace and config.get("parser_contract") != MARKETPLACE_PARSER_CONTRACT:
        reasons.append("parser_contract_missing")
    if is_marketplace and config.get("fixture_contract") != MARKETPLACE_FIXTURE_CONTRACT:
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
        "required_evidence": MARKETPLACE_REQUIRED_READINESS_EVIDENCE if is_marketplace else MART3_REQUIRED_READINESS_EVIDENCE,
        "fixture_contract": config.get("fixture_contract"),
        "parser_contract": config.get("parser_contract"),
        "bounded_diagnostics": bounded,
        "operator_approval": approval,
        "safe_db_mutation_allowed": False,
        "downstream_flow": {
            "current_stage": "live_ready" if not reasons else "fixture_diagnostics_only",
            "next_stage": "no_db_ai_review" if not reasons else ("saved_fixture_diagnostics" if is_marketplace else "bounded_live_diagnostics"),
            "db_mutation_allowed": False,
        },
        "operator_next_actions": MARKETPLACE_OPERATOR_NEXT_ACTIONS if is_marketplace else MART3_OPERATOR_NEXT_ACTIONS,
    }


def _collection_reliability(
    status: str,
    quality: dict[str, Any] | None,
    live_ready: bool | None = True,
    readiness_gate: dict[str, Any] | None = None,
) -> str:
    if status != "registered":
        return "missing"
    quality_status = (quality.get("quality_summary") or {}).get("status") if quality else None
    if quality_status and quality_status != "collecting":
        return quality_status
    if (readiness_gate or {}).get("required") and not (readiness_gate or {}).get("passed"):
        return "registered_unverified"
    if live_ready is False:
        return "registered_unverified"
    if not quality:
        return "registered_unverified"
    return quality_status or "registered_unverified"


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
    if source.get("required_for") == "mart3":
        return [
            {
                "code": "mart3_live_readiness_gate_blocked",
                "severity": "warning",
                "message": (
                    f"{source['source_id']} cannot claim mart3 live readiness until required evidence is present: "
                    f"{', '.join(reasons)}."
                ),
                "next_action": (
                    "Keep fixture diagnostics separate from live readiness. Attach bounded live diagnostics with "
                    "max_requests/max_pages/timeout_seconds, evidence_id, captured_at, source field coverage, and "
                    "operator approval before live_ready=true or one-shot AI/DB handoff."
                ),
                "reasons": reasons,
                "required_evidence": readiness_gate.get("required_evidence", []),
                "operator_next_actions": readiness_gate.get("operator_next_actions", MART3_OPERATOR_NEXT_ACTIONS),
                "safe_db_mutation_allowed": readiness_gate.get("safe_db_mutation_allowed", False),
            }
        ]
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
        summary_actions = ((quality or {}).get("quality_summary") or {}).get("next_actions") or (quality or {}).get("next_actions")
        if summary_actions:
            return str(summary_actions[0])
        if (readiness_gate or {}).get("required") and not (readiness_gate or {}).get("passed"):
            if source.get("required_for") == "mart3":
                return (
                    "Keep this mart crawler fixture_diagnostics_ready at most. Add or run saved-fixture diagnostics, "
                    "record source_raw/parsed/valid plus URL/image/period/unit/category coverage, then attach bounded "
                    "live diagnostics with run limits, evidence_id, captured_at, and operator approval before any "
                    "live_ready=true or one-shot AI/DB handoff claim."
                )
            return (
                "Keep this marketplace crawler skeleton/fixture-only. Add or run saved-fixture dry-run diagnostics, "
                "then attach bounded live diagnostics with run limits, collecting quality evidence, and operator "
                "approval before enabling one-shot automation or live_ready=true; any later DB mutation must first "
                "go through no-DB AI review."
            )
        if reliability == "collecting":
            return "Keep parser drift fixtures and bounded diagnostics in CI; this registered crawler is currently collecting in dry-run/mock evidence."
        return (
            "Add or run saved-fixture dry-run diagnostics that report source_raw, parsed, valid, validation drops, "
            "critical field coverage, and parser drift before enabling one-shot automation."
        )
    return (
        f"Add a modular {source['source_id']} crawler plugin with parser tests, "
        "source metadata, per-stage counts, and zero-result diagnostics before one-shot coverage can be claimed."
    )
