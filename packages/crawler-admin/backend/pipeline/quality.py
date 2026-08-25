"""Crawler run quality summaries for operator-facing reliability checks."""

from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import uuid4

CRITICAL_FIELD_THRESHOLDS: dict[str, float] = {
    "name": 1.0,
    "sale_price": 1.0,
    "detail_url": 0.8,
}

ZERO_RESULT_NEXT_ACTIONS: dict[str, str] = {
    "live_disabled_no_fixture": (
        "This crawler is registered but live network collection is disabled and no saved fixture/raw input was provided. "
        "Attach a recent approved fixture or raw_data sample, run the bounded dry-run again, and only ask an admin to "
        "enable live collection after that fixture produces valid rows with required fields."
    ),
    "fixture_or_raw_missing": (
        "Provide a saved fixture or raw_data sample for this bounded dry-run; without input there is no evidence that "
        "the source is empty or that parsing works. Re-run the dry-run with fixture input before changing crawler code."
    ),
    "source_zero_raw_rows": (
        "The run had input but found zero source candidate rows. Replay the saved/mock response and confirm it contains "
        "product cards or JSON product objects; then check request URL, query terms, headers, status/rate-limit handling, "
        "and source blocking before any live one-shot run."
    ),
    "parse_filtered_all_raw_rows": (
        "Source candidate rows exist but the parser emitted zero discount rows. Update the exact CSS selectors or JSON "
        "paths against the saved fixture, then add a parser drift regression fixture before enabling automation."
    ),
    "validation_rejected_all_rows": (
        "Parser output exists but every row was rejected. Inspect parser-to-model field mapping and validation/normalization "
        "rules for required name and price fields, then add a fixture proving at least one raw row validates."
    ),
    "zero_valid_items_unknown": (
        "Per-stage counts disagree, so do not guess. Inspect source errors, source_raw, parsed, valid, and validation-drop "
        "counters from this run to identify the failing stage before enabling automation."
    ),
}

DUPLICATE_HEAVY_NEXT_ACTION = (
    "Output is duplicate-heavy after validation. Compare duplicate keys (store/source, name/title, sale_price/price) "
    "in the fixture, fix parser pagination/card selectors or dedupe keys, and re-run until duplicates are under threshold."
)


def _next_action_for_stage(stage: str) -> str:
    return ZERO_RESULT_NEXT_ACTIONS.get(stage, ZERO_RESULT_NEXT_ACTIONS["zero_valid_items_unknown"])


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _ratio(count: int, total: int) -> float:
    return round(count / total, 3) if total else 0.0


def _discount_key(item: dict[str, Any]) -> tuple[Any, Any, Any]:
    return (
        item.get("store") or item.get("source") or "",
        item.get("name") or item.get("title") or "",
        item.get("sale_price") if item.get("sale_price") is not None else item.get("price"),
    )


def summarize_discount_run(
    items: list[dict[str, Any]],
    *,
    raw_count: int | None = None,
    source_raw_count: int | None = None,
    invalid_count: int = 0,
    errors: list[str] | None = None,
    strategy_used: str | None = None,
    fallback_used: bool = False,
    queries_attempted: int | None = None,
    pages_attempted: int | None = None,
    live_enabled: bool | None = None,
    fixture_available: bool | None = None,
) -> dict[str, Any]:
    """Build a normalized mart-discount quality summary before DB review."""
    ingestion_run_id = uuid4().hex
    total = len(items)
    parsed_total = raw_count if raw_count is not None else total + invalid_count
    source_total = source_raw_count if source_raw_count is not None else parsed_total
    field_counts = {
        "name": sum(1 for item in items if _present(item.get("name") or item.get("title"))),
        "sale_price": sum(
            1 for item in items if _present(item.get("sale_price") or item.get("current_price") or item.get("price"))
        ),
        "original_price": sum(1 for item in items if _present(item.get("original_price"))),
        "discount_percent": sum(1 for item in items if _present(item.get("discount_percent"))),
        "image_url": sum(1 for item in items if _present(item.get("image_url"))),
        "detail_url": sum(1 for item in items if _present(item.get("detail_url") or item.get("source_url") or item.get("url"))),
        "source_url": sum(
            1
            for item in items
            if _present(item.get("source_url"))
            or _present(item.get("detail_url"))
            or _present((item.get("attributes") or {}).get("source_url"))
        ),
        "period": sum(
            1
            for item in items
            if _present(item.get("period"))
            or _present(item.get("valid_from"))
            or _present(item.get("valid_until"))
            or _present((item.get("attributes") or {}).get("period"))
        ),
        "unit": sum(
            1
            for item in items
            if _present(item.get("unit"))
            or _present(item.get("display_unit"))
            or _present(item.get("package_quantity"))
            or _present(item.get("package_unit"))
            or _present(item.get("package_info"))
        ),
        "category_hint": sum(
            1
            for item in items
            if _present(item.get("category"))
            or _present(item.get("category_hint"))
            or _present((item.get("attributes") or {}).get("category_hint"))
            or _present((item.get("attributes") or {}).get("category_hints"))
            or _present((item.get("attributes") or {}).get("category_path"))
        ),
    }
    duplicate_count = sum(count - 1 for count in Counter(_discount_key(item) for item in items).values() if count > 1)
    invalid_ratio = _ratio(invalid_count, parsed_total)
    duplicate_ratio = _ratio(duplicate_count, total)
    coverage = {field: _ratio(count, total) for field, count in field_counts.items()}

    score = 100.0
    if total == 0:
        score = 0.0
    else:
        score -= invalid_ratio * 30
        score -= duplicate_ratio * 20
        score -= (1 - coverage["sale_price"]) * 30
        score -= (1 - coverage["detail_url"]) * 12
        score -= (1 - coverage["image_url"]) * 10
        score -= (1 - coverage["original_price"]) * 8
        score -= min(len(errors or []), 5) * 3
        if fallback_used:
            score -= 5
    score = round(max(0.0, min(100.0, score)), 1)

    alerts: list[str] = []
    operator_diagnostics: list[dict[str, Any]] = []
    next_actions: list[str] = []
    if total == 0:
        alerts.append("zero_valid_items")
    low_critical_fields: list[dict[str, Any]] = []
    for field, threshold in CRITICAL_FIELD_THRESHOLDS.items():
        field_coverage = coverage.get(field, 0)
        if field_coverage < threshold:
            low_critical_fields.append(
                {
                    "field": field,
                    "coverage": field_coverage,
                    "threshold": threshold,
                    "present": field_counts.get(field, 0),
                    "total": total,
                }
            )
            alert = "missing_sale_price" if field == "sale_price" else f"low_{field}_coverage"
            if alert not in alerts:
                alerts.append(alert)
    if coverage.get("image_url", 0) < 0.5:
        alerts.append("low_image_coverage")
    if low_critical_fields and total > 0:
        field_names = ", ".join(field["field"] for field in low_critical_fields)
        next_action = (
            f"Fix parser field mapping for critical fields with low coverage ({field_names}) using saved fixtures; "
            "do not treat this registered crawler as reliably collecting until coverage meets thresholds."
        )
        next_actions.append(next_action)
        operator_diagnostics.append(
            {
                "code": "low_critical_field_coverage",
                "severity": "warning",
                "message": f"Critical field coverage is below thresholds for: {field_names}.",
                "next_action": next_action,
                "fields": low_critical_fields,
            }
        )
    if invalid_ratio > 0.2:
        alerts.append("high_invalid_drop_rate")
    if duplicate_ratio > 0.1:
        alerts.append("high_duplicate_rate")
        next_actions.append(DUPLICATE_HEAVY_NEXT_ACTION)
        operator_diagnostics.append(
            {
                "code": "duplicate_heavy_output",
                "severity": "warning",
                "message": (
                    f"{duplicate_count} of {total} valid rows are duplicates by store/source, name/title, and price."
                ),
                "next_action": DUPLICATE_HEAVY_NEXT_ACTION,
                "duplicate_count": duplicate_count,
                "duplicate_ratio": duplicate_ratio,
                "threshold": 0.1,
            }
        )
    if fallback_used:
        alerts.append("fallback_used")
    if errors:
        alerts.append("source_errors_present")

    zero_result_diagnostic: dict[str, Any] | None = None
    if total == 0:
        if live_enabled is False and fixture_available is False:
            zero_stage = "live_disabled_no_fixture"
            alerts.extend(["live_collection_disabled", "fixture_or_raw_missing"])
            message = (
                "Live collection is disabled and the run did not include a saved fixture/raw input, so registration "
                "cannot be treated as collection evidence."
            )
        elif fixture_available is False:
            zero_stage = "fixture_or_raw_missing"
            alerts.append("fixture_or_raw_missing")
            message = (
                "The bounded run did not receive saved fixture/raw input, so it cannot prove whether the source, parser, "
                "or validation stage is working."
            )
        elif source_total == 0:
            zero_stage = "source_zero_raw_rows"
            alerts.append("zero_source_raw_rows")
            message = (
                "Input was available but source extraction found zero candidate rows. Check fixture contents, source "
                "candidate selectors/JSON paths, request URL, status/rate limiting, source blocking, and query terms."
            )
        elif parsed_total == 0:
            zero_stage = "parse_filtered_all_raw_rows"
            alerts.append("raw_rows_not_parsed")
            message = (
                "Source returned candidate rows but parser produced zero discount items. Check __NEXT_DATA__/JSON "
                "paths, CSS selectors, required price/name fields, or source markup/schema changes."
            )
        elif invalid_count >= parsed_total:
            zero_stage = "validation_rejected_all_rows"
            alerts.append("validation_rejected_all_rows")
            message = (
                "Parser produced rows but validation rejected every row. Check price/name validation, duplicate "
                "keys, required fields, and normalization rules."
            )
        else:
            zero_stage = "zero_valid_items_unknown"
            alerts.append("zero_valid_items_unknown")
            message = (
                "No valid rows reached output, but source/parse counts do not identify a single stage. "
                "Inspect recent source errors and per-stage counts."
            )
        next_action = _next_action_for_stage(zero_stage)
        next_actions.insert(0, next_action)
        zero_result_diagnostic = {
            "stage": zero_stage,
            "message": message,
            "operator_action": message,
            "next_action": next_action,
            "crawler_next_action": next_action,
            "dry_run_safe": True,
                "counts": {
                    "source_raw": source_total,
                    "parsed": parsed_total,
                    "valid": total,
                    "invalid_or_dropped": invalid_count,
                },
                "live_enabled": live_enabled,
                "fixture_available": fixture_available,
                "source_errors": list(errors or [])[:10],
            }
        operator_diagnostics.insert(
            0,
            {
                "code": zero_stage,
                "severity": "error",
                "stage": zero_stage,
                "message": message,
                "next_action": next_action,
                "counts": zero_result_diagnostic["counts"],
                "live_enabled": live_enabled,
                "fixture_available": fixture_available,
                "source_errors": zero_result_diagnostic["source_errors"],
            },
        )

    if total == 0:
        reliability_status = "failing"
    elif low_critical_fields or invalid_ratio > 0.2 or duplicate_ratio > 0.1 or errors:
        reliability_status = "warning"
    else:
        reliability_status = "collecting"

    next_actions = list(dict.fromkeys(next_actions))
    quality_summary = {
        "status": reliability_status,
        "score": score,
        "registered_vs_collecting": reliability_status,
        "critical_field_coverage": {field: coverage.get(field, 0) for field in CRITICAL_FIELD_THRESHOLDS},
        "low_critical_fields": low_critical_fields,
        "zero_result_stage": zero_result_diagnostic.get("stage") if zero_result_diagnostic else None,
        "diagnostic_count": len(operator_diagnostics),
        "next_actions": next_actions,
    }

    return {
        "schema": "crawler_run_summary.v1",
        "ingestion_run_id": ingestion_run_id,
        "score": score,
        "item_counts": {
            "raw": parsed_total,
            "source_raw": source_total,
            "parsed": parsed_total,
            "valid": total,
            "invalid_or_dropped": invalid_count,
            "duplicates_after_validation": duplicate_count,
        },
        "coverage": coverage,
        "critical_field_thresholds": CRITICAL_FIELD_THRESHOLDS,
        "fetch": {
            "strategy_used": strategy_used,
            "fallback_used": fallback_used,
            "queries_attempted": queries_attempted,
            "pages_attempted": pages_attempted,
            "live_enabled": live_enabled,
            "fixture_available": fixture_available,
        },
        "alerts": alerts,
        "source_error_count": len(errors or []),
        "source_errors": list(errors or [])[:10],
        "operator_diagnostics": operator_diagnostics,
        "quality_summary": quality_summary,
        "next_actions": next_actions,
        "zero_result_diagnostic": zero_result_diagnostic,
    }

