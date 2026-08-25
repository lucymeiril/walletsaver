"""오케스트레이터 API 라우트 — /api/v1/plugins, /api/v1/schedules, /api/v1/runs."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services import crawl_orchestrator as orch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["orchestrator"])


class ScheduleCreate(BaseModel):
    plugin_name: str
    cron_expr: Optional[str] = None
    interval_hours: Optional[float] = None
    target_categories: Optional[list[str]] = None
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    plugin_name: Optional[str] = None
    cron_expr: Optional[str] = None
    interval_hours: Optional[float] = None
    target_categories: Optional[list[str]] = None
    enabled: Optional[bool] = None


class TriggerRunBody(BaseModel):
    plugin_name: str
    target_categories: Optional[list[str]] = None


class AdHocBody(BaseModel):
    plugin_name: str
    search_query: Optional[str] = None
    canonical_id: Optional[str] = None
    requested_by: str = "admin"


_PLUGIN_INIT_DONE = False


def _ensure_plugins_registered() -> None:
    global _PLUGIN_INIT_DONE
    if _PLUGIN_INIT_DONE:
        return
    _PLUGIN_INIT_DONE = True
    for mod in ("emart", "homeplus", "lottemart", "costco"):
        try:
            module = __import__(f"crawlers.marts.{mod}.plugin", fromlist=["register"])
            module.register()
        except Exception as exc:  # pragma: no cover
            logger.warning("[orchestrator] plugin %s register failed: %s", mod, exc)


def _require_registered_plugin(plugin_name: str):
    _ensure_plugins_registered()
    plugin = orch.get_registry().get(plugin_name)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"플러그인을 찾을 수 없습니다: {plugin_name}")
    return plugin


def _validate_schedule_values(
    *,
    cron_expr: Optional[str],
    interval_hours: Optional[float],
    allow_empty: bool = False,
) -> None:
    if cron_expr is None and interval_hours is None:
        if allow_empty:
            return
        raise HTTPException(status_code=400, detail="cron_expr 또는 interval_hours 중 하나는 필수입니다.")
    if cron_expr is not None:
        try:
            CronTrigger.from_crontab(cron_expr)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="올바른 cron 표현식이 필요합니다.") from exc
    if interval_hours is not None and interval_hours <= 0:
        raise HTTPException(status_code=400, detail="interval_hours는 0보다 커야 합니다.")


# ── Schedule execution loop ──────────────────────────────────────

_SCHEDULE_POLL_SECONDS = max(
    30,
    int(os.getenv("WALLETSAVIOR_SCHEDULE_POLL_SECONDS", "60")),
)
_schedule_task: asyncio.Task | None = None


async def _run_due_once() -> list[dict]:
    _ensure_plugins_registered()
    return await asyncio.to_thread(orch.run_due_schedules)


async def _schedule_loop() -> None:
    while True:
        try:
            await _run_due_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[orchestrator] schedule tick failed")
        await asyncio.sleep(_SCHEDULE_POLL_SECONDS)


def schedule_loop_enabled() -> bool:
    return os.getenv("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", "").lower() not in {
        "1",
        "true",
        "yes",
    }


def schedule_loop_running() -> bool:
    return bool(
        schedule_loop_enabled()
        and _schedule_task is not None
        and not _schedule_task.done()
    )


@router.on_event("startup")
async def _start_schedule_loop() -> None:
    global _schedule_task
    if not schedule_loop_enabled():
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


@router.get("/plugins")
async def list_plugins():
    _ensure_plugins_registered()
    registry = orch.get_registry()
    store = orch.get_run_store()
    out = []
    for plugin in registry.list_all():
        last = store.last_run_for_plugin(plugin.name)
        out.append({
            "name": plugin.name,
            "mart_kind": getattr(plugin, "mart_kind", plugin.name),
            "display_name": getattr(plugin, "display_name", plugin.name),
            # The current four mart adapters always run their full CrawlPipeline.
            "supports_targeted_search": False,
            "last_run": last,
        })
    return {"plugins": out}


@router.get("/schedules")
async def list_schedules(plugin_name: Optional[str] = None):
    store = orch.get_run_store()
    return {"schedules": store.list_schedules(plugin_name=plugin_name)}


@router.post("/schedules", status_code=201)
async def create_schedule(body: ScheduleCreate):
    _require_registered_plugin(body.plugin_name)
    _validate_schedule_values(
        cron_expr=body.cron_expr,
        interval_hours=body.interval_hours,
    )
    store = orch.get_run_store()
    sid = store.create_schedule(
        plugin_name=body.plugin_name,
        cron_expr=body.cron_expr,
        interval_hours=body.interval_hours,
        target_categories=body.target_categories,
        enabled=body.enabled,
    )
    return store.get_schedule(sid)


@router.patch("/schedules/{schedule_id}")
async def update_schedule(schedule_id: str, body: ScheduleUpdate):
    store = orch.get_run_store()
    if store.get_schedule(schedule_id) is None:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다.")
    if body.plugin_name is not None:
        _require_registered_plugin(body.plugin_name)
    _validate_schedule_values(
        cron_expr=body.cron_expr,
        interval_hours=body.interval_hours,
        allow_empty=True,
    )
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    return store.update_schedule(schedule_id, **fields)


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(schedule_id: str):
    store = orch.get_run_store()
    ok = store.delete_schedule(schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="스케줄을 찾을 수 없습니다.")
    return {"deleted": True, "id": schedule_id}


@router.post("/runs/trigger", status_code=202)
async def trigger_run_endpoint(body: TriggerRunBody):
    _require_registered_plugin(body.plugin_name)
    try:
        run_id = orch.trigger_run(
            plugin_name=body.plugin_name,
            target_categories=body.target_categories,
            triggered_by="manual",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    run = orch.get_run_store().get_run(run_id)
    return {"run_id": run_id, "run": run}


@router.post("/runs/ad-hoc", status_code=202)
async def run_ad_hoc_endpoint(body: AdHocBody):
    plugin = _require_registered_plugin(body.plugin_name)
    if body.search_query and not plugin.supports_targeted_search(body.search_query):
        raise HTTPException(
            status_code=400,
            detail=f"{body.plugin_name} 크롤러는 현재 개별 검색 실행을 지원하지 않습니다.",
        )
    try:
        request_id = orch.run_ad_hoc(
            plugin_name=body.plugin_name,
            search_query=body.search_query,
            canonical_id=body.canonical_id,
            requested_by=body.requested_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    req = orch.get_run_store().get_request(request_id)
    return {"request_id": request_id, "request": req}


@router.get("/runs")
async def list_runs(
    status: Optional[str] = None,
    plugin: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
):
    store = orch.get_run_store()
    return store.list_runs(plugin_name=plugin, status=status, page=page, page_size=page_size)


@router.get("/runs/{run_id}/logs")
async def run_logs(run_id: str):
    store = orch.get_run_store()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "log_lines": run.get("log_lines", []),
        "failure_reasons": run.get("failure_reasons", []),
        "items_found": run.get("items_found", 0),
        "items_saved": run.get("items_saved", 0),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
    }


@router.post("/runs/{run_id}/retry", status_code=202)
async def retry_run_endpoint(run_id: str):
    _ensure_plugins_registered()
    try:
        new_run_id = orch.retry_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": new_run_id, "retried_from": run_id}


@router.post("/runs/retry-last-failed/{plugin_name}", status_code=202)
async def retry_last_failed_endpoint(plugin_name: str):
    _require_registered_plugin(plugin_name)
    page = orch.get_run_store().list_runs(
        plugin_name=plugin_name,
        status="failed",
        page=1,
        page_size=1,
    )
    items = page.get("items", [])
    if not items:
        raise HTTPException(status_code=404, detail=f"{plugin_name}의 최근 실패 run을 찾을 수 없습니다.")
    failed_run_id = items[0].get("run_id") or items[0].get("id")
    if not failed_run_id:
        raise HTTPException(status_code=500, detail="실패 run의 ID를 확인할 수 없습니다.")
    try:
        new_run_id = orch.retry_run(failed_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "run_id": new_run_id,
        "retried_from": failed_run_id,
        "plugin_name": plugin_name,
    }
