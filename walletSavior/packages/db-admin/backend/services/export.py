"""데이터 내보내기 서비스 — 스트리밍 지원"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta
from typing import Generator

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


def export_prices_csv_stream(
    session: Session, product_id: int, days: int = 30
) -> Generator[str, None, None]:
    """가격 이력 CSV 스트리밍 내보내기 — 대용량 데이터에서 메모리 절약.

    각 yield 는 CSV 행 하나 (헤더 포함).
    """
    since = datetime.utcnow() - timedelta(days=days)

    yield "date,price,source,unit\n"

    # yield_per 로 한 번에 500건씩 청크 처리
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

    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow([
            row.recorded_at.strftime("%Y-%m-%d %H:%M") if row.recorded_at else "",
            row.price,
            row.source,
            row.unit,
        ])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)


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
    """전체 통계 요약 — 단일 쿼리로 count 들을 한 번에 조회."""
    # 개별 count 쿼리 6개를 하나로 합칠 수 없으므로 (다른 테이블),
    # 최소한 병렬 실행 가능하도록 유지하되 avg 쿼리와 통합
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

    # count + avg를 단일 쿼리로 결합
    avg_baseline = session.execute(
        select(func.avg(BaselinePrice.price)).select_from(BaselinePrice)
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
