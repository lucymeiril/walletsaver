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
import time
from fastapi import APIRouter, Request, Query, HTTPException
from api.schemas.common import ApiResponse, PaginationMeta
from api.utils.cache import TTLCache

router = APIRouter()

# Listing cache (60s TTL)
_listing_cache = TTLCache(ttl_seconds=60, max_size=32)

# Simple per-IP rate limiter for vote/report (max 10 per minute)
_rate_limit_store: dict[str, list[float]] = {}
_RATE_LIMIT_WINDOW = 60
_RATE_LIMIT_MAX = 10


def _check_rate_limit(client_ip: str) -> bool:
    """Returns True if request is allowed, False if rate-limited."""
    now = time.time()
    hits = _rate_limit_store.get(client_ip, [])
    hits = [t for t in hits if now - t < _RATE_LIMIT_WINDOW]
    if len(hits) >= _RATE_LIMIT_MAX:
        _rate_limit_store[client_ip] = hits
        return False
    hits.append(now)
    _rate_limit_store[client_ip] = hits
    return True


@router.get("")
async def list_hotdeals(
    request: Request,
    category: str = Query("all", description="카테고리 (food, electronics, fashion, living, all)"),
    source: str = Query(None, description="출처 필터"),
    sort: str = Query("recent", description="정렬 (recent, popular, discount, price_asc)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """핫딜 목록 — DB에서 실제 핫딜 데이터 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))

    cache_key = f"hotdeals:{category}:{source}:{sort}:{page}:{per_page}"
    cached = _listing_cache.get(cache_key)
    if cached is not None:
        return cached

    resp = ApiResponse(data=storage.get_hotdeals(category=category, source=source, sort=sort, page=page, per_page=per_page))
    _listing_cache.set(cache_key, resp)
    return resp


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
    """핫딜 출처(커뮤니티) 목록 — DB에서 고유 source 값 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=["전체"])

    # DB에서 핫딜 출처 목록 추출
    try:
        all_deals = storage.get_hotdeals(per_page=200)
        sources = sorted(set(d.get("source", "") for d in all_deals if d.get("source")))
        return ApiResponse(data=["전체"] + sources)
    except Exception:
        return ApiResponse(data=["전체"])


@router.get("/{hotdeal_id}")
async def get_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 상세 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="DB 미연결")

    result = storage.get_hotdeal_detail(hotdeal_id)
    if not result:
        raise HTTPException(status_code=404, detail="핫딜을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.post("/{hotdeal_id}/vote")
async def vote_hotdeal(request: Request, hotdeal_id: int):
    """핫딜 투표 (hot/not)."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"vote:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests")

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
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"report:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests")

    body = await request.json()
    reason = body.get("reason", "")

    storage = request.app.state.storage
    if storage is not None:
        try:
            storage.report_hotdeal(hotdeal_id, reason)
        except Exception:
            pass

    return ApiResponse(data={"success": True, "message": "신고가 접수되었습니다"})


# --------------- 핫딜 댓글 API ---------------

_hotdeal_comments: dict[int, list] = {}
_comment_id_seq = 0


@router.get("/{hotdeal_id}/comments")
async def get_hotdeal_comments(request: Request, hotdeal_id: int):
    """핫딜 댓글 목록."""
    storage = request.app.state.storage
    if storage is not None:
        try:
            result = storage.get_hotdeal_comments(hotdeal_id)
            return ApiResponse(data=result)
        except Exception:
            pass
    return ApiResponse(data=_hotdeal_comments.get(hotdeal_id, []))


@router.post("/{hotdeal_id}/comments")
async def add_hotdeal_comment(request: Request, hotdeal_id: int):
    """핫딜 댓글 작성."""
    global _comment_id_seq
    body = await request.json()
    content = body.get("content", "").strip()
    author = body.get("author", "익명")

    if not content:
        raise HTTPException(status_code=400, detail="댓글 내용을 입력해주세요")

    storage = request.app.state.storage
    if storage is not None:
        try:
            result = storage.add_hotdeal_comment(hotdeal_id, content, author)
            return ApiResponse(data=result)
        except Exception:
            pass

    _comment_id_seq += 1
    comment = {
        "id": _comment_id_seq,
        "author": author,
        "text": content,
        "time": "방금 전",
        "hotdeal_id": hotdeal_id,
    }
    _hotdeal_comments.setdefault(hotdeal_id, []).append(comment)
    return ApiResponse(data=comment)


@router.delete("/{hotdeal_id}/comments/{comment_id}")
async def delete_hotdeal_comment(request: Request, hotdeal_id: int, comment_id: int):
    """핫딜 댓글 삭제."""
    storage = request.app.state.storage
    if storage is not None:
        try:
            storage.delete_hotdeal_comment(comment_id)
            return ApiResponse(data={"success": True})
        except Exception:
            pass

    comments = _hotdeal_comments.get(hotdeal_id, [])
    _hotdeal_comments[hotdeal_id] = [c for c in comments if c["id"] != comment_id]
    return ApiResponse(data={"success": True})
