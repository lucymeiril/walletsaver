"""
통계 신뢰도 엔진.

"싸다고 말하려면 근거가 있어야 한다."

- 이동평균 (SMA, EMA)
- IQR 이상치 제거
- 계절성 보정 (전년 동기 대비)
- 신뢰구간 (±2σ)
- 가격 등급 판정 (역대급/좋은가격/평균/비쌈)
"""

from __future__ import annotations
import math
from typing import Optional
from pydantic import BaseModel


class PriceStats(BaseModel):
    """가격 통계 결과."""
    mean: float           # 평균
    median: float         # 중간값
    std: float            # 표준편차
    low: float            # 최저
    high: float           # 최고
    q1: float             # 1사분위
    q3: float             # 3사분위
    count: int            # 데이터 수
    confidence_low: float # 신뢰구간 하한 (mean - 2σ)
    confidence_high: float# 신뢰구간 상한 (mean + 2σ)
    outliers_removed: int # 제거된 이상치 수
    data_days: int        # 데이터 기간 (일)


class PriceTier(BaseModel):
    """가격 등급 판정 결과."""
    tier: str          # "ultra" | "great" | "good" | "wait" | "bad"
    label: str         # "역대급 기회!" | "좋은 가격" | ...
    icon: str          # "🔥" | "💙" | ...
    ratio: float       # 현재가 / 평균 (0.7 = 30% 저렴)
    description: str   # "현재 1,680원은 평균보다 9% 저렴합니다."


class MovingAverage(BaseModel):
    """이동평균 결과."""
    sma_7: list[float]     # 7일 단순이동평균
    sma_30: list[float]    # 30일 단순이동평균
    ema_7: list[float]     # 7일 지수이동평균


# ===== 핵심 함수 =====

def remove_outliers_iqr(prices: list[float], factor: float = 1.5) -> tuple[list[float], int]:
    """
    IQR 방식으로 이상치 제거.
    factor=1.5 → 일반적, 3.0 → 극단만 제거.
    Returns: (정제된 가격 리스트, 제거된 개수)
    """
    if len(prices) < 4:
        return prices, 0

    sorted_p = sorted(prices)
    n = len(sorted_p)
    q1 = sorted_p[n // 4]
    q3 = sorted_p[3 * n // 4]
    iqr = q3 - q1

    lower = q1 - factor * iqr
    upper = q3 + factor * iqr

    cleaned = [p for p in prices if lower <= p <= upper]
    removed = len(prices) - len(cleaned)
    return cleaned, removed


def compute_stats(prices: list[float], data_days: int = 0) -> PriceStats:
    """가격 리스트에서 통계 계산 (IQR 이상치 제거 포함)."""
    if not prices:
        return PriceStats(
            mean=0, median=0, std=0, low=0, high=0,
            q1=0, q3=0, count=0,
            confidence_low=0, confidence_high=0,
            outliers_removed=0, data_days=data_days,
        )

    cleaned, removed = remove_outliers_iqr(prices)
    if not cleaned:
        cleaned = prices
        removed = 0

    n = len(cleaned)
    sorted_c = sorted(cleaned)
    mean = sum(cleaned) / n
    median = sorted_c[n // 2] if n % 2 else (sorted_c[n//2-1] + sorted_c[n//2]) / 2
    variance = sum((p - mean) ** 2 for p in cleaned) / max(n - 1, 1)
    std = math.sqrt(variance)

    return PriceStats(
        mean=round(mean, 1),
        median=round(median, 1),
        std=round(std, 1),
        low=sorted_c[0],
        high=sorted_c[-1],
        q1=sorted_c[n // 4] if n >= 4 else sorted_c[0],
        q3=sorted_c[3 * n // 4] if n >= 4 else sorted_c[-1],
        count=n,
        confidence_low=round(mean - 2 * std, 1),
        confidence_high=round(mean + 2 * std, 1),
        outliers_removed=removed,
        data_days=data_days,
    )


def simple_moving_average(prices: list[float], window: int) -> list[float]:
    """단순 이동평균 (SMA). window 미만이면 누적 평균."""
    if not prices:
        return []
    result = []
    for i in range(len(prices)):
        start = max(0, i - window + 1)
        window_data = prices[start:i+1]
        result.append(round(sum(window_data) / len(window_data), 1))
    return result


def exponential_moving_average(prices: list[float], window: int) -> list[float]:
    """지수 이동평균 (EMA). 최근 가격에 가중치."""
    if not prices:
        return []
    alpha = 2 / (window + 1)
    result = [prices[0]]
    for i in range(1, len(prices)):
        ema = alpha * prices[i] + (1 - alpha) * result[-1]
        result.append(round(ema, 1))
    return result


def compute_moving_averages(prices: list[float]) -> MovingAverage:
    """7일, 30일 SMA + 7일 EMA 계산."""
    return MovingAverage(
        sma_7=simple_moving_average(prices, 7),
        sma_30=simple_moving_average(prices, 30),
        ema_7=exponential_moving_average(prices, 7),
    )


def determine_tier(current_price: float, stats: PriceStats) -> PriceTier:
    """현재 가격의 등급 판정."""
    if stats.mean == 0:
        return PriceTier(tier="good", label="데이터 부족", icon="❓", ratio=1.0, description="아직 충분한 데이터가 없습니다.")

    ratio = current_price / stats.mean
    diff = current_price - stats.mean
    diff_str = f"+{diff:,.0f}" if diff >= 0 else f"{diff:,.0f}"

    if ratio <= 0.70:
        return PriceTier(
            tier="ultra", label="역대급 기회!", icon="🔥", ratio=round(ratio, 3),
            description=f"현재 {current_price:,.0f}원은 평균보다 {(1-ratio)*100:.0f}% 저렴합니다. 지금 바로 구매하세요!"
        )
    elif ratio <= 0.85:
        return PriceTier(
            tier="great", label="좋은 가격이에요!", icon="💙", ratio=round(ratio, 3),
            description=f"현재 {current_price:,.0f}원은 평균({stats.mean:,.0f}원)보다 {(1-ratio)*100:.0f}% 저렴합니다."
        )
    elif ratio <= 1.05:
        return PriceTier(
            tier="good", label="지금 사도 괜찮아요!", icon="✅", ratio=round(ratio, 3),
            description=f"현재 {current_price:,.0f}원은 평균({stats.mean:,.0f}원) 수준입니다. ({diff_str}원)"
        )
    else:
        return PriceTier(
            tier="wait", label="조금 기다려보세요", icon="⏳", ratio=round(ratio, 3),
            description=f"현재 {current_price:,.0f}원은 평균보다 {(ratio-1)*100:.0f}% 비쌉니다. 할인을 기다려보세요."
        )


def seasonal_comparison(
    current_price: float,
    same_period_last_year: Optional[list[float]] = None,
) -> Optional[dict]:
    """전년 동기 대비 비교."""
    if not same_period_last_year:
        return None
    last_year_avg = sum(same_period_last_year) / len(same_period_last_year)
    change = (current_price - last_year_avg) / last_year_avg * 100
    return {
        "last_year_avg": round(last_year_avg, 1),
        "change_pct": round(change, 1),
        "label": f"전년 동기 대비 {'↑' if change > 0 else '↓'}{abs(change):.1f}%",
    }
