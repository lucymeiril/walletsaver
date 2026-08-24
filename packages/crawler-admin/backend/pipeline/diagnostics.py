"""Lightweight diagnostics for currently registered crawlers.

The older diagnostics layer carried a second, static product plan containing
marketplace skeletons, disabled-live gates, source completion claims, and AI
handoff stages.  That made historical planning assumptions look like current
runtime requirements.  This module now does only two things:

* describe a bounded plan for crawlers that are actually registered; and
* parse/validate caller-supplied fixtures without performing network crawling.
"""
from __future__ import annotations

import inspect
from typing import Any

from crawlers.source_coverage import build_source_coverage
from pipeline.quality import summarize_discount_run

DIAGNOSTICS_SCHEMA = "bounded_crawler_diagnostics.v2"
LIVE_DIAGNOSTICS_PLAN_SCHEMA = "bounded_diagnostics_plan.v2"
DEFAULT_LIVE_DIAGNOSTIC_RUN_LIMITS = {
    "max_requests": 3,
    "max_pages": 1,
    "timeout_seconds": 15,
}


def _registry_dict(registry: Any) -> dict[str, dict[str, Any]]:
    return getattr(registry, "_registry", registry)


def _item_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "dict"):
        return item.dict()
    try:
        return {k: v for k, v in vars(item).items() if not k.startswith("_")}
    except TypeError:
        return {}


def _fixture_for(crawler_id: str, info: dict[str, Any], fixtures: dict[str, str]) -> str | None:
    config = (info or {}).get("config") or {}
    keys = [crawler_id, config.get("name"), config.get("source_id")]
    aliases = config.get("plugin_aliases") or []
    keys.extend(aliases if isinstance(aliases, list) else [])
    lowered = {str(key).lower(): value for key, value in fixtures.items()}
    for key in keys:
        if key is None:
            continue
        if str(key) in fixtures:
            return fixtures[str(key)]
        if str(key).lower() in lowered:
            return lowered[str(key).lower()]
    return None


def _fixture_snapshot(source_id: str, fixture_snapshots: dict[str, Any]) -> dict[str, Any]:
    value = fixture_snapshots.get(source_id)
    if isinstance(value, dict):
        path = value.get("path")
        return {
            "path": path,
            "status": value.get("status") or ("available" if path else "missing"),
        }
    if isinstance(value, str) and value.strip():
        return {"path": value, "status": "available"}
    return {"path": None, "status": "missing"}


def build_bounded_live_diagnostics_plan(
    registry: Any,
    *,
    quality_by_source: dict[str, dict[str, Any]] | None = None,
    health_baseline_by_source: dict[str, dict[str, Any]] | None = None,
    fixture_snapshots: dict[str, Any] | None = None,
    allow_live: bool = False,
    run_limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Describe bounded diagnostics for the current registry without running them."""
    coverage = build_source_coverage(
        _registry_dict(registry),
        quality_by_source=quality_by_source,
        health_baseline_by_source=health_baseline_by_source,
    )
    fixture_snapshots = fixture_snapshots or {}
    limits = {**DEFAULT_LIVE_DIAGNOSTIC_RUN_LIMITS, **(run_limits or {})}

    sources = []
    for row in coverage["sources"]:
        source_id = row["source_id"]
        snapshot = _fixture_snapshot(source_id, fixture_snapshots)
        sources.append(
            {
                "source_id": source_id,
                "fixture_snapshot": snapshot,
                "fixture_snapshot_path": snapshot["path"],
                "fixture_snapshot_status": snapshot["status"],
                "requested_live": bool(allow_live),
                "max_requests": int(limits["max_requests"]),
                "max_pages": int(limits["max_pages"]),
                "timeout_seconds": int(limits["timeout_seconds"]),
            }
        )

    return {
        "schema": LIVE_DIAGNOSTICS_PLAN_SCHEMA,
        "source_coverage": coverage,
        "default_run_limits": DEFAULT_LIVE_DIAGNOSTIC_RUN_LIMITS,
        "sources": sources,
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def run_bounded_crawler_diagnostics(
    registry: Any,
    *,
    fixture_by_source: dict[str, str] | None = None,
    crawler_ids: list[str] | None = None,
    health_baseline_by_source: dict[str, dict[str, Any]] | None = None,
    live_enabled: bool = False,
) -> dict[str, Any]:
    """Parse and validate supplied fixtures for currently registered crawlers.

    ``live_enabled`` remains in the signature for API compatibility, but this
    helper never performs network crawling.  Live crawler execution belongs to
    the normal crawler run path, not to diagnostics.
    """
    del health_baseline_by_source, live_enabled
    fixture_by_source = fixture_by_source or {}
    registry_data = _registry_dict(registry)
    selected = crawler_ids or sorted(registry_data)

    rows: list[dict[str, Any]] = []
    for crawler_id in selected:
        info = registry_data.get(crawler_id)
        if info is None:
            rows.append(
                {
                    "crawler_id": crawler_id,
                    "status": "not_registered",
                    "fixture": {"available": False},
                    "quality_evidence": {"has_quality_evidence": False},
                }
            )
            continue

        fixture = _fixture_for(crawler_id, info, fixture_by_source)
        if fixture is None:
            rows.append(
                {
                    "crawler_id": crawler_id,
                    "status": "fixture_missing",
                    "fixture": {"available": False},
                    "quality_evidence": {
                        "has_quality_evidence": False,
                        "can_claim_collecting": False,
                    },
                }
            )
            continue

        try:
            crawler = registry.get_crawler(crawler_id)
            source_raw_count = None
            counter = getattr(crawler, "count_raw_candidates", None)
            if callable(counter):
                try:
                    source_raw_count = int(await _maybe_await(counter(fixture)))
                except Exception:
                    source_raw_count = None

            parser = getattr(crawler, "parse", None)
            if not callable(parser):
                raise AttributeError("crawler has no parse()")
            parsed_raw = await _maybe_await(parser(fixture))
            parsed = list(parsed_raw or [])

            validator = getattr(crawler, "validate", None)
            if callable(validator):
                valid_raw = await _maybe_await(validator(parsed))
                valid = list(valid_raw or [])
            else:
                valid = parsed

            valid_dicts = [_item_to_dict(item) for item in valid]
            valid_dicts = [item for item in valid_dicts if item]
            summary = summarize_discount_run(
                valid_dicts,
                raw_count=len(parsed),
                source_raw_count=source_raw_count if source_raw_count is not None else len(parsed),
                invalid_count=max(0, len(parsed) - len(valid_dicts)),
                fixture_available=True,
            )
            rows.append(
                {
                    "crawler_id": crawler_id,
                    "status": "checked",
                    "fixture": {"available": True},
                    "quality_evidence": {
                        "has_quality_evidence": True,
                        "counts": {
                            "source_raw": source_raw_count if source_raw_count is not None else len(parsed),
                            "parsed": len(parsed),
                            "valid": len(valid_dicts),
                            "invalid_or_dropped": max(0, len(parsed) - len(valid_dicts)),
                        },
                        "score": summary.get("score"),
                        "quality_summary": summary.get("quality_summary"),
                        "alerts": summary.get("alerts") or [],
                    },
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "crawler_id": crawler_id,
                    "status": "diagnostic_failed",
                    "fixture": {"available": True},
                    "error": str(exc),
                    "quality_evidence": {"has_quality_evidence": False},
                }
            )

    return {
        "schema": DIAGNOSTICS_SCHEMA,
        "mode": "supplied_fixture_only",
        "crawlers": rows,
    }
