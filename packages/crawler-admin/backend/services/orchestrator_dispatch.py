"""Non-blocking dispatch helpers for the crawler orchestrator control plane.

The core service keeps synchronous helpers for deterministic unit-level use.
HTTP endpoints and the schedule loop use this module so a crawl is recorded as
``running`` and its ID is returned before the potentially long crawl finishes.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import Optional

from services import crawl_orchestrator as orch

logger = logging.getLogger(__name__)

_MAX_WORKERS = max(
    1,
    min(16, int(os.getenv("WALLETSAVIOR_ORCHESTRATOR_WORKERS", "4"))),
)
_EXECUTOR = ThreadPoolExecutor(
    max_workers=_MAX_WORKERS,
    thread_name_prefix="walletsavior-orchestrator",
)


def _log_worker_failure(future: Future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("[orchestrator-dispatch] background worker failed")


def _submit(func, *args) -> None:
    future = _EXECUTOR.submit(func, *args)
    future.add_done_callback(_log_worker_failure)


def dispatch_run(
    plugin_name: str,
    target_categories: list[str] | None = None,
    *,
    triggered_by: str = "manual",
    schedule_id: Optional[str] = None,
    store: Optional[orch.OrchestratorStore] = None,
    registry: Optional[orch.PluginRegistry] = None,
) -> str:
    """Create a run and return its ID immediately while execution continues."""
    store = store or orch.get_run_store()
    registry = registry or orch.get_registry()
    plugin = registry.get(plugin_name)
    if plugin is None:
        raise ValueError(f"플러그인을 찾을 수 없습니다: {plugin_name}")

    run_id = store.create_run(
        plugin_name,
        schedule_id=schedule_id,
        triggered_by=triggered_by,
    )
    _submit(
        orch._execute_plugin_sync,
        plugin,
        target_categories,
        run_id,
        store,
    )
    return run_id


def _finish_ad_hoc_request(
    plugin,
    targets: list[str] | None,
    run_id: str,
    request_id: str,
    store: orch.OrchestratorStore,
) -> None:
    try:
        result = orch._execute_plugin_sync(plugin, targets, run_id, store)
        final_status = (
            "done"
            if result.get("status") in {"success", "partial"}
            else "failed"
        )
        preview = {
            "status": result.get("status"),
            "items_found": result.get("items_found", 0),
            "items_saved": result.get("items_saved", 0),
            "errors": result.get("errors", []),
        }
    except Exception as exc:  # defensive wrapper around the shared executor path
        logger.exception("[orchestrator-dispatch] ad-hoc request failed")
        final_status = "failed"
        preview = {
            "status": "failed",
            "items_found": 0,
            "items_saved": 0,
            "errors": [str(exc)],
        }
    store.update_request(
        request_id,
        status=final_status,
        result_preview=preview,
    )


def dispatch_ad_hoc(
    plugin_name: str,
    search_query: Optional[str],
    canonical_id: Optional[str],
    requested_by: str,
    *,
    store: Optional[orch.OrchestratorStore] = None,
    registry: Optional[orch.PluginRegistry] = None,
) -> str:
    """Create an ad-hoc request and return its request ID immediately."""
    store = store or orch.get_run_store()
    registry = registry or orch.get_registry()
    plugin = registry.get(plugin_name)
    if plugin is None:
        raise ValueError(f"플러그인을 찾을 수 없습니다: {plugin_name}")

    request_id = store.create_request(
        plugin_name=plugin_name,
        search_query=search_query,
        canonical_id=canonical_id,
        requested_by=requested_by,
    )
    targets = [search_query] if search_query else None
    run_id = store.create_run(plugin_name, triggered_by="ad-hoc")
    store.update_request(request_id, status="running", run_id=run_id)
    _submit(
        _finish_ad_hoc_request,
        plugin,
        targets,
        run_id,
        request_id,
        store,
    )
    return request_id


def dispatch_retry(
    run_id: str,
    *,
    store: Optional[orch.OrchestratorStore] = None,
    registry: Optional[orch.PluginRegistry] = None,
) -> str:
    """Create one retry run and return its ID without waiting for completion."""
    store = store or orch.get_run_store()
    registry = registry or orch.get_registry()
    source = store.get_run(run_id)
    if source is None:
        raise ValueError(f"run을 찾을 수 없습니다: {run_id}")

    existing = store.find_retry_run(run_id)
    if existing is not None:
        return existing["run_id"]

    plugin = registry.get(source["plugin_name"])
    if plugin is None:
        raise ValueError(f"플러그인을 찾을 수 없습니다: {source['plugin_name']}")

    new_run_id = store.create_run(
        plugin_name=source["plugin_name"],
        schedule_id=source.get("schedule_id"),
        triggered_by="retry",
        retried_from=run_id,
    )
    _submit(
        orch._execute_plugin_sync,
        plugin,
        None,
        new_run_id,
        store,
    )
    return new_run_id


def dispatch_due_schedules(
    now: Optional[datetime] = None,
    *,
    store: Optional[orch.OrchestratorStore] = None,
    registry: Optional[orch.PluginRegistry] = None,
) -> list[dict]:
    """Start due schedules without blocking the scheduler loop on crawl work."""
    now = now or datetime.utcnow()
    store = store or orch.get_run_store()
    registry = registry or orch.get_registry()
    summaries: list[dict] = []

    for schedule in store.list_schedules(enabled_only=True):
        last = store.last_run_for_schedule(schedule["id"])
        if last and last.get("status") == "running":
            continue
        last_started = orch._parse_iso(last["started_at"]) if last else None
        if not orch._schedule_is_due(schedule, now, last_started):
            continue

        plugin = registry.get(schedule["plugin_name"])
        if plugin is None:
            summaries.append(
                {
                    "schedule_id": schedule["id"],
                    "plugin_name": schedule["plugin_name"],
                    "status": "skipped",
                    "reason": "plugin_not_registered",
                }
            )
            continue

        run_id = store.create_run(
            plugin_name=schedule["plugin_name"],
            schedule_id=schedule["id"],
            triggered_by="schedule",
        )
        _submit(
            orch._execute_plugin_sync,
            plugin,
            schedule.get("target_categories") or None,
            run_id,
            store,
        )
        summaries.append(
            {
                "schedule_id": schedule["id"],
                "plugin_name": schedule["plugin_name"],
                "run_id": run_id,
                "status": "running",
            }
        )

    return summaries
