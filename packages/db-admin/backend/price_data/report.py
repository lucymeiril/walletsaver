"""
가격 분석 리포트 생성기 — 제품별, 카테고리별 분석 리포트를 JSON으로 출력.

API 소비를 위한 구조화된 리포트를 제공하며,
기준가, 추세, 구매 적기, 가격 티어 임계값 등을 포함한다.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from . import baseline as bl
from . import archive as ar
from .sample_data import PRODUCT_CATALOG


def generate_product_report(
    baseline_records: list[dict],
    discount_records: list[dict],
    product_id: int,
    product_name: str = "",
    product_unit: str = "",
) -> dict:
    """
    단일 제품에 대한 종합 가격 분석 리포트를 생성한다.

    Returns: {
        "product_id", "product_name", "unit",
        "generated_at",
        "baseline": {"recommended", "statistics", ...},
        "trend": {"direction", "change_pct", ...},
        "seasonal": {"best_month", "worst_month", ...},
        "confidence": {"score", "grade", ...},
        "price_tiers": {"ultra_threshold", ...},
        "best_time_to_buy": str,
        "store_comparison": [...],
    }
    """
    all_records = list(baseline_records) + list(discount_records)

    extended = bl.calculate_extended_baseline(
        baseline_records=baseline_records,
        discount_records=discount_records,
        product_name=product_name,
    )

    store_comparison = ar.aggregate_by_store(all_records, product_id)
    trend_data = ar.generate_price_trend(all_records, product_id, "weekly")

    # 구매 적기 판단
    best_time = _determine_best_time(extended, product_name)

    return {
        "product_id": product_id,
        "product_name": product_name,
        "unit": product_unit,
        "generated_at": datetime.now().isoformat(),
        "baseline": {
            "recommended": extended["recommended_baseline"],
            "statistics": extended["statistics"],
        },
        "trend": extended["trend"],
        "seasonal": extended["seasonal"],
        "confidence": extended["confidence"],
        "price_tiers": extended["price_tiers"],
        "best_time_to_buy": best_time,
        "store_comparison": store_comparison,
        "price_trend": trend_data,
    }


def _determine_best_time(extended: dict, product_name: str) -> str:
    """구매 적기를 판단한다."""
    trend = extended.get("trend", {})
    seasonal = extended.get("seasonal", {})
    confidence = extended.get("confidence", {})

    if confidence.get("score", 0) < 20:
        return "데이터 부족으로 판단 불가"

    direction = trend.get("direction", "stable")
    best_month = seasonal.get("best_month")

    month_names = {
        1: "1월", 2: "2월", 3: "3월", 4: "4월",
        5: "5월", 6: "6월", 7: "7월", 8: "8월",
        9: "9월", 10: "10월", 11: "11월", 12: "12월",
    }

    parts: list[str] = []

    if direction == "down":
        parts.append("가격 하락 추세 — 조금 더 기다리면 저렴해질 수 있습니다")
    elif direction == "up":
        parts.append("가격 상승 추세 — 지금 구매하는 것이 유리합니다")
    else:
        parts.append("가격이 안정적입니다")

    if best_month and best_month in month_names:
        parts.append(f"연중 가장 저렴한 달: {month_names[best_month]}")

    return ". ".join(parts) + "."


def generate_category_summary(
    all_records: list[dict],
    products: list[dict],
    category: str,
) -> dict:
    """
    카테고리별 요약 리포트를 생성한다.

    Returns: {
        "category",
        "product_count",
        "avg_price_change_pct",
        "cheapest_products": [...],
        "most_expensive_products": [...],
        "overall_trend",
        "products_summary": [...]
    }
    """
    cat_products = [p for p in products if p.get("category") == category]

    if not cat_products:
        return {
            "category": category,
            "product_count": 0,
            "avg_price_change_pct": 0,
            "cheapest_products": [],
            "most_expensive_products": [],
            "overall_trend": "데이터 없음",
            "products_summary": [],
        }

    summaries: list[dict] = []
    change_pcts: list[float] = []

    for prod in cat_products:
        pid = prod["id"]
        prod_records = [r for r in all_records if r.get("product_id") == pid]

        if not prod_records:
            summaries.append({
                "product_id": pid,
                "product_name": prod["name"],
                "avg_price": prod.get("base_price", 0),
                "trend": "데이터 없음",
                "change_pct": 0,
            })
            continue

        prices = [r["price"] for r in prod_records if r.get("price", 0) > 0]
        avg = sum(prices) / len(prices) if prices else 0

        trend = bl.analyze_trend(prod_records)
        change_pcts.append(trend["change_pct"])

        summaries.append({
            "product_id": pid,
            "product_name": prod["name"],
            "avg_price": round(avg, 1),
            "trend": trend["direction"],
            "change_pct": trend["change_pct"],
        })

    # 가격순 정렬 (base_price 기준)
    sorted_by_price = sorted(cat_products, key=lambda p: p.get("base_price", 0))

    avg_change = sum(change_pcts) / len(change_pcts) if change_pcts else 0

    if avg_change > 5:
        overall = "상승"
    elif avg_change < -5:
        overall = "하락"
    else:
        overall = "안정"

    return {
        "category": category,
        "product_count": len(cat_products),
        "avg_price_change_pct": round(avg_change, 2),
        "cheapest_products": [
            {"name": p["name"], "base_price": p.get("base_price", 0)}
            for p in sorted_by_price[:3]
        ],
        "most_expensive_products": [
            {"name": p["name"], "base_price": p.get("base_price", 0)}
            for p in sorted_by_price[-3:]
        ],
        "overall_trend": overall,
        "products_summary": summaries,
    }


def generate_full_report(
    baseline_records: list[dict],
    discount_records: list[dict],
    products: Optional[list[dict]] = None,
) -> dict:
    """
    전체 가격 분석 리포트를 생성한다 (모든 제품 + 카테고리).

    Returns: {
        "generated_at",
        "total_products",
        "total_records",
        "product_reports": {product_id: {...}, ...},
        "category_summaries": {category: {...}, ...},
        "overall_stats": {...},
    }
    """
    if products is None:
        products = PRODUCT_CATALOG

    all_records = list(baseline_records) + list(discount_records)

    product_reports: dict[int, dict] = {}
    for prod in products:
        pid = prod["id"]
        prod_baseline = [r for r in baseline_records if r.get("product_id") == pid]
        prod_discount = [r for r in discount_records if r.get("product_id") == pid]

        product_reports[pid] = generate_product_report(
            baseline_records=prod_baseline,
            discount_records=prod_discount,
            product_id=pid,
            product_name=prod["name"],
            product_unit=prod.get("unit", ""),
        )

    # 카테고리 요약
    categories = sorted({p.get("category", "") for p in products})
    category_summaries: dict[str, dict] = {}
    for cat in categories:
        category_summaries[cat] = generate_category_summary(all_records, products, cat)

    # 전체 통계
    all_prices = [r.get("price", 0) for r in all_records if r.get("price", 0) > 0]
    overall = {
        "total_price_records": len(all_prices),
        "avg_price": round(sum(all_prices) / len(all_prices), 1) if all_prices else 0,
        "products_with_data": sum(1 for pid in product_reports if product_reports[pid]["confidence"]["score"] > 0),
        "high_confidence_products": sum(
            1 for pid in product_reports
            if product_reports[pid]["confidence"]["score"] >= 60
        ),
    }

    return {
        "generated_at": datetime.now().isoformat(),
        "total_products": len(products),
        "total_records": len(all_records),
        "product_reports": product_reports,
        "category_summaries": category_summaries,
        "overall_stats": overall,
    }


def export_report_to_json(report: dict, indent: int = 2) -> str:
    """리포트를 JSON 문자열로 직렬화한다."""

    def _default(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"JSON 직렬화 불가: {type(obj)}")

    return json.dumps(report, ensure_ascii=False, indent=indent, default=_default)
