"""상품 CRUD + 가격 조회 + 통계 + 유사 상품 라우트"""
from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import AliasChoices, BaseModel, Field, field_validator
from typing import Optional, Any
from datetime import datetime, timedelta

from sqlalchemy import func, desc, asc, distinct, case, or_
from sqlalchemy.orm import Session

import logging

from services.base import get_session, managed_session

logger = logging.getLogger(__name__)
from api.auth import require_viewer, require_moderator, require_admin
from services.audit import log_action
from services.price_calc import (
    calculate_baseline_average,
    calculate_hotdeal_price,
    get_price_tier,
    get_price_history,
    get_price_comparison,
)
from storage.models import Product, DiscountHistory, HotdealPrice, Category, CrawlLog, BaselinePrice, ProductKeyword, Keyword
from api.security import (
    escape_like, MAX_NAME_LEN, MAX_CATEGORY_ID_LEN, MAX_UNIT_LEN,
    MAX_DESCRIPTION_LEN, MAX_URL_LEN, MAX_BULK_IDS, MAX_SOURCE_LEN,
)
from api.source_normalization import normalize_source_key, source_aliases

router = APIRouter(prefix="/products", tags=["products"])


class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=MAX_NAME_LEN)
    category_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
    unit: str = Field("개", min_length=1, max_length=MAX_UNIT_LEN)
    description: Optional[str] = Field(None, max_length=MAX_DESCRIPTION_LEN)
    image_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    source_type: Optional[str] = Field("unknown", max_length=MAX_SOURCE_LEN)
    attributes: Optional[dict[str, Any]] = None
    is_active: bool = True
    keyword_ids: Optional[list[int]] = None
    offer_source: Optional[str] = Field(None, max_length=MAX_SOURCE_LEN)
    channel: Optional[str] = Field(None, max_length=30)
    current_price: Optional[float] = Field(None, gt=0, validation_alias=AliasChoices("current_price", "sale_price"))
    original_price: Optional[float] = Field(None, gt=0)
    discount_rate: Optional[float] = Field(None, ge=0, le=100)
    discount_rate_manual: bool = False
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    source_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    quantity: Optional[str] = Field(None, max_length=100)
    offer_notes: Optional[str] = Field(None, max_length=MAX_DESCRIPTION_LEN)
    offer_raw_data: Optional[dict[str, Any]] = None

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("상품명은 공백만으로 구성될 수 없습니다.")
        return v.strip()

    @field_validator("image_url", "source_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다.")
        return v


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=MAX_NAME_LEN)
    category_id: Optional[str] = Field(None, max_length=MAX_CATEGORY_ID_LEN)
    unit: Optional[str] = Field(None, min_length=1, max_length=MAX_UNIT_LEN)
    description: Optional[str] = Field(None, max_length=MAX_DESCRIPTION_LEN)
    image_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    source_type: Optional[str] = Field(None, max_length=MAX_SOURCE_LEN)
    attributes: Optional[dict[str, Any]] = None
    is_active: Optional[bool] = None
    keyword_ids: Optional[list[int]] = None
    offer_source: Optional[str] = Field(None, max_length=MAX_SOURCE_LEN)
    channel: Optional[str] = Field(None, max_length=30)
    current_price: Optional[float] = Field(None, gt=0, validation_alias=AliasChoices("current_price", "sale_price"))
    original_price: Optional[float] = Field(None, gt=0)
    discount_rate: Optional[float] = Field(None, ge=0, le=100)
    discount_rate_manual: Optional[bool] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    source_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    quantity: Optional[str] = Field(None, max_length=100)
    offer_notes: Optional[str] = Field(None, max_length=MAX_DESCRIPTION_LEN)
    offer_raw_data: Optional[dict[str, Any]] = None

    @field_validator("image_url", "source_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v is not None and v and not v.startswith(("http://", "https://")):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다.")
        return v


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=MAX_BULK_IDS)


class BulkCategoryRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=MAX_BULK_IDS)
    category_id: str = Field(..., min_length=1, max_length=MAX_CATEGORY_ID_LEN)


OFFER_FIELDS = {
    "offer_source", "channel", "current_price", "original_price", "discount_rate",
    "discount_rate_manual", "valid_from", "valid_to", "source_url", "quantity",
    "offer_notes", "offer_raw_data",
}
PRODUCT_UPDATE_FIELDS = {
    "name", "category_id", "unit", "description", "image_url", "source_type",
    "attributes", "is_active",
}


def _has_offer_fields(body: ProductCreate | ProductUpdate) -> bool:
    for field in OFFER_FIELDS:
        if field not in body.model_fields_set:
            continue
        value = getattr(body, field)
        if field == "discount_rate_manual":
            if value is True:
                return True
            continue
        if value not in (None, ""):
            return True
    return False


def _clean_raw_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in raw_data.items() if v not in (None, "")}


def _discount_rate(current_price: float, original_price: float | None, manual_rate: float | None) -> float | None:
    if manual_rate is not None:
        return manual_rate
    if original_price and original_price > 0 and current_price > 0 and original_price >= current_price:
        return round((original_price - current_price) / original_price * 100, 1)
    return None


def _upsert_current_offer(session: Session, product: Product, body: ProductCreate | ProductUpdate) -> DiscountHistory | None:
    """Create/update the admin-managed current offer without inventing zero prices."""
    if not _has_offer_fields(body):
        return None

    latest = (
        session.query(DiscountHistory)
        .filter(DiscountHistory.product_id == product.id)
        .order_by(desc(DiscountHistory.crawled_at))
        .first()
    )

    current_price = body.current_price if body.current_price is not None else (latest.price if latest else None)
    if current_price is None or current_price <= 0:
        raise HTTPException(status_code=422, detail="현재 판매가를 0보다 큰 값으로 입력해야 가격 정보를 저장할 수 있습니다.")

    original_price = body.original_price if body.original_price is not None else (latest.original_price if latest else None)
    source = (body.offer_source or product.source_type or (latest.source if latest else None) or "user_submitted").strip()
    raw_data = dict(latest.raw_data or {}) if latest and latest.raw_data else {}
    raw_data.update(body.offer_raw_data or {})
    raw_data.update(_clean_raw_data({
        "channel": body.channel,
        "quantity": body.quantity,
        "notes": body.offer_notes,
        "unit": product.unit,
        "image_url": product.image_url,
        "admin_managed": True,
        "discount_rate_manual": bool(body.discount_rate_manual),
    }))

    target = latest or DiscountHistory(product_id=product.id, crawled_at=datetime.utcnow())
    if latest is None:
        session.add(target)

    target.price = current_price
    target.original_price = original_price
    target.discount_rate = _discount_rate(current_price, original_price, body.discount_rate)
    target.source = source or "user_submitted"
    target.source_url = body.source_url if body.source_url is not None else (latest.source_url if latest else None)
    target.valid_from = body.valid_from if "valid_from" in body.model_fields_set else (latest.valid_from if latest else None)
    target.valid_to = body.valid_to if "valid_to" in body.model_fields_set else (latest.valid_to if latest else None)
    target.crawled_at = datetime.utcnow()
    target.raw_data = raw_data or None
    return target


def _enrich_product(session: Session, p: Product) -> dict:
    """상품에 최신 가격 정보를 추가하여 반환."""
    try:
        latest = (
            session.query(DiscountHistory)
            .filter(DiscountHistory.product_id == p.id)
            .order_by(desc(DiscountHistory.crawled_at))
            .first()
        )
        # distinct()를 column wrapper가 아닌 query modifier로 사용
        # (cyextension resultproxy가 UnaryExpression 언팩 시 tuple index error 발생 방지)
        sources = (
            session.query(DiscountHistory.source)
            .filter(DiscountHistory.product_id == p.id)
            .distinct()
            .all()
        )
        hotdeal_sources = (
            session.query(HotdealPrice.source)
            .filter(HotdealPrice.product_id == p.id)
            .distinct()
            .all()
        )
        cat_name = ""
        if p.category_id and p.category:
            cat_name = p.category.name

        keyword_list = []
        try:
            for pk in (p.product_keywords or []):
                if pk.keyword:
                    keyword_list.append({"id": pk.keyword_id, "keyword": pk.keyword.word})
        except Exception:
            pass

        return {
            "id": p.id,
            "name": p.name,
            "category_id": p.category_id,
            "category_name": cat_name,
            "unit": p.unit,
            "description": p.description,
            "image_url": p.image_url,
            "source_type": p.source_type,
            "attributes": p.attributes,
            "is_active": p.is_active,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "current_price": latest.price if latest else None,
            "original_price": latest.original_price if latest else None,
            "discount_rate": latest.discount_rate if latest else None,
            "source": latest.source if latest else None,
            "offer_source": latest.source if latest else None,
            "source_url": latest.source_url if latest else None,
            "channel": (latest.raw_data or {}).get("channel") if latest else None,
            "quantity": (latest.raw_data or {}).get("quantity") if latest else None,
            "offer_notes": (latest.raw_data or {}).get("notes") if latest else None,
            "offer_raw_data": latest.raw_data if latest else None,
            "discount_rate_manual": bool((latest.raw_data or {}).get("discount_rate_manual")) if latest else False,
            "sources": sorted({
                normalized
                for raw in [s[0] for s in sources] + [s[0] for s in hotdeal_sources]
                if (normalized := normalize_source_key(raw))
            }),
            "valid_from": latest.valid_from.isoformat() if latest and latest.valid_from else None,
            "valid_to": latest.valid_to.isoformat() if latest and latest.valid_to else None,
            "crawled_at": latest.crawled_at.isoformat() if latest and latest.crawled_at else None,
            "keywords": keyword_list,
        }
    except Exception as e:
        logger.warning("_enrich_product failed for product %d: %s", p.id, str(e)[:200])
        cat_name = ""
        if p.category_id and p.category:
            try:
                cat_name = p.category.name
            except Exception:
                pass
        return {
            "id": p.id,
            "name": p.name,
            "category_id": p.category_id,
            "category_name": cat_name,
            "unit": p.unit,
            "description": getattr(p, "description", None),
            "image_url": getattr(p, "image_url", None),
            "source_type": getattr(p, "source_type", None),
            "attributes": getattr(p, "attributes", None),
            "is_active": getattr(p, "is_active", None),
            "created_at": p.created_at.isoformat() if getattr(p, "created_at", None) else None,
            "updated_at": p.updated_at.isoformat() if getattr(p, "updated_at", None) else None,
            "current_price": None,
            "original_price": None,
            "discount_rate": None,
            "source": None,
            "offer_source": None,
            "source_url": None,
            "channel": None,
            "quantity": None,
            "offer_notes": None,
            "offer_raw_data": None,
            "discount_rate_manual": False,
            "sources": [],
            "valid_from": None,
            "valid_to": None,
            "crawled_at": None,
            "keywords": [],
        }


@router.get("/stats")
def product_stats(identity: dict = Depends(require_viewer)):
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
        by_source = {}
        for raw_source, count in source_counts_q:
            source_key = normalize_source_key(raw_source)
            if not source_key:
                continue
            by_source[source_key] = by_source.get(source_key, 0) + count

        hotdeal_source_counts_q = (
            session.query(
                HotdealPrice.source,
                func.count(distinct(HotdealPrice.product_id)),
            )
            .join(Product, Product.id == HotdealPrice.product_id)
            .filter(Product.is_active == True)
            .group_by(HotdealPrice.source)
            .all()
        )
        for raw_source, count in hotdeal_source_counts_q:
            source_key = normalize_source_key(raw_source)
            if not source_key:
                continue
            by_source[source_key] = by_source.get(source_key, 0) + count

        source_type_counts_q = (
            session.query(Product.source_type, func.count(Product.id))
            .filter(Product.is_active == True, Product.source_type.isnot(None), Product.source_type != "unknown", Product.source_type != "")
            .group_by(Product.source_type)
            .all()
        )
        for source_type, count in source_type_counts_q:
            source_key = normalize_source_key(source_type)
            if source_key:
                by_source[source_key] = max(by_source.get(source_key, 0), count)
        by_source.setdefault("algumon", by_source.get("algumon", 0))

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
    category_search: Optional[str] = Query(None, description="카테고리명 검색"),
    keyword_id: Optional[int] = Query(None, description="키워드 ID 필터"),
    keyword_search: Optional[str] = Query(None, description="키워드 단어 검색"),
    sort_by: str = Query("name", description="정렬 기준 (name, price, discount_rate, created_at)"),
    sort_dir: str = Query("asc", description="정렬 방향 (asc, desc)"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    identity: dict = Depends(require_viewer),
):
    """상품 목록 — 필터·정렬·페이지네이션 지원."""
    session = get_session()
    try:
        query = session.query(Product).filter(Product.is_active == True)

        # 소스 필터: 가격 이력 source 또는 상품 source_type에서 해당 소스를 가진 상품
        if source:
            normalized_source = normalize_source_key(source, default=source)
            source_values = source_aliases(normalized_source) or {normalized_source}
            discount_source_filter = DiscountHistory.source.in_(source_values)
            hotdeal_source_filter = HotdealPrice.source.in_(source_values)
            product_source_filter = Product.source_type.in_(source_values)
            if normalized_source == "algumon":
                discount_source_filter = or_(discount_source_filter, DiscountHistory.source.ilike("%algumon.com%"))
                hotdeal_source_filter = or_(hotdeal_source_filter, HotdealPrice.source.ilike("%algumon.com%"))
                product_source_filter = or_(product_source_filter, Product.source_type.ilike("%algumon.com%"))
            product_ids = (
                session.query(distinct(DiscountHistory.product_id))
                .filter(discount_source_filter)
                .subquery()
            )
            hotdeal_product_ids = (
                session.query(distinct(HotdealPrice.product_id))
                .filter(hotdeal_source_filter)
                .subquery()
            )
            query = query.filter(or_(
                product_source_filter,
                Product.id.in_(session.query(product_ids)),
                Product.id.in_(session.query(hotdeal_product_ids)),
            ))

        # 카테고리 필터
        if category:
            query = query.filter(Product.category_id == category)

        # 검색
        if search:
            query = query.filter(Product.name.ilike(f"%{escape_like(search)}%"))

        if category_search:
            query = query.outerjoin(Category, Product.category_id == Category.id).filter(
                or_(
                    Product.category_id.ilike(f"%{escape_like(category_search)}%"),
                    Category.name.ilike(f"%{escape_like(category_search)}%"),
                )
            )

        # 키워드 ID 필터
        if keyword_id is not None:
            kw_product_ids = (
                session.query(ProductKeyword.product_id)
                .filter(ProductKeyword.keyword_id == keyword_id)
                .subquery()
            )
            query = query.filter(Product.id.in_(session.query(kw_product_ids)))

        # 키워드 단어 검색
        if keyword_search:
            kw_product_ids = (
                session.query(ProductKeyword.product_id)
                .join(Keyword, Keyword.id == ProductKeyword.keyword_id)
                .filter(Keyword.word.ilike(f"%{escape_like(keyword_search)}%"))
                .subquery()
            )
            query = query.filter(Product.id.in_(session.query(kw_product_ids)))

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
def get_product(product_id: int, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        return _enrich_product(session, p)
    finally:
        session.close()


@router.post("/", status_code=201)
def create_product(body: ProductCreate, request: Request, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        p = Product(
            name=body.name, category_id=body.category_id,
            unit=body.unit, description=body.description, image_url=body.image_url,
            source_type=body.source_type or "unknown", attributes=body.attributes,
            is_active=body.is_active,
        )
        session.add(p)
        session.flush()
        if body.keyword_ids:
            for kid in body.keyword_ids:
                session.add(ProductKeyword(product_id=p.id, keyword_id=kid))
            session.flush()
        _upsert_current_offer(session, p, body)
        session.refresh(p)
        return _enrich_product(session, p)


@router.put("/{product_id}")
def update_product(product_id: int, body: ProductUpdate, request: Request, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        for key, val in body.model_dump(
            exclude_unset=True,
            exclude=set(OFFER_FIELDS) | {"keyword_ids"},
        ).items():
            if key not in PRODUCT_UPDATE_FIELDS:
                continue
            setattr(p, key, val)
        if body.keyword_ids is not None:
            session.query(ProductKeyword).filter_by(product_id=product_id).delete()
            for kid in body.keyword_ids:
                session.add(ProductKeyword(product_id=product_id, keyword_id=kid))
        _upsert_current_offer(session, p, body)
        session.flush()
        session.refresh(p)
        return _enrich_product(session, p)


@router.delete("/{product_id}")
def delete_product(product_id: int, request: Request, identity: dict = Depends(require_admin)):
    """상품 삭제."""
    with managed_session() as session:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        session.delete(p)
        return {"deleted": True, "id": product_id}


@router.post("/bulk-delete")
def bulk_delete_products(body: BulkDeleteRequest, request: Request, identity: dict = Depends(require_admin)):
    """여러 상품 일괄 삭제."""
    with managed_session() as session:
        count = session.query(Product).filter(Product.id.in_(body.ids)).delete(synchronize_session=False)
        return {"deleted": count, "ids": body.ids}


@router.post("/bulk-category")
def bulk_update_category(body: BulkCategoryRequest, request: Request, identity: dict = Depends(require_moderator)):
    """여러 상품의 카테고리 일괄 변경."""
    with managed_session() as session:
        count = (
            session.query(Product)
            .filter(Product.id.in_(body.ids))
            .update({"category_id": body.category_id}, synchronize_session=False)
        )
        return {"updated": count, "category_id": body.category_id}


@router.get("/{product_id}/baseline")
def product_baseline(product_id: int, days: int = 90, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return calculate_baseline_average(session, product_id, days)
    finally:
        session.close()


@router.get("/{product_id}/hotdeal-price")
def product_hotdeal(product_id: int, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return calculate_hotdeal_price(session, product_id)
    finally:
        session.close()


@router.get("/{product_id}/tier")
def product_tier(product_id: int, price: float, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return get_price_tier(session, price, product_id)
    finally:
        session.close()


@router.get("/{product_id}/history")
def product_history(product_id: int, days: int = 30, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return get_price_history(session, product_id, days)
    finally:
        session.close()


@router.get("/{product_id}/comparison")
def product_comparison(product_id: int, identity: dict = Depends(require_viewer)):
    session = get_session()
    try:
        return get_price_comparison(session, product_id)
    finally:
        session.close()


@router.get("/{product_id}/similar")
def similar_products(product_id: int, limit: int = 10, identity: dict = Depends(require_viewer)):
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
        filters = [Product.name.ilike(f"%{escape_like(token)}%") for token in tokens[:5]]
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
