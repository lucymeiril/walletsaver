"""
마트별 최소 카운트 게이트 — crawler-FINAL §2-3 / §6-A / §6-C 의 *볼륨 게이트*.

yaml `output.minimum_rows` 를 1차 소스로 사용하되, 마트별 라이브 실측 기준값을
*하한* 으로 갖는다 (yaml 이 무지성 0 인 경우에도 라이브 게이트가 작동하도록).

본 게이트는 pipeline.quality 의 일부로 호출되거나, 독립 진단으로도 호출 가능.
판정 결과:
- pass    : minimum_rows 이상
- below   : 임계 미달 — 즉시 알람
- baseline: yaml 도 라이브 실측도 없음 — 게이트 생략 + 진단 신호만
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class GateStatus(str, Enum):
    PASS = "pass"
    BELOW = "below"
    BASELINE_MISSING = "baseline_missing"


@dataclass
class GateVerdict:
    status: GateStatus
    source_id: str
    actual: int
    threshold: int
    reason: str = ""

    def is_pass(self) -> bool:
        return self.status == GateStatus.PASS


# crawler-FINAL §2-3 라이브 실측 임계 (yaml 미설정 시 하한).
# - 이마트  : 직전 라운드 ~274 → 270
# - 롯데마트: 3회 연속 240 → 240
# - 홈플러스: 임계 근접 → 195
# - 코스트코: 3회 연속 995, 안전마진 95 → 900
# - 코코달인: 임시 → 50
LIVE_THRESHOLDS: dict[str, int] = {
    "emart": 270,
    "lottemart": 240,
    "homeplus": 195,
    "costco": 900,
    "cocodalin": 50,
    "cocodalin_mart": 50,
}


def threshold_for(source_id: str, yaml_minimum: Optional[int] = None) -> int:
    """게이트가 적용할 임계.

    우선순위:
      1) yaml `output.minimum_rows` (> 0)
      2) LIVE_THRESHOLDS[source_id]
      3) 0 (게이트 사실상 비활성)
    """
    if yaml_minimum is not None and yaml_minimum > 0:
        return int(yaml_minimum)
    return int(LIVE_THRESHOLDS.get(source_id, 0))


def check(source_id: str, row_count: int, yaml_minimum: Optional[int] = None) -> GateVerdict:
    th = threshold_for(source_id, yaml_minimum)
    if th <= 0:
        return GateVerdict(
            status=GateStatus.BASELINE_MISSING,
            source_id=source_id,
            actual=row_count,
            threshold=th,
            reason="yaml 미설정 + 라이브 baseline 없음",
        )
    if row_count >= th:
        return GateVerdict(
            status=GateStatus.PASS,
            source_id=source_id,
            actual=row_count,
            threshold=th,
        )
    return GateVerdict(
        status=GateStatus.BELOW,
        source_id=source_id,
        actual=row_count,
        threshold=th,
        reason=f"row_count {row_count} < threshold {th}",
    )
