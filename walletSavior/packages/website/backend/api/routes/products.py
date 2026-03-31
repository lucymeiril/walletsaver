"""
상품(물가비교) API — 프론트엔드 '물가비교' 탭의 데이터 소스.

엔드포인트:
    GET /api/products/search          — 상품 검색
    GET /api/products/{id}            — 상품 상세
    GET /api/products/{id}/price-history  — 가격 이력
    GET /api/products/{id}/price-compare  — 출처별 비교
"""

import math
from fastapi import APIRouter, Request, HTTPException, Query
from api.schemas.common import ApiResponse, PaginationMeta

router = APIRouter()


@router.get("/search")
async def search_products(
    request: Request,
    q: str = Query("", description="검색어"),
    category: str = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """상품 검색 — 이름/카테고리에 검색어가 포함된 상품."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        results = MOCK_PRODUCTS
        if q:
            q_lower = q.lower()
            results = [p for p in results if q_lower in p["name"] or q_lower in p["cat"]]
        if category:
            results = [p for p in results if category in p.get("cat", "")]

        total = len(results)
        start = (page - 1) * per_page
        paginated = results[start:start + per_page]

        return ApiResponse(
            data=paginated,
            meta=PaginationMeta(
                page=page,
                per_page=per_page,
                total=total,
                total_pages=math.ceil(total / per_page) if total > 0 else 0,
            ),
        )

    data = storage.search_products(q, category=category, page=page, per_page=per_page)
    return ApiResponse(data=data)


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    """단일 상품 상세."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        return ApiResponse(data=product)

    result = storage.get_product_detail(product_id)
    if not result:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.get("/{product_id}/price-history")
async def get_price_history(
    request: Request,
    product_id: int,
    days: int = Query(30, ge=7, le=365, description="조회 기간 (일)"),
):
    """가격 추이 — 차트 렌더링용."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import mock_price_history, MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        return ApiResponse(data=mock_price_history(product_id, days))

    return ApiResponse(data=storage.get_price_history(product_id, days))


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    """출처별 가격 비교."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")

        compare = []
        for source, price in product.get("stores", {}).items():
            orig = product["avg"]
            disc = round((1 - price / orig) * 100, 1) if orig else None
            compare.append({
                "source": source,
                "price": price,
                "original_price": orig,
                "discount_rate": disc,
                "url": None,
            })
        compare.sort(key=lambda x: x["price"])
        return ApiResponse(data=compare)

    return ApiResponse(data=storage.get_price_compare(product_id))
