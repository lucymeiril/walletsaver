"""WalletSavior Phase F4 — 주유소 가격 분위수 기반 등급 계산기.

price_grading.py 패턴 준수.
시군구 × 유종 그룹별 분위수 계산 → CHEAP/NORMAL/EXPENSIVE 분류.

분위수 설계:
    P25 이하 → CHEAP      (저렴 — 상위 25% 이하)
    P25~P75 → NORMAL      (보통)
    P75 초과 → EXPENSIVE  (비쌈)
    sample_size < 5 → INSUFFICIENT_DATA

sufficient 기준:
    sample_size >= 5 — 주유소 가격은 지역 내 편차가 작아 5개면 충분.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from core.fuel_models import FuelKind

SUFFICIENT_SAMPLE_THRESHOLD: int = 5
"""분위수 신뢰도 최소 표본 수."""

FuelGradeLabel = Literal["CHEAP", "NORMAL", "EXPENSIVE", "INSUFFICIENT_DATA"]


@dataclass
class FuelPriceGrade:
    """(sido, sigungu, fuel_kind) 별 가격 분위수 등급."""

    sido: str
    sigungu: str
    fuel_kind: FuelKind
    sample_size: int
    p25: Optional[float]    # CHEAP 임계 (이하 → CHEAP)
    p50: Optional[float]    # 중앙가
    p75: Optional[float]    # EXPENSIVE 임계 (초과 → EXPENSIVE)
    computed_at: datetime
    sufficient: bool        # sample_size >= SUFFICIENT_SAMPLE_THRESHOLD


def _percentile(sorted_data: list[float], pct: float) -> float:
    """선형 보간 분위수 (price_grading.py 동일 구현).

    Args:
        sorted_data: 오름차순 정렬된 가격 리스트.
        pct: 0.0–100.0 범위의 분위.
    """
    n = len(sorted_data)
    if n == 1:
        return float(sorted_data[0])
    idx = pct / 100.0 * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return float(sorted_data[-1])
    frac = idx - lo
    return sorted_data[lo] * (1.0 - frac) + sorted_data[hi] * frac


def compute_fuel_grade(
    sido: str,
    sigungu: str,
    fuel_kind: FuelKind,
    prices: list[float],
    computed_at: Optional[datetime] = None,
) -> FuelPriceGrade:
    """분위수 기반 FuelPriceGrade 산출.

    Args:
        sido: 시도명.
        sigungu: 시군구명.
        fuel_kind: 유종.
        prices: 해당 (sido, sigungu, fuel_kind) 그룹의 가격 표본 리스트.
                이미 그룹 필터링된 값만 전달해야 한다.
        computed_at: 산출 시각 (None이면 현재 시각).

    Returns:
        FuelPriceGrade — sufficient=False이면 p25/p75는 None.
        p50(중앙가)은 표본이 1개 이상이면 항상 산출된다.
    """
    if computed_at is None:
        computed_at = datetime.now()

    n = len(prices)
    sufficient = n >= SUFFICIENT_SAMPLE_THRESHOLD

    if n == 0:
        return FuelPriceGrade(
            sido=sido,
            sigungu=sigungu,
            fuel_kind=fuel_kind,
            sample_size=0,
            p25=None,
            p50=None,
            p75=None,
            computed_at=computed_at,
            sufficient=False,
        )

    s = sorted(prices)
    p50 = _percentile(s, 50.0)

    if sufficient:
        p25 = _percentile(s, 25.0)
        p75 = _percentile(s, 75.0)
    else:
        p25 = p75 = None

    return FuelPriceGrade(
        sido=sido,
        sigungu=sigungu,
        fuel_kind=fuel_kind,
        sample_size=n,
        p25=p25,
        p50=p50,
        p75=p75,
        computed_at=computed_at,
        sufficient=sufficient,
    )


def classify_fuel(price: float, grade: FuelPriceGrade) -> FuelGradeLabel:
    """관측 가격을 FuelPriceGrade에 따라 등급으로 분류.

    분류 기준:
        INSUFFICIENT_DATA: 표본 부족(sufficient=False) 또는 p25 미산출.
        CHEAP:             price <= p25
        NORMAL:            p25 < price <= p75
        EXPENSIVE:         price > p75
    """
    if not grade.sufficient or grade.p25 is None:
        return "INSUFFICIENT_DATA"
    if price <= grade.p25:
        return "CHEAP"
    if grade.p75 is not None and price <= grade.p75:
        return "NORMAL"
    return "EXPENSIVE"


def compute_all_fuel_grades(
    observations: list[tuple[str, str, FuelKind, float]],
    computed_at: Optional[datetime] = None,
) -> dict[tuple[str, str, str], FuelPriceGrade]:
    """전체 관측값에서 (sido, sigungu, fuel_kind) 별 등급 산출.

    Args:
        observations: (sido, sigungu, fuel_kind, price) 튜플 리스트.
        computed_at: 산출 시각.

    Returns:
        {(sido, sigungu, fuel_kind.value): FuelPriceGrade}
    """
    if computed_at is None:
        computed_at = datetime.now()

    grouped: dict[tuple[str, str, str], list[float]] = {}
    for sido, sigungu, fuel_kind, price in observations:
        key = (sido, sigungu, fuel_kind.value if isinstance(fuel_kind, FuelKind) else fuel_kind)
        grouped.setdefault(key, []).append(float(price))

    result = {}
    for (sido, sigungu, fk_val), prices in grouped.items():
        fk = FuelKind(fk_val) if not isinstance(fk_val, FuelKind) else fk_val
        result[(sido, sigungu, fk_val)] = compute_fuel_grade(
            sido, sigungu, fk, prices, computed_at
        )
    return result
