"""External hotdeal API.

External hotdeals are crawled locally and uploaded as a replaceable snapshot.
User-created hotdeal posts remain part of the separate community board.
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse, PaginationMeta
from services.hotdeal_report_storage import HotdealReportStore

router = APIRouter()


def _require_storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="핫딜 저장소를 사용할 수 없습니다")
    return storage


@router.get("")
async def list_hotdeals(
    request: Request,
    category: str = Query("all"),
    source: str | None = Query(None),
    sort: str = Query("recent"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    data = _require_storage(request).get_hotdeals(
        category=category,
        source=source,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    return ApiResponse(
        data=data,
        meta=PaginationMeta(
            page=page,
            per_page=per_page,
            total=len(data),
            total_pages=math.ceil(len(data) / per_page) if data else 0,
        ),
    )


@router.get("/categories")
async def get_hotdeal_categories():
    return ApiResponse(data=[
        {"key": "food", "label": "식품"},
        {"key": "electronics", "label": "전자제품"},
        {"key": "fashion", "label": "패션"},
        {"key": "living", "label": "생활"},
        {"key": "beauty", "label": "뷰티"},
        {"key": "travel", "label": "여행"},
        {"key": "etc", "label": "기타"},
    ])


@router.get("/sources")
async def get_hotdeal_sources(request: Request):
    storage = _require_storage(request)
    source_store = getattr(storage, "external_hotdeals", None)
    if source_store is not None and hasattr(source_store, "sources"):
        sources = source_store.sources()
    else:
        sources = sorted({
            str(row.get("source"))
            for row in storage.get_hotdeals(category="all", per_page=100)
            if row.get("source")
        })
    return ApiResponse(data=[{"key": source, "label": source} for source in sources])


@router.get("/{hotdeal_id}")
async def get_hotdeal(request: Request, hotdeal_id: int):
    result = _require_storage(request).get_hotdeal_detail(hotdeal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.post("/{hotdeal_id}/vote")
async def vote_hotdeal(
    request: Request,
    hotdeal_id: int,
    user: dict = Depends(require_auth),
):
    body = await request.json()
    vote_type = body.get("vote_type", "hot")
    if vote_type not in ("hot", "not"):
        raise HTTPException(status_code=422, detail="vote_type은 'hot' 또는 'not'이어야 합니다")
    try:
        result = _require_storage(request).vote_hotdeal(
            hotdeal_id,
            vote_type,
            identity_key=f"user:{int(user['id'])}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다") from exc
    return ApiResponse(data=result)


@router.post("/{hotdeal_id}/report")
async def report_hotdeal(
    request: Request,
    hotdeal_id: int,
    user: dict = Depends(require_auth),
):
    body = await request.json()
    reason = str(body.get("reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="신고 사유를 입력하세요")
    if len(reason) > 1000:
        raise HTTPException(status_code=422, detail="신고 사유는 1000자 이내여야 합니다")

    storage = _require_storage(request)
    try:
        result = HotdealReportStore(storage).report(
            hotdeal_id=hotdeal_id,
            user_id=int(user["id"]),
            reason=reason,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="신고 저장소를 사용할 수 없습니다") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    return ApiResponse(data={
        "success": True,
        "message": "신고가 접수되었습니다",
        "report_id": result["id"],
        "status": result["status"],
    })
