"""External hotdeal API.

External hotdeals are crawled locally and uploaded as a replaceable snapshot.
User-created hotdeal posts remain part of the separate community board.
"""
from __future__ import annotations

import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.middleware.auth import get_current_user, require_auth
from api.schemas.common import ApiResponse, PaginationMeta
from services.hotdeal_report_storage import HotdealReportStore

router = APIRouter()


def _require_storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="핫딜 저장소를 사용할 수 없습니다")
    return storage


def _interaction_store(storage):
    interaction_store = getattr(storage, "interactions", None)
    if interaction_store is None:
        raise HTTPException(status_code=503, detail="핫딜 상호작용 저장소를 사용할 수 없습니다")
    return interaction_store


def _comment_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%m.%d %H:%M")
    except ValueError:
        return str(value)


def _comment_payload(row: dict, current_user_id: int | None = None) -> dict:
    own = current_user_id is not None and int(row["user_id"]) == int(current_user_id)
    return {
        "id": int(row["id"]),
        "hotdeal_id": int(row["hotdeal_id"]),
        "author": "나" if own else row.get("author") or "사용자",
        "text": row.get("content") or "",
        "time": _comment_time(row.get("created_at")),
        "created_at": row.get("created_at") or "",
        "is_mine": own,
    }


@router.get("")
async def list_hotdeals(
    request: Request,
    category: str = Query("all"),
    source: str | None = Query(None),
    sort: str = Query("recent"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    storage = _require_storage(request)
    data = storage.get_hotdeals(
        category=category,
        source=source,
        sort=sort,
        page=page,
        per_page=per_page,
    )
    interaction_store = _interaction_store(storage)
    for item in data:
        item["comments"] = interaction_store.comment_count(int(item["id"]))

    source_store = getattr(storage, "external_hotdeals", None)
    if source_store is not None and hasattr(source_store, "count_hotdeals"):
        total = source_store.count_hotdeals(category=category, source=source)
    else:
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
    return ApiResponse(data=["전체", *sources])


@router.get("/{hotdeal_id}")
async def get_hotdeal(request: Request, hotdeal_id: int):
    storage = _require_storage(request)
    result = storage.get_hotdeal_detail(hotdeal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    result["comments"] = _interaction_store(storage).comment_count(hotdeal_id)
    return ApiResponse(data=result)


@router.get("/{hotdeal_id}/comments")
async def list_hotdeal_comments(
    request: Request,
    hotdeal_id: int,
    user: dict | None = Depends(get_current_user),
):
    storage = _require_storage(request)
    if storage.get_hotdeal_detail(hotdeal_id) is None:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    rows = _interaction_store(storage).list_comments(hotdeal_id)
    user_id = int(user["id"]) if user else None
    return ApiResponse(data=[_comment_payload(row, user_id) for row in rows])


@router.post("/{hotdeal_id}/comments")
async def add_hotdeal_comment(
    request: Request,
    hotdeal_id: int,
    user: dict = Depends(require_auth),
):
    body = await request.json()
    content = str(body.get("content", "")).strip()
    if not content:
        raise HTTPException(status_code=422, detail="댓글 내용을 입력하세요")
    if len(content) > 1000:
        raise HTTPException(status_code=422, detail="댓글은 1000자 이내여야 합니다")

    storage = _require_storage(request)
    if storage.get_hotdeal_detail(hotdeal_id) is None:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    row = _interaction_store(storage).add_comment(
        hotdeal_id,
        int(user["id"]),
        str(user.get("nickname") or user.get("email") or "사용자"),
        content,
    )
    return ApiResponse(data=_comment_payload(row, int(user["id"])))


@router.delete("/{hotdeal_id}/comments/{comment_id}")
async def delete_hotdeal_comment(
    request: Request,
    hotdeal_id: int,
    comment_id: int,
    user: dict = Depends(require_auth),
):
    storage = _require_storage(request)
    if storage.get_hotdeal_detail(hotdeal_id) is None:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    result = _interaction_store(storage).delete_comment(
        hotdeal_id,
        comment_id,
        int(user["id"]),
    )
    if result == "not_found":
        raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="본인 댓글만 삭제할 수 있습니다")
    return ApiResponse(data={"deleted": True, "id": comment_id})


@router.post("/{hotdeal_id}/vote")
async def vote_hotdeal(
    request: Request,
    hotdeal_id: int,
    user: dict = Depends(require_auth),
):
    body = await request.json()
    vote_type = body.get("vote_type", "hot")
    if vote_type not in ("hot", "not", "cancel"):
        raise HTTPException(status_code=422, detail="vote_type은 'hot', 'not', 'cancel' 중 하나여야 합니다")

    storage = _require_storage(request)
    identity_key = f"user:{int(user['id'])}"
    try:
        if vote_type == "cancel":
            if storage.get_hotdeal_detail(hotdeal_id) is None:
                raise ValueError("hotdeal not found")
            interaction_store = _interaction_store(storage)
            if not hasattr(interaction_store, "clear_vote"):
                raise HTTPException(status_code=503, detail="투표 저장소를 사용할 수 없습니다")
            result = interaction_store.clear_vote(hotdeal_id, identity_key)
        else:
            result = storage.vote_hotdeal(
                hotdeal_id,
                vote_type,
                identity_key=identity_key,
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
