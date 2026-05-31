"""
주유소 API — 주변 주유소 가격 조회.

엔드포인트:
    GET /api/gas/nearby — 주변 주유소 (lat, lng, radius, fuel_type, sort)
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


@router.get("/nearby")
async def nearby_gas_stations(
    request: Request,
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    radius: int = Query(5000, ge=100, le=50000, description="반경 (미터)"),
    fuel_type: str = Query("gasoline", description="연료 종류 (gasoline, diesel, lpg)"),
    sort: str = Query("price_asc", description="정렬 (price_asc, distance)"),
):
    """주변 주유소 가격 정보."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[], message="주유소 가격 DB가 연결되지 않았습니다")

    data = storage.get_gas_prices(lat=lat, lng=lng, radius=radius, fuel_type=fuel_type, sort_by=sort)
    return ApiResponse(data=data)
