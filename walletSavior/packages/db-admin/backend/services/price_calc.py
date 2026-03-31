"""가격 계산 서비스 — 적정가, 핫딜가, 가격 티어 산출"""
from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from storage.models import (
    Product, BaselinePrice, DiscountHistory, HotdealPrice, DeliveryItem,
)

# shared statistics 모듈 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from core.statistics import (
    compute_stats, determine_tier, compute_moving_averages,
    remove_outliers_iqr, PriceStats, PriceTier,
)


def calculate_baseline_average(
    session: Session, product_id: int, days: int = 90
) -> dict:
    """baseline_prices + discount_history에서 평균가 계산"""
    since = datetime.utcnow() - timedelta(days=days)

    baseline_rows = session.execute(
        select(BaselinePrice.price).where(
            BaselinePrice.product_id == product_id,
            BaselinePrice.recorded_at >= since,
        )
    ).scalars().all()

    discount_rows = session.execute(
        select(DiscountHistory.price).where(
            DiscountHistory.product_id == product_id,
            DiscountHistory.crawled_at >= since,
        )
    ).scalars().all()

    all_prices = list(baseline_rows) + list(discount_rows)
    if not all_prices:
        return {"average": 0, "count": 0, "days": days}

    stats = compute_stats(all_prices, data_days=days)
    return {
        "average": stats.mean,
        "median": stats.median,
        "count": stats.count,
        "days": days,
        "std": stats.std,
        "low": stats.low,
        "high": stats.high,
    }


def calculate_hotdeal_price(session: Session, product_id: int) -> dict:
    """핫딜 적정가 산출 (IQR 기반 이상치 제거 후)"""
    hotdeal_rows = session.execute(
        select(HotdealPrice.price).where(
            HotdealPrice.product_id == product_id,
        )
    ).scalars().all()

    prices = list(hotdeal_rows)
    if not prices:
        return {"hotdeal_avg": 0, "count": 0, "outliers_removed": 0}

    cleaned, removed = remove_outliers_iqr(prices)
    if not cleaned:
        cleaned = prices
        removed = 0

    avg = sum(cleaned) / len(cleaned)
    return {
        "hotdeal_avg": round(avg, 1),
        "count": len(cleaned),
        "outliers_removed": removed,
        "min": min(cleaned),
        "max": max(cleaned),
    }


def get_price_tier(
    session: Session, price: float, product_id: int, days: int = 90
) -> dict:
    """ultra/great/good/wait 판정"""
    baseline = calculate_baseline_average(session, product_id, days)
    if baseline["count"] == 0:
        return {"tier": "good", "label": "데이터 부족", "ratio": 1.0}

    since = datetime.utcnow() - timedelta(days=days)
    all_prices = []
    for row in session.execute(
        select(BaselinePrice.price).where(
            BaselinePrice.product_id == product_id,
            BaselinePrice.recorded_at >= since,
        )
    ).scalars().all():
        all_prices.append(row)
    for row in session.execute(
        select(DiscountHistory.price).where(
            DiscountHistory.product_id == product_id,
            DiscountHistory.crawled_at >= since,
        )
    ).scalars().all():
        all_prices.append(row)

    stats = compute_stats(all_prices, data_days=days)
    tier_result = determine_tier(price, stats)
    return {
        "tier": tier_result.tier,
        "label": tier_result.label,
        "icon": tier_result.icon,
        "ratio": tier_result.ratio,
        "description": tier_result.description,
    }


def get_price_history(
    session: Session, product_id: int, days: int = 30
) -> list[dict]:
    """일별 가격 추이"""
    since = datetime.utcnow() - timedelta(days=days)

    rows = session.execute(
        select(
            BaselinePrice.recorded_at,
            BaselinePrice.price,
            BaselinePrice.source,
        ).where(
            BaselinePrice.product_id == product_id,
            BaselinePrice.recorded_at >= since,
        ).order_by(BaselinePrice.recorded_at)
    ).all()

    history = []
    for row in rows:
        history.append({
            "date": row.recorded_at.strftime("%Y-%m-%d"),
            "price": row.price,
            "source": row.source,
        })
    return history


def get_price_comparison(session: Session, product_id: int) -> list[dict]:
    """출처별(마트별) 가격 비교"""
    rows = session.execute(
        select(
            DiscountHistory.source,
            func.avg(DiscountHistory.price).label("avg_price"),
            func.min(DiscountHistory.price).label("min_price"),
            func.max(DiscountHistory.price).label("max_price"),
            func.count().label("count"),
        ).where(
            DiscountHistory.product_id == product_id,
        ).group_by(DiscountHistory.source)
    ).all()

    return [
        {
            "source": row.source,
            "avg_price": round(row.avg_price, 1),
            "min_price": row.min_price,
            "max_price": row.max_price,
            "count": row.count,
        }
        for row in rows
    ]


def calculate_recipe_vs_delivery(
    session: Session, recipe_ingredients: list[dict]
) -> dict:
    """
    직접 해먹기 vs 배달 vs 외식 비교.
    recipe_ingredients: [{"product_id": 1, "quantity": 2}, ...]
    """
    cook_total = 0.0
    for ing in recipe_ingredients:
        pid = ing.get("product_id")
        qty = ing.get("quantity", 1)
        row = session.execute(
            select(func.avg(BaselinePrice.price)).where(
                BaselinePrice.product_id == pid
            )
        ).scalar()
        if row:
            cook_total += row * qty

    delivery_rows = session.execute(
        select(func.avg(DeliveryItem.price))
    ).scalar()
    delivery_avg = delivery_rows if delivery_rows else 0

    return {
        "cook_cost": round(cook_total, 1),
        "delivery_avg": round(delivery_avg, 1) if delivery_avg else 0,
        "savings": round((delivery_avg or 0) - cook_total, 1),
    }
