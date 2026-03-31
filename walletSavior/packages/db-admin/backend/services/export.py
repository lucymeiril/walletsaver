"""데이터 내보내기 서비스"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from storage.models import (
    Product, BaselinePrice, DiscountHistory, HotdealPrice,
    Category, Keyword,
)


def export_prices_csv(
    session: Session, product_id: int, days: int = 30
) -> str:
    """가격 이력 CSV 내보내기"""
    since = datetime.utcnow() - timedelta(days=days)

    rows = session.execute(
        select(
            BaselinePrice.recorded_at,
            BaselinePrice.price,
            BaselinePrice.source,
            BaselinePrice.unit,
        ).where(
            BaselinePrice.product_id == product_id,
            BaselinePrice.recorded_at >= since,
        ).order_by(BaselinePrice.recorded_at)
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "price", "source", "unit"])
    for row in rows:
        writer.writerow([
            row.recorded_at.strftime("%Y-%m-%d %H:%M") if row.recorded_at else "",
            row.price,
            row.source,
            row.unit,
        ])
    return output.getvalue()


def export_products_json(
    session: Session, category_id: str | None = None
) -> str:
    """상품 목록 JSON 내보내기"""
    stmt = select(Product).where(Product.is_active == True)
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)

    products = session.execute(stmt).scalars().all()

    data = [
        {
            "id": p.id,
            "name": p.name,
            "category_id": p.category_id,
            "unit": p.unit,
            "description": p.description,
        }
        for p in products
    ]
    return json.dumps(data, ensure_ascii=False, indent=2)


def get_statistics_summary(session: Session) -> dict:
    """전체 통계 요약"""
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

    keyword_count = session.execute(
        select(func.count()).select_from(Keyword)
    ).scalar() or 0

    avg_baseline = session.execute(
        select(func.avg(BaselinePrice.price))
    ).scalar()

    return {
        "products": product_count,
        "baseline_prices": baseline_count,
        "discount_records": discount_count,
        "hotdeal_records": hotdeal_count,
        "categories": category_count,
        "keywords": keyword_count,
        "avg_baseline_price": round(avg_baseline, 1) if avg_baseline else 0,
        "generated_at": datetime.utcnow().isoformat(),
    }
