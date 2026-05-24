"""pending_db_review escalation 큐 라우트.

GET  /api/escalation/pending          — 정체 건 목록 + 알람 상태 (UI 폴링용)
GET  /api/escalation/alarm            — 알람 상태만 빠르게 조회
POST /api/escalation/sweep            — 자동 escalation sweep (Rule A 건 ai_safe_final_approve)
POST /api/escalation/{id}/approve     — 1-click 사람 승인 (ai_safe_final_approve + force fallback)
POST /api/escalation/{id}/reject      — 1-click 사람 거부 (rolled_back 처리)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from storage import Database, get_default_database
from storage.models import AIPublishRecord
from services.pending_escalation import (
    STALE_ALARM_HOURS,
    evaluate_pending_record,
    get_alarm_status,
    get_pending_for_ui,
    run_escalation_sweep,
)
from services.db_admin_adapter import ai_safe_final_approve_db_admin
from services.review_publish import mark_publish_record_rolled_back

router = APIRouter(prefix="/api/escalation", tags=["escalation"])


def get_db() -> Database:
    return get_default_database()


class ApproveRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    notes: Optional[str] = None
    # force=True 이면 db-admin 호출 없이 published 로 직접 전환 (오프라인 테스트/긴급 해소용)
    force: bool = False


class RejectRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@router.get("/pending")
def list_pending(db: Database = Depends(get_db)) -> dict[str, Any]:
    """정체 건 목록과 알람 상태를 반환한다.

    UI는 이 엔드포인트를 주기적으로 폴링하여 escalation 큐 패널을 갱신한다.
    """
    with db.session_scope() as session:
        return get_pending_for_ui(session)


@router.get("/alarm")
def alarm_status(db: Database = Depends(get_db)) -> dict[str, Any]:
    """알람 상태만 빠르게 조회한다 (MatchMonitor 패널 폴링용)."""
    with db.session_scope() as session:
        return get_alarm_status(session)


@router.post("/sweep")
async def run_sweep(db: Database = Depends(get_db)) -> dict[str, Any]:
    """Rule A 해당 건에 ai_safe_final_approve 를 자동 호출한다.

    각 건별로 db-admin 호출 결과를 수집하고, 성공/실패를 구분하여 반환한다.
    db-admin 이 오프라인이어도 전체 sweep 이 중단되지 않도록 예외를 per-item 처리한다.
    """
    with db.session_scope() as session:
        sweep = run_escalation_sweep(session)

    auto_items = sweep["auto_publish_items"]
    results = []
    for item in auto_items:
        raw_id = item["raw_record_id"]
        ingestion_id = item["db_ingestion_id"]
        result: dict[str, Any] = {"raw_record_id": raw_id, "db_ingestion_id": ingestion_id}
        try:
            resp = await ai_safe_final_approve_db_admin(
                ingestion_id,
                notes=f"escalation-sweep: auto Rule-A approve for {raw_id}",
            )
            result["status"] = "published"
            result["db_admin_response"] = resp
            # 성공 시 ai_publish_records 상태를 published 로 업데이트
            with db.session_scope() as session:
                _mark_published(session, raw_id, reviewer_id="system:escalation-sweep")
        except Exception as exc:
            result["status"] = "sweep_failed"
            result["error"] = str(exc)
        results.append(result)

    published_count = sum(1 for r in results if r["status"] == "published")
    failed_count = len(results) - published_count

    return {
        **sweep,
        "sweep_applied": len(results),
        "sweep_published": published_count,
        "sweep_failed": failed_count,
        "sweep_results": results,
    }


@router.post("/{raw_record_id}/approve")
async def approve_pending(
    raw_record_id: str,
    payload: ApproveRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """1-click 사람 승인: ai_safe_final_approve 를 호출하거나 force 모드로 직접 published 전환.

    force=True 는 db-admin 이 오프라인이거나 이미 손수 승인된 경우의 긴급 해소용이다.
    """
    with db.session_scope() as session:
        record = session.get(AIPublishRecord, raw_record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="publish record not found")
    if record.status != "pending_db_review":
        raise HTTPException(
            status_code=400,
            detail=f"record is not in pending_db_review; current status: {record.status}",
        )

    decision = evaluate_pending_record(record)

    if payload.force:
        # 강제 해소: db-admin 호출 없이 published 로 직접 전환
        with db.session_scope() as session:
            _mark_published(
                session,
                raw_record_id,
                reviewer_id=payload.reviewer_id,
                notes=f"force-approve by {payload.reviewer_id}: {payload.notes or 'operator override'}",
            )
        return {
            "raw_record_id": raw_record_id,
            "status": "published",
            "method": "force_approve",
            "reviewer_id": payload.reviewer_id,
            "decision": _decision_summary(decision),
        }

    if not record.db_ingestion_id:
        raise HTTPException(
            status_code=400,
            detail="db_ingestion_id 없음 — db-admin 에 제출되지 않은 건입니다. force=true 로 강제 해소하거나 재발행하세요.",
        )

    try:
        resp = await ai_safe_final_approve_db_admin(
            record.db_ingestion_id,
            notes=f"escalation-manual-approve by {payload.reviewer_id}: {payload.notes or ''}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"db-admin ai_safe_final_approve 실패: {exc}. force=true 로 강제 해소할 수 있습니다.",
        ) from exc

    with db.session_scope() as session:
        _mark_published(
            session,
            raw_record_id,
            reviewer_id=payload.reviewer_id,
            notes=f"escalation-approve by {payload.reviewer_id}",
        )

    return {
        "raw_record_id": raw_record_id,
        "status": "published",
        "method": "ai_safe_final_approve",
        "reviewer_id": payload.reviewer_id,
        "db_ingestion_id": record.db_ingestion_id,
        "db_admin_response": resp,
        "decision": _decision_summary(decision),
    }


@router.post("/{raw_record_id}/reject")
def reject_pending(
    raw_record_id: str,
    payload: RejectRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    """1-click 사람 거부: rolled_back 처리.

    DB-admin ingestion 도 수동으로 거부/삭제해야 함을 운영자에게 안내한다.
    """
    with db.session_scope() as session:
        try:
            row = mark_publish_record_rolled_back(
                session,
                raw_record_id,
                requested_by=payload.reviewer_id,
                reason=f"escalation-reject: {payload.reason}",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="publish record not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        db_ingestion_id = row.db_ingestion_id

    return {
        "raw_record_id": raw_record_id,
        "status": "rolled_back",
        "reviewer_id": payload.reviewer_id,
        "db_ingestion_id": db_ingestion_id,
        "operator_instructions": (
            f"DB-admin ingestion {db_ingestion_id} 을 거부/삭제하세요. "
            "AI-admin 롤백은 DB-admin 에 자동 전파되지 않습니다."
            if db_ingestion_id
            else "DB-admin 에 제출된 ingestion 이 없습니다."
        ),
    }


def _mark_published(
    session,
    raw_record_id: str,
    *,
    reviewer_id: str,
    notes: str = "",
) -> None:
    """ai_publish_records 상태를 published 로 직접 갱신한다."""
    from datetime import datetime

    row = session.get(AIPublishRecord, raw_record_id)
    if row is None:
        return
    row.status = "published"
    row.published_at = datetime.now()
    row.updated_at = datetime.now()
    row.requested_by = reviewer_id
    if notes:
        row.last_error = None  # 이전 에러 클리어
        if not row.db_ingestion_result:
            row.db_ingestion_result = {}
        row.db_ingestion_result = {**(row.db_ingestion_result or {}), "escalation_notes": notes}
    session.flush()


def _decision_summary(d) -> dict[str, Any]:
    """EscalationDecision 의 요약본을 반환한다."""
    return {
        "rule": d.rule,
        "gate_passed_count": d.gate_passed_count,
        "hours_stale": round(d.hours_stale, 1) if d.hours_stale != float("inf") else None,
        "blockers": d.blockers,
    }
