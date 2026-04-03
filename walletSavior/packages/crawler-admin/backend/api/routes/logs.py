"""로그 조회 라우트 — 이력 조회 및 CSV 내보내기."""

from __future__ import annotations

import csv
import io
from datetime import datetime
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


def _filter_by_date(
    history: list[dict],
    date_from: str | None,
    date_to: str | None,
) -> list[dict]:
    """날짜 범위로 로그 필터링."""
    if not date_from and not date_to:
        return history

    filtered = []
    for h in history:
        started = h.get("started_at")
        if not started:
            continue
        try:
            ts = datetime.fromisoformat(started)
        except (ValueError, TypeError):
            continue

        if date_from:
            if ts.date() < datetime.fromisoformat(date_from).date():
                continue
        if date_to:
            if ts.date() > datetime.fromisoformat(date_to).date():
                continue
        filtered.append(h)
    return filtered


def _enrich_with_sample(entry: dict) -> dict:
    """로그 항목에 dataSample(상위 5건) 필드 추가."""
    result = entry.get("result") or {}
    raw_items = result.get("items") or result.get("data") or []
    entry["dataSample"] = raw_items[:5] if isinstance(raw_items, list) else []
    return entry


@router.get("")
async def get_logs(
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    status: Optional[str] = Query(None, description="Filter by status"),
    date_from: Optional[str] = Query(None, description="시작일 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료일 (YYYY-MM-DD)"),
):
    """작업 실행 이력 조회."""
    tracker = _get_tracker()
    history = tracker.get_history(job_id=job_id, limit=limit)
    if status:
        history = [h for h in history if h["status"] == status]
    history = _filter_by_date(history, date_from, date_to)
    history = [_enrich_with_sample(h) for h in history]
    return {
        "total": len(history),
        "logs": history,
    }


@router.get("/export")
async def export_logs_csv(
    job_id: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="시작일 (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="종료일 (YYYY-MM-DD)"),
):
    """로그를 CSV로 내보내기 — 전체 필드 포함."""
    tracker = _get_tracker()
    history = tracker.get_history(job_id=job_id, limit=limit)
    if status:
        history = [h for h in history if h["status"] == status]
    history = _filter_by_date(history, date_from, date_to)

    columns = [
        "job_id", "started_at", "ended_at", "status",
        "items_found", "items_saved", "duration",
        "quality_score", "strategy_used", "error",
    ]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    for entry in history:
        result = entry.get("result") or {}
        writer.writerow([
            entry.get("job_id", ""),
            entry.get("started_at", ""),
            entry.get("ended_at", ""),
            entry.get("status", ""),
            result.get("items_found", ""),
            result.get("items_saved", ""),
            result.get("duration", ""),
            result.get("quality_score", ""),
            result.get("strategy_used", ""),
            entry.get("error", ""),
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=crawl_logs.csv"},
    )
