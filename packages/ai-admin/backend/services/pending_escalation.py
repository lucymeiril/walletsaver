"""pending_db_review 자동 escalation 룰.

역할:
    ai_publish_records 중 pending_db_review 상태의 건을 세 규칙으로 처리한다.

    Rule A (AUTO_PUBLISH):
        db_ingestion_id 있음 + eligibility_errors=[] + last_error=None
        + publish_attempts < MAX_ATTEMPTS + 경과 시간 < STALE_ALARM_HOURS
        → ai_safe_final_approve 자동 호출 대상

    Rule B (HUMAN_REVIEW):
        db_ingestion_id 있지만 에러/blockers 존재, 또는 attempts 초과
        → escalation 큐 사람 검토 대상

    Rule C (ALARM):
        requested_at 으로부터 STALE_ALARM_HOURS 초과 → 알람 플래그

임계값 근거:
    STALE_ALARM_HOURS=24: 업무일 기준 1일 대기는 운영 기준 초과.
    STALE_ALARM_COUNT=100: 배치 1회 평균 처리 건수를 고려한 임계.
    MAX_PUBLISH_ATTEMPTS=5: 재시도 3회 이상은 구조적 문제를 시사.
    CONFIDENCE_MIN=0.7: postcheck_gate C2 Gate2 기준과 동일.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from storage.models import AIPublishRecord

# ─── 임계값 상수 ──────────────────────────────────────────────────────────────
STALE_ALARM_HOURS: int = 24
"""이 시간(시) 이상 pending_db_review 상태이면 Rule C 알람."""

STALE_ALARM_COUNT: int = 100
"""pending_db_review 건수가 이 수 이상이면 알람."""

MAX_PUBLISH_ATTEMPTS: int = 5
"""publish_attempts 이 값 이상이면 Rule A 자동 발행 차단, Rule B 인간 검토."""

CONFIDENCE_MIN: float = 0.7
"""최소 신뢰도 임계값 (eligibility_errors 내 confidence 실패 여부 판단)."""

RECENT_STALE_HOURS: int = 1
"""'최근 1시간 정체' 카운터 기준 시간."""


# ─── 게이트 정의 ──────────────────────────────────────────────────────────────
# Rule A를 위한 4개 게이트 이름
GATE_DB_SUBMITTED = "gate_db_submitted"       # Gate 1: db_ingestion_id 존재
GATE_NO_ERRORS = "gate_no_errors"             # Gate 2: eligibility_errors=[] + last_error None
GATE_ATTEMPTS_OK = "gate_attempts_ok"         # Gate 3: publish_attempts < MAX_PUBLISH_ATTEMPTS
GATE_NOT_STALE = "gate_not_stale"             # Gate 4: 경과시간 < STALE_ALARM_HOURS


@dataclass
class GateResult:
    """단일 게이트 평가 결과."""
    name: str
    passed: bool
    reason: str


@dataclass
class EscalationDecision:
    """한 건의 pending_db_review 레코드에 대한 escalation 판정."""
    raw_record_id: str
    batch_id: str
    source_name: str
    db_ingestion_id: Optional[str]
    publish_attempts: int
    requested_at: Optional[datetime]
    hours_stale: float
    is_stale: bool                                          # Rule C 알람 여부
    rule: Literal["auto_publish", "human_review", "alarm"]  # 적용 규칙
    gates: list[GateResult] = field(default_factory=list)
    gate_passed_count: int = 0
    blockers: list[str] = field(default_factory=list)
    last_error: Optional[str] = None


def _hours_since(dt: Optional[datetime]) -> float:
    """datetime 으로부터 경과 시간(시)을 반환한다. None이면 매우 큰 값 반환."""
    if dt is None:
        return float("inf")
    return (datetime.now() - dt).total_seconds() / 3600


def evaluate_pending_record(record: AIPublishRecord) -> EscalationDecision:
    """한 건의 pending_db_review 레코드에 escalation 룰을 평가한다.

    4개 게이트를 순서대로 평가하고, 모두 통과하면 Rule A(AUTO_PUBLISH),
    일부만 통과하면 Rule B(HUMAN_REVIEW), 24h 초과면 Rule C(ALARM).
    Rule C는 Rule A/B와 중복 적용 가능하다 (알람 + 처리 큐 동시 발생).
    """
    hours_stale = _hours_since(record.requested_at)
    is_stale = hours_stale >= STALE_ALARM_HOURS

    # 4개 게이트 평가 ────────────────────────────────────────────────────────
    gates: list[GateResult] = [
        GateResult(
            name=GATE_DB_SUBMITTED,
            passed=bool(record.db_ingestion_id),
            reason=(
                "db_ingestion_id 있음 — db-admin에 제출됨"
                if record.db_ingestion_id
                else "db_ingestion_id 없음 — db-admin 미제출 상태"
            ),
        ),
        GateResult(
            name=GATE_NO_ERRORS,
            passed=(not record.eligibility_errors and not record.last_error),
            reason=(
                "eligibility_errors=[] + last_error=None"
                if (not record.eligibility_errors and not record.last_error)
                else f"eligibility_errors={record.eligibility_errors} | last_error={record.last_error}"
            ),
        ),
        GateResult(
            name=GATE_ATTEMPTS_OK,
            passed=(record.publish_attempts < MAX_PUBLISH_ATTEMPTS),
            reason=(
                f"publish_attempts={record.publish_attempts} < {MAX_PUBLISH_ATTEMPTS}"
                if record.publish_attempts < MAX_PUBLISH_ATTEMPTS
                else f"publish_attempts={record.publish_attempts} >= {MAX_PUBLISH_ATTEMPTS} (자동 발행 차단)"
            ),
        ),
        GateResult(
            name=GATE_NOT_STALE,
            passed=not is_stale,
            reason=(
                f"경과 {hours_stale:.1f}h < {STALE_ALARM_HOURS}h 알람 임계"
                if not is_stale
                else f"경과 {hours_stale:.1f}h >= {STALE_ALARM_HOURS}h — Rule C 알람 대상"
            ),
        ),
    ]

    gate_passed_count = sum(1 for g in gates if g.passed)
    blockers = [g.reason for g in gates if not g.passed]

    # 규칙 결정: 4개 모두 통과 → Rule A, 아니면 Rule B, 알람이면 Rule C 우선
    if is_stale:
        rule: Literal["auto_publish", "human_review", "alarm"] = "alarm"
    elif gate_passed_count == 4:
        rule = "auto_publish"
    else:
        rule = "human_review"

    return EscalationDecision(
        raw_record_id=record.raw_record_id,
        batch_id=record.batch_id,
        source_name=record.source_name,
        db_ingestion_id=record.db_ingestion_id,
        publish_attempts=record.publish_attempts,
        requested_at=record.requested_at,
        hours_stale=hours_stale,
        is_stale=is_stale,
        rule=rule,
        gates=gates,
        gate_passed_count=gate_passed_count,
        blockers=blockers,
        last_error=record.last_error,
    )


def run_escalation_sweep(session) -> dict[str, Any]:
    """pending_db_review 전체를 평가하여 결과를 반환한다 (DB 변경 없음).

    실제 ai_safe_final_approve 호출은 escalation 라우트에서 비동기로 처리한다.
    """
    records: list[AIPublishRecord] = (
        session.query(AIPublishRecord)
        .filter(AIPublishRecord.status == "pending_db_review")
        .order_by(AIPublishRecord.requested_at)
        .all()
    )

    decisions = [evaluate_pending_record(r) for r in records]

    auto_publish = [d for d in decisions if d.rule == "auto_publish"]
    human_review = [d for d in decisions if d.rule == "human_review"]
    alarm_items = [d for d in decisions if d.rule == "alarm"]

    now = datetime.now()
    stale_1h = [
        d for d in decisions
        if d.requested_at and (now - d.requested_at) <= timedelta(hours=RECENT_STALE_HOURS)
        and d.is_stale
    ]

    return {
        "total_pending": len(decisions),
        "auto_publish_count": len(auto_publish),
        "human_review_count": len(human_review),
        "alarm_count": len(alarm_items),
        "recent_stale_1h_count": len(stale_1h),
        "alarm_triggered": len(alarm_items) > 0 or len(decisions) >= STALE_ALARM_COUNT,
        "alarm_reason": _alarm_reason(decisions),
        "auto_publish_items": [_decision_to_dict(d) for d in auto_publish],
        "human_review_items": [_decision_to_dict(d) for d in human_review],
        "alarm_items": [_decision_to_dict(d) for d in alarm_items],
        "all_items": [_decision_to_dict(d) for d in decisions],
    }


def get_alarm_status(session) -> dict[str, Any]:
    """알람 상태만 빠르게 조회한다 (UI 폴링용)."""
    records: list[AIPublishRecord] = (
        session.query(AIPublishRecord)
        .filter(AIPublishRecord.status == "pending_db_review")
        .all()
    )
    decisions = [evaluate_pending_record(r) for r in records]
    alarm_items = [d for d in decisions if d.rule == "alarm"]
    total = len(decisions)

    # 가장 오래된 정체 건의 경과 시간
    max_hours = max((d.hours_stale for d in decisions if d.hours_stale != float("inf")), default=0.0)

    triggered = bool(alarm_items) or total >= STALE_ALARM_COUNT
    return {
        "alarm_triggered": triggered,
        "total_pending": total,
        "stale_count": len(alarm_items),
        "max_stale_hours": round(max_hours, 1),
        "alarm_reason": _alarm_reason(decisions),
        "thresholds": {
            "stale_alarm_hours": STALE_ALARM_HOURS,
            "stale_alarm_count": STALE_ALARM_COUNT,
        },
    }


def get_pending_for_ui(session) -> dict[str, Any]:
    """escalation 큐 UI용 전체 데이터를 반환한다."""
    records: list[AIPublishRecord] = (
        session.query(AIPublishRecord)
        .filter(AIPublishRecord.status == "pending_db_review")
        .order_by(AIPublishRecord.requested_at)
        .all()
    )
    decisions = [evaluate_pending_record(r) for r in records]

    now = datetime.now()
    recent_1h_count = sum(
        1 for d in decisions
        if d.requested_at and (now - d.requested_at) <= timedelta(hours=RECENT_STALE_HOURS)
    )
    alarm_status = get_alarm_status(session)

    return {
        "total_pending": len(decisions),
        "recent_stale_1h_count": recent_1h_count,
        "alarm": alarm_status,
        "items": [_decision_to_dict(d) for d in decisions],
    }


def _alarm_reason(decisions: list[EscalationDecision]) -> Optional[str]:
    """알람 사유 문자열을 반환한다 (알람 없으면 None)."""
    alarm_items = [d for d in decisions if d.rule == "alarm"]
    total = len(decisions)
    reasons = []
    if alarm_items:
        reasons.append(f"{len(alarm_items)}건이 {STALE_ALARM_HOURS}시간 이상 정체")
    if total >= STALE_ALARM_COUNT:
        reasons.append(f"총 정체 {total}건 >= 임계 {STALE_ALARM_COUNT}건")
    return "; ".join(reasons) if reasons else None


def _decision_to_dict(d: EscalationDecision) -> dict[str, Any]:
    """EscalationDecision을 JSON-직렬화 가능한 dict로 변환한다."""
    return {
        "raw_record_id": d.raw_record_id,
        "batch_id": d.batch_id,
        "source_name": d.source_name,
        "db_ingestion_id": d.db_ingestion_id,
        "publish_attempts": d.publish_attempts,
        "requested_at": d.requested_at.isoformat() if d.requested_at else None,
        "hours_stale": round(d.hours_stale, 1) if d.hours_stale != float("inf") else None,
        "is_stale": d.is_stale,
        "rule": d.rule,
        "gate_passed_count": d.gate_passed_count,
        "gates": [
            {"name": g.name, "passed": g.passed, "reason": g.reason}
            for g in d.gates
        ],
        "blockers": d.blockers,
        "last_error": d.last_error,
    }
