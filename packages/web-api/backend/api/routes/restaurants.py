"""
식당 / 레시피 API.

엔드포인트:
    GET /api/restaurants/nearby   — 주변 식당
    GET /api/recipes/compare      — 레시피 가격 비교
"""

from fastapi import APIRouter, Request, Query
from api.schemas.common import ApiResponse

router = APIRouter()

@router.get("/restaurants/nearby")
async def nearby_restaurants(
    request: Request,
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    radius: int = Query(5000, ge=100, le=50000, description="반경 (미터)"),
    category: str = Query(None, description="카테고리 필터"),
    sort: str = Query("distance", description="정렬 (distance, rating, price_asc)"),
):
    """주변 식당 조회.

    실제 식당 데이터는 /api/local 네이버 검색 경로에서 제공한다.
    """
    return ApiResponse(data=[])


@router.get("/recipes/compare")
async def compare_recipes(request: Request):
    """레시피 가격 비교 (직접 해먹기 vs 배달 vs 외식)."""
    return ApiResponse(data=[])
