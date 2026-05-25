"""
4-라벨 drift 감지 — crawler-FINAL §4-B.

기존 source_health 의 단일 drift 점수는 false positive 가 많다.
4종으로 분리:
- parser_drift          : selector hit ↓ + HTML 구조 hash 변화 + fixture 도 실패
- source_volume_anomaly : row count 만 ↓, selector hit 유지 (행사 종료 등 비즈니스 변동)
- session_state_loss    : 로그인/지역/회원가 probe 실패
- catalog_business_change: 신규 카테고리 / 가격 표시 변경 / 상품명 일괄 변경

본 모듈은 *판정* 만 한다 — 알람/UI/큐 진입은 호출자가 결정.
baseline: 전년/전월/요일 평균 + 단골 probe 키워드 (호출자가 제공).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DriftLabel(str, Enum):
    NONE = "none"
    PARSER_DRIFT = "parser_drift"
    SOURCE_VOLUME_ANOMALY = "source_volume_anomaly"
    SESSION_STATE_LOSS = "session_state_loss"
    CATALOG_BUSINESS_CHANGE = "catalog_business_change"


@dataclass
class DriftSignals:
    """드리프트 판정 입력. 누락 필드는 보수적으로 '신호 없음' 으로 본다."""
    source_id: str
    row_count: int = 0
    baseline_row_count: Optional[int] = None
    selector_hit_rate: Optional[float] = None       # 0.0~1.0, fixture 검증 결과
    baseline_selector_hit_rate: Optional[float] = None
    fixture_passes: bool = True                     # fixture replay 성공 여부
    html_structure_hash: Optional[str] = None
    baseline_html_structure_hash: Optional[str] = None
    login_probe_ok: bool = True
    region_probe_ok: bool = True
    member_price_probe_ok: bool = True
    new_categories_seen: int = 0                    # baseline 대비 신규 카테고리 수
    title_change_ratio: float = 0.0                 # 0.0~1.0, 상품명 일괄 변경 비율
    price_display_format_changed: bool = False


@dataclass
class DriftVerdict:
    label: DriftLabel
    confidence: float                               # 0.0~1.0
    reasons: list[str] = field(default_factory=list)
    recommended_action: str = ""


def _ratio(a: int, b: Optional[int]) -> Optional[float]:
    if b is None or b <= 0:
        return None
    return a / b


def classify(signals: DriftSignals) -> DriftVerdict:
    """4-라벨 분류. 가장 강한 신호 1개 선택 (multi-label 은 호출자 책임).

    판정 우선순위 (FINAL §4-B 표 순서):
      1) parser_drift          (가장 위험 — 운영자 즉시 개입)
      2) session_state_loss    (profile refresh queue)
      3) catalog_business_change
      4) source_volume_anomaly
    """
    reasons: list[str] = []

    # 1) parser_drift — selector hit ↓ AND (구조 hash 변화 OR fixture 실패)
    hit_now = signals.selector_hit_rate
    hit_base = signals.baseline_selector_hit_rate
    hit_dropped = (
        hit_now is not None and hit_base is not None
        and hit_now < hit_base * 0.7 and hit_base > 0.0
    )
    hash_changed = (
        signals.html_structure_hash and signals.baseline_html_structure_hash
        and signals.html_structure_hash != signals.baseline_html_structure_hash
    )
    if hit_dropped and (hash_changed or not signals.fixture_passes):
        reasons.append(f"selector_hit {hit_now:.2f} ↓ from {hit_base:.2f}")
        if hash_changed:
            reasons.append("HTML 구조 hash 변경")
        if not signals.fixture_passes:
            reasons.append("fixture replay 실패")
        return DriftVerdict(
            label=DriftLabel.PARSER_DRIFT,
            confidence=0.95 if (hash_changed and not signals.fixture_passes) else 0.85,
            reasons=reasons,
            recommended_action="셀렉터 편집 UI 즉시",
        )

    # 2) session_state_loss
    probes = {
        "login_probe": signals.login_probe_ok,
        "region_probe": signals.region_probe_ok,
        "member_price_probe": signals.member_price_probe_ok,
    }
    failed = [name for name, ok in probes.items() if not ok]
    if failed:
        return DriftVerdict(
            label=DriftLabel.SESSION_STATE_LOSS,
            confidence=0.9,
            reasons=[f"probe 실패: {', '.join(failed)}"],
            recommended_action="profile refresh queue",
        )

    # 3) catalog_business_change
    if (
        signals.new_categories_seen >= 1
        or signals.title_change_ratio >= 0.3
        or signals.price_display_format_changed
    ):
        cr = []
        if signals.new_categories_seen >= 1:
            cr.append(f"신규 카테고리 {signals.new_categories_seen}")
        if signals.title_change_ratio >= 0.3:
            cr.append(f"상품명 변경비율 {signals.title_change_ratio:.0%}")
        if signals.price_display_format_changed:
            cr.append("가격 표시 형식 변경")
        return DriftVerdict(
            label=DriftLabel.CATALOG_BUSINESS_CHANGE,
            confidence=0.7,
            reasons=cr,
            recommended_action="운영자 검토 — 코드 수정 가능성",
        )

    # 4) source_volume_anomaly — row count 만 ↓, selector hit 유지
    ratio = _ratio(signals.row_count, signals.baseline_row_count)
    if ratio is not None and ratio < 0.5:
        # selector hit 가 정상 (baseline 의 90% 이상) 이거나 측정 없음 → volume_anomaly
        selector_ok = (
            hit_now is None
            or hit_base is None
            or (hit_now >= hit_base * 0.9)
        )
        if selector_ok:
            return DriftVerdict(
                label=DriftLabel.SOURCE_VOLUME_ANOMALY,
                confidence=0.6,
                reasons=[f"row {signals.row_count} / baseline {signals.baseline_row_count} ({ratio:.0%})"],
                recommended_action="알람 약함, 7일 baseline 비교 후 결정",
            )

    return DriftVerdict(label=DriftLabel.NONE, confidence=1.0, reasons=[], recommended_action="")
