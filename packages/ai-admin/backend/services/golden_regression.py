"""§8 골든셋 회귀 — track regression between labeling runs.

A "golden set" is a hand-curated mini-dataset that should always classify the
same way. We persist its expected labels as a JSON blob and run it through the
current pipeline; the result vs expected diff is the regression score.

This module exposes:
  - `evaluate(session, golden_rows, current_predictor)` → metrics
  - `compare_runs(session, run_a_id, run_b_id)` → per-mart deltas

It is intentionally side-effect free (no DB writes); the caller decides what to
persist via `LabelingRunLogRepository`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from sqlalchemy.orm import Session

from storage.models import LabelingRunLog


@dataclass
class GoldenRow:
    raw_title: str
    expected_category_id: str
    source_name: str = "golden"


@dataclass
class GoldenEvalResult:
    total: int
    correct: int
    accuracy: float
    misses: list[dict[str, str]]


def evaluate(
    golden_rows: Iterable[GoldenRow],
    predictor: Callable[[GoldenRow], Optional[str]],
) -> GoldenEvalResult:
    rows = list(golden_rows)
    misses: list[dict[str, str]] = []
    correct = 0
    for r in rows:
        predicted = predictor(r) or ""
        if predicted == r.expected_category_id:
            correct += 1
        else:
            misses.append({
                "raw_title": r.raw_title,
                "expected": r.expected_category_id,
                "predicted": predicted,
                "source_name": r.source_name,
            })
    total = len(rows)
    return GoldenEvalResult(
        total=total,
        correct=correct,
        accuracy=(correct / total) if total else 0.0,
        misses=misses,
    )


def compare_runs(session: Session, run_a_id: str, run_b_id: str) -> dict[str, dict[str, int]]:
    """Per-mart delta between two labeling runs (cumulative regression view)."""
    a = session.get(LabelingRunLog, run_a_id)
    b = session.get(LabelingRunLog, run_b_id)
    if a is None or b is None:
        raise KeyError(f"unknown run(s): {run_a_id}, {run_b_id}")
    out: dict[str, dict[str, int]] = {}
    marts = set(a.by_mart.keys()) | set(b.by_mart.keys())
    for m in marts:
        am = a.by_mart.get(m, {}) or {}
        bm = b.by_mart.get(m, {}) or {}
        out[m] = {
            "ai_called_delta": int(bm.get("ai_called", 0)) - int(am.get("ai_called", 0)),
            "ai_resolved_delta": int(bm.get("ai_resolved", 0)) - int(am.get("ai_resolved", 0)),
            "gate_escalated_delta": int(bm.get("gate_escalated", 0)) - int(am.get("gate_escalated", 0)),
        }
    return out
