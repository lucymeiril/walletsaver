"""§9 user-feedback ingestion → AI learning queue.

The public website / web-api hands reports to ai-admin via a thin HTTP endpoint;
this module is the persistence + querying layer. It is intentionally policy-free:

  - `record_feedback(...)` stores one row.
  - `recent_feedback_for_match(match_id)` lets the labeling pipeline raise a
    "신고 많음" badge (v5 §9, P0 4단계 중 1~3).
  - `mark_handled(...)` closes the loop.

No automatic disabling of matches happens here — spec §14.6 explicitly forbids
"신고 N건 → 자동 중지". Operators decide.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from storage.models import UserFeedback


VALID_KINDS = {"bad_match", "wrong_category", "wrong_canonical", "missing_keyword", "other"}


@dataclass
class FeedbackSummary:
    match_id: Optional[str]
    open_count: int
    total_count: int
    kinds: dict[str, int]


def record_feedback(
    session: Session,
    *,
    kind: str,
    raw_record_id: Optional[str] = None,
    match_id: Optional[str] = None,
    knowledge_id: Optional[str] = None,
    category_id: Optional[str] = None,
    reporter_id: Optional[str] = None,
    note: str = "",
) -> str:
    if kind not in VALID_KINDS:
        raise ValueError(f"unknown feedback kind: {kind!r}")
    feedback_id = f"fb-{uuid.uuid4().hex[:16]}"
    session.add(UserFeedback(
        feedback_id=feedback_id,
        kind=kind,
        raw_record_id=raw_record_id,
        match_id=match_id,
        knowledge_id=knowledge_id,
        category_id=category_id,
        reporter_id=reporter_id,
        note=note,
        status="open",
        created_at=datetime.now(),
    ))
    session.flush()
    return feedback_id


def summary_for_match(session: Session, match_id: str) -> FeedbackSummary:
    rows = (
        session.query(UserFeedback)
        .filter(UserFeedback.match_id == match_id)
        .all()
    )
    kinds: dict[str, int] = {}
    open_count = 0
    for r in rows:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
        if r.status == "open":
            open_count += 1
    return FeedbackSummary(
        match_id=match_id,
        open_count=open_count,
        total_count=len(rows),
        kinds=kinds,
    )


def mark_handled(
    session: Session,
    feedback_id: str,
    *,
    handled_by: str,
    resolution: str,
    new_status: str = "applied",
) -> None:
    row = session.get(UserFeedback, feedback_id)
    if row is None:
        raise KeyError(f"user feedback {feedback_id} not found")
    if new_status not in {"applied", "dismissed", "reviewed"}:
        raise ValueError(f"invalid status: {new_status}")
    row.status = new_status
    row.handled_at = datetime.now()
    row.handled_by = handled_by
    row.resolution = resolution
    session.flush()


def open_counts_per_match(session: Session, limit: int = 200) -> list[tuple[str, int]]:
    """Return [(match_id, open_count), ...] for the labeling pipeline to badge."""
    rows = (
        session.query(UserFeedback.match_id, func.count(UserFeedback.feedback_id))
        .filter(UserFeedback.status == "open")
        .filter(UserFeedback.match_id.isnot(None))
        .group_by(UserFeedback.match_id)
        .order_by(func.count(UserFeedback.feedback_id).desc())
        .limit(limit)
        .all()
    )
    return [(m, int(c)) for m, c in rows]
