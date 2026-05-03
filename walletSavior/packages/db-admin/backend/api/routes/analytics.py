"""분석 데이터 라우트"""
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime, timedelta

from sqlalchemy import select, func, case, and_, distinct

from services.base import get_session, managed_session
from api.auth import require_viewer, require_moderator, require_admin
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
from api.middleware.rate_limit import limiter, EXPORT_LIMIT
from starlette.requests import Request as StarletteRequest
from storage.models import (
    Product, BaselinePrice, DiscountHistory, HotdealPrice,
    Category, CrawlLog, CrawlStatus,
)
from api.source_normalization import normalize_sources

from api.security import escape_like, make_error, MAX_VALIDATE_ITEMS

ALLOWED_DUPLICATE_FIELDS = {
    "products": {"name", "category_id"},
    "baseline_prices": {"product_id", "source", "price"},
    "discount_history": {"product_id", "source", "price"},
    "hotdeal_prices": {"product_id", "source", "price"},
    "categories": {"name", "parent_id"},
    "keywords": {"word"},
}
ALLOWED_TABLE_NAMES = set(ALLOWED_DUPLICATE_FIELDS.keys())

router = APIRouter(prefix="/analytics", tags=["analytics"])


class DuplicateRequest(BaseModel):
    table_name: str = Field(..., max_length=50)
    fields: list[str] = Field(..., min_length=1, max_length=5)

    @field_validator("table_name")
    @classmethod
    def validate_table(cls, v: str) -> str:
        if v not in ALLOWED_TABLE_NAMES:
            raise ValueError(f"허용되지 않는 테이블: {v}")
        return v


class ValidateRequest(BaseModel):
    items: list[dict] = Field(..., min_length=1, max_length=MAX_VALIDATE_ITEMS)


class OutlierActionRequest(BaseModel):
    action: Literal["whitelist", "delete", "edit"]
    new_price: Optional[float] = None


@router.get("/outliers/{product_id}")
def outliers(product_id: int, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return check_price_outliers(session, product_id)
    finally:
        session.close()


@router.post("/duplicates")
def duplicates(body: DuplicateRequest, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return find_duplicates(session, body.table_name, body.fields)
    finally:
        session.close()


@router.post("/validate")
def validate(body: ValidateRequest, identity: dict = Depends(require_viewer)):
    return validate_crawl_data(body.items)


@router.get("/quality-report")
def quality_report(identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return generate_quality_report(session)
    finally:
        session.close()


@router.post("/cleanup")
def cleanup(days: int = 180, identity: dict = Depends(require_admin)):
    with managed_session() as session:
        return cleanup_stale_data(session, days)


@router.get("/export/prices/{product_id}")
@limiter.limit(EXPORT_LIMIT)
def export_prices(request: StarletteRequest, product_id: int, days: int = 30, identity: dict = Depends(require_moderator)):
    session = get_session()
    try:
        csv_data = export_prices_csv(session, product_id, days)
        return {"csv": csv_data}
    finally:
        session.close()


@router.get("/export/products")
@limiter.limit(EXPORT_LIMIT)
def export_products(request: StarletteRequest, category_id: Optional[str] = None, identity: dict = Depends(require_moderator)):
    session = get_session()
    try:
        json_data = export_products_json(session, category_id)
        return {"json": json_data}
    finally:
        session.close()


@router.get("/summary")
def summary(identity: dict = Depends(require_viewer)):
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


@router.get("/price-trends")
def price_trends(
    product_ids: list[int] = Query(default=[]),
    days: int = 30,
    identity: dict = Depends(require_viewer),
):
    """복수 상품 가격 추이 — 같은 차트에 여러 상품 라인 비교"""
    session = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        result = {}

        for pid in product_ids[:5]:
            product = session.execute(
                select(Product).where(Product.id == pid)
            ).scalar_one_or_none()
            if not product:
                continue

            # 기준가 이력
            baseline_rows = session.execute(
                select(BaselinePrice.price, BaselinePrice.recorded_at)
                .where(and_(
                    BaselinePrice.product_id == pid,
                    BaselinePrice.recorded_at >= cutoff,
                ))
                .order_by(BaselinePrice.recorded_at)
            ).all()

            # 할인가 이력
            discount_rows = session.execute(
                select(DiscountHistory.price, DiscountHistory.crawled_at)
                .where(and_(
                    DiscountHistory.product_id == pid,
                    DiscountHistory.crawled_at >= cutoff,
                ))
                .order_by(DiscountHistory.crawled_at)
            ).all()

            # 날짜별 가격 병합 (기준가 우선)
            date_prices: dict[str, float] = {}
            for r in baseline_rows:
                d = r.recorded_at.strftime("%Y-%m-%d") if r.recorded_at else None
                if d:
                    date_prices[d] = r.price
            for r in discount_rows:
                d = r.crawled_at.strftime("%Y-%m-%d") if r.crawled_at else None
                if d and d not in date_prices:
                    date_prices[d] = r.price

            data = [{"date": d, "price": p} for d, p in sorted(date_prices.items())]

            # 최신 기준가 (수평선용)
            latest_baseline = session.execute(
                select(BaselinePrice.price)
                .where(BaselinePrice.product_id == pid)
                .order_by(BaselinePrice.recorded_at.desc())
                .limit(1)
            ).scalar()

            # 최저 핫딜가 (수평선용)
            hotdeal_min = session.execute(
                select(func.min(HotdealPrice.price))
                .where(HotdealPrice.product_id == pid)
            ).scalar()

            result[str(pid)] = {
                "name": product.name,
                "data": data,
                "baselinePrice": latest_baseline,
                "hotdealPrice": float(hotdeal_min) if hotdeal_min else None,
            }

        return result
    finally:
        session.close()


@router.get("/source-stats")
def source_stats_detail(identity: dict = Depends(require_viewer)):
    """소스별 상세 통계 — 상품 수, 평균 가격, 최근 업데이트"""
    session = get_session()
    try:
        now = datetime.utcnow()
        stats: dict[str, dict] = {}

        # 기준가 소스별
        baseline_rows = session.execute(
            select(
                BaselinePrice.source,
                func.count(func.distinct(BaselinePrice.product_id)).label("product_count"),
                func.avg(BaselinePrice.price).label("avg_price"),
                func.max(BaselinePrice.recorded_at).label("last_update"),
                func.count().label("total_records"),
            ).group_by(BaselinePrice.source)
        ).all()

        for r in baseline_rows:
            hours = (
                (now - r.last_update).total_seconds() / 3600
                if r.last_update else 999
            )
            status = "error" if hours > 72 else ("warning" if hours > 24 else "active")
            stats[r.source] = {
                "source": r.source,
                "productCount": r.product_count,
                "avgPrice": round(float(r.avg_price or 0)),
                "lastUpdate": r.last_update.isoformat() if r.last_update else None,
                "totalRecords": r.total_records,
                "status": status,
            }

        # 할인가 소스별
        discount_rows = session.execute(
            select(
                DiscountHistory.source,
                func.count(func.distinct(DiscountHistory.product_id)).label("product_count"),
                func.avg(DiscountHistory.price).label("avg_price"),
                func.max(DiscountHistory.crawled_at).label("last_update"),
                func.count().label("total_records"),
            ).group_by(DiscountHistory.source)
        ).all()

        for r in discount_rows:
            hours = (
                (now - r.last_update).total_seconds() / 3600
                if r.last_update else 999
            )
            status = "error" if hours > 72 else ("warning" if hours > 24 else "active")
            if r.source in stats:
                existing = stats[r.source]
                existing["productCount"] += r.product_count
                existing["avgPrice"] = round(
                    (existing["avgPrice"] + float(r.avg_price or 0)) / 2
                )
                existing["totalRecords"] += r.total_records
                # 최신 업데이트 일시 갱신
                if r.last_update:
                    iso = r.last_update.isoformat()
                    if not existing["lastUpdate"] or iso > existing["lastUpdate"]:
                        existing["lastUpdate"] = iso
                # 상태 재계산
                lu = existing["lastUpdate"]
                if lu:
                    h = (now - datetime.fromisoformat(lu)).total_seconds() / 3600
                    existing["status"] = (
                        "error" if h > 72 else ("warning" if h > 24 else "active")
                    )
            else:
                stats[r.source] = {
                    "source": r.source,
                    "productCount": r.product_count,
                    "avgPrice": round(float(r.avg_price or 0)),
                    "lastUpdate": r.last_update.isoformat() if r.last_update else None,
                    "totalRecords": r.total_records,
                    "status": status,
                }

        return sorted(stats.values(), key=lambda x: x["totalRecords"], reverse=True)
    finally:
        session.close()


@router.get("/products/search")
def search_products_autocomplete(q: str = "", limit: int = 10, identity: dict = Depends(require_viewer)):
    """상품 검색 자동완성"""
    session = get_session()
    try:
        stmt = (
            select(Product.id, Product.name)
            .where(Product.is_active == True, Product.name.ilike(f"%{escape_like(q)}%"))
            .order_by(Product.name)
            .limit(limit)
        )
        rows = session.execute(stmt).all()
        return [{"id": r.id, "name": r.name} for r in rows]
    finally:
        session.close()


@router.get("/source-distribution")
def source_distribution(identity: dict = Depends(require_viewer)):
    """소스별 상품 수 분포 (도넛 차트용)"""
    session = get_session()
    try:
        rows = session.execute(
            select(
                DiscountHistory.source.label("source"),
                func.count(distinct(DiscountHistory.product_id)).label("count"),
            )
            .join(Product, Product.id == DiscountHistory.product_id)
            .filter(Product.is_active == True)
            .group_by(DiscountHistory.source)
            .order_by(func.count(distinct(DiscountHistory.product_id)).desc())
        ).all()
        total = sum(r.count for r in rows) or 1
        return [
            {"source": r.source, "count": r.count, "percentage": round(r.count / total * 100, 1)}
            for r in rows
        ]
    finally:
        session.close()


@router.get("/category-distribution")
def category_distribution(identity: dict = Depends(require_viewer)):
    """카테고리별 상품 수 (가로 막대 차트용)"""
    session = get_session()
    try:
        rows = session.execute(
            select(
                Category.name.label("category"),
                func.count(Product.id).label("count"),
            )
            .join(Product, Product.category_id == Category.id)
            .filter(Product.is_active == True)
            .group_by(Category.name)
            .order_by(func.count(Product.id).desc())
        ).all()
        return [{"category": r.category, "count": r.count} for r in rows]
    finally:
        session.close()


@router.get("/daily-trend")
def daily_trend(days: int = Query(30, ge=1, le=90), identity: dict = Depends(require_viewer)):
    """일별 상품 추가 추이 (라인 차트용)"""
    session = get_session()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        rows = session.execute(
            select(
                func.date(Product.created_at).label("date"),
                func.count(Product.id).label("count"),
            )
            .filter(Product.created_at >= cutoff)
            .group_by(func.date(Product.created_at))
            .order_by(func.date(Product.created_at))
        ).all()

        date_counts = {str(r.date): r.count for r in rows}
        result = []
        for i in range(days):
            d = (datetime.utcnow() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            result.append({"date": d, "count": date_counts.get(d, 0)})
        return result
    finally:
        session.close()


@router.get("/data-quality-summary")
def data_quality_summary(identity: dict = Depends(require_viewer)):
    """데이터 품질 요약 — 완성도 메트릭"""
    session = get_session()
    try:
        total = session.execute(
            select(func.count(Product.id)).filter(Product.is_active == True)
        ).scalar() or 0

        with_price = session.execute(
            select(func.count(distinct(DiscountHistory.product_id)))
            .join(Product, Product.id == DiscountHistory.product_id)
            .filter(Product.is_active == True)
        ).scalar() or 0

        with_category = session.execute(
            select(func.count(Product.id))
            .filter(Product.is_active == True, Product.category_id.isnot(None))
        ).scalar() or 0

        with_image = session.execute(
            select(func.count(Product.id))
            .filter(Product.is_active == True, Product.image_url.isnot(None), Product.image_url != "")
        ).scalar() or 0

        now = datetime.utcnow()
        expired = session.execute(
            select(func.count(distinct(DiscountHistory.product_id)))
            .filter(
                DiscountHistory.valid_to.isnot(None),
                DiscountHistory.valid_to < now,
            )
        ).scalar() or 0

        return {
            "total": total,
            "withPrice": with_price,
            "withPriceRate": round(with_price / total * 100, 1) if total else 0,
            "withCategory": with_category,
            "withCategoryRate": round(with_category / total * 100, 1) if total else 0,
            "withImage": with_image,
            "withImageRate": round(with_image / total * 100, 1) if total else 0,
            "expired": expired,
        }
    finally:
        session.close()


@router.post("/outliers/{outlier_id}/action")
def outlier_action(outlier_id: str, body: OutlierActionRequest, identity: dict = Depends(require_viewer)):
    """이상치 관리 — 정상/삭제/수정"""
    raw_id = outlier_id.replace("o-", "") if outlier_id.startswith("o-") else outlier_id
    try:
        bp_id = int(raw_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="잘못된 이상치 ID입니다")

    session = get_session()
    try:
        bp = session.get(BaselinePrice, bp_id)
        if not bp:
            raise HTTPException(status_code=404, detail="해당 가격 레코드를 찾을 수 없습니다")

        if body.action == "whitelist":
            from api.routes.prices import _load_whitelist, _save_whitelist
            whitelist = _load_whitelist()
            whitelist.add(bp_id)
            _save_whitelist(whitelist)
            return {"status": "ok", "action": "whitelist", "id": outlier_id}

        elif body.action == "delete":
            session.delete(bp)
            session.commit()
            return {"status": "ok", "action": "delete", "id": outlier_id}

        elif body.action == "edit":
            if body.new_price is None or body.new_price <= 0:
                raise HTTPException(status_code=400, detail="수정할 가격을 입력하세요")
            bp.price = body.new_price
            session.commit()
            return {"status": "ok", "action": "edit", "id": outlier_id, "newPrice": body.new_price}

        else:
            raise HTTPException(status_code=400, detail="잘못된 액션입니다")
    finally:
        session.close()


@router.get("/source-types")
def source_types(identity: dict = Depends(require_viewer)):
    """DB에 존재하는 모든 소스 타입 목록"""
    session = get_session()
    try:
        discount_sources = session.execute(
            select(distinct(DiscountHistory.source))
            .filter(DiscountHistory.source.isnot(None))
        ).scalars().all()

        hotdeal_sources = session.execute(
            select(distinct(HotdealPrice.source))
            .filter(HotdealPrice.source.isnot(None))
        ).scalars().all()

        product_sources = session.execute(
            select(distinct(Product.source_type))
            .filter(Product.source_type.isnot(None))
        ).scalars().all()

        return normalize_sources([*discount_sources, *hotdeal_sources, *product_sources, "algumon"])
    finally:
        session.close()
