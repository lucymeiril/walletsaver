"""§4-E v5 ReviewDecision undo window.

Two modes per spec:

1. **Toast mode** — within `undoable_until` (default 5s after a decision is taken)
   AND `downstream_application_count == 0`. One-click revert: flip `is_undone=True`,
   wipe any side-effect rows the decision spawned (learned alias, product match) by
   marking them `is_active=False` with `disabled_reason='undo'`.

2. **Cascade mode** — past the 5s window OR the decision was already reused in a
   later labeling run. The caller must pass `cascade=True`; we still flip the
   decision and walk `reused_in_run_ids` to disable every downstream
   `LearnedKnowledge` / `ProductMatch` that referenced this decision.

This module is NOT a route. The route layer (`api/routes/review.py`) calls
`open_undo_window()` right after `ReviewDecisionRepository.save()` and exposes
`undo_decision()` over HTTP.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from storage.models import (
    AliasAuditLog,
    LearnedKnowledge,
    ProductMatch,
    ReviewDecisionRecord,
)

# §4-A v5: 30초 토스트 undo. 운영자가 결정을 되돌릴 여유 시간을 30초로 확장.
DEFAULT_UNDO_WINDOW_SECONDS = 30


@dataclass
class UndoResult:
    decision_id: str
    mode: str  # "toast" | "cascade" | "noop"
    disabled_matches: list[str]
    disabled_knowledge: list[str]
    audit_ids: list[str]


def open_undo_window(
    session: Session,
    decision_id: str,
    *,
    now: Optional[datetime] = None,
    window_seconds: int = DEFAULT_UNDO_WINDOW_SECONDS,
) -> Optional[datetime]:
    """Set `undoable_until = now + window` on the decision row. Returns the deadline."""
    row = session.get(ReviewDecisionRecord, decision_id)
    if row is None:
        return None
    now = now or datetime.now()
    row.undoable_until = now + timedelta(seconds=window_seconds)
    session.flush()
    return row.undoable_until


def record_downstream_application(
    session: Session,
    decision_id: str,
    run_id: str,
) -> None:
    """Bump `downstream_application_count` and append `run_id`.

    Called by labeling runs whenever a previously-saved decision is re-applied
    (e.g. learned alias kicks in for a new raw record).
    """
    row = session.get(ReviewDecisionRecord, decision_id)
    if row is None:
        return
    runs = list(row.reused_in_run_ids or [])
    if run_id not in runs:
        runs.append(run_id)
        row.reused_in_run_ids = runs
    row.downstream_application_count = (row.downstream_application_count or 0) + 1
    session.flush()


def undo_decision(
    session: Session,
    decision_id: str,
    *,
    actor: str,
    cascade: bool = False,
    now: Optional[datetime] = None,
) -> UndoResult:
    """Reverse a review decision.

    - If `undoable_until` is in the future AND `downstream_application_count == 0`
      → toast mode.
    - Otherwise the caller must pass `cascade=True` and we will disable downstream
      learned aliases / product matches that this decision spawned.

    Raises `ValueError` if the cascade flag is required but not provided.
    """
    row = session.get(ReviewDecisionRecord, decision_id)
    if row is None:
        raise KeyError(f"review decision {decision_id} not found")
    if row.is_undone:
        return UndoResult(decision_id=decision_id, mode="noop",
                          disabled_matches=[], disabled_knowledge=[], audit_ids=[])

    now = now or datetime.now()
    within_window = bool(row.undoable_until and row.undoable_until >= now)
    has_downstream = (row.downstream_application_count or 0) > 0

    if not within_window or has_downstream:
        if not cascade:
            raise ValueError(
                f"decision {decision_id} is past the 30s undo window or already "
                f"reused (downstream={row.downstream_application_count}); "
                "pass cascade=True to force cascade revert"
            )

    # 1) flip the decision
    row.is_undone = True
    row.undone_at = now
    row.undone_by = actor
    session.flush()

    # 2) disable downstream LearnedKnowledge created from this decision
    disabled_knowledge: list[str] = []
    knowledge_rows = (
        session.query(LearnedKnowledge)
        .filter(LearnedKnowledge.created_from_decision_id == decision_id)
        .all()
    )
    audit_ids: list[str] = []
    for kn in knowledge_rows:
        if kn.is_active:
            kn.is_active = False
            disabled_knowledge.append(kn.knowledge_id)
            audit_ids.append(
                _audit(session, alias_kind="learned_knowledge",
                       alias_key=kn.pattern, action="recall",
                       actor=actor, reason=f"undo of decision {decision_id}",
                       related_decision_id=decision_id,
                       related_knowledge_id=kn.knowledge_id,
                       recoverable_via_decision_id=decision_id)
            )

    # 3) disable downstream ProductMatch rows tagged with this decision in audit_metadata
    disabled_matches: list[str] = []
    pm_rows = session.query(ProductMatch).filter(ProductMatch.is_active.is_(True)).all()
    for pm in pm_rows:
        meta = pm.audit_metadata or {}
        if meta.get("source_decision_id") == decision_id:
            pm.is_active = False
            pm.disabled_reason = f"undo of decision {decision_id} by {actor}"
            disabled_matches.append(pm.match_id)
            audit_ids.append(
                _audit(session, alias_kind="product_match",
                       alias_key=pm.signature_key, action="recall",
                       actor=actor, reason=f"undo of decision {decision_id}",
                       related_decision_id=decision_id,
                       related_match_id=pm.match_id,
                       recoverable_via_decision_id=decision_id)
            )
    session.flush()

    mode = "cascade" if (cascade and (not within_window or has_downstream)) else "toast"
    return UndoResult(decision_id=decision_id, mode=mode,
                      disabled_matches=disabled_matches,
                      disabled_knowledge=disabled_knowledge,
                      audit_ids=audit_ids)


def _audit(
    session: Session, *, alias_kind: str, alias_key: str, action: str,
    actor: str, reason: str,
    related_decision_id: Optional[str] = None,
    related_match_id: Optional[str] = None,
    related_knowledge_id: Optional[str] = None,
    recoverable_via_decision_id: Optional[str] = None,
) -> str:
    import uuid
    audit_id = f"audit-{uuid.uuid4().hex[:16]}"
    session.add(AliasAuditLog(
        audit_id=audit_id,
        alias_kind=alias_kind,
        alias_key=alias_key,
        action=action,
        actor=actor,
        reason=reason,
        related_decision_id=related_decision_id,
        related_match_id=related_match_id,
        related_knowledge_id=related_knowledge_id,
        recoverable_via_decision_id=recoverable_via_decision_id,
    ))
    session.flush()
    return audit_id
