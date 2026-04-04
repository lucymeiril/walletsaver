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

_MAX_RESTAURANT_RESULTS = 200
_DEFAULT_RESTAURANT_LIMIT = 50


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
    limit: int = Query(_DEFAULT_RESTAURANT_LIMIT, ge=1, le=_MAX_RESTAURANT_RESULTS, description="최대 결과 수"),
):
    """주변 식당 조회 — DB에서 실제 데이터 조회."""
    storage = request.app.state.storage
    # DB에서 식당 데이터 조회 시도
    if storage is not None:
        try:
            from sqlalchemy import select
            from storage.models import Restaurant
            with storage.SessionLocal() as session:
                stmt = select(Restaurant).limit(1000)  # DB-level safety cap
                rows = session.execute(stmt).scalars().all()
                results = []
                for r in rows:
                    if r.lat and r.lng:
                        dist = _haversine(lat, lng, r.lat, r.lng)
                        if dist > radius:
                            continue
                    else:
                        dist = 0
                    entry = {
                        "id": r.id,
                        "name": r.name,
                        "category": r.category or "",
                        "address": r.address or "",
                        "lat": r.lat,
                        "lng": r.lng,
                        "avg_price": 0,
                        "rating": r.rating or 0,
                        "review_count": r.review_count or 0,
                        "distance": round(dist),
                    }
                    if category and entry["category"] != category:
                        continue
                    results.append(entry)
                if sort == "rating":
                    results.sort(key=lambda x: x.get("rating", 0), reverse=True)
                elif sort == "price_asc":
                    results.sort(key=lambda x: x.get("avg_price", float("inf")))
                else:
                    results.sort(key=lambda x: x["distance"])

                # 클라이언트 요청 limit 적용
                results = results[:limit]
                return ApiResponse(data=results)
        except Exception:
            pass

    # DB 미연결 또는 조회 실패 시 빈 배열 반환
    return ApiResponse(data=[])


@router.get("/recipes/compare")
async def compare_recipes(request: Request):
    """레시피 가격 비교 — 현재 DB에 레시피 데이터가 없으므로 빈 배열 반환."""
    return ApiResponse(data=[])
