"""
상품(물가비교) API — 프론트엔드 '물가비교' 탭의 데이터 소스.

엔드포인트:
    GET /api/products/search             — 상품 검색
    GET /api/products/categories         — 카테고리 목록
    GET /api/products/popular            — 인기 상품
    GET /api/products/{id}               — 상품 상세
    GET /api/products/{id}/price-history — 가격 이력
    GET /api/products/{id}/price-compare — 출처별 비교
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
    """상품 검색 — DB에서 이름/카테고리에 검색어가 포함된 상품 조회."""
    storage = request.app.state.storage
    if storage is None:
        # DB 미연결 시 빈 결과 반환
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))

    data = storage.search_products(q, category=category, page=page, per_page=per_page)
    return ApiResponse(data=data)


@router.get("/categories")
async def get_categories(request: Request):
    """상품 카테고리 목록."""
    DEFAULT_CATEGORIES = [
        {"id": "agricultural", "name": "농산물", "icon": "🥬"},
        {"id": "livestock", "name": "축산물", "icon": "🥩"},
        {"id": "seafood", "name": "수산물", "icon": "🐟"},
        {"id": "processed", "name": "가공식품", "icon": "🥫"},
        {"id": "living", "name": "생활용품", "icon": "🧴"},
        {"id": "electronics", "name": "전자제품", "icon": "📱"},
        {"id": "fashion", "name": "패션", "icon": "👕"},
        {"id": "etc", "name": "기타", "icon": "📦"},
    ]
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=DEFAULT_CATEGORIES)

    try:
        categories = storage.get_categories()
        return ApiResponse(data=categories)
    except Exception:
        return ApiResponse(data=DEFAULT_CATEGORIES)


@router.get("/trending")
async def get_trending_keywords(request: Request):
    """인기 검색어 — DB 상품명 기반 트렌딩 키워드 조회."""
    storage = request.app.state.storage
    default_keywords = ["삼겹살", "계란", "양파", "우유", "라면", "사과", "쌀", "배추"]
    if storage is None:
        return ApiResponse(data=default_keywords)

    try:
        products = storage.search_products("")
        if products:
            keywords = [p["name"] for p in products[:8]]
            return ApiResponse(data=keywords if keywords else default_keywords)
    except Exception:
        pass
    return ApiResponse(data=default_keywords)


@router.get("/popular")
async def get_popular_products(
    request: Request,
    per_page: int = Query(10, ge=1, le=50),
):
    """인기/트렌딩 상품 목록 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    results = storage.search_products("")
    if isinstance(results, dict) and "items" in results:
        return ApiResponse(data=results["items"][:per_page])
    if isinstance(results, list):
        return ApiResponse(data=results[:per_page])
    return ApiResponse(data=results)


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    """단일 상품 상세 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="DB 미연결")

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
    """가격 추이 — 차트 렌더링용. DB에서 실제 가격 이력 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    return ApiResponse(data=storage.get_price_history(product_id, days))


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    """출처별 가격 비교 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    return ApiResponse(data=storage.get_price_compare(product_id))
