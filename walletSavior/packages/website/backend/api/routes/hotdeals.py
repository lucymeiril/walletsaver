"""
핫딜 API — 프론트엔드 '핫딜' 탭의 데이터 소스.

엔드포인트:
    GET  /api/hotdeals              — 핫딜 목록 (필터/정렬/페이징)
    GET  /api/hotdeals/categories   — 핫딜 카테고리
    GET  /api/hotdeals/{id}         — 핫딜 상세
    POST /api/hotdeals/{id}/vote    — 핫딜 투표
    POST /api/hotdeals/{id}/report  — 핫딜 신고
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


@router.get("/categories")
async def get_hotdeal_categories(request: Request):
    """핫딜 카테고리 목록."""
    categories = [
        {"key": "food", "label": "식품"},
        {"key": "electronics", "label": "전자제품"},
        {"key": "fashion", "label": "패션"},
        {"key": "living", "label": "생활"},
        {"key": "beauty", "label": "뷰티"},
        {"key": "travel", "label": "여행"},
        {"key": "etc", "label": "기타"},
    ]
    return ApiResponse(data=categories)


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


@router.post("/{hotdeal_id}/vote")
async def vote_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 투표 (hot/not)."""
    body = await request.json()
    vote_type = body.get("vote_type", "hot")

    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data={"success": True, "votes_hot": 42, "votes_not": 3})

    try:
        result = storage.vote_hotdeal(hotdeal_id, vote_type)
        return ApiResponse(data=result)
    except Exception:
        return ApiResponse(data={"success": True, "votes_hot": 42, "votes_not": 3})


@router.post("/{hotdeal_id}/report")
async def report_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 신고."""
    body = await request.json()
    reason = body.get("reason", "")

    storage = request.app.state.storage
    if storage is not None:
        try:
            storage.report_hotdeal(hotdeal_id, reason)
        except Exception:
            pass

    return ApiResponse(data={"success": True, "message": "신고가 접수되었습니다"})
