"""분석 데이터 라우트"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select, func, case, and_

from services.base import get_session
from services.data_quality import (
    check_price_outliers,
    find_duplicates,
    validate_crawl_data,
    generate_quality_report,
    cleanup_stale_data,
)
from services.export import (
    export_prices_csv,
    export_products_json,
    get_statistics_summary,
)
from storage.models import (
    Product, BaselinePrice, DiscountHistory, Category, CrawlLog, CrawlStatus,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


class DuplicateRequest(BaseModel):
    table_name: str
    fields: list[str]


class ValidateRequest(BaseModel):
    items: list[dict]


@router.get("/outliers/{product_id}")
def outliers(product_id: int):
    session = get_session()
    try:
        return check_price_outliers(session, product_id)
    finally:
        session.close()


@router.post("/duplicates")
def duplicates(body: DuplicateRequest):
    session = get_session()
    try:
        return find_duplicates(session, body.table_name, body.fields)
    finally:
        session.close()


@router.post("/validate")
def validate(body: ValidateRequest):
    return validate_crawl_data(body.items)


@router.get("/quality-report")
def quality_report():
    session = get_session()
    try:
        return generate_quality_report(session)
    finally:
        session.close()


@router.post("/cleanup")
def cleanup(days: int = 180):
    session = get_session()
    try:
        return cleanup_stale_data(session, days)
    finally:
        session.close()


@router.get("/export/prices/{product_id}")
def export_prices(product_id: int, days: int = 30):
    session = get_session()
    try:
        csv_data = export_prices_csv(session, product_id, days)
        return {"csv": csv_data}
    finally:
        session.close()


@router.get("/export/products")
def export_products(category_id: Optional[str] = None):
    session = get_session()
    try:
        json_data = export_products_json(session, category_id)
        return {"json": json_data}
    finally:
        session.close()


@router.get("/summary")
def summary():
    session = get_session()
    try:
        base = get_statistics_summary(session)

        # ── 카테고리별 평균 가격 ──
        cat_rows = session.execute(
            select(
                Category.name.label("category"),
                func.avg(BaselinePrice.price).label("avg_price"),
            )
            .join(Product, Product.category_id == Category.id)
            .join(BaselinePrice, BaselinePrice.product_id == Product.id)
            .group_by(Category.name)
            .order_by(func.avg(BaselinePrice.price).desc())
        ).all()

        category_avg_prices = [
            {"category": r.category, "avgPrice": round(r.avg_price, 1)}
            for r in cat_rows
        ] if cat_rows else []

        # ── 크롤 출처별 통계 ──
        now = datetime.utcnow()
        source_rows = session.execute(
            select(
                CrawlLog.crawler_name.label("source"),
                func.count().label("records"),
                func.max(CrawlLog.started_at).label("last_crawl"),
                func.sum(case((CrawlLog.status == CrawlStatus.FAILED, 1), else_=0)).label("fail_count"),
                func.count().label("total_count"),
            )
            .group_by(CrawlLog.crawler_name)
            .order_by(func.count().desc())
        ).all()

        source_stats = []
        for r in source_rows:
            fail_ratio = (r.fail_count or 0) / max(r.total_count, 1)
            hours_since = (now - r.last_crawl).total_seconds() / 3600 if r.last_crawl else 999
            if fail_ratio > 0.5 or hours_since > 72:
                status = "error"
            elif fail_ratio > 0.2 or hours_since > 24:
                status = "warning"
            else:
                status = "active"
            source_stats.append({
                "source": r.source,
                "records": r.records,
                "lastCrawl": r.last_crawl.isoformat() if r.last_crawl else None,
                "status": status,
            })

        # ── 최근 수집 활동 ──
        recent_rows = session.execute(
            select(CrawlLog)
            .order_by(CrawlLog.started_at.desc())
            .limit(10)
        ).scalars().all()

        recent_ingestions = []
        for r in recent_rows:
            st = "success"
            if r.status == CrawlStatus.FAILED:
                st = "error"
            elif r.status == CrawlStatus.PARTIAL:
                st = "warning"
            recent_ingestions.append({
                "id": f"ri-{r.id}",
                "source": r.crawler_name,
                "count": r.items_saved or r.items_found or 0,
                "date": r.started_at.strftime("%Y-%m-%d") if r.started_at else "",
                "status": st,
            })

        base["categoryAvgPrices"] = category_avg_prices
        base["sourceStats"] = source_stats
        base["recentIngestions"] = recent_ingestions
        return base
    finally:
        session.close()
