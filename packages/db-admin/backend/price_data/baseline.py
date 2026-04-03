"""
확장 기준가 계산기 — 통계 분석, 이상치 제거, 계절 보정, 추세 분석.

price_calc.py가 DB 세션 기반이라면, 이 모듈은 순수 데이터(리스트)를 입력받아
더 깊은 통계 분석을 제공한다. 테스트에서 DB 없이 독립적으로 사용 가능.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional


def remove_outliers_iqr(
    prices: list[float], factor: float = 1.5
) -> tuple[list[float], list[float]]:
    """
    IQR 기반 이상치 제거.

    Returns: (정제된 리스트, 제거된 이상치 리스트)
    """
    if len(prices) < 4:
        return list(prices), []

    sorted_p = sorted(prices)
    n = len(sorted_p)
    q1 = sorted_p[n // 4]
    q3 = sorted_p[3 * n // 4]
    iqr = q3 - q1

    lower = q1 - factor * iqr
    upper = q3 + factor * iqr

    cleaned = [p for p in prices if lower <= p <= upper]
    outliers = [p for p in prices if p < lower or p > upper]
    return cleaned, outliers


def calculate_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def calculate_median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def calculate_mode(values: list[float], round_to: int = -1) -> Optional[float]:
    """
    최빈값 계산. round_to로 반올림 단위 지정 (예: -1 → 10원 단위).
    """
    if not values:
        return None
    rounded = [round(v, round_to) if round_to >= 0 else round(v / (10 ** abs(round_to))) * (10 ** abs(round_to)) for v in values]
    counter = Counter(rounded)
    most_common = counter.most_common(1)
    return most_common[0][0] if most_common else None


def calculate_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = calculate_mean(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def calculate_percentile(values: list[float], percentile: float) -> float:
    """백분위수 계산 (0-100)."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    k = (percentile / 100) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def full_statistics(prices: list[float]) -> dict:
    """
    가격 리스트의 종합 통계를 계산한다.

    Returns: {
        "count", "mean", "median", "mode", "std",
        "min", "max", "q1", "q3", "iqr",
        "p10", "p25", "p75", "p90",
        "cv" (변동계수), "skewness"
    }
    """
    if not prices:
        return {
            "count": 0, "mean": 0, "median": 0, "mode": None, "std": 0,
            "min": 0, "max": 0, "q1": 0, "q3": 0, "iqr": 0,
            "p10": 0, "p25": 0, "p75": 0, "p90": 0,
            "cv": 0, "skewness": 0,
        }

    cleaned, outliers = remove_outliers_iqr(prices)
    if not cleaned:
        cleaned = list(prices)

    mean = calculate_mean(cleaned)
    std = calculate_std(cleaned)
    q1 = calculate_percentile(cleaned, 25)
    q3 = calculate_percentile(cleaned, 75)

    # 왜도 (skewness): 양수 = 오른쪽 꼬리, 음수 = 왼쪽 꼬리
    skewness = 0.0
    if std > 0 and len(cleaned) >= 3:
        n = len(cleaned)
        skewness = (n / ((n - 1) * (n - 2))) * sum(((v - mean) / std) ** 3 for v in cleaned)

    return {
        "count": len(cleaned),
        "mean": round(mean, 1),
        "median": round(calculate_median(cleaned), 1),
        "mode": calculate_mode(cleaned),
        "std": round(std, 1),
        "min": min(cleaned),
        "max": max(cleaned),
        "q1": round(q1, 1),
        "q3": round(q3, 1),
        "iqr": round(q3 - q1, 1),
        "p10": round(calculate_percentile(cleaned, 10), 1),
        "p25": round(q1, 1),
        "p75": round(q3, 1),
        "p90": round(calculate_percentile(cleaned, 90), 1),
        "cv": round(std / mean * 100, 2) if mean > 0 else 0,
        "skewness": round(skewness, 3),
        "outliers_removed": len(outliers),
    }


# ═══════════════════════════════════════════════
# 계절 보정 (Seasonal Adjustment)
# ═══════════════════════════════════════════════

# 농산물 월별 계절 지수 (1.0 = 평균, >1.0 = 비싼 계절)
SEASONAL_INDICES: dict[str, list[float]] = {
    "배추":   [1.20, 1.15, 1.30, 1.10, 0.95, 0.85, 0.80, 0.75, 0.70, 0.65, 0.80, 1.00],
    "딸기":   [0.85, 0.70, 0.75, 0.90, 1.10, 1.30, 1.40, 1.50, 1.30, 1.10, 0.90, 0.80],
    "수박":   [1.50, 1.40, 1.20, 1.00, 0.80, 0.65, 0.55, 0.60, 0.80, 1.10, 1.30, 1.50],
    "포도":   [1.30, 1.25, 1.40, 1.20, 1.00, 0.85, 0.70, 0.65, 0.60, 0.80, 1.10, 1.25],
    "사과":   [1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.10, 0.95, 0.80, 0.70, 0.85, 0.95],
    "귤":     [1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.20, 1.00, 0.85, 0.70, 0.65, 0.60],
    "시금치": [0.80, 0.85, 0.90, 1.00, 1.10, 1.20, 1.40, 1.30, 1.10, 0.95, 0.85, 0.75],
    "상추":   [0.90, 0.85, 0.80, 0.70, 0.85, 1.00, 1.30, 1.40, 1.20, 1.00, 0.95, 0.90],
    "토마토": [1.30, 1.20, 1.10, 0.95, 0.80, 0.70, 0.65, 0.75, 0.85, 1.00, 1.15, 1.25],
    "대파":   [0.90, 0.85, 0.95, 1.00, 1.10, 1.20, 1.35, 1.40, 1.20, 1.00, 0.80, 0.85],
}


def get_seasonal_factor(product_name: str, month: int) -> float:
    """
    제품명과 월로 계절 보정 계수를 반환한다.

    Returns: 계절 지수 (1.0 = 평균, >1.0 = 비싼 계절)
    """
    if month < 1 or month > 12:
        return 1.0
    indices = SEASONAL_INDICES.get(product_name)
    if indices is None:
        return 1.0
    return indices[month - 1]


def adjust_for_season(price: float, product_name: str, month: int) -> float:
    """
    계절 보정된 가격을 반환. 비싼 계절이면 보정가가 낮아진다 (실제 가치 반영).
    """
    factor = get_seasonal_factor(product_name, month)
    if factor == 0:
        return price
    return round(price / factor, 1)


def calculate_seasonal_baseline(
    price_records: list[dict],
    product_name: str,
) -> dict:
    """
    계절 보정된 기준가를 계산한다.

    Returns: {
        "raw_mean": 보정 전 평균,
        "adjusted_mean": 보정 후 평균,
        "monthly_averages": {1: avg, 2: avg, ...},
        "seasonal_factors": {1: factor, ...},
        "best_month": 가장 저렴한 달,
        "worst_month": 가장 비싼 달,
    }
    """
    if not price_records:
        return {
            "raw_mean": 0, "adjusted_mean": 0,
            "monthly_averages": {}, "seasonal_factors": {},
            "best_month": None, "worst_month": None,
        }

    # 월별 그룹핑
    monthly: dict[int, list[float]] = {}
    all_prices: list[float] = []

    for r in price_records:
        price = r.get("price", 0)
        if price <= 0:
            continue
        all_prices.append(price)

        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            m = dt.month
        elif isinstance(dt, str):
            try:
                m = datetime.fromisoformat(dt).month
            except ValueError:
                continue
        else:
            continue

        monthly.setdefault(m, []).append(price)

    raw_mean = calculate_mean(all_prices) if all_prices else 0

    # 월별 평균
    monthly_avgs = {m: calculate_mean(ps) for m, ps in monthly.items()}

    # 계절 보정
    adjusted_prices = []
    for r in price_records:
        price = r.get("price", 0)
        if price <= 0:
            continue
        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            m = dt.month
        elif isinstance(dt, str):
            try:
                m = datetime.fromisoformat(dt).month
            except ValueError:
                continue
        else:
            continue
        adjusted_prices.append(adjust_for_season(price, product_name, m))

    adjusted_mean = calculate_mean(adjusted_prices) if adjusted_prices else raw_mean

    # 계절 계수
    seasonal_factors = {}
    for m in range(1, 13):
        seasonal_factors[m] = get_seasonal_factor(product_name, m)

    best_month = min(monthly_avgs, key=monthly_avgs.get) if monthly_avgs else None
    worst_month = max(monthly_avgs, key=monthly_avgs.get) if monthly_avgs else None

    return {
        "raw_mean": round(raw_mean, 1),
        "adjusted_mean": round(adjusted_mean, 1),
        "monthly_averages": {m: round(v, 1) for m, v in monthly_avgs.items()},
        "seasonal_factors": seasonal_factors,
        "best_month": best_month,
        "worst_month": worst_month,
    }


# ═══════════════════════════════════════════════
# 추세 분석 (Trend Analysis)
# ═══════════════════════════════════════════════

def analyze_trend(
    price_records: list[dict],
    window_days: int = 30,
) -> dict:
    """
    가격 추세를 분석한다 (상승/하락/안정).

    최근 window_days 기간의 가격 vs 이전 window_days 기간을 비교.

    Returns: {
        "direction": "up" | "down" | "stable",
        "change_pct": 변화율 (%),
        "recent_avg": 최근 평균,
        "previous_avg": 이전 평균,
        "label": "상승 추세" | "하락 추세" | "안정",
    }
    """
    if not price_records:
        return {
            "direction": "stable", "change_pct": 0,
            "recent_avg": 0, "previous_avg": 0, "label": "데이터 부족",
        }

    # 날짜-가격 추출 및 정렬
    dated_prices: list[tuple[datetime, float]] = []
    for r in price_records:
        price = r.get("price", 0)
        if price <= 0:
            continue
        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            dated_prices.append((dt, price))
        elif isinstance(dt, str):
            try:
                dated_prices.append((datetime.fromisoformat(dt), price))
            except ValueError:
                continue

    if len(dated_prices) < 2:
        return {
            "direction": "stable", "change_pct": 0,
            "recent_avg": 0, "previous_avg": 0, "label": "데이터 부족",
        }

    dated_prices.sort(key=lambda x: x[0])
    latest_date = dated_prices[-1][0]
    cutoff = latest_date - timedelta(days=window_days)
    mid_cutoff = cutoff - timedelta(days=window_days)

    recent = [p for d, p in dated_prices if d >= cutoff]
    previous = [p for d, p in dated_prices if mid_cutoff <= d < cutoff]

    if not recent or not previous:
        all_prices = [p for _, p in dated_prices]
        mid = len(all_prices) // 2
        if mid == 0:
            return {
                "direction": "stable", "change_pct": 0,
                "recent_avg": calculate_mean(all_prices),
                "previous_avg": calculate_mean(all_prices),
                "label": "데이터 부족",
            }
        recent = all_prices[mid:]
        previous = all_prices[:mid]

    recent_avg = calculate_mean(recent)
    prev_avg = calculate_mean(previous)

    if prev_avg == 0:
        change_pct = 0
    else:
        change_pct = ((recent_avg - prev_avg) / prev_avg) * 100

    # ±5% 이내는 안정
    if change_pct > 5:
        direction = "up"
        label = "상승 추세"
    elif change_pct < -5:
        direction = "down"
        label = "하락 추세"
    else:
        direction = "stable"
        label = "안정"

    return {
        "direction": direction,
        "change_pct": round(change_pct, 2),
        "recent_avg": round(recent_avg, 1),
        "previous_avg": round(prev_avg, 1),
        "label": label,
    }


# ═══════════════════════════════════════════════
# 신뢰도 점수 (Confidence Score)
# ═══════════════════════════════════════════════

def calculate_confidence(
    price_records: list[dict],
    min_data_points: int = 10,
    max_age_days: int = 90,
) -> dict:
    """
    기준가의 신뢰도 점수를 계산한다.

    신뢰도는 데이터 양, 최신성, 다양성(소스 수)에 기반한다.

    Returns: {
        "score": 0-100 신뢰도 점수,
        "grade": "A" | "B" | "C" | "D" | "F",
        "factors": {
            "data_quantity": 0-40 (데이터 양),
            "data_recency": 0-30 (최신성),
            "source_diversity": 0-30 (소스 다양성),
        },
        "recommendation": str,
    }
    """
    if not price_records:
        return {
            "score": 0, "grade": "F",
            "factors": {"data_quantity": 0, "data_recency": 0, "source_diversity": 0},
            "recommendation": "데이터가 없습니다. 크롤링을 시작하세요.",
        }

    now = datetime.now()
    valid_prices = [r for r in price_records if r.get("price", 0) > 0]
    count = len(valid_prices)

    # 1) 데이터 양 점수 (0-40)
    quantity_score = min(40, count / min_data_points * 40)

    # 2) 최신성 점수 (0-30)
    recent_dates: list[datetime] = []
    for r in valid_prices:
        dt = r.get("recorded_at")
        if isinstance(dt, datetime):
            recent_dates.append(dt)
        elif isinstance(dt, str):
            try:
                recent_dates.append(datetime.fromisoformat(dt))
            except ValueError:
                pass

    if recent_dates:
        newest = max(recent_dates)
        age_days = (now - newest).days
        recency_score = max(0, 30 * (1 - age_days / max_age_days))
    else:
        recency_score = 0

    # 3) 소스 다양성 점수 (0-30)
    sources = set()
    for r in valid_prices:
        src = r.get("source", "")
        if src:
            sources.add(src)
    source_count = len(sources)
    diversity_score = min(30, source_count / 3 * 30)

    total = round(quantity_score + recency_score + diversity_score)
    total = min(100, max(0, total))

    if total >= 80:
        grade = "A"
        rec = "신뢰할 수 있는 기준가입니다."
    elif total >= 60:
        grade = "B"
        rec = "양호한 수준이지만, 더 많은 데이터가 도움이 됩니다."
    elif total >= 40:
        grade = "C"
        rec = "참고용으로만 사용하세요. 데이터가 부족합니다."
    elif total >= 20:
        grade = "D"
        rec = "기준가 정확도가 낮습니다. 추가 데이터 수집이 필요합니다."
    else:
        grade = "F"
        rec = "데이터가 너무 부족합니다. 크롤링을 시작하세요."

    return {
        "score": total,
        "grade": grade,
        "factors": {
            "data_quantity": round(quantity_score, 1),
            "data_recency": round(recency_score, 1),
            "source_diversity": round(diversity_score, 1),
        },
        "recommendation": rec,
    }


# ═══════════════════════════════════════════════
# 확장 기준가 계산 (통합)
# ═══════════════════════════════════════════════

def calculate_extended_baseline(
    baseline_records: list[dict],
    discount_records: list[dict],
    product_name: str = "",
    exclude_hotdeals: bool = True,
) -> dict:
    """
    확장 기준가 계산 — 통계 + 계절 보정 + 추세 + 신뢰도를 종합.

    baseline_records: baseline_prices 데이터
    discount_records: discount_history 데이터
    (hotdeal_prices는 기준가에 포함하지 않음 — 가격 오염 방지)

    Returns: {
        "statistics": {...},
        "seasonal": {...},
        "trend": {...},
        "confidence": {...},
        "recommended_baseline": float,
        "price_tiers": {...},
    }
    """
    all_records = list(baseline_records) + list(discount_records)
    all_prices = [r.get("price", 0) for r in all_records if r.get("price", 0) > 0]

    stats = full_statistics(all_prices)
    seasonal = calculate_seasonal_baseline(all_records, product_name)
    trend = analyze_trend(all_records)
    confidence = calculate_confidence(all_records)

    # 추천 기준가: 계절 보정 평균이 있으면 우선, 없으면 일반 평균
    if seasonal["adjusted_mean"] > 0:
        recommended = seasonal["adjusted_mean"]
    else:
        recommended = stats["mean"]

    # 가격 티어 임계값 계산
    price_tiers = {}
    if recommended > 0:
        price_tiers = {
            "ultra_threshold": round(recommended * 0.70),
            "great_threshold": round(recommended * 0.85),
            "good_threshold": round(recommended * 1.05),
            "wait_threshold": round(recommended * 1.05),
        }

    return {
        "statistics": stats,
        "seasonal": seasonal,
        "trend": trend,
        "confidence": confidence,
        "recommended_baseline": round(recommended, 1),
        "price_tiers": price_tiers,
    }
