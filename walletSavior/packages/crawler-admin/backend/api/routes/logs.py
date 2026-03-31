"""로그 조회 라우트."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from scheduler.job_tracker import JobTracker

router = APIRouter(prefix="/api/logs", tags=["logs"])

_tracker: JobTracker | None = None


def _get_tracker() -> JobTracker:
    global _tracker
    if _tracker is None:
        _tracker = JobTracker()
    return _tracker


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
