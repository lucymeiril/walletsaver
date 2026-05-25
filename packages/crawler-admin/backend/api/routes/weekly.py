"""주간 diff API 라우트.

엔드포인트:
    GET  /api/weekly/diff?mart=emart&days=7      — WeeklyDiffReport JSON
    GET  /api/weekly/alerts?status=open          — 사라진 SKU alert 목록
    POST /api/weekly/alerts/{id}/resolve         — alert resolved_at 설정
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, text, select
from sqlalchemy.orm import Session, sessionmaker

from services.weekly_diff import (
    AlertDisappearedSkuModel,
    AlertSkuBase,
    WeeklyDiffReport,
    compute_weekly_diff,
    persist_alerts,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/weekly", tags=["weekly"])

# ─────────────────────────────────────────────────────────────────────────────
# DB 세션 팩토리 (lazy init)
# ─────────────────────────────────────────────────────────────────────────────

_engine = None
_SessionLocal = None


def _get_session() -> Session:
    global _engine, _SessionLocal
    if _engine is None:
        db_url = os.getenv("WEEKLY_DIFF_DB_URL") or os.getenv("DATABASE_URL", "")
        if not db_url:
            raise HTTPException(status_code=503, detail="DATABASE_URL not configured")
        _engine = create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _SessionLocal()


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/diff")
def get_weekly_diff(
    mart: str = Query(..., description="마트 식별자 (emart, homeplus, lottemart, costco)"),
    days: int = Query(7, ge=1, le=90, description="current window 기간(일)"),
):
    """현재 window vs 이전 window 비교 결과 반환."""
    until = datetime.now(timezone.utc).replace(tzinfo=None)
    since = until - timedelta(days=days)

    session = _get_session()
    try:
        report = compute_weekly_diff(session, mart=mart, since=since, until=until)
        return report.to_dict()
    except Exception as exc:
        logger.exception("[weekly/diff] error mart=%s", mart)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/alerts")
def get_alerts(
    status: str = Query("open", description="open | resolved | all"),
    mart: Optional[str] = Query(None, description="마트 필터 (없으면 전체)"),
    limit: int = Query(100, ge=1, le=1000),
):
    """사라진 SKU alert 목록 반환."""
    session = _get_session()
    try:
        q = select(AlertDisappearedSkuModel)
        if status == "open":
            q = q.where(AlertDisappearedSkuModel.resolved_at.is_(None))
        elif status == "resolved":
            q = q.where(AlertDisappearedSkuModel.resolved_at.isnot(None))
        # status == "all" → 필터 없음

        if mart:
            q = q.where(AlertDisappearedSkuModel.mart == mart)

        q = q.order_by(AlertDisappearedSkuModel.detected_at.desc()).limit(limit)
        rows = session.execute(q).scalars().all()
        return [_alert_to_dict(r) for r in rows]
    except Exception as exc:
        logger.exception("[weekly/alerts] error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int):
    """alert resolved_at 설정."""
    session = _get_session()
    try:
        alert = session.get(AlertDisappearedSkuModel, alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail="alert not found")
        if alert.resolved_at is not None:
            return {"status": "already_resolved", "resolved_at": alert.resolved_at.isoformat()}

        alert.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.commit()
        return {"status": "resolved", "resolved_at": alert.resolved_at.isoformat()}
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        logger.exception("[weekly/resolve] alert_id=%d", alert_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────────────────


def _alert_to_dict(row: AlertDisappearedSkuModel) -> dict:
    return {
        "id": row.id,
        "mart": row.mart,
        "source_record_key": row.source_record_key,
        "last_seen_title": row.last_seen_title,
        "last_seen_price": row.last_seen_price,
        "last_captured_at": row.last_captured_at.isoformat() if row.last_captured_at else None,
        "detected_at": row.detected_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        "status": "resolved" if row.resolved_at else "open",
    }
