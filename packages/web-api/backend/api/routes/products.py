"""Public catalog API backed by the replaceable catalog SQLite snapshot."""
from __future__ import annotations

import math

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas.common import ApiResponse, PaginationMeta
from services.catalog_storage import CatalogUnavailable

router = APIRouter()


def _storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="상품 DB 연결이 없습니다")
    return storage


def _catalog_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CatalogUnavailable):
        return HTTPException(status_code=503, detail="상품 snapshot을 사용할 수 없습니다")
    return HTTPException(status_code=503, detail="상품 데이터를 불러올 수 없습니다")


@router.get("/search")
async def search_products(
    request: Request,
    q: str = Query("", description="검색어"),
    category: str | None = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    storage = _storage(request)
    try:
        search_page = getattr(storage, "search_products_page", None)
        if callable(search_page):
            data, total = search_page(
                q, category=category, page=page, per_page=per_page
            )
        else:
            data = storage.search_products(
                q, category=category, page=page, per_page=per_page
            )
            total = len(data)
    except Exception as exc:
        raise _catalog_error(exc) from exc
    return ApiResponse(
        data=data,
        meta=PaginationMeta(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=math.ceil(total / per_page) if total else 0,
        ),
    )


@router.get("/categories")
async def get_categories(request: Request):
    try:
        return ApiResponse(data=_storage(request).get_category_tree())
    except Exception as exc:
        raise _catalog_error(exc) from exc


@router.get("/popular")
async def get_popular_products(
    request: Request,
    per_page: int = Query(10, ge=1, le=50),
):
    try:
        data = _storage(request).search_products("", page=1, per_page=per_page)
    except Exception as exc:
        raise _catalog_error(exc) from exc
    return ApiResponse(data=data[:per_page])


@router.get("/category/{category_id}/compare")
async def compare_category_products(
    request: Request,
    category_id: str,
    sort: str = Query("price_asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    storage = _storage(request)
    try:
        children, category_total_count, category_path = storage.get_category_children(category_id)
        if children:
            raw_products = []
            total_rows = 0
        else:
            raw_products, total_rows = storage.get_category_products(
                category_id, page=page, per_page=per_page
            )
            if not raw_products:
                search_page = getattr(storage, "search_products_page", None)
                if callable(search_page):
                    raw_products, total_rows = search_page(
                        "", category=category_id, page=page, per_page=per_page
                    )
                else:
                    raw_products = storage.search_products(
                        "", category=category_id, page=page, per_page=per_page
                    )
                    total_rows = len(raw_products)
    except Exception as exc:
        raise _catalog_error(exc) from exc

    products = []
    for row in raw_products:
        current = row.get("cur") or row.get("price") or 0
        original = row.get("original_price") or row.get("avg") or current
        discount_pct = row.get("discount_pct")
        if discount_pct is None and current and original and original > current:
            discount_pct = round((1 - current / original) * 100)
        products.append({
            "id": row.get("id"),
            "name": row.get("name", ""),
            "source": row.get("source") or "",
            "brand": row.get("brand") or "",
            "category_path": row.get("cat") or "",
            "price": {
                "current": current,
                "original": original,
                "discount_pct": discount_pct or 0,
            },
            "normalized": {
                "per_100g": current,
                "unit_price_display": (
                    row.get("unit_price_display")
                    or row.get("display_unit")
                    or row.get("unit")
                    or ""
                ),
            },
            "attributes": row.get("attributes") or {},
            "image_url": row.get("img") or row.get("image_url") or "",
            "price_rank": row.get("price_tier") or "fair",
        })

    prices = [
        item["normalized"]["per_100g"]
        for item in products
        if item["normalized"]["per_100g"]
    ]
    avg = round(sum(prices) / len(prices)) if prices else 0
    summary = {
        "category_id": category_id,
        "category_path": (
            raw_products[0].get("cat", category_path)
            if raw_products else category_path
        ),
        "product_count": category_total_count if children else total_rows,
        "is_leaf": not bool(children),
        "avg_price_per_100g": avg,
        "min_price_per_100g": min(prices) if prices else 0,
        "max_price_per_100g": max(prices) if prices else 0,
        "hotdeal_threshold": round(avg * 0.85) if avg else 0,
        "ultra_threshold": round(avg * 0.7) if avg else 0,
    }

    if sort == "price_desc":
        products.sort(key=lambda item: item["price"]["current"] or 0, reverse=True)
    elif sort in ("price_asc", "discount"):
        products.sort(key=lambda item: item["price"]["current"] or 0)

    total = total_rows or len(products)
    return ApiResponse(data={
        "summary": summary,
        "subcategories": children,
        "products": products,
        "alternatives": [],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": math.ceil(total / per_page) if total else 0,
        },
    })


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    try:
        result = _storage(request).get_product_detail(product_id)
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.get("/{product_id}/price-history")
async def get_price_history(
    request: Request,
    product_id: int,
    days: int = Query(30, ge=7, le=365),
):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        history = storage.get_price_history(product_id, days) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=history)


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        compare = storage.get_price_compare(product_id) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=compare)


@router.get("/{product_id}/trust")
async def get_product_trust(request: Request, product_id: int):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        history = storage.get_price_history(product_id, 30) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")

    current = product.get("cur") or product.get("price") or 0
    prices = [row.get("price") for row in history if row.get("price")]
    avg = round(sum(prices) / len(prices)) if prices else product.get("avg") or current
    low = min(prices) if prices else product.get("low") or current
    return ApiResponse(data={
        "score": 75 if current and avg and current <= avg else 50,
        "confidence": "보통",
        "current_price": current,
        "historical_average_price": avg,
        "historical_low_price": low,
        "reference_count": len(prices),
        "standard_unit": (
            product.get("unit_price_display")
            or product.get("display_unit")
            or product.get("unit")
            or "100g"
        ),
        "rationale": "최근 가격 이력과 현재 관측가를 비교한 임시 신뢰도입니다.",
    })
