"""Current crawler registry coverage.

Coverage is derived only from plugin registrations that actually exist in the
current repository.  It intentionally does not maintain a separate required
source universe, readiness programme, marketplace skeleton list, or AI handoff
policy.  Those older planning layers could make deleted product scope appear
required merely because a test still named it.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

SOURCE_COVERAGE_SCHEMA = "crawler_source_coverage.v2"


def _group_for(config: dict[str, Any]) -> str:
    return str(
        config.get("source_group")
        or config.get("category")
        or config.get("group")
        or "unknown"
    )


def _schedule_for(config: dict[str, Any]) -> str:
    schedule = config.get("schedule", "manual")
    if isinstance(schedule, dict):
        return str(schedule.get("cron") or "manual")
    return str(schedule or "manual")


def build_source_coverage(
    registry_data: dict[str, dict[str, Any]],
    *,
    quality_by_source: dict[str, dict[str, Any]] | None = None,
    health_baseline_by_source: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe only crawlers that are actually registered now.

    ``health_baseline_by_source`` is retained in the signature for compatibility
    with older callers, but no longer creates or requires synthetic source
    entries.  Quality evidence, when supplied, is attached to the matching
    registered source only.
    """
    del health_baseline_by_source
    quality_by_source = quality_by_source or {}

    rows: list[dict[str, Any]] = []
    for registry_name, info in sorted(registry_data.items()):
        config = dict((info or {}).get("config") or {})
        source_id = str(config.get("name") or registry_name)
        quality = quality_by_source.get(source_id) or quality_by_source.get(registry_name)
        quality_summary = (quality or {}).get("quality_summary") or {}

        rows.append(
            {
                "source_id": source_id,
                "registered_name": registry_name,
                "registration_status": "registered",
                "group": _group_for(config),
                "schedule": _schedule_for(config),
                "module_path": (info or {}).get("module_path"),
                "path": (info or {}).get("path"),
                "quality_evidence": {
                    "has_quality_evidence": quality is not None,
                    "status": quality_summary.get("status") if quality else None,
                    "score": (quality or {}).get("score") if quality else None,
                },
            }
        )

    counts = Counter(row["group"] for row in rows)
    return {
        "schema": SOURCE_COVERAGE_SCHEMA,
        "total_registered": len(rows),
        "registered_by_group": dict(sorted(counts.items())),
        "sources": rows,
    }
