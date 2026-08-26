"""주간 diff API 라우트.

주간 비교 입력은 db-admin의 실제 가격 이력(``discount_history`` + ``products``)
에서 읽는다. 사라진 SKU alert는 crawler-admin 소유의 별도 SQLite 상태 DB에
저장하므로 weekly alert 쓰기는 db-admin working DB를 건드리지 않는다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from config import DB_ADMIN_DATABASE_URL, WEEKLY_STATE_DB_PATH
from services.weekly_diff import (
    AlertDisappearedSkuModel,
    compute_weekly_diff,
    create_weekly_alert_engine,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/weekly", tags=["weekly"])

_history_engine = None
_HistorySessionLocal = None
_alert_engine = None
_AlertSessionLocal = None


def _get_history_session() -> Session:
    """Open the db-admin price-history input session."""
    global _history_engine, _HistorySessionLocal
    if _history_engine is None:
        db_url = DB_ADMIN_DATABASE_URL
        if not db_url:
            raise HTTPException(status_code=503, detail="DB_ADMIN_DATABASE_URL not configured")
        _history_engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
        )
        _HistorySessionLocal = sessionmaker(
            bind=_history_engine,
            autoflush=False,
            autocommit=False,
        )
    return _HistorySessionLocal()


def _get_alert_session() -> Session:
    """Open crawler-owned weekly alert state, never the db-admin working DB."""
    global _alert_engine, _AlertSessionLocal
    if _alert_engine is None:
        _alert_engine = create_weekly_alert_engine(WEEKLY_STATE_DB_PATH)
        _AlertSessionLocal = sessionmaker(
            bind=_alert_engine,
            autoflush=False,
            autocommit=False,
        )
    return _AlertSessionLocal()


@router.get("/diff")
def get_weekly_diff(
    mart: str = Query(..., description="마트 식별자 (emart, homeplus, lottemart, costco)"),
    days: int = Query(7, ge=1, le=90, description="current window 기간(일)"),
):
    """현재 window와 바로 이전 동일 길이 window를 비교한다."""
    until = datetime.now(timezone.utc).replace(tzinfo=None)
    since = until - timedelta(days=days)

    session = _get_history_session()
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
    """crawler-owned 사라진 SKU alert 목록 반환."""
    if status not in {"open", "resolved", "all"}:
        raise HTTPException(status_code=400, detail="status must be open, resolved, or all")

    session = _get_alert_session()
    try:
        q = select(AlertDisappearedSkuModel)
        if status == "open":
            q = q.where(AlertDisappearedSkuModel.resolved_at.is_(None))
        elif status == "resolved":
            q = q.where(AlertDisappearedSkuModel.resolved_at.isnot(None))

        if mart:
            q = q.where(AlertDisappearedSkuModel.mart == mart)

        q = q.order_by(AlertDisappearedSkuModel.detected_at.desc()).limit(limit)
        rows = session.execute(q).scalars().all()
        return [_alert_to_dict(r) for r in rows]
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[weekly/alerts] error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        session.close()


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int):
    """crawler-owned alert의 resolved_at 설정."""
    session = _get_alert_session()
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
