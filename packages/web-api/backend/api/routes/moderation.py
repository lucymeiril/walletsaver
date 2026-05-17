"""Moderation API routes — reports, bans, audit log."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from services.auth import require_mod
from storage.board_models import (
    Comment,
    ModerationLog,
    Post,
    Report,
    User,
    get_board_db,
)

router = APIRouter(tags=["moderation"])


def _now() -> str:
    return datetime.utcnow().isoformat()


class ReportOut(BaseModel):
    id: str
    target_kind: str
    target_id: str
    reason: Optional[str] = None
    status: str
    created_at: str
    reporter_user_id: str


class ResolveReq(BaseModel):
    action: str  # hide_target | delete_target | dismiss | ban_user
    note: Optional[str] = None


class AuditOut(BaseModel):
    id: str
    action: str
    target_kind: Optional[str] = None
    target_id: Optional[str] = None
    actor_user_id: Optional[str] = None
    note: Optional[str] = None
    created_at: str


@router.get("/reports", response_model=list[ReportOut])
def list_reports(
    status: str = "open",
    db: Session = Depends(get_board_db),
    _: User = Depends(require_mod),
):
    rows = db.query(Report).filter(Report.status == status).order_by(desc(Report.created_at)).all()
    return [
        ReportOut(
            id=r.id,
            target_kind=r.target_kind,
            target_id=r.target_id,
            reason=r.reason,
            status=r.status,
            created_at=r.created_at,
            reporter_user_id=r.reporter_user_id,
        )
        for r in rows
    ]


@router.post("/reports/{report_id}/resolve")
def resolve_report(
    report_id: str,
    body: ResolveReq,
    db: Session = Depends(get_board_db),
    actor: User = Depends(require_mod),
):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "report_not_found")
    if r.status != "open":
        raise HTTPException(400, "report_not_open")

    action = body.action
    if action not in ("hide_target", "delete_target", "dismiss", "ban_user"):
        raise HTTPException(400, "invalid_action")

    if action in ("hide_target", "delete_target"):
        if r.target_kind == "post":
            p = db.get(Post, r.target_id)
            if p:
                p.hidden_at = _now()
                p.hidden_reason = body.note or action
        elif r.target_kind == "comment":
            c = db.get(Comment, r.target_id)
            if c:
                c.hidden_at = _now()
        r.status = "resolved"
    elif action == "ban_user":
        target_user_id = None
        if r.target_kind == "post":
            p = db.get(Post, r.target_id)
            target_user_id = p.user_id if p else None
            if p:
                p.hidden_at = _now()
                p.hidden_reason = "user_banned"
        elif r.target_kind == "comment":
            c = db.get(Comment, r.target_id)
            target_user_id = c.user_id if c else None
            if c:
                c.hidden_at = _now()
        if target_user_id:
            tu = db.get(User, target_user_id)
            if tu:
                tu.banned_at = _now()
        r.status = "resolved"
    else:  # dismiss
        r.status = "dismissed"

    r.resolved_by_user_id = actor.id
    r.resolved_at = _now()

    db.add(
        ModerationLog(
            action=f"resolve_report:{action}",
            target_kind=r.target_kind,
            target_id=r.target_id,
            actor_user_id=actor.id,
            note=body.note,
            created_at=_now(),
        )
    )
    db.commit()
    return {"ok": True, "status": r.status}


@router.post("/users/{user_id}/ban")
def ban_user(
    user_id: str,
    db: Session = Depends(get_board_db),
    actor: User = Depends(require_mod),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "user_not_found")
    u.banned_at = _now()
    db.add(
        ModerationLog(
            action="ban_user",
            target_kind="user",
            target_id=user_id,
            actor_user_id=actor.id,
            created_at=_now(),
        )
    )
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/unban")
def unban_user(
    user_id: str,
    db: Session = Depends(get_board_db),
    actor: User = Depends(require_mod),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "user_not_found")
    u.banned_at = None
    db.add(
        ModerationLog(
            action="unban_user",
            target_kind="user",
            target_id=user_id,
            actor_user_id=actor.id,
            created_at=_now(),
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/admin/audit", response_model=list[AuditOut])
def audit_log(
    db: Session = Depends(get_board_db),
    _: User = Depends(require_mod),
):
    rows = db.query(ModerationLog).order_by(desc(ModerationLog.created_at)).limit(200).all()
    return [
        AuditOut(
            id=m.id,
            action=m.action,
            target_kind=m.target_kind,
            target_id=m.target_id,
            actor_user_id=m.actor_user_id,
            note=m.note,
            created_at=m.created_at,
        )
        for m in rows
    ]
