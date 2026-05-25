"""Routes that surface the new P0 services.

- /api/threshold/calibrate      — POST: run threshold_calibrator, return rows
- /api/threshold/active         — GET : the current threshold table
- /api/alias-audit              — GET : alias change history (filterable)
- /api/feedback                 — POST: record user feedback (from web-api)
- /api/feedback                 — GET : list open feedback
- /api/feedback/{id}/handle     — POST: mark handled
- /api/review/undo/{decision_id}— POST: §4-E undo with optional cascade
- /api/rule-mapper/stats        — GET : per-process rule_mapper counters
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_db_session
from sqlalchemy.orm import Session

from services import threshold_calibrator, user_feedback, rule_mapper
from services.undo_window import undo_decision
from storage.models import AliasAuditLog, ThresholdCalibration, UserFeedback


router = APIRouter(tags=["p0-ai"])


# ---------------------------------------------------------------------------
# Threshold calibration
# ---------------------------------------------------------------------------

@router.post("/api/threshold/calibrate")
def run_calibration(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    results = threshold_calibrator.calibrate_all(session, persist=True)
    return {
        "calibrated_at": datetime.now().isoformat(),
        "results": [
            {
                "metric_name": r.metric_name,
                "value": r.value,
                "sample_size": r.sample_size,
                "method": r.method,
                "notes": r.notes,
            }
            for r in results
        ],
    }


@router.get("/api/threshold/active")
def list_active_thresholds(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    rows = (
        session.query(ThresholdCalibration)
        .order_by(ThresholdCalibration.created_at.desc())
        .all()
    )
    # newest per metric
    seen: dict[str, ThresholdCalibration] = {}
    for r in rows:
        seen.setdefault(r.metric_name, r)
    return {
        "metrics": [
            {
                "metric_name": r.metric_name,
                "value": r.value,
                "sample_size": r.sample_size,
                "method": r.method,
                "created_at": r.created_at.isoformat(),
                "notes": r.notes,
            }
            for r in seen.values()
        ]
    }


# ---------------------------------------------------------------------------
# Alias audit
# ---------------------------------------------------------------------------

@router.get("/api/alias-audit")
def list_alias_audit(
    alias_kind: Optional[str] = None,
    limit: int = 100,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    q = session.query(AliasAuditLog).order_by(AliasAuditLog.created_at.desc())
    if alias_kind:
        q = q.filter(AliasAuditLog.alias_kind == alias_kind)
    rows = q.limit(max(1, min(limit, 500))).all()
    return {
        "rows": [
            {
                "audit_id": r.audit_id,
                "alias_kind": r.alias_kind,
                "alias_key": r.alias_key,
                "action": r.action,
                "actor": r.actor,
                "reason": r.reason,
                "before_value": r.before_value,
                "after_value": r.after_value,
                "related_decision_id": r.related_decision_id,
                "related_match_id": r.related_match_id,
                "related_knowledge_id": r.related_knowledge_id,
                "recoverable_via_decision_id": r.recoverable_via_decision_id,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


# ---------------------------------------------------------------------------
# User feedback
# ---------------------------------------------------------------------------

class FeedbackIn(BaseModel):
    kind: str = Field(min_length=1)
    raw_record_id: Optional[str] = None
    match_id: Optional[str] = None
    knowledge_id: Optional[str] = None
    category_id: Optional[str] = None
    reporter_id: Optional[str] = None
    note: str = ""


class FeedbackHandle(BaseModel):
    handled_by: str = Field(min_length=1)
    resolution: str = ""
    new_status: str = "applied"


@router.post("/api/feedback", status_code=201)
def post_feedback(payload: FeedbackIn, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    try:
        fid = user_feedback.record_feedback(
            session,
            kind=payload.kind,
            raw_record_id=payload.raw_record_id,
            match_id=payload.match_id,
            knowledge_id=payload.knowledge_id,
            category_id=payload.category_id,
            reporter_id=payload.reporter_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"feedback_id": fid}


@router.get("/api/feedback")
def list_feedback(
    status: str = "open",
    limit: int = 100,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    rows = (
        session.query(UserFeedback)
        .filter(UserFeedback.status == status)
        .order_by(UserFeedback.created_at.desc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return {
        "rows": [
            {
                "feedback_id": r.feedback_id,
                "kind": r.kind,
                "match_id": r.match_id,
                "raw_record_id": r.raw_record_id,
                "reporter_id": r.reporter_id,
                "note": r.note,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "by_match": user_feedback.open_counts_per_match(session),
    }


@router.post("/api/feedback/{feedback_id}/handle")
def handle_feedback(
    feedback_id: str,
    payload: FeedbackHandle,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        user_feedback.mark_handled(
            session, feedback_id,
            handled_by=payload.handled_by,
            resolution=payload.resolution,
            new_status=payload.new_status,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"feedback_id": feedback_id, "status": payload.new_status}


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

class UndoIn(BaseModel):
    actor: str = Field(min_length=1)
    cascade: bool = False


@router.post("/api/review/undo/{decision_id}")
def post_undo(
    decision_id: str,
    payload: UndoIn,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    try:
        result = undo_decision(
            session, decision_id, actor=payload.actor, cascade=payload.cascade
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "decision_id": result.decision_id,
        "mode": result.mode,
        "disabled_matches": result.disabled_matches,
        "disabled_knowledge": result.disabled_knowledge,
        "audit_ids": result.audit_ids,
    }


# ---------------------------------------------------------------------------
# Rule mapper stats
# ---------------------------------------------------------------------------

@router.get("/api/rule-mapper/stats")
def get_rule_mapper_stats() -> dict[str, Any]:
    return rule_mapper.get_stats().to_dict()
