"""Schedule compatibility API backed by the current crawl orchestrator.

The frontend still calls ``/api/schedules``.  This router preserves that small
HTTP contract while storing schedules and run history only in ``orchestrator.db``.
The abandoned ``schedules.json`` + ``CrawlScheduler`` control plane is gone.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import crawl_orchestrator as orch

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schedules", tags=["schedules"])

_DISPLAY_NAMES = {
    "emart": "이마트",
    "homeplus": "홈플러스",
    "lottemart": "롯데마트",
    "costco": "코스트코",
}
_SCHEDULE_POLL_SECONDS = max(30, int(os.getenv("WALLETSAVIOR_SCHEDULE_POLL_SECONDS", "60")))
_schedule_task: asyncio.Task | None = None


class ScheduleCreate(BaseModel):
    crawler_name: str
    cron: str


class ScheduleUpdate(BaseModel):
    cron: str
    description: str | None = None


class ScheduleToggle(BaseModel):
    enabled: bool


def _ensure_current_plugins_registered() -> None:
    """Register the four current mart adapters idempotently."""
    for mod_name in ("emart", "homeplus", "lottemart", "costco"):
        try:
            module = __import__(f"crawlers.marts.{mod_name}.plugin", fromlist=["register"])
            module.register()
        except Exception as exc:
            logger.warning("[schedule] plugin %s registration failed: %s", mod_name, exc)


def _resolve_schedule(identifier: str) -> dict | None:
    """Resolve a new schedule id, with crawler-name fallback for old UI calls."""
    store = orch.get_run_store()
    found = store.get_schedule(identifier)
    if found is not None:
        return found
    matches = store.list_schedules(plugin_name=identifier)
    return matches[0] if matches else None


def _next_runs(cron_expr: str, count: int = 3) -> list[str]:
    if not cron_expr:
        return []
    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone.utc)
    except Exception:
        return []

    runs: list[str] = []
    cursor = datetime.now(timezone.utc)
    previous = None
    for _ in range(count):
        next_time = trigger.get_next_fire_time(previous, cursor)
        if next_time is None:
            break
        runs.append(next_time.isoformat())
        previous = next_time
        cursor = next_time
    return runs


def _legacy_view(schedule: dict) -> dict:
    cron = schedule.get("cron_expr") or ""
    next_runs = _next_runs(cron)
    plugin_name = schedule.get("plugin_name") or ""
    return {
        "id": schedule["id"],
        "crawlerId": plugin_name,
        "crawlerName": _DISPLAY_NAMES.get(plugin_name, plugin_name),
        "cron": cron,
        "description": "",
        "nextRun": next_runs[0] if next_runs else None,
        "nextRuns": next_runs,
        "enabled": bool(schedule.get("enabled")),
    }


async def _run_due_once() -> list[dict]:
    """Run currently due orchestrator schedules without blocking FastAPI's loop."""
    _ensure_current_plugins_registered()
    return await asyncio.to_thread(orch.run_due_schedules)


async def _schedule_loop() -> None:
    while True:
        try:
            await _run_due_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[schedule] orchestrator schedule tick failed")
        await asyncio.sleep(_SCHEDULE_POLL_SECONDS)


@router.on_event("startup")
async def _start_schedule_loop() -> None:
    global _schedule_task
    if os.getenv("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", "").lower() in {"1", "true", "yes"}:
        return
    if _schedule_task is None or _schedule_task.done():
        _schedule_task = asyncio.create_task(_schedule_loop())


@router.on_event("shutdown")
async def _stop_schedule_loop() -> None:
    global _schedule_task
    if _schedule_task is None:
        return
    _schedule_task.cancel()
    try:
        await _schedule_task
    except asyncio.CancelledError:
        pass
    _schedule_task = None


@router.get("")
async def list_schedules():
    return {"schedules": [_legacy_view(row) for row in orch.get_run_store().list_schedules()]}


@router.post("")
async def create_schedule(body: ScheduleCreate):
    if not _next_runs(body.cron, count=1):
        raise HTTPException(status_code=400, detail="올바른 cron 표현식이 필요합니다")
    schedule_id = orch.get_run_store().create_schedule(
        plugin_name=body.crawler_name,
        cron_expr=body.cron,
        enabled=True,
    )
    return _legacy_view(orch.get_run_store().get_schedule(schedule_id))


@router.put("/{identifier}")
async def update_schedule(identifier: str, body: ScheduleUpdate):
    if not _next_runs(body.cron, count=1):
        raise HTTPException(status_code=400, detail="올바른 cron 표현식이 필요합니다")
    schedule = _resolve_schedule(identifier)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    updated = orch.get_run_store().update_schedule(schedule["id"], cron_expr=body.cron)
    return _legacy_view(updated)


@router.delete("/{identifier}")
async def delete_schedule(identifier: str):
    schedule = _resolve_schedule(identifier)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    orch.get_run_store().delete_schedule(schedule["id"])
    return {"status": "removed", "id": schedule["id"], "crawler_name": schedule["plugin_name"]}


@router.put("/{identifier}/toggle")
async def toggle_schedule(identifier: str, body: ScheduleToggle):
    schedule = _resolve_schedule(identifier)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    updated = orch.get_run_store().update_schedule(schedule["id"], enabled=body.enabled)
    return _legacy_view(updated)


async def _trigger_schedule(schedule: dict) -> None:
    _ensure_current_plugins_registered()
    try:
        await asyncio.to_thread(
            orch.trigger_run,
            plugin_name=schedule["plugin_name"],
            triggered_by="manual",
            schedule_id=schedule["id"],
        )
    except Exception:
        logger.exception("[schedule] manual run failed for %s", schedule["plugin_name"])


@router.post("/{identifier}/run-now")
async def run_schedule_now(identifier: str):
    schedule = _resolve_schedule(identifier)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    asyncio.create_task(_trigger_schedule(schedule))
    return {
        "status": "started",
        "schedule_id": schedule["id"],
        "crawler_name": schedule["plugin_name"],
    }
