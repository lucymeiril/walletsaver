"""WalletSavior Phase D1 — 가격 분위수 기반 등급 계산기.

정책 (repo memory 준수):
    마트4사+쿠팡 최근 N개월 PriceObservation의 unit_price_normalized(원/표준단위)를
    분위수로 분석해 품목별 가격 등급을 산출한다.
    KAMIS(공공 데이터) 가격은 절대 사용하지 않는다.

분위수 설계:
    P10 = 핫딜가 임계 (이하 → HOT_DEAL)
    P25 = 세일가 임계 (P10 초과 P25 이하 → SALE)
    P50 = 중앙가 (기준가)
    P75 = 상한 임계 (초과 → OVERPRICED; 이하 → NORMAL)

sufficient 기준:
    sample_size >= 5 — 5개 미만은 분위수 신뢰도 부족 → INSUFFICIENT_DATA.
    이 임계는 운영 초기에 fixture 기반으로만 운영될 때를 감안한 최소 기준이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

SUFFICIENT_SAMPLE_THRESHOLD: int = 5
"""분위수 신뢰도 최소 표본 수."""


@dataclass
class PriceGrade:
    """canonical_id별 가격 분위수 등급."""

    canonical_id: str
    window_months: int
    sample_size: int
    p10: Optional[float]   # 핫딜가 임계 (HOT_DEAL ≤ p10)
    p25: Optional[float]   # 세일가 임계 (SALE ≤ p25)
    p50: Optional[float]   # 중앙가
    p75: Optional[float]   # 상한 임계 (OVERPRICED > p75)
    computed_at: datetime
    sufficient: bool        # sample_size >= SUFFICIENT_SAMPLE_THRESHOLD


GradeLabel = Literal["HOT_DEAL", "SALE", "NORMAL", "OVERPRICED", "INSUFFICIENT_DATA"]


def _percentile(sorted_data: list[float], pct: float) -> float:
    """선형 보간 분위수 (0.0–100.0 범위).

    Args:
        sorted_data: 오름차순 정렬된 가격 리스트. 비어있으면 안 됨.
        pct: 0.0–100.0 범위의 분위.

    Returns:
        선형 보간된 분위수 값.

    왜 선형 보간인가:
        Python statistics.quantiles는 기본적으로 exclusive method를 사용하지만,
        표본 크기가 작을 때 경계값 처리가 다르다. 선형 보간(method='inclusive'와 유사)은
        직관적이고 예측 가능하며, R의 type 7(기본)과 동일한 결과를 낸다.
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


def compute_price_grade(
    canonical_id: str,
    prices: list[float],
    window_months: int = 6,
    computed_at: Optional[datetime] = None,
) -> PriceGrade:
    """분위수 기반 PriceGrade 산출.

    Args:
        canonical_id: 상품 식별자.
        prices: 해당 canonical_id의 가격 표본 리스트
                (unit_price_normalized 우선, 없으면 sale_price 폴백).
                이미 window_months 기간으로 필터링된 값만 전달해야 한다.
        window_months: 집계 기간 (월) — 기록용. 실제 필터링은 호출자가 수행.
        computed_at: 산출 시각 (None이면 현재 시각).

    Returns:
        PriceGrade — sufficient=False이면 p10/p25/p75는 None.
        p50(중앙가)은 표본이 1개 이상이면 항상 산출된다.
    """
    if computed_at is None:
        computed_at = datetime.now()

    n = len(prices)
    sufficient = n >= SUFFICIENT_SAMPLE_THRESHOLD

    if n == 0:
        return PriceGrade(
            canonical_id=canonical_id,
            window_months=window_months,
            sample_size=0,
            p10=None,
            p25=None,
            p50=None,
            p75=None,
            computed_at=computed_at,
            sufficient=False,
        )

    s = sorted(prices)
    p50 = _percentile(s, 50.0)

    if sufficient:
        p10 = _percentile(s, 10.0)
        p25 = _percentile(s, 25.0)
        p75 = _percentile(s, 75.0)
    else:
        p10 = p25 = p75 = None

    return PriceGrade(
        canonical_id=canonical_id,
        window_months=window_months,
        sample_size=n,
        p10=p10,
        p25=p25,
        p50=p50,
        p75=p75,
        computed_at=computed_at,
        sufficient=sufficient,
    )


def classify(observed_price: float, grade: PriceGrade) -> GradeLabel:
    """관측 가격을 PriceGrade에 따라 등급으로 분류한다.

    분류 기준:
        INSUFFICIENT_DATA: 표본 부족(sufficient=False) 또는 p10 미산출.
        HOT_DEAL:          observed_price <= p10
        SALE:              p10 < observed_price <= p25
        NORMAL:            p25 < observed_price <= p75
        OVERPRICED:        observed_price > p75

    Args:
        observed_price: 현재 관측 가격 (단위: 원/표준단위 또는 raw price).
        grade: compute_price_grade()로 산출된 PriceGrade.

    Returns:
        GradeLabel 문자열.
    """
    if not grade.sufficient or grade.p10 is None:
        return "INSUFFICIENT_DATA"
    if observed_price <= grade.p10:
        return "HOT_DEAL"
    if grade.p25 is not None and observed_price <= grade.p25:
        return "SALE"
    if grade.p75 is not None and observed_price <= grade.p75:
        return "NORMAL"
    return "OVERPRICED"
