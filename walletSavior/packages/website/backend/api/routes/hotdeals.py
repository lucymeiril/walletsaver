"""
핫딜 API — 프론트엔드 '핫딜' 탭의 데이터 소스.

엔드포인트:
    GET  /api/hotdeals              — 핫딜 목록 (필터/정렬/페이징)
    GET  /api/hotdeals/categories   — 핫딜 카테고리
    GET  /api/hotdeals/{id}         — 핫딜 상세
    POST /api/hotdeals/{id}/vote    — 핫딜 투표
    POST /api/hotdeals/{id}/report  — 핫딜 신고
"""

import logging
import math
import time
from fastapi import APIRouter, Request, Query, HTTPException
from api.schemas.common import ApiResponse, PaginationMeta
from api.utils.cache import TTLCache
from services.db import managed_session
from storage.models import HotDealComment, HotDealVote, Base
from sqlalchemy import func

logger = logging.getLogger(__name__)

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

    data = storage.get_hotdeals(category=category, source=source, sort=sort, page=page, per_page=per_page)
    total = (page - 1) * per_page + len(data) if len(data) < per_page else page * per_page + 1
    total_pages = math.ceil(total / per_page) if per_page else 0
    resp = ApiResponse(data=data, meta=PaginationMeta(page=page, per_page=per_page, total=total, total_pages=total_pages))
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
    """핫딜 투표 (hot/not) — DB 영속화."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"vote:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests")

    body = await request.json()
    vote_type = body.get("vote_type", "hot")
    if vote_type not in ("hot", "not"):
        raise HTTPException(status_code=400, detail="vote_type must be 'hot' or 'not'")

    storage = request.app.state.storage
    if storage is not None:
        try:
            result = storage.vote_hotdeal(hotdeal_id, vote_type)
            return ApiResponse(data=result)
        except Exception:
            logger.debug("storage.vote_hotdeal failed, falling back to DB")

    try:
        with managed_session() as session:
            vote = HotDealVote(
                hotdeal_id=hotdeal_id,
                vote_type=vote_type,
                client_ip=client_ip,
            )
            session.add(vote)
            session.flush()

            votes_hot = session.query(func.count(HotDealVote.id)).filter(
                HotDealVote.hotdeal_id == hotdeal_id,
                HotDealVote.vote_type == "hot",
            ).scalar() or 0
            votes_not = session.query(func.count(HotDealVote.id)).filter(
                HotDealVote.hotdeal_id == hotdeal_id,
                HotDealVote.vote_type == "not",
            ).scalar() or 0

            return ApiResponse(data={
                "success": True,
                "votes_hot": votes_hot,
                "votes_not": votes_not,
            })
    except Exception:
        logger.exception("hotdeal vote DB error for hotdeal_id=%s", hotdeal_id)
        raise HTTPException(status_code=500, detail="투표 처리 중 오류가 발생했습니다")


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
            logger.warning("report_hotdeal storage error for hotdeal_id=%s", hotdeal_id)

    return ApiResponse(data={"success": True, "message": "신고가 접수되었습니다"})


# --------------- 핫딜 댓글 API ---------------


@router.get("/{hotdeal_id}/comments")
async def get_hotdeal_comments(request: Request, hotdeal_id: int):
    """핫딜 댓글 목록 — DB 기반."""
    storage = request.app.state.storage
    if storage is not None:
        try:
            result = storage.get_hotdeal_comments(hotdeal_id)
            return ApiResponse(data=result)
        except Exception:
            logger.debug("storage.get_hotdeal_comments failed, falling back to DB")

    try:
        with managed_session() as session:
            comments = (
                session.query(HotDealComment)
                .filter(HotDealComment.hotdeal_id == hotdeal_id)
                .order_by(HotDealComment.created_at)
                .all()
            )
            return ApiResponse(data=[
                {
                    "id": c.id,
                    "author": c.author,
                    "text": c.content,
                    "time": c.created_at.isoformat() if c.created_at else "",
                    "hotdeal_id": c.hotdeal_id,
                }
                for c in comments
            ])
    except Exception:
        logger.exception("hotdeal comments DB error for hotdeal_id=%s", hotdeal_id)
        return ApiResponse(data=[])


@router.post("/{hotdeal_id}/comments")
async def add_hotdeal_comment(request: Request, hotdeal_id: int):
    """핫딜 댓글 작성 — DB 영속화."""
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
            logger.debug("storage.add_hotdeal_comment failed, falling back to DB")

    try:
        with managed_session() as session:
            comment = HotDealComment(
                hotdeal_id=hotdeal_id,
                author=author,
                content=content,
            )
            session.add(comment)
            session.flush()
            data = {
                "id": comment.id,
                "author": comment.author,
                "text": comment.content,
                "time": comment.created_at.isoformat() if comment.created_at else "방금 전",
                "hotdeal_id": comment.hotdeal_id,
            }
            return ApiResponse(data=data)
    except Exception:
        logger.exception("hotdeal comment create DB error for hotdeal_id=%s", hotdeal_id)
        raise HTTPException(status_code=500, detail="댓글 작성 중 오류가 발생했습니다")


@router.delete("/{hotdeal_id}/comments/{comment_id}")
async def delete_hotdeal_comment(request: Request, hotdeal_id: int, comment_id: int):
    """핫딜 댓글 삭제 — DB 기반."""
    storage = request.app.state.storage
    if storage is not None:
        try:
            storage.delete_hotdeal_comment(comment_id)
            return ApiResponse(data={"success": True})
        except Exception:
            logger.debug("storage.delete_hotdeal_comment failed, falling back to DB")

    try:
        with managed_session() as session:
            comment = session.get(HotDealComment, comment_id)
            if comment and comment.hotdeal_id == hotdeal_id:
                session.delete(comment)
            return ApiResponse(data={"success": True})
    except Exception:
        logger.exception("hotdeal comment delete DB error for comment_id=%s", comment_id)
        raise HTTPException(status_code=500, detail="댓글 삭제 중 오류가 발생했습니다")
