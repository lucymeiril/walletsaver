"""대시보드 통계 라우트 — 실시간 상태 분포, 에러 추이, 알림, 크롤러 카드, 신선도 제공."""

from __future__ import annotations

import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query

from scheduler.job_tracker import JobTracker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

# 대시보드 캐시: 빈번한 새로고침 시 DB/파일 재조회 방지 (60초 TTL)
_stats_cache: dict[str, Any] = {}
_cache_ts: float = 0
_CACHE_TTL = 60  # seconds

_tracker: JobTracker | None = None

CATEGORY_MAP: dict[str, str] = {
    "emart": "mart", "homeplus": "mart", "lottemart": "mart",
    "costco": "mart", "cocodalin": "mart",
    "fmkorea": "hotdeal", "ppomppu": "hotdeal", "ruliweb": "hotdeal",
    "quasarzone": "hotdeal", "coolenjoy": "hotdeal",
    "musinsa": "shopping", "coupang": "shopping", "gmarket": "shopping",
    "opinet": "gas",
}

CATEGORY_LABELS: dict[str, str] = {
    "mart": "마트",
    "hotdeal": "핫딜",
    "shopping": "쇼핑",
    "gas": "주유소",
}


def _get_tracker() -> JobTracker:
    global _tracker
    if _tracker is None:
        _tracker = JobTracker()
    return _tracker


def set_tracker(tracker: JobTracker) -> None:
    """외부에서 공유 JobTracker를 주입할 때 사용."""
    global _tracker
    _tracker = tracker


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _resolve_category(job_id: str) -> str:
    lower = job_id.lower().replace("-", "").replace("_", "")
    for key, cat in CATEGORY_MAP.items():
        if key in lower:
            return cat
    return "etc"


@router.get("/stats")
async def get_dashboard_stats(days: int = Query(7, ge=1, le=90)):
    """대시보드 통계 — 상태 분포, 에러 추이, 알림, 크롤러 카드, 데이터 신선도."""
    global _stats_cache, _cache_ts

    cache_key = f"stats_{days}"
    now_ts = time.time()
    # 캐시 유효 시 즉시 반환 — 60초 내 동일 요청은 재계산 생략
    if cache_key in _stats_cache and (now_ts - _cache_ts) < _CACHE_TTL:
        return _stats_cache[cache_key]

    tracker = _get_tracker()
    history = tracker.get_history(limit=500)
    now = datetime.now()
    today = now.date()

    # --- 상태 분포 (전체 실행 기록 기준) ---
    status_counter: Counter[str] = Counter()
    for entry in history:
        status_counter[entry["status"]] += 1

    status_distribution = {
        "success": status_counter.get("success", 0),
        "failure": status_counter.get("failed", 0),
        "partial": status_counter.get("partial", 0),
    }

    # --- 에러 추이 (날짜 범위 지원) ---
    error_trend = []
    for days_ago in range(days - 1, -1, -1):
        day = now - timedelta(days=days_ago)
        day_str = f"{day.month}/{day.day}"
        day_date = day.date()

        errors_on_day = 0
        for entry in history:
            entry_dt = _parse_dt(entry.get("started_at", ""))
            if entry_dt and entry_dt.date() == day_date and entry["status"] in ("failed", "partial"):
                errors_on_day += 1

        error_trend.append({"date": day_str, "errors": errors_on_day})

    # --- 크롤러별 최신 실행 정보 수집 ---
    latest_by_crawler: dict[str, dict] = {}
    for entry in history:
        job_id = entry.get("job_id", "")
        if not job_id:
            continue
        started = entry.get("started_at", "")
        if job_id not in latest_by_crawler:
            latest_by_crawler[job_id] = entry
        else:
            prev = latest_by_crawler[job_id].get("started_at", "")
            if started > prev:
                latest_by_crawler[job_id] = entry

    total_crawlers = len(latest_by_crawler)

    # --- 긴급 알림: 최근 실행이 실패인 크롤러 ---
    alerts = []
    for job_id, entry in latest_by_crawler.items():
        if entry["status"] in ("failed",):
            alerts.append({
                "crawlerName": job_id,
                "status": "failed",
                "lastRun": entry.get("started_at", ""),
                "error": entry.get("error", ""),
            })

    # --- 크롤러별 상태 카드 ---
    status_mapping = {"success": "success", "failed": "failure", "running": "running"}
    crawler_cards = []
    for job_id, entry in sorted(latest_by_crawler.items()):
        raw_status = entry["status"]
        card_status = status_mapping.get(raw_status, raw_status)
        items = 0
        result = entry.get("result")
        if isinstance(result, dict):
            items = result.get("items_count", result.get("count", 0))
        crawler_cards.append({
            "name": job_id,
            "status": card_status,
            "lastRun": entry.get("started_at", ""),
            "itemsCount": items,
        })

    # --- 오늘 크롤 횟수 ---
    today_crawls = 0
    for entry in history:
        entry_dt = _parse_dt(entry.get("started_at", ""))
        if entry_dt and entry_dt.date() == today:
            today_crawls += 1
            
    # --- 성공률 ---
    total = sum(status_distribution.values())
    success_rate = round(
        (status_distribution["success"] / total * 100) if total > 0 else 0.0,
        1,
    )

    # --- 데이터 신선도 (카테고리별 마지막 성공 시간) ---
    cat_latest: dict[str, str] = {}
    for job_id, entry in latest_by_crawler.items():
        if entry["status"] != "success":
            continue
        cat = _resolve_category(job_id)
        if cat == "etc":
            continue
        ts = entry.get("started_at", "")
        if ts and (cat not in cat_latest or ts > cat_latest[cat]):
            cat_latest[cat] = ts

    freshness = []
    for cat_key, cat_label in CATEGORY_LABELS.items():
        last_ts = cat_latest.get(cat_key)
        status = "unknown"
        if last_ts:
            dt = _parse_dt(last_ts)
            if dt:
                age_hours = (now - dt).total_seconds() / 3600
                if age_hours < 24:
                    status = "fresh"
                elif age_hours < 72:
                    status = "stale"
                else:
                    status = "expired"
        freshness.append({
            "category": cat_key,
            "label": cat_label,
            "lastUpdate": last_ts or "",
            "status": status,
        })

    result = {
        "statusDistribution": status_distribution,
        "errorTrend": error_trend,
        "totalCrawlers": total_crawlers,
        "activeCrawlers": total_crawlers,
        "todayCrawls": today_crawls,
        "successRate": success_rate,
        "alerts": alerts,
        "crawlerCards": crawler_cards,
        "freshness": freshness,
    }

    # 캐시 저장
    _stats_cache[cache_key] = result
    _cache_ts = now_ts

    return result
