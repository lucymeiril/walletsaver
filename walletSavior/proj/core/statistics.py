"""
가격 통계·신뢰도 엔진 — "싸다고 말하려면 근거가 있어야 한다."

왜 존재하는가:
    유저에게 "지금 사도 괜찮아요" vs "기다리세요"를 말하려면 통계적 근거가 필요하다.
    단순 평균만 쓰면 "1원 이벤트"나 입력 오류가 결과를 왜곡하므로,
    IQR 이상치 제거 → 정제된 평균·중간값 산출 → 신뢰구간 계산 → 등급 판정 파이프라인을 거친다.
어디서 쓰이는가:
    storage에서 ProductPrice 리스트 조회 → compute_stats()로 통계 산출 →
    determine_tier()로 등급 판정 → API 응답 / 대시보드 표시.

왜 IQR이고 z-score가 아닌가:
    식료품 가격은 정규분포가 아니라 오른쪽 꼬리(프리미엄 제품)가 긴 분포다.
    z-score는 정규분포를 가정하므로 이런 비대칭 분포에서 이상치를 놓친다.
    IQR은 분포 형태에 무관하게 사분위수 기반으로 동작하여 더 안정적이다.

왜 SMA와 EMA를 둘 다 제공하는가:
    SMA(단순이동평균)는 추세 파악, EMA(지수이동평균)는 최근 급등락 감지에 유리하다.
    대시보드에서 두 선을 겹쳐 보여주면 "최근 급등"인지 "장기 상승"인지 구분 가능.
"""

from __future__ import annotations
import math
from typing import Optional
from pydantic import BaseModel


class PriceStats(BaseModel):
    """이상치 제거 후 산출된 가격 통계 — determine_tier()의 입력이자 API 응답의 핵심 데이터."""
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
    """
    현재가의 "살까 말까" 등급 판정 결과 — 유저에게 직접 보여주는 최종 결론.

    tier 값의 의미:
        ultra (ratio ≤ 0.70): 평균 대비 30%+ 저렴, 역대급 — 즉시 구매 권장
        great (ratio ≤ 0.85): 15~30% 저렴 — 좋은 가격
        good  (ratio ≤ 1.05): ±5% 이내 — 평균 수준, 사도 무방
        wait  (ratio > 1.05): 5%+ 비쌈 — 할인 대기 권장
    """
    tier: str          # "ultra" | "great" | "good" | "wait" | "bad"
    label: str         # "역대급 기회!" | "좋은 가격" | ...
    icon: str          # "🔥" | "💙" | ...
    ratio: float       # 현재가 / 평균 (0.7 = 30% 저렴)
    description: str   # "현재 1,680원은 평균보다 9% 저렴합니다."


class MovingAverage(BaseModel):
    """이동평균 계산 결과 — 대시보드 가격 추세 차트의 데이터 소스."""
    sma_7: list[float]     # 7일 단순이동평균
    sma_30: list[float]    # 30일 단순이동평균
    ema_7: list[float]     # 7일 지수이동평균


# ===== 핵심 함수 =====

def remove_outliers_iqr(prices: list[float], factor: float = 1.5) -> tuple[list[float], int]:
    """
    핫딜이나 입력 오류로 들어온 비정상 가격을 평균 산출에서 제외한다.

    왜 필요한가: 마트 크롤링 시 "1원 이벤트" 같은 이상치가 평균가를 왜곡한다.
    왜 IQR인가: 식료품 가격은 정규분포가 아니라 z-score보다 IQR이 안정적이다.
    factor=1.5는 통계학 표준(Tukey fence), 3.0은 극단값만 제거할 때 사용.
    어디서 쓰이나: compute_stats() → 이 함수 → 정제된 리스트
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
    """
    원시 가격 리스트를 이상치 제거 후 통계로 요약한다 — 등급 판정의 기반.

    어디서 쓰이나: storage에서 ProductPrice 리스트 조회 → 이 함수 → PriceStats → determine_tier()
    """
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
    """단순 이동평균 (SMA) — 장기 추세 파악용. 대시보드 차트에서 "전체 흐름" 라인으로 표시."""
    if not prices:
        return []
    result = []
    for i in range(len(prices)):
        start = max(0, i - window + 1)
        window_data = prices[start:i+1]
        result.append(round(sum(window_data) / len(window_data), 1))
    return result


def exponential_moving_average(prices: list[float], window: int) -> list[float]:
    """지수 이동평균 (EMA) — 최근 가격에 가중치를 두어 급등락을 SMA보다 빠르게 반영한다."""
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
    """
    현재가를 통계 기반으로 등급 판정한다 — 유저가 보는 최종 "사도 될까?" 결론.

    임계값 근거 (한국 식료품 시장 기준):
        ≤ 0.70: 평균의 70% 이하는 역대급 할인 — 대형마트 특가전에서도 드문 수준
        ≤ 0.85: 전단 할인 수준 — 충분히 좋은 가격
        ≤ 1.05: ±5%는 일상적 가격 변동 범위 — 굳이 기다릴 필요 없음
        > 1.05: 명확히 비쌈 — 할인 시즌 대기 권장
    """
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
    """
    전년 동기 대비 비교 — 계절성 식품(수박, 딸기 등)의 "올해가 비싼 건지" 판단 근거.

    왜 필요한가: 딸기가 12월에 비싼 건 당연하다. 작년 12월 대비 더 비싼지가 진짜 정보다.
    """
    if not same_period_last_year:
        return None
    last_year_avg = sum(same_period_last_year) / len(same_period_last_year)
    change = (current_price - last_year_avg) / last_year_avg * 100
    return {
        "last_year_avg": round(last_year_avg, 1),
        "change_pct": round(change, 1),
        "label": f"전년 동기 대비 {'↑' if change > 0 else '↓'}{abs(change):.1f}%",
    }
