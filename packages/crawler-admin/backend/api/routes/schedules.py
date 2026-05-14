"""스케줄 관리 라우트 — JSON 파일 기반 영구 저장."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from apscheduler.triggers.cron import CronTrigger

from api.app import limiter
from audit import audit_log, AuditEventType
from scheduler.scheduler import CrawlScheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

_scheduler: CrawlScheduler | None = None
_SCHEDULES_FILE = Path(__file__).resolve().parent.parent.parent / "schedules.json"


def _load_saved_schedules() -> list[dict]:
    """저장된 스케줄을 파일에서 로드."""
    if _SCHEDULES_FILE.exists():
        try:
            with open(_SCHEDULES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_schedules(schedules: list[dict]) -> None:
    """스케줄을 파일에 저장."""
    try:
        with open(_SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump(schedules, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"스케줄 저장 실패: {e}")


def _sync_to_file(sched: CrawlScheduler) -> None:
    """현재 APScheduler 상태를 파일에 동기화."""
    jobs = sched.list_jobs()
    saved = _load_saved_schedules()
    # 기존 저장 데이터에서 enabled 상태 유지
    enabled_map = {s["crawler_name"]: s.get("enabled", True) for s in saved}
    cron_map = {s["crawler_name"]: s.get("cron", "") for s in saved}

    result = []
    for job in jobs:
        crawler_name = job.get("name", "").replace("crawl:", "")
        if not crawler_name:
            crawler_name = job.get("job_id", "").replace("crawl_", "")
        result.append({
            "crawler_name": crawler_name,
            "job_id": job.get("job_id", ""),
            "cron": cron_map.get(crawler_name, str(job.get("trigger", ""))),
            "next_run": job.get("next_run"),
            "enabled": enabled_map.get(crawler_name, True),
        })

    # 비활성 스케줄도 유지 (APScheduler에는 없지만 파일에 저장)
    active_names = {r["crawler_name"] for r in result}
    for s in saved:
        if s["crawler_name"] not in active_names and not s.get("enabled", True):
            result.append(s)

    _save_schedules(result)


def _get_scheduler() -> CrawlScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = CrawlScheduler()
        # 시작 시 저장된 스케줄 복원
        saved = _load_saved_schedules()
        for s in saved:
            if s.get("enabled", True) and s.get("cron"):
                try:
                    _scheduler.add_job(s["crawler_name"], s["cron"])
                except Exception as e:
                    logger.warning(f"스케줄 복원 실패 {s['crawler_name']}: {e}")
    return _scheduler


def _compute_next_runs(cron_expr: str, count: int = 3) -> list[str]:
    """cron 표현식에서 다음 N회 실행 시간 계산."""
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        runs: list[str] = []
        current = datetime.now(timezone.utc)
        for _ in range(count):
            next_time = trigger.get_next_fire_time(None, current)
            if next_time is None:
                break
            runs.append(next_time.isoformat())
            current = next_time + timedelta(seconds=1)
        return runs
    except Exception:
        return []


class ScheduleCreate(BaseModel):
    crawler_name: str
    cron: str


class ScheduleUpdate(BaseModel):
    cron: str
    description: Optional[str] = None


class ScheduleToggle(BaseModel):
    enabled: bool


@router.get("")
async def list_schedules():
    """현재 스케줄 목록 (파일 저장 데이터 + APScheduler 상태 병합)."""
    sched = _get_scheduler()
    jobs = sched.list_jobs()
    saved = _load_saved_schedules()

    # APScheduler 작업 → dict
    job_map = {}
    for job in jobs:
        crawler_name = job.get("name", "").replace("crawl:", "")
        if not crawler_name:
            crawler_name = job.get("job_id", "").replace("crawl_", "")
        job_map[crawler_name] = job

    # 저장된 스케줄 기반으로 병합
    saved_map = {s["crawler_name"]: s for s in saved}

    result = []
    # 저장 파일의 스케줄 순회
    seen = set()
    for s in saved:
        name = s["crawler_name"]
        seen.add(name)
        job = job_map.get(name)
        cron_expr = s.get("cron", "")
        result.append({
            "id": s.get("job_id", f"crawl_{name}"),
            "crawlerId": name,
            "crawlerName": s.get("display_name", name),
            "cron": cron_expr,
            "description": s.get("description", ""),
            "nextRun": job["next_run"] if job else s.get("next_run"),
            "nextRuns": _compute_next_runs(cron_expr) if cron_expr else [],
            "enabled": s.get("enabled", True),
        })

    # APScheduler에만 있는 작업 추가
    for name, job in job_map.items():
        if name not in seen:
            job_cron = str(job.get("trigger", ""))
            result.append({
                "id": job.get("job_id", f"crawl_{name}"),
                "crawlerId": name,
                "crawlerName": name,
                "cron": job_cron,
                "description": "",
                "nextRun": job.get("next_run"),
                "nextRuns": _compute_next_runs(job_cron) if job_cron else [],
                "enabled": True,
            })

    return {"schedules": result}


@router.post("")
async def create_schedule(request: Request, body: ScheduleCreate):
    """스케줄 추가 + 파일 저장."""
    sched = _get_scheduler()
    try:
        result = sched.add_job(body.crawler_name, body.cron)
    except Exception as exc:
        logger.warning("스케줄 생성 실패 %s: %s", body.crawler_name, exc)
        raise HTTPException(status_code=400, detail="스케줄 생성에 실패했습니다. 입력값을 확인하세요.")

    # 파일에 저장
    saved = _load_saved_schedules()
    saved = [s for s in saved if s["crawler_name"] != body.crawler_name]
    saved.append({
        "crawler_name": body.crawler_name,
        "job_id": result.get("job_id", f"crawl_{body.crawler_name}"),
        "cron": body.cron,
        "enabled": True,
    })
    _save_schedules(saved)

    audit_log(
        AuditEventType.SCHEDULE_CREATE,
        request=request,
        resource=body.crawler_name,
        detail={"cron": body.cron},
    )

    return result


@router.put("/{crawler_name}")
async def update_schedule(crawler_name: str, request: Request, body: ScheduleUpdate):
    """스케줄 변경 + 파일 저장."""
    sched = _get_scheduler()
    try:
        result = sched.update_job(crawler_name, body.cron)
    except Exception as exc:
        logger.warning("스케줄 변경 실패 %s: %s", crawler_name, exc)
        raise HTTPException(status_code=400, detail="스케줄 변경에 실패했습니다. 입력값을 확인하세요.")

    # 파일 업데이트
    saved = _load_saved_schedules()
    updated = False
    for s in saved:
        if s["crawler_name"] == crawler_name:
            s["cron"] = body.cron
            if body.description:
                s["description"] = body.description
            updated = True
            break
    if not updated:
        saved.append({
            "crawler_name": crawler_name,
            "job_id": f"crawl_{crawler_name}",
            "cron": body.cron,
            "description": body.description or "",
            "enabled": True,
        })
    _save_schedules(saved)

    return result


@router.delete("/{crawler_name}")
async def delete_schedule(crawler_name: str, request: Request):
    """스케줄 삭제 + 파일에서 제거."""
    sched = _get_scheduler()
    removed = sched.remove_job(crawler_name)
    if not removed:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # 파일에서 제거
    saved = _load_saved_schedules()
    saved = [s for s in saved if s["crawler_name"] != crawler_name]
    _save_schedules(saved)

    audit_log(
        AuditEventType.SCHEDULE_DELETE,
        request=request,
        resource=crawler_name,
    )

    return {"status": "removed", "crawler_name": crawler_name}


@router.put("/{crawler_name}/toggle")
async def toggle_schedule(crawler_name: str, request: Request, body: ScheduleToggle):
    """스케줄 활성/비활성 토글 — 파일에 저장하고 APScheduler에 반영."""
    sched = _get_scheduler()
    saved = _load_saved_schedules()

    target = None
    for s in saved:
        if s["crawler_name"] == crawler_name:
            target = s
            break

    if body.enabled:
        # 활성화: APScheduler에 작업 추가
        cron = target["cron"] if target else None
        if not cron:
            raise HTTPException(400, "cron 표현식을 찾을 수 없습니다")
        try:
            sched.add_job(crawler_name, cron)
        except Exception as e:
            logger.warning("스케줄 활성화 실패 %s: %s", crawler_name, e)
            raise HTTPException(400, "스케줄 활성화에 실패했습니다.")
    else:
        # 비활성화: APScheduler에서 제거
        sched.remove_job(crawler_name)

    if target:
        target["enabled"] = body.enabled
    else:
        saved.append({
            "crawler_name": crawler_name,
            "job_id": f"crawl_{crawler_name}",
            "cron": "",
            "enabled": body.enabled,
        })
    _save_schedules(saved)

    audit_log(
        AuditEventType.SCHEDULE_TOGGLE,
        request=request,
        resource=crawler_name,
        detail={"enabled": body.enabled},
    )

    return {"crawler_name": crawler_name, "enabled": body.enabled}


@router.post("/{crawler_name}/run-now")
async def run_schedule_now(crawler_name: str):
    """스케줄된 크롤러를 즉시 실행."""
    sched = _get_scheduler()

    saved = _load_saved_schedules()
    exists = any(s["crawler_name"] == crawler_name for s in saved)
    if not exists:
        jobs = sched.list_jobs()
        exists = any(
            j.get("name", "").replace("crawl:", "") == crawler_name
            or j.get("job_id", "").replace("crawl_", "") == crawler_name
            for j in jobs
        )
    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"스케줄 '{crawler_name}'을(를) 찾을 수 없습니다",
        )

    try:
        asyncio.create_task(sched.run_now(crawler_name))
        return {
            "status": "started",
            "crawler_name": crawler_name,
            "message": f"'{crawler_name}' 즉시 실행 시작",
        }
    except Exception as exc:
        logger.error("즉시 실행 실패 %s: %s", crawler_name, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="즉시 실행에 실패했습니다.")
