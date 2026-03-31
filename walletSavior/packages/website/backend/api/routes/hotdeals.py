"""
핫딜 API — 프론트엔드 '핫딜' 탭의 데이터 소스.

엔드포인트:
    GET /api/hotdeals          — 핫딜 목록 (필터/정렬/페이징)
    GET /api/hotdeals/{id}     — 핫딜 상세
"""

import math
from fastapi import APIRouter, Request, Query, HTTPException
from api.schemas.common import ApiResponse, PaginationMeta

router = APIRouter()


@router.get("")
async def list_hotdeals(
    request: Request,
    category: str = Query("all", description="카테고리 (food, electronics, fashion, living, all)"),
    source: str = Query(None, description="출처 필터"),
    sort: str = Query("recent", description="정렬 (recent, popular, discount, price_asc)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """핫딜 목록."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_HOTDEALS
        filtered = list(MOCK_HOTDEALS)
        if category != "all":
            filtered = [h for h in filtered if h["cat"] == category]
        if source:
            filtered = [h for h in filtered if h["source"] == source]
        if sort == "popular":
            filtered.sort(key=lambda x: x["views"], reverse=True)
        elif sort == "price_asc":
            filtered.sort(key=lambda x: x["price"] if x["price"] is not None else float("inf"))
        elif sort == "discount":
            def disc_key(h):
                if h["price"] and h["origPrice"]:
                    return h["price"] / h["origPrice"]
                return 1.0
            filtered.sort(key=disc_key)

        total = len(filtered)
        start = (page - 1) * per_page
        paginated = filtered[start:start + per_page]

        return ApiResponse(
            data=paginated,
            meta=PaginationMeta(
                page=page,
                per_page=per_page,
                total=total,
                total_pages=math.ceil(total / per_page) if total > 0 else 0,
            ),
        )

    return ApiResponse(data=storage.get_hotdeals(category=category, source=source, sort=sort, page=page, per_page=per_page))


@router.get("/{hotdeal_id}")
async def get_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 상세."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_HOTDEALS
        deal = next((h for h in MOCK_HOTDEALS if h["id"] == hotdeal_id), None)
        if not deal:
            raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
        return ApiResponse(data=deal)

    result = storage.get_hotdeal_detail(hotdeal_id)
    if not result:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    return ApiResponse(data=result)
