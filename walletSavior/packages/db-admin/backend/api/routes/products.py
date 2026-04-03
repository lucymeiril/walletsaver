"""상품 CRUD + 가격 조회 + 통계 + 유사 상품 라우트"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import func, desc, asc, distinct, case, or_
from sqlalchemy.orm import Session

from services.base import get_session
from services.price_calc import (
    calculate_baseline_average,
    calculate_hotdeal_price,
    get_price_tier,
    get_price_history,
    get_price_comparison,
)
from storage.models import Product, DiscountHistory, Category, CrawlLog, BaselinePrice

router = APIRouter(prefix="/products", tags=["products"])


class ProductCreate(BaseModel):
    name: str
    category_id: Optional[str] = None
    unit: str = "개"
    description: Optional[str] = None
    image_url: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class BulkDeleteRequest(BaseModel):
    ids: list[int]


class BulkCategoryRequest(BaseModel):
    ids: list[int]
    category_id: str


def _enrich_product(session: Session, p: Product) -> dict:
    """상품에 최신 가격 정보를 추가하여 반환."""
    latest = (
        session.query(DiscountHistory)
        .filter(DiscountHistory.product_id == p.id)
        .order_by(desc(DiscountHistory.crawled_at))
        .first()
    )
    sources = (
        session.query(distinct(DiscountHistory.source))
        .filter(DiscountHistory.product_id == p.id)
        .all()
    )
    cat_name = ""
    if p.category_id and p.category:
        cat_name = p.category.name

    return {
        "id": p.id,
        "name": p.name,
        "category_id": p.category_id,
        "category_name": cat_name,
        "unit": p.unit,
        "description": p.description,
        "image_url": p.image_url,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "current_price": latest.price if latest else None,
        "original_price": latest.original_price if latest else None,
        "discount_rate": latest.discount_rate if latest else None,
        "source": latest.source if latest else None,
        "sources": [s[0] for s in sources],
        "valid_from": latest.valid_from.isoformat() if latest and latest.valid_from else None,
        "valid_to": latest.valid_to.isoformat() if latest and latest.valid_to else None,
        "crawled_at": latest.crawled_at.isoformat() if latest and latest.crawled_at else None,
    }


@router.get("/stats")
def product_stats():
    """통계 — 소스별·카테고리별 상품 수, 마지막 크롤 날짜."""
    session = get_session()
    try:
        total = session.query(func.count(Product.id)).filter(Product.is_active == True).scalar() or 0

        # 소스별 상품 수 (DiscountHistory 기준)
        source_counts_q = (
            session.query(
                DiscountHistory.source,
                func.count(distinct(DiscountHistory.product_id)),
            )
            .join(Product, Product.id == DiscountHistory.product_id)
            .filter(Product.is_active == True)
            .group_by(DiscountHistory.source)
            .all()
        )
        by_source = {row[0]: row[1] for row in source_counts_q}

        # 카테고리별 상품 수
        cat_counts_q = (
            session.query(
                Category.name,
                func.count(Product.id),
            )
            .join(Product, Product.category_id == Category.id)
            .filter(Product.is_active == True)
            .group_by(Category.name)
            .order_by(desc(func.count(Product.id)))
            .limit(10)
            .all()
        )
        by_category = [{"name": row[0], "count": row[1]} for row in cat_counts_q]

        # 가격 없는 상품 수 (DiscountHistory 없는 활성 상품)
        products_with_price = (
            session.query(distinct(DiscountHistory.product_id))
            .join(Product, Product.id == DiscountHistory.product_id)
            .filter(Product.is_active == True)
            .subquery()
        )
        no_price = (
            session.query(func.count(Product.id))
            .filter(Product.is_active == True)
            .filter(~Product.id.in_(session.query(products_with_price)))
            .scalar()
        ) or 0

        # 마지막 크롤 날짜 (DiscountHistory 기준)
        last_crawl_q = (
            session.query(
                DiscountHistory.source,
                func.max(DiscountHistory.crawled_at),
            )
            .group_by(DiscountHistory.source)
            .all()
        )
        last_crawl = {
            row[0]: row[1].isoformat() if row[1] else None
            for row in last_crawl_q
        }

        return {
            "total": total,
            "by_source": by_source,
            "by_category": by_category,
            "no_price": no_price,
            "last_crawl": last_crawl,
        }
    finally:
        session.close()


@router.get("/")
def list_products(
    source: Optional[str] = Query(None, description="소스 필터 (emart, homeplus 등)"),
    category: Optional[str] = Query(None, description="카테고리 ID 필터"),
    search: Optional[str] = Query(None, description="상품명 검색"),
    sort_by: str = Query("name", description="정렬 기준 (name, price, discount_rate, created_at)"),
    sort_dir: str = Query("asc", description="정렬 방향 (asc, desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
):
    """상품 목록 — 필터·정렬·페이지네이션 지원."""
    session = get_session()
    try:
        query = session.query(Product).filter(Product.is_active == True)

        # 소스 필터: DiscountHistory에서 해당 소스를 가진 상품만
        if source:
            product_ids = (
                session.query(distinct(DiscountHistory.product_id))
                .filter(DiscountHistory.source == source)
                .subquery()
            )
            query = query.filter(Product.id.in_(
                session.query(product_ids)
            ))

        # 카테고리 필터
        if category:
            query = query.filter(Product.category_id == category)

        # 검색
        if search:
            query = query.filter(Product.name.contains(search))

        # 총 개수
        total = query.count()

        # 정렬
        sort_col = {
            "name": Product.name,
            "created_at": Product.created_at,
        }.get(sort_by, Product.name)

        if sort_by in ("price", "discount_rate"):
            # 가격/할인율 정렬: 최신 DiscountHistory 서브쿼리
            latest_sub = (
                session.query(
                    DiscountHistory.product_id,
                    func.max(DiscountHistory.crawled_at).label("max_date"),
                )
                .group_by(DiscountHistory.product_id)
                .subquery()
            )
            price_sub = (
                session.query(
                    DiscountHistory.product_id,
                    DiscountHistory.price,
                    DiscountHistory.discount_rate,
                )
                .join(
                    latest_sub,
                    (DiscountHistory.product_id == latest_sub.c.product_id)
                    & (DiscountHistory.crawled_at == latest_sub.c.max_date),
                )
                .subquery()
            )
            query = query.outerjoin(price_sub, Product.id == price_sub.c.product_id)
            sort_col = price_sub.c.price if sort_by == "price" else price_sub.c.discount_rate

        order_fn = desc if sort_dir == "desc" else asc
        query = query.order_by(order_fn(sort_col))

        # 페이지네이션
        offset = (page - 1) * per_page
        products = query.offset(offset).limit(per_page).all()

        items = [_enrich_product(session, p) for p in products]

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }
    finally:
        session.close()


@router.get("/{product_id}")
def get_product(product_id: int):
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        return _enrich_product(session, p)
    finally:
        session.close()


@router.post("/", status_code=201)
def create_product(body: ProductCreate):
    session = get_session()
    try:
        p = Product(
            name=body.name, category_id=body.category_id,
            unit=body.unit, description=body.description, image_url=body.image_url,
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        return {"id": p.id, "name": p.name}
    finally:
        session.close()


@router.put("/{product_id}")
def update_product(product_id: int, body: ProductUpdate):
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        for key, val in body.model_dump(exclude_unset=True).items():
            setattr(p, key, val)
        session.commit()
        return {"id": p.id, "name": p.name}
    finally:
        session.close()


@router.delete("/{product_id}")
def delete_product(product_id: int):
    """상품 삭제."""
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        session.delete(p)
        session.commit()
        return {"deleted": True, "id": product_id}
    finally:
        session.close()


@router.post("/bulk-delete")
def bulk_delete_products(body: BulkDeleteRequest):
    """여러 상품 일괄 삭제."""
    session = get_session()
    try:
        count = session.query(Product).filter(Product.id.in_(body.ids)).delete(synchronize_session=False)
        session.commit()
        return {"deleted": count, "ids": body.ids}
    finally:
        session.close()


@router.post("/bulk-category")
def bulk_update_category(body: BulkCategoryRequest):
    """여러 상품의 카테고리 일괄 변경."""
    session = get_session()
    try:
        count = (
            session.query(Product)
            .filter(Product.id.in_(body.ids))
            .update({"category_id": body.category_id}, synchronize_session=False)
        )
        session.commit()
        return {"updated": count, "category_id": body.category_id}
    finally:
        session.close()


@router.get("/{product_id}/baseline")
def product_baseline(product_id: int, days: int = 90):
    session = get_session()
    try:
        return calculate_baseline_average(session, product_id, days)
    finally:
        session.close()


@router.get("/{product_id}/hotdeal-price")
def product_hotdeal(product_id: int):
    session = get_session()
    try:
        return calculate_hotdeal_price(session, product_id)
    finally:
        session.close()


@router.get("/{product_id}/tier")
def product_tier(product_id: int, price: float):
    session = get_session()
    try:
        return get_price_tier(session, price, product_id)
    finally:
        session.close()


@router.get("/{product_id}/history")
def product_history(product_id: int, days: int = 30):
    session = get_session()
    try:
        return get_price_history(session, product_id, days)
    finally:
        session.close()


@router.get("/{product_id}/comparison")
def product_comparison(product_id: int):
    session = get_session()
    try:
        return get_price_comparison(session, product_id)
    finally:
        session.close()


@router.get("/{product_id}/similar")
def similar_products(product_id: int, limit: int = 10):
    """유사 상품 감지 — 이름 포함 관계 기반 중복 후보 반환."""
    session = get_session()
    try:
        product = session.get(Product, product_id)
        if not product:
            raise HTTPException(404, "Product not found")

        name = product.name.strip()
        # 이름에서 핵심 토큰 추출 (2글자 이상)
        tokens = [t for t in name.replace("(", " ").replace(")", " ").split() if len(t) >= 2]

        if not tokens:
            return []

        # 각 토큰을 포함하는 다른 상품 검색
        filters = [Product.name.contains(token) for token in tokens[:5]]
        candidates = (
            session.query(Product)
            .filter(Product.id != product_id, Product.is_active == True)
            .filter(or_(*filters))
            .limit(limit * 3)
            .all()
        )

        # 토큰 매칭 점수 계산
        scored = []
        for c in candidates:
            cname = c.name.lower()
            matched = sum(1 for t in tokens if t.lower() in cname)
            score = matched / len(tokens) if tokens else 0
            if score >= 0.4:  # 40% 이상 토큰 일치
                scored.append((c, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        result = []
        for c, score in scored[:limit]:
            result.append({
                "id": c.id,
                "name": c.name,
                "category_id": c.category_id,
                "similarity": round(score, 2),
            })
        return result
    finally:
        session.close()
