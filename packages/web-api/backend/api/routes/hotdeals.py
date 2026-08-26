"""
핫딜 API — 프론트엔드 '핫딜' 탭의 실제 데이터 소스.

저장소 장애나 빈 결과를 mock 데이터로 덮지 않는다. 저장소가 없으면 503,
데이터가 없으면 빈 목록/404를 그대로 반환한다.
"""

import math
from fastapi import APIRouter, Request, Query, HTTPException
from api.schemas.common import ApiResponse, PaginationMeta

router = APIRouter()


def _require_storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="핫딜 저장소를 사용할 수 없습니다")
    return storage


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
    storage = _require_storage(request)
    data = storage.get_hotdeals(category=category, source=source, sort=sort, page=page, per_page=per_page)
    total = len(data)
    return ApiResponse(
        data=data,
        meta=PaginationMeta(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=math.ceil(total / per_page) if total else 0,
        ),
    )


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


@router.get("/sources")
async def get_hotdeal_sources(request: Request):
    """현재 저장된 핫딜에서 실제 출처 목록을 계산한다."""
    storage = _require_storage(request)
    sources: set[str] = set()
    for deal in storage.get_hotdeals(category="all", per_page=100):
        source = deal.get("source")
        if source:
            sources.add(source)
    return ApiResponse(data=[{"key": source, "label": source} for source in sorted(sources)])


@router.get("/{hotdeal_id}")
async def get_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 상세."""
    storage = _require_storage(request)
    result = storage.get_hotdeal_detail(hotdeal_id)
    if not result:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.post("/{hotdeal_id}/vote")
async def vote_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 투표 (hot/not)."""
    body = await request.json()
    vote_type = body.get("vote_type", "hot")
    if vote_type not in ("hot", "not"):
        raise HTTPException(status_code=422, detail="vote_type은 'hot' 또는 'not'이어야 합니다")

    storage = _require_storage(request)
    result = storage.vote_hotdeal(hotdeal_id, vote_type)
    return ApiResponse(data=result)


@router.post("/{hotdeal_id}/report")
async def report_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 신고 — 실제 저장 성공 뒤에만 성공 응답."""
    body = await request.json()
    reason = body.get("reason", "").strip()
    if not reason:
        raise HTTPException(status_code=422, detail="신고 사유를 입력하세요")

    storage = _require_storage(request)
    storage.report_hotdeal(hotdeal_id, reason)
    return ApiResponse(data={"success": True, "message": "신고가 접수되었습니다"})
