"""
샘플 가격 데이터 생성기 — 실제 크롤 데이터가 없는 개발 단계에서 사용.

한국 식료품 시장의 현실적 가격 패턴을 반영하여 3-6개월치 데이터를 생성한다.
계절별 가격 변동, 마트별 가격 차이, 핫딜 이상치 등을 포함한다.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Optional


# ═══════════════════════════════════════════════
# 50+ 한국 식료품 마스터 데이터 (현실적 가격 범위)
# ═══════════════════════════════════════════════

PRODUCT_CATALOG: list[dict] = [
    # ── 채소류 (농산물) ──
    {"id": 1,  "name": "배추",    "category": "농산물", "unit": "1포기", "base_price": 3200,  "price_range": (2200, 8000),  "seasonal": {"peak_month": 3, "trough_month": 10, "amplitude": 0.40}},
    {"id": 2,  "name": "양파",    "category": "농산물", "unit": "1kg",   "base_price": 2350,  "price_range": (1500, 4500),  "seasonal": {"peak_month": 4, "trough_month": 9,  "amplitude": 0.30}},
    {"id": 3,  "name": "감자",    "category": "농산물", "unit": "1kg",   "base_price": 2800,  "price_range": (1800, 5000),  "seasonal": {"peak_month": 3, "trough_month": 7,  "amplitude": 0.25}},
    {"id": 4,  "name": "토마토",  "category": "농산물", "unit": "1kg",   "base_price": 4500,  "price_range": (2500, 8000),  "seasonal": {"peak_month": 1, "trough_month": 7,  "amplitude": 0.35}},
    {"id": 5,  "name": "당근",    "category": "농산물", "unit": "1kg",   "base_price": 3200,  "price_range": (2000, 5500),  "seasonal": {"peak_month": 5, "trough_month": 11, "amplitude": 0.20}},
    {"id": 6,  "name": "시금치",  "category": "농산물", "unit": "1단",   "base_price": 2500,  "price_range": (1500, 5500),  "seasonal": {"peak_month": 7, "trough_month": 12, "amplitude": 0.45}},
    {"id": 7,  "name": "상추",    "category": "농산물", "unit": "100g",  "base_price": 1200,  "price_range": (600, 3000),   "seasonal": {"peak_month": 7, "trough_month": 4,  "amplitude": 0.40}},
    {"id": 8,  "name": "대파",    "category": "농산물", "unit": "1단",   "base_price": 1800,  "price_range": (800, 5000),   "seasonal": {"peak_month": 8, "trough_month": 11, "amplitude": 0.50}},
    {"id": 9,  "name": "고추",    "category": "농산물", "unit": "100g",  "base_price": 1500,  "price_range": (800, 3500),   "seasonal": {"peak_month": 3, "trough_month": 8,  "amplitude": 0.35}},
    {"id": 10, "name": "오이",    "category": "농산물", "unit": "3개",   "base_price": 2000,  "price_range": (1000, 4500),  "seasonal": {"peak_month": 1, "trough_month": 7,  "amplitude": 0.40}},
    {"id": 11, "name": "마늘",    "category": "농산물", "unit": "1kg",   "base_price": 8500,  "price_range": (5500, 14000), "seasonal": {"peak_month": 4, "trough_month": 7,  "amplitude": 0.25}},
    {"id": 12, "name": "무",      "category": "농산물", "unit": "1개",   "base_price": 1800,  "price_range": (800, 3500),   "seasonal": {"peak_month": 6, "trough_month": 11, "amplitude": 0.35}},

    # ── 과일류 ──
    {"id": 13, "name": "사과",    "category": "농산물", "unit": "1kg",   "base_price": 4800,  "price_range": (3000, 9000),  "seasonal": {"peak_month": 6, "trough_month": 10, "amplitude": 0.35}},
    {"id": 14, "name": "딸기",    "category": "농산물", "unit": "500g",  "base_price": 7500,  "price_range": (4000, 15000), "seasonal": {"peak_month": 8, "trough_month": 2,  "amplitude": 0.50}},
    {"id": 15, "name": "바나나",  "category": "농산물", "unit": "1송이", "base_price": 3800,  "price_range": (2500, 5500),  "seasonal": None},
    {"id": 16, "name": "포도",    "category": "농산물", "unit": "1kg",   "base_price": 6500,  "price_range": (3500, 12000), "seasonal": {"peak_month": 3, "trough_month": 9,  "amplitude": 0.40}},
    {"id": 17, "name": "수박",    "category": "농산물", "unit": "1통",   "base_price": 15000, "price_range": (8000, 28000), "seasonal": {"peak_month": 1, "trough_month": 7,  "amplitude": 0.45}},
    {"id": 18, "name": "귤",      "category": "농산물", "unit": "1kg",   "base_price": 3500,  "price_range": (2000, 7000),  "seasonal": {"peak_month": 6, "trough_month": 12, "amplitude": 0.40}},
    {"id": 19, "name": "배",      "category": "농산물", "unit": "1개",   "base_price": 3000,  "price_range": (1800, 5500),  "seasonal": {"peak_month": 5, "trough_month": 9,  "amplitude": 0.30}},
    {"id": 20, "name": "복숭아",  "category": "농산물", "unit": "1kg",   "base_price": 7000,  "price_range": (4000, 13000), "seasonal": {"peak_month": 1, "trough_month": 8,  "amplitude": 0.50}},

    # ── 축산물 ──
    {"id": 21, "name": "삼겹살",  "category": "축산물", "unit": "100g",  "base_price": 1850,  "price_range": (1300, 2800),  "seasonal": {"peak_month": 5, "trough_month": 2,  "amplitude": 0.12}},
    {"id": 22, "name": "목살",    "category": "축산물", "unit": "100g",  "base_price": 1650,  "price_range": (1100, 2500),  "seasonal": {"peak_month": 5, "trough_month": 2,  "amplitude": 0.10}},
    {"id": 23, "name": "소등심",  "category": "축산물", "unit": "100g",  "base_price": 4500,  "price_range": (3200, 7500),  "seasonal": {"peak_month": 9, "trough_month": 3,  "amplitude": 0.15}},
    {"id": 24, "name": "닭가슴살","category": "축산물", "unit": "1kg",   "base_price": 8500,  "price_range": (5500, 12000), "seasonal": None},
    {"id": 25, "name": "계란",    "category": "축산물", "unit": "30구",  "base_price": 6200,  "price_range": (4500, 9500),  "seasonal": {"peak_month": 1, "trough_month": 6,  "amplitude": 0.15}},
    {"id": 26, "name": "통닭",    "category": "축산물", "unit": "1마리", "base_price": 6500,  "price_range": (4500, 9000),  "seasonal": None},
    {"id": 27, "name": "차돌박이","category": "축산물", "unit": "100g",  "base_price": 3800,  "price_range": (2800, 5500),  "seasonal": {"peak_month": 9, "trough_month": 3,  "amplitude": 0.12}},
    {"id": 28, "name": "돼지안심","category": "축산물", "unit": "100g",  "base_price": 1400,  "price_range": (900, 2200),   "seasonal": None},

    # ── 수산물 ──
    {"id": 29, "name": "고등어",  "category": "수산물", "unit": "1마리", "base_price": 3500,  "price_range": (2200, 5500),  "seasonal": {"peak_month": 3, "trough_month": 10, "amplitude": 0.25}},
    {"id": 30, "name": "연어",    "category": "수산물", "unit": "100g",  "base_price": 3200,  "price_range": (2200, 5000),  "seasonal": None},
    {"id": 31, "name": "새우",    "category": "수산물", "unit": "100g",  "base_price": 2500,  "price_range": (1500, 4500),  "seasonal": {"peak_month": 12, "trough_month": 5, "amplitude": 0.20}},
    {"id": 32, "name": "오징어",  "category": "수산물", "unit": "1마리", "base_price": 4000,  "price_range": (2500, 7000),  "seasonal": {"peak_month": 4,  "trough_month": 9, "amplitude": 0.30}},
    {"id": 33, "name": "갈치",    "category": "수산물", "unit": "1마리", "base_price": 5500,  "price_range": (3500, 9000),  "seasonal": {"peak_month": 3,  "trough_month": 9, "amplitude": 0.25}},
    {"id": 34, "name": "멸치",    "category": "수산물", "unit": "100g",  "base_price": 3800,  "price_range": (2500, 5500),  "seasonal": None},
    {"id": 35, "name": "김",      "category": "수산물", "unit": "10장",  "base_price": 3000,  "price_range": (1800, 4500),  "seasonal": None},

    # ── 가공식품 ──
    {"id": 36, "name": "두부",    "category": "가공식품", "unit": "1모",   "base_price": 1800,  "price_range": (1200, 2800),  "seasonal": None},
    {"id": 37, "name": "라면",    "category": "가공식품", "unit": "5입",   "base_price": 3900,  "price_range": (2800, 5200),  "seasonal": None},
    {"id": 38, "name": "식용유",  "category": "가공식품", "unit": "1.8L",  "base_price": 5800,  "price_range": (4200, 8000),  "seasonal": None},
    {"id": 39, "name": "간장",    "category": "가공식품", "unit": "500ml", "base_price": 3200,  "price_range": (2200, 4500),  "seasonal": None},
    {"id": 40, "name": "참기름",  "category": "가공식품", "unit": "320ml", "base_price": 8500,  "price_range": (6000, 12000), "seasonal": None},
    {"id": 41, "name": "고추장",  "category": "가공식품", "unit": "500g",  "base_price": 4500,  "price_range": (3200, 6500),  "seasonal": None},
    {"id": 42, "name": "된장",    "category": "가공식품", "unit": "500g",  "base_price": 3800,  "price_range": (2500, 5500),  "seasonal": None},
    {"id": 43, "name": "햄",      "category": "가공식품", "unit": "200g",  "base_price": 3500,  "price_range": (2500, 5000),  "seasonal": None},
    {"id": 44, "name": "어묵",    "category": "가공식품", "unit": "300g",  "base_price": 2800,  "price_range": (1800, 4000),  "seasonal": None},

    # ── 유제품 / 음료 ──
    {"id": 45, "name": "우유",    "category": "음료",     "unit": "1L",    "base_price": 2650,  "price_range": (2000, 3500),  "seasonal": None},
    {"id": 46, "name": "요구르트","category": "음료",     "unit": "450ml", "base_price": 2200,  "price_range": (1500, 3200),  "seasonal": None},
    {"id": 47, "name": "치즈",    "category": "가공식품", "unit": "200g",  "base_price": 4500,  "price_range": (3000, 6500),  "seasonal": None},
    {"id": 48, "name": "버터",    "category": "가공식품", "unit": "200g",  "base_price": 5500,  "price_range": (3800, 7500),  "seasonal": None},

    # ── 곡류 ──
    {"id": 49, "name": "쌀",      "category": "가공식품", "unit": "10kg",  "base_price": 28500, "price_range": (22000, 38000), "seasonal": {"peak_month": 6, "trough_month": 10, "amplitude": 0.10}},
    {"id": 50, "name": "밀가루",  "category": "가공식품", "unit": "1kg",   "base_price": 2200,  "price_range": (1500, 3200),   "seasonal": None},

    # ── 생활용품 ──
    {"id": 51, "name": "휴지",    "category": "생활용품", "unit": "30롤",  "base_price": 12000, "price_range": (8000, 18000),  "seasonal": None},
    {"id": 52, "name": "세제",    "category": "생활용품", "unit": "2.5L",  "base_price": 9500,  "price_range": (6500, 14000),  "seasonal": None},
    {"id": 53, "name": "샴푸",    "category": "생활용품", "unit": "500ml", "base_price": 8000,  "price_range": (5000, 12000),  "seasonal": None},
    {"id": 54, "name": "칫솔",    "category": "생활용품", "unit": "4개입", "base_price": 5500,  "price_range": (3500, 8500),   "seasonal": None},
    {"id": 55, "name": "치약",    "category": "생활용품", "unit": "180g",  "base_price": 3500,  "price_range": (2200, 5500),   "seasonal": None},
]

# 마트별 가격 편차 계수 (1.0 = 평균)
STORE_PROFILES: dict[str, dict] = {
    "emart":     {"name": "이마트",     "price_factor": 0.97, "discount_freq": 0.15, "discount_depth": (0.15, 0.35)},
    "homeplus":  {"name": "홈플러스",   "price_factor": 1.00, "discount_freq": 0.12, "discount_depth": (0.10, 0.30)},
    "lottemart": {"name": "롯데마트",   "price_factor": 1.02, "discount_freq": 0.13, "discount_depth": (0.12, 0.32)},
    "costco":    {"name": "코스트코",   "price_factor": 0.92, "discount_freq": 0.08, "discount_depth": (0.20, 0.40)},
}

# 핫딜 커뮤니티 소스
HOTDEAL_SOURCES = ["뽐뿌", "클리앙", "루리웹", "퀘사이저"]


def _seasonal_factor(month: int, seasonal: Optional[dict]) -> float:
    """월별 계절 계수 계산. 1.0 = 기준가, >1.0 = 비싼 계절, <1.0 = 저렴한 계절."""
    if seasonal is None:
        return 1.0
    peak = seasonal["peak_month"]
    amplitude = seasonal["amplitude"]
    # 피크에서 가장 비싸고 반대편(6개월 후)에서 가장 저렴
    phase = 2 * math.pi * (month - peak) / 12
    return 1.0 + amplitude * math.cos(phase)


def _daily_noise(base: float, noise_pct: float = 0.03) -> float:
    """일별 가격 소음 추가 (±3% 기본)."""
    return base * (1 + random.uniform(-noise_pct, noise_pct))


def generate_baseline_prices(
    products: Optional[list[dict]] = None,
    months: int = 6,
    end_date: Optional[datetime] = None,
    seed: Optional[int] = None,
) -> list[dict]:
    """
    baseline_prices 테이블용 샘플 데이터 생성.

    각 제품 × 마트 × 일별로 현실적 가격을 생성한다.
    KAMIS 공공데이터 가격도 포함 (주 1회).

    Returns: [{"product_id", "product_name", "price", "source", "unit", "recorded_at"}, ...]
    """
    if seed is not None:
        random.seed(seed)

    if products is None:
        products = PRODUCT_CATALOG
    if end_date is None:
        end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    start_date = end_date - timedelta(days=months * 30)
    records: list[dict] = []

    for product in products:
        pid = product["id"]
        base = product["base_price"]
        seasonal = product.get("seasonal")
        lo, hi = product["price_range"]

        current = start_date
        while current <= end_date:
            month = current.month
            s_factor = _seasonal_factor(month, seasonal)

            # 장기 추세 (연 ±5% 인플레이션)
            days_elapsed = (current - start_date).days
            trend = 1.0 + 0.05 * (days_elapsed / 365)

            for store_key, store_info in STORE_PROFILES.items():
                store_base = base * s_factor * trend * store_info["price_factor"]
                price = _daily_noise(store_base)
                price = max(lo, min(hi, round(price, -1)))  # 10원 단위 반올림, 범위 클램프

                records.append({
                    "product_id": pid,
                    "product_name": product["name"],
                    "price": price,
                    "source": store_key,
                    "unit": product["unit"],
                    "recorded_at": current,
                })

            # KAMIS 공공 데이터 (주 1회, 수요일)
            if current.weekday() == 2:
                kamis_price = base * s_factor * trend
                kamis_price = max(lo, min(hi, round(kamis_price, -1)))
                records.append({
                    "product_id": pid,
                    "product_name": product["name"],
                    "price": kamis_price,
                    "source": "kamis",
                    "unit": product["unit"],
                    "recorded_at": current,
                })

            current += timedelta(days=1)

    return records


def generate_discount_history(
    products: Optional[list[dict]] = None,
    months: int = 6,
    end_date: Optional[datetime] = None,
    seed: Optional[int] = None,
) -> list[dict]:
    """
    discount_history 테이블용 할인 이벤트 데이터 생성.

    각 마트별 주기적 할인 행사 데이터를 생성한다.

    Returns: [{"product_id", "product_name", "price", "original_price",
               "discount_rate", "source", "valid_from", "valid_to"}, ...]
    """
    if seed is not None:
        random.seed(seed)

    if products is None:
        products = PRODUCT_CATALOG
    if end_date is None:
        end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    start_date = end_date - timedelta(days=months * 30)
    records: list[dict] = []

    for product in products:
        pid = product["id"]
        base = product["base_price"]
        seasonal = product.get("seasonal")

        for store_key, store_info in STORE_PROFILES.items():
            freq = store_info["discount_freq"]
            depth_lo, depth_hi = store_info["discount_depth"]
            num_events = max(1, int(months * 30 * freq / 7))

            for _ in range(num_events):
                event_start = start_date + timedelta(
                    days=random.randint(0, max(1, (end_date - start_date).days - 7))
                )
                duration = random.randint(3, 14)
                event_end = event_start + timedelta(days=duration)

                month = event_start.month
                s_factor = _seasonal_factor(month, seasonal)
                original = round(base * s_factor * store_info["price_factor"], -1)
                rate = random.uniform(depth_lo, depth_hi)
                sale_price = round(original * (1 - rate), -1)

                lo, hi = product["price_range"]
                sale_price = max(lo * 0.6, min(hi, sale_price))
                original = max(sale_price, original)

                records.append({
                    "product_id": pid,
                    "product_name": product["name"],
                    "price": sale_price,
                    "original_price": original,
                    "discount_rate": round(rate * 100, 1),
                    "source": store_key,
                    "valid_from": event_start,
                    "valid_to": event_end,
                })

    return records


def generate_hotdeal_prices(
    products: Optional[list[dict]] = None,
    months: int = 6,
    end_date: Optional[datetime] = None,
    seed: Optional[int] = None,
) -> list[dict]:
    """
    hotdeal_prices 테이블용 커뮤니티 핫딜 데이터 생성.

    핫딜은 baseline에 포함되지 않는 "가격 오염 방지" 원칙을 반영.
    가끔 극단적 할인(40-70% off)이 포함된다.

    Returns: [{"product_id", "product_name", "price", "source",
               "title", "votes_hot", "votes_not", "posted_at"}, ...]
    """
    if seed is not None:
        random.seed(seed)

    if products is None:
        products = PRODUCT_CATALOG
    if end_date is None:
        end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    start_date = end_date - timedelta(days=months * 30)
    records: list[dict] = []

    for product in products:
        pid = product["id"]
        base = product["base_price"]
        # 핫딜은 제품당 2-8개 (희소)
        num_deals = random.randint(2, 8)

        for _ in range(num_deals):
            posted = start_date + timedelta(
                days=random.randint(0, max(1, (end_date - start_date).days))
            )
            source = random.choice(HOTDEAL_SOURCES)

            # 할인 깊이: 보통 30-50%, 가끔 60-70% (극딜)
            if random.random() < 0.15:
                discount = random.uniform(0.55, 0.70)
            else:
                discount = random.uniform(0.25, 0.50)

            price = round(base * (1 - discount), -1)
            lo = product["price_range"][0]
            price = max(lo * 0.3, price)

            votes_hot = random.randint(5, 300)
            votes_not = random.randint(0, max(1, votes_hot // 5))

            title = f"[{source}] {product['name']} {product['unit']} {int(price):,}원 ({int(discount*100)}% 할인)"

            records.append({
                "product_id": pid,
                "product_name": product["name"],
                "price": price,
                "source": source,
                "title": title,
                "votes_hot": votes_hot,
                "votes_not": votes_not,
                "posted_at": posted,
            })

    return records


def generate_all_sample_data(
    months: int = 6,
    end_date: Optional[datetime] = None,
    seed: Optional[int] = 42,
) -> dict:
    """
    모든 종류의 샘플 데이터를 한번에 생성.

    Returns:
        {
            "baseline_prices": [...],
            "discount_history": [...],
            "hotdeal_prices": [...],
            "products": PRODUCT_CATALOG,
            "summary": {"products": N, "baseline_count": N, ...}
        }
    """
    baseline = generate_baseline_prices(months=months, end_date=end_date, seed=seed)
    discounts = generate_discount_history(months=months, end_date=end_date, seed=(seed + 1 if seed else None))
    hotdeals = generate_hotdeal_prices(months=months, end_date=end_date, seed=(seed + 2 if seed else None))

    return {
        "baseline_prices": baseline,
        "discount_history": discounts,
        "hotdeal_prices": hotdeals,
        "products": PRODUCT_CATALOG,
        "summary": {
            "products": len(PRODUCT_CATALOG),
            "baseline_count": len(baseline),
            "discount_count": len(discounts),
            "hotdeal_count": len(hotdeals),
            "months": months,
            "categories": list({p["category"] for p in PRODUCT_CATALOG}),
        },
    }
