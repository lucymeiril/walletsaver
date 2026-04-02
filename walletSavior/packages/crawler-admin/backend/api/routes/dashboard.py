"""대시보드 통계 라우트 — 실시간 상태 분포 및 에러 추이 제공."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta

from fastapi import APIRouter

from scheduler.job_tracker import JobTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

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


@router.get("/stats")
async def get_dashboard_stats():
    """대시보드 통계 — 상태 분포, 에러 추이, 요약 카드."""
    tracker = _get_tracker()
    history = tracker.get_history(limit=500)

    # --- 상태 분포 (전체 실행 기록 기준) ---
    status_counter: Counter[str] = Counter()
    for entry in history:
        status_counter[entry["status"]] += 1

    status_distribution = {
        "success": status_counter.get("success", 0),
        "failure": status_counter.get("failed", 0),
        "partial": status_counter.get("partial", 0),
    }

    # --- 에러 추이 (최근 7일) ---
    now = datetime.now()
    error_trend = []
    for days_ago in range(6, -1, -1):
        day = now - timedelta(days=days_ago)
        day_str = day.strftime("%-m/%-d") if hasattr(day, "strftime") else f"{day.month}/{day.day}"
        # Windows strftime doesn't support %-m
        day_str = f"{day.month}/{day.day}"
        day_date = day.date()

        errors_on_day = 0
        for entry in history:
            started = entry.get("started_at", "")
            if not started:
                continue
            try:
                entry_date = datetime.fromisoformat(started).date()
            except (ValueError, TypeError):
                continue
            if entry_date == day_date and entry["status"] in ("failed", "partial"):
                errors_on_day += 1

        error_trend.append({"date": day_str, "errors": errors_on_day})

    # --- 요약 통계 ---
    # 고유 크롤러 이름 추출
    crawler_names = set()
    for entry in history:
        job_id = entry.get("job_id", "")
        crawler_names.add(job_id)

    total_crawlers = len(crawler_names) if crawler_names else 0

    # 오늘 크롤 횟수
    today = now.date()
    today_crawls = 0
    today_success = 0
    for entry in history:
        started = entry.get("started_at", "")
        if not started:
            continue
        try:
            entry_date = datetime.fromisoformat(started).date()
        except (ValueError, TypeError):
            continue
        if entry_date == today:
            today_crawls += 1
            if entry["status"] == "success":
                today_success += 1

    total = sum(status_distribution.values())
    success_rate = round(
        (status_distribution["success"] / total * 100) if total > 0 else 0.0,
        1,
    )

    return {
        "statusDistribution": status_distribution,
        "errorTrend": error_trend,
        "totalCrawlers": total_crawlers,
        "activeCrawlers": total_crawlers,
        "todayCrawls": today_crawls,
        "successRate": success_rate,
    }
