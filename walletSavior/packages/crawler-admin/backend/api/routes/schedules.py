"""스케줄 관리 라우트."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scheduler.scheduler import CrawlScheduler

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

_scheduler: CrawlScheduler | None = None


def _get_scheduler() -> CrawlScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CrawlScheduler()
    return _scheduler


class ScheduleCreate(BaseModel):
    crawler_name: str
    cron: str


class ScheduleUpdate(BaseModel):
    cron: str


@router.get("")
async def list_schedules():
    """현재 스케줄 목록."""
    sched = _get_scheduler()
    return {"schedules": sched.list_jobs()}


@router.post("")
async def create_schedule(body: ScheduleCreate):
    """스케줄 추가."""
    sched = _get_scheduler()
    try:
        result = sched.add_job(body.crawler_name, body.cron)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.put("/{crawler_name}")
async def update_schedule(crawler_name: str, body: ScheduleUpdate):
    """스케줄 변경."""
    sched = _get_scheduler()
    try:
        result = sched.update_job(crawler_name, body.cron)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.delete("/{crawler_name}")
async def delete_schedule(crawler_name: str):
    """스케줄 삭제."""
    sched = _get_scheduler()
    removed = sched.remove_job(crawler_name)
    if not removed:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "removed", "crawler_name": crawler_name}
