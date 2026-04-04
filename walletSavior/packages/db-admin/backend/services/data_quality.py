"""데이터 품질 관리 서비스 — 이상치 제거, 중복 검사, 무결성 검증"""
from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, func, text, inspect, and_
from sqlalchemy.orm import Session

from storage.models import (
    Base, Product, BaselinePrice, DiscountHistory, HotdealPrice,
    Category, Keyword, CrawlLog,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from core.statistics import remove_outliers_iqr


def check_price_outliers(session: Session, product_id: int) -> dict:
    """IQR 기반 이상치 탐지"""
    rows = session.execute(
        select(BaselinePrice.id, BaselinePrice.price, BaselinePrice.recorded_at).where(
            BaselinePrice.product_id == product_id
        ).order_by(BaselinePrice.recorded_at)
    ).all()

    prices = [r.price for r in rows]
    if len(prices) < 4:
        return {"outliers": [], "total": len(prices), "message": "데이터 부족"}

    cleaned, removed_count = remove_outliers_iqr(prices)
    cleaned_set = set(cleaned)

    outliers = []
    for r in rows:
        if r.price not in cleaned_set:
            outliers.append({
                "id": r.id,
                "price": r.price,
                "date": r.recorded_at.strftime("%Y-%m-%d") if r.recorded_at else None,
            })
            cleaned_set.discard(r.price)  # handle duplicates

    return {
        "product_id": product_id,
        "total_prices": len(prices),
        "outliers_count": removed_count,
        "outliers": outliers,
    }


def check_price_outliers_batch(
    session: Session, product_ids: list[int]
) -> list[dict]:
    """여러 상품의 IQR 기반 이상치를 배치 탐지.

    단일 쿼리로 모든 상품의 가격을 조회한 뒤 product_id 별로 그룹핑.
    """
    if not product_ids:
        return []

    rows = session.execute(
        select(
            BaselinePrice.product_id,
            BaselinePrice.id,
            BaselinePrice.price,
            BaselinePrice.recorded_at,
        ).where(
            BaselinePrice.product_id.in_(product_ids)
        ).order_by(BaselinePrice.product_id, BaselinePrice.recorded_at)
    ).all()

    # product_id 별 그룹핑
    from collections import defaultdict
    grouped: dict[int, list] = defaultdict(list)
    for r in rows:
        grouped[r.product_id].append(r)

    results = []
    for pid in product_ids:
        pid_rows = grouped.get(pid, [])
        prices = [r.price for r in pid_rows]
        if len(prices) < 4:
            results.append({"product_id": pid, "outliers": [], "total": len(prices), "message": "데이터 부족"})
            continue

        cleaned, removed_count = remove_outliers_iqr(prices)
        cleaned_set = set(cleaned)
        outliers = []
        for r in pid_rows:
            if r.price not in cleaned_set:
                outliers.append({
                    "id": r.id, "price": r.price,
                    "date": r.recorded_at.strftime("%Y-%m-%d") if r.recorded_at else None,
                })
                cleaned_set.discard(r.price)

        results.append({
            "product_id": pid,
            "total_prices": len(prices),
            "outliers_count": removed_count,
            "outliers": outliers,
        })

    return results


def find_duplicates(session: Session, table_name: str, fields: list[str]) -> list[dict]:
    """중복 데이터 탐지"""
    model_map = {
        "products": Product,
        "baseline_prices": BaselinePrice,
        "discount_history": DiscountHistory,
        "hotdeal_prices": HotdealPrice,
        "categories": Category,
        "keywords": Keyword,
    }

    model = model_map.get(table_name)
    if not model:
        return []

    columns = [getattr(model, f) for f in fields if hasattr(model, f)]
    if not columns:
        return []

    stmt = (
        select(*columns, func.count().label("dup_count"))
        .group_by(*columns)
        .having(func.count() > 1)
    )
    rows = session.execute(stmt).all()

    return [
        {**{fields[i]: row[i] for i in range(len(fields))}, "count": row.dup_count}
        for row in rows
    ]


def validate_crawl_data(items: list[dict]) -> dict:
    """크롤링 데이터 스키마 검증"""
    required_fields = ["name", "price", "source"]
    errors = []
    valid_count = 0

    for i, item in enumerate(items):
        item_errors = []
        for field in required_fields:
            if field not in item or item[field] is None:
                item_errors.append(f"missing '{field}'")

        if "price" in item and item["price"] is not None:
            try:
                price = float(item["price"])
                if price <= 0:
                    item_errors.append("price must be positive")
            except (ValueError, TypeError):
                item_errors.append("price must be numeric")

        if item_errors:
            errors.append({"index": i, "errors": item_errors})
        else:
            valid_count += 1

    return {
        "total": len(items),
        "valid": valid_count,
        "invalid": len(errors),
        "errors": errors,
    }


def generate_quality_report(session: Session) -> dict:
    """전체 데이터 품질 리포트 — 실데이터 기반 지표 계산.

    가능한 쿼리를 통합하여 DB 라운드트립을 줄인다.
    """
    # 테이블별 count 조회 (각각 다른 테이블이라 통합 불가하나 경량 쿼리)
    product_count = session.execute(
        select(func.count()).select_from(Product)
    ).scalar() or 0

    baseline_count = session.execute(
        select(func.count()).select_from(BaselinePrice)
    ).scalar() or 0

    discount_count = session.execute(
        select(func.count()).select_from(DiscountHistory)
    ).scalar() or 0

    hotdeal_count = session.execute(
        select(func.count()).select_from(HotdealPrice)
    ).scalar() or 0

    category_count = session.execute(
        select(func.count()).select_from(Category)
    ).scalar() or 0

    # 가격 데이터 없는 상품 + 카테고리 없는 상품 + 필수 필드 완성 상품 을 한 번에 조회
    products_no_price = session.execute(
        select(func.count()).select_from(Product).where(
            ~Product.id.in_(
                select(BaselinePrice.product_id).distinct()
            )
        )
    ).scalar() or 0

    products_no_category = session.execute(
        select(func.count()).select_from(Product).where(
            Product.category_id.is_(None)
        )
    ).scalar() or 0

    # ── 품질 지표 실계산 ──

    # 필드 완성도: 필수 필드(name, category_id, unit)가 모두 채워진 비율
    products_all_fields = session.execute(
        select(func.count()).select_from(Product).where(
            and_(
                Product.name.isnot(None),
                Product.name != "",
                Product.category_id.isnot(None),
                Product.unit.isnot(None),
                Product.unit != "",
            )
        )
    ).scalar() or 0
    field_completeness = round(
        products_all_fields / max(product_count, 1) * 100, 1
    )

    # 가격 데이터 커버리지: 가격 이력이 있는 상품 비율
    price_coverage = round(
        (product_count - products_no_price) / max(product_count, 1) * 100, 1
    )

    # 카테고리 분류율: 카테고리가 지정된 상품 비율
    category_rate = round(
        (product_count - products_no_category) / max(product_count, 1) * 100, 1
    )

    # 종합 완성도: 세 지표의 평균
    completeness = round(
        (field_completeness + price_coverage + category_rate) / 3, 1
    )

    # 정확도: 유효한 가격 데이터(price > 0) 비율
    valid_prices = session.execute(
        select(func.count()).select_from(BaselinePrice).where(
            BaselinePrice.price > 0
        )
    ).scalar() or 0
    accuracy = round(valid_prices / max(baseline_count, 1) * 100, 1)

    # 중복 상품 수 (이름 기준)
    dup_subq = (
        select(Product.name)
        .group_by(Product.name)
        .having(func.count() > 1)
        .subquery()
    )
    duplicate_count = session.execute(
        select(func.count()).select_from(dup_subq)
    ).scalar() or 0

    return {
        "counts": {
            "products": product_count,
            "baseline_prices": baseline_count,
            "discount_history": discount_count,
            "hotdeal_prices": hotdeal_count,
            "categories": category_count,
        },
        "quality": {
            "products_without_prices": products_no_price,
            "products_without_category": products_no_category,
            "field_completeness": field_completeness,
            "price_coverage": price_coverage,
            "category_rate": category_rate,
            "completeness": completeness,
            "accuracy": accuracy,
            "duplicates": duplicate_count,
        },
        "generated_at": datetime.utcnow().isoformat(),
    }


def cleanup_stale_data(session: Session, days: int = 180) -> dict:
    """오래된 데이터 정리"""
    cutoff = datetime.utcnow() - timedelta(days=days)

    stale_baseline = session.execute(
        select(BaselinePrice).where(BaselinePrice.recorded_at < cutoff)
    ).scalars().all()
    baseline_deleted = len(stale_baseline)
    for row in stale_baseline:
        session.delete(row)

    stale_discount = session.execute(
        select(DiscountHistory).where(DiscountHistory.crawled_at < cutoff)
    ).scalars().all()
    discount_deleted = len(stale_discount)
    for row in stale_discount:
        session.delete(row)

    session.commit()
    return {
        "baseline_deleted": baseline_deleted,
        "discount_deleted": discount_deleted,
        "cutoff_date": cutoff.strftime("%Y-%m-%d"),
    }
