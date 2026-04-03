"""
식당 / 레시피 API.

엔드포인트:
    GET /api/restaurants/nearby   — 주변 식당
    GET /api/recipes/compare      — 레시피 가격 비교
"""

import math
from fastapi import APIRouter, Request, Query
from api.schemas.common import ApiResponse

router = APIRouter()


def _haversine(lat1, lng1, lat2, lng2):
    """두 좌표 간 거리 (미터)."""
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.get("/restaurants/nearby")
async def nearby_restaurants(
    request: Request,
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    radius: int = Query(5000, ge=100, le=50000, description="반경 (미터)"),
    category: str = Query(None, description="카테고리 필터"),
    sort: str = Query("distance", description="정렬 (distance, rating, price_asc)"),
):
    """주변 식당 조회."""
    from api.mock_responses import MOCK_RESTAURANTS

    results = []
    for r in MOCK_RESTAURANTS:
        dist = _haversine(lat, lng, r["lat"], r["lng"])
        if dist <= radius:
            results.append({**r, "distance": round(dist)})

    if category:
        results = [r for r in results if r["category"] == category]

    if sort == "rating":
        results.sort(key=lambda x: x.get("rating", 0), reverse=True)
    elif sort == "price_asc":
        results.sort(key=lambda x: x.get("avg_price", float("inf")))
    else:
        results.sort(key=lambda x: x["distance"])

    return ApiResponse(data=results)


@router.get("/recipes/compare")
async def compare_recipes(request: Request):
    """레시피 가격 비교 (직접 해먹기 vs 배달 vs 외식)."""
    from api.mock_responses import MOCK_RECIPE_COMPARE
    return ApiResponse(data=MOCK_RECIPE_COMPARE)
