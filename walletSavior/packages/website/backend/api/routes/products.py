"""
상품(물가비교) API — 프론트엔드 '물가비교' 탭의 데이터 소스.

엔드포인트:
    GET /api/products          — 전체 상품 + 가격 통계
    GET /api/products/search   — 품목 검색
    GET /api/products/{id}     — 단일 상품 상세
    GET /api/products/{id}/history — 가격 추이 (차트용)
"""

from fastapi import APIRouter, Request, HTTPException, Query

router = APIRouter()


@router.get("")
async def list_products(request: Request):
    """
    전체 상품 목록 — 현재가/평균/최저/최고/매장별 가격 포함.

    프론트엔드 PRODUCTS 배열과 동일 shape 반환.
    """
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        return MOCK_PRODUCTS

    return storage.get_products()


@router.get("/search")
async def search_products(request: Request, q: str = Query(..., description="검색어")):
    """품목 검색 — 이름 또는 카테고리에 검색어가 포함된 상품."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        q_lower = q.lower()
        return [p for p in MOCK_PRODUCTS if q_lower in p["name"] or q_lower in p["cat"]]

    return storage.search_products(q)


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    """단일 상품 상세 — 전체 통계 + 매장별 가격."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        return product

    result = storage.get_product_detail(product_id)
    if not result:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return result


@router.get("/{product_id}/history")
async def get_price_history(
    request: Request,
    product_id: int,
    days: int = Query(30, ge=7, le=365, description="조회 기간 (일)"),
):
    """
    가격 추이 — 차트 렌더링용 [{date, price}] 배열.

    프론트엔드 genPriceHistory()와 동일 shape.
    """
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import mock_price_history
        return mock_price_history(product_id, days)

    return storage.get_price_history(product_id, days)
