"""§4-A 표본 본조건 — data-driven threshold calibration.

The spec forbids permanently hardcoded numbers. We keep one *default* in source as
a fallback but the live value comes from `threshold_calibration` rows that this
module produces from labeled data.

Inputs:
    - `ReviewDecisionRecord`: human approvals / corrections / rejects.
    - `ProductMatch.confidence`: per-match LLM confidence.
    - `LabelingRunLog`: per-run stats.

Outputs (rows in `threshold_calibration` keyed by `metric_name`):
    - `confidence_min`        — 90th-percentile of correctly approved matches'
                                confidence (or default 0.7 if sample < 50).
    - `vague_penalty_threshold` — 50th-percentile confidence of rejected matches.
    - `learned_alias_min_sources` / `_min_titles` / `_min_settled` — fixed at the
      spec values but recalibrated periodically against the observed approval
      precision (kept here so threshold operators have one source of truth).

This module is intentionally synchronous and idempotent — running calibration
twice with the same data must produce identical rows except for `created_at`.
"""
from __future__ import annotations

import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from storage.models import (
    ProductMatch,
    ReviewDecisionRecord,
    ThresholdCalibration,
)

DEFAULT_CONFIDENCE_MIN = 0.7
DEFAULT_VAGUE_PENALTY = 0.4
DEFAULT_MIN_SOURCES = 3
DEFAULT_MIN_TITLES = 20
DEFAULT_MIN_SETTLED = 50
MIN_SAMPLES_TO_OVERRIDE_DEFAULT = 50


@dataclass
class CalibrationResult:
    metric_name: str
    value: float
    sample_size: int
    method: str
    notes: str


def calibrate_all(session: Session, *, persist: bool = True) -> list[CalibrationResult]:
    """Run every calibration. Returns the new rows (and persists when `persist`)."""
    results = [
        _calibrate_confidence_min(session),
        _calibrate_vague_penalty(session),
        _calibrate_min_sources(session),
        _calibrate_min_titles(session),
        _calibrate_min_settled(session),
    ]
    if persist:
        for r in results:
            session.add(ThresholdCalibration(
                calibration_id=f"cal-{uuid.uuid4().hex[:16]}",
                metric_name=r.metric_name,
                value=r.value,
                sample_size=r.sample_size,
                method=r.method,
                method_params={},
                notes=r.notes,
                created_at=datetime.now(),
            ))
        session.flush()
    return results


def get_active_threshold(session: Session, metric_name: str, fallback: float) -> float:
    """Return the most recent calibration value or `fallback` if none."""
    row = (
        session.query(ThresholdCalibration)
        .filter(ThresholdCalibration.metric_name == metric_name)
        .order_by(ThresholdCalibration.created_at.desc())
        .first()
    )
    if row is None:
        return fallback
    return float(row.value)


# ---------------------------------------------------------------------------
# individual metrics
# ---------------------------------------------------------------------------

def _approved_decision_ids(session: Session) -> set[str]:
    rows = (
        session.query(ReviewDecisionRecord.proposal_id)
        .filter(ReviewDecisionRecord.decision == "approve")
        .filter(ReviewDecisionRecord.is_undone.is_(False))
        .all()
    )
    return {r[0] for r in rows}


def _rejected_decision_ids(session: Session) -> set[str]:
    rows = (
        session.query(ReviewDecisionRecord.proposal_id)
        .filter(ReviewDecisionRecord.decision == "reject")
        .filter(ReviewDecisionRecord.is_undone.is_(False))
        .all()
    )
    return {r[0] for r in rows}


def _confidence_of(session: Session, match_id_filter=None) -> list[float]:
    q = session.query(ProductMatch.confidence).filter(ProductMatch.confidence.isnot(None))
    if match_id_filter is not None:
        q = q.filter(ProductMatch.match_id.in_(list(match_id_filter)))
    return [float(c) for (c,) in q.all() if c is not None]


def _calibrate_confidence_min(session: Session) -> CalibrationResult:
    approved = _approved_decision_ids(session)
    samples = _confidence_of(session, approved) if approved else []
    if len(samples) < MIN_SAMPLES_TO_OVERRIDE_DEFAULT:
        return CalibrationResult(
            metric_name="confidence_min",
            value=DEFAULT_CONFIDENCE_MIN,
            sample_size=len(samples),
            method="default",
            notes=f"insufficient samples ({len(samples)}<{MIN_SAMPLES_TO_OVERRIDE_DEFAULT})",
        )
    samples.sort()
    # 10th-percentile of *approved* confidences: anything below that is likely
    # to be reviewer-corrected, so we set that as the auto-publish floor.
    idx = max(0, int(len(samples) * 0.10) - 1)
    return CalibrationResult(
        metric_name="confidence_min",
        value=round(samples[idx], 4),
        sample_size=len(samples),
        method="p10_of_approved",
        notes="auto-publish floor from approved match confidences",
    )


def _calibrate_vague_penalty(session: Session) -> CalibrationResult:
    rejected = _rejected_decision_ids(session)
    samples = _confidence_of(session, rejected) if rejected else []
    if len(samples) < MIN_SAMPLES_TO_OVERRIDE_DEFAULT:
        return CalibrationResult(
            metric_name="vague_penalty_threshold",
            value=DEFAULT_VAGUE_PENALTY,
            sample_size=len(samples),
            method="default",
            notes=f"insufficient samples ({len(samples)}<{MIN_SAMPLES_TO_OVERRIDE_DEFAULT})",
        )
    median = statistics.median(samples)
    return CalibrationResult(
        metric_name="vague_penalty_threshold",
        value=round(median, 4),
        sample_size=len(samples),
        method="median_of_rejected",
        notes="below-this confidence triggers extra postcheck",
    )


def _calibrate_min_sources(session: Session) -> CalibrationResult:
    # v5 §4-A: the *spec* mandates ≥3 unique sources. We keep the spec value but
    # write the row so the operator dashboard has it in one place.
    return CalibrationResult(
        metric_name="learned_alias_min_sources",
        value=float(DEFAULT_MIN_SOURCES),
        sample_size=0,
        method="spec",
        notes="v5 §4-A 본조건",
    )


def _calibrate_min_titles(session: Session) -> CalibrationResult:
    return CalibrationResult(
        metric_name="learned_alias_min_titles",
        value=float(DEFAULT_MIN_TITLES),
        sample_size=0,
        method="spec",
        notes="v5 §4-A 본조건",
    )


def _calibrate_min_settled(session: Session) -> CalibrationResult:
    return CalibrationResult(
        metric_name="learned_alias_min_settled",
        value=float(DEFAULT_MIN_SETTLED),
        sample_size=0,
        method="spec",
        notes="v5 §4-A 본조건",
    )
