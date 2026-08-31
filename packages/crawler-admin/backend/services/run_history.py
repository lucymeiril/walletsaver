"""Compatibility views over the canonical crawler orchestrator run store."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from services.crawl_orchestrator import get_run_store

_STORE_PAGE_SIZE = 200


def get_history(
    job_id: str | None = None,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return orchestrator runs in the older logs/dashboard response shape."""
    requested = max(0, int(limit))
    if requested == 0:
        return []
    page_size = min(_STORE_PAGE_SIZE, requested)
    page = 1
    runs: list[dict[str, Any]] = []
    store = get_run_store()

    while len(runs) < requested:
        result = store.list_runs(
            plugin_name=job_id,
            status=status,
            page=page,
            page_size=page_size,
        )
        batch = result.get("items", [])
        runs.extend(batch)
        if len(batch) < page_size or len(runs) >= result.get("total", 0):
            break
        page += 1

    return [_to_history_entry(run) for run in runs[:requested]]


def _to_history_entry(run: dict[str, Any]) -> dict[str, Any]:
    failure_reasons = run.get("failure_reasons") or []
    if not isinstance(failure_reasons, list):
        failure_reasons = [str(failure_reasons)]

    return {
        "job_id": run.get("plugin_name", ""),
        "run_id": run.get("run_id"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("finished_at"),
        "status": run.get("status", "running"),
        "result": {
            "items_found": run.get("items_found", 0),
            "items_saved": run.get("items_saved", 0),
            "duration": _duration_seconds(run.get("started_at"), run.get("finished_at")),
        },
        "error": "; ".join(str(reason) for reason in failure_reasons) or None,
        "log_lines": run.get("log_lines") or [],
    }


def _duration_seconds(started_at: Any, finished_at: Any) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        started = datetime.fromisoformat(str(started_at))
        finished = datetime.fromisoformat(str(finished_at))
    except (TypeError, ValueError):
        return None
    return max(0.0, round((finished - started).total_seconds(), 3))
