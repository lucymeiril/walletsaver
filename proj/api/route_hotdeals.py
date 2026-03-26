"""
핫딜 API — 프론트엔드 '핫딜' 탭의 데이터 소스.

엔드포인트:
    GET /api/hotdeals          — 핫딜 목록 (필터/정렬/페이징)
    GET /api/hotdeals/filters  — 카테고리 필터 목록
"""

from fastapi import APIRouter, Request, Query

router = APIRouter()


@router.get("")
async def list_hotdeals(
    request: Request,
    cat: str = Query("all", description="카테고리 필터 (food, electronics, fashion, living, all)"),
    sort: str = Query("time", description="정렬 기준 (time, views, comments)"),
    limit: int = Query(20, ge=1, le=100, description="반환 건수"),
):
    """
    핫딜 목록 — 커뮤니티(뽐뿌, 어미새, 루리웹) 핫딜 게시글.

    프론트엔드 HOTDEALS 배열과 동일 shape 반환.
    cat 필터로 카테고리별 조회, sort로 최신순/조회수/댓글수 정렬.
    """
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_HOTDEALS
        filtered = MOCK_HOTDEALS
        if cat != "all":
            filtered = [h for h in filtered if h["cat"] == cat]
        if sort == "views":
            filtered = sorted(filtered, key=lambda x: x["views"], reverse=True)
        elif sort == "comments":
            filtered = sorted(filtered, key=lambda x: x["comments"], reverse=True)
        return filtered[:limit]

    return storage.get_hotdeals(category=cat, sort=sort, limit=limit)


@router.get("/filters")
async def get_hotdeal_filters():
    """핫딜 카테고리 필터 목록 — UI 필터 탭 렌더링용."""
    from api.mock_responses import MOCK_HOTDEAL_FILTERS
    return MOCK_HOTDEAL_FILTERS
