"""로그 조회 라우트 — 이력 조회 및 CSV 내보내기."""

from __future__ import annotations

import csv
import io
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from scheduler.job_tracker import JobTracker

router = APIRouter(prefix="/api/logs", tags=["logs"])

_tracker: JobTracker | None = None


def _get_tracker() -> JobTracker:
    global _tracker
    if _tracker is None:
        _tracker = JobTracker()
    return _tracker


def set_tracker(tracker: JobTracker) -> None:
    """외부에서 공유 JobTracker를 주입할 때 사용."""
    global _tracker
    _tracker = tracker


@router.get("")
async def get_logs(
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    status: Optional[str] = Query(None, description="Filter by status"),
):
    """작업 실행 이력 조회."""
    tracker = _get_tracker()
    history = tracker.get_history(job_id=job_id, limit=limit)
    if status:
        history = [h for h in history if h["status"] == status]
    return {
        "total": len(history),
        "logs": history,
    }


@router.get("/export")
async def export_logs_csv(
    job_id: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    status: Optional[str] = Query(None),
):
    """로그를 CSV로 내보내기."""
    tracker = _get_tracker()
    history = tracker.get_history(job_id=job_id, limit=limit)
    if status:
        history = [h for h in history if h["status"] == status]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["job_id", "started_at", "ended_at", "status", "error"])
    for entry in history:
        writer.writerow([
            entry.get("job_id", ""),
            entry.get("started_at", ""),
            entry.get("ended_at", ""),
            entry.get("status", ""),
            entry.get("error", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=crawl_logs.csv"},
    )
