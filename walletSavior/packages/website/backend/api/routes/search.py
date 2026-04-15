"""
통합 검색 API.

엔드포인트:
    GET /api/search             — 통합 검색
    GET /api/search/autocomplete — 자동완성 (키워드 + 동의어 + 상품)
    GET /api/search/trending     — 인기 검색어
    POST /api/search/track       — 검색 횟수 추적
"""

import logging
import math
from fastapi import APIRouter, Request, Query
from api.schemas.common import ApiResponse, PaginationMeta
from api.utils.cache import TTLCache, RequestDeduplicator
from api.middleware.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

# Autocomplete cache (10 min TTL)
_autocomplete_cache = TTLCache(ttl_seconds=600, max_size=128)
_autocomplete_dedup = RequestDeduplicator()
# Trending cache (2 min TTL)
_trending_cache = TTLCache(ttl_seconds=120, max_size=8)


@router.get("")
@limiter.limit("30/minute")
async def search(
    request: Request,
    q: str = Query("", description="검색어", max_length=200),
    type: str = Query(None, description="결과 유형 (product, hotdeal, post, mart)"),
    sort: str = Query("relevant", description="정렬 (relevant, recent, popular)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """통합 검색 — DB에서 실제 데이터 검색."""
    storage = request.app.state.storage
    results = []
    q_lower = q.lower() if q else ""

    # 상품 검색
    if not type or type == "product":
        if storage:
            products = storage.search_products(q)
            for p in products:
                results.append({
                    "type": "product",
                    "id": p["id"],
                    "title": p["name"],
                    "description": f"{p['unit']} / 현재가 {p['cur']}원",
                    "price": p["cur"],
                    "image": p.get("img"),
                })

    # 핫딜 검색
    if not type or type == "hotdeal":
        if storage:
            hotdeals = storage.get_hotdeals(sort="recent", per_page=50)
            for h in hotdeals:
                if q_lower and q_lower not in h.get("title", "").lower():
                    continue
                results.append({
                    "type": "hotdeal",
                    "id": h["id"],
                    "title": h["title"],
                    "description": f"{h['source']} / {h['time']}",
                    "price": h.get("price"),
                    "image": h.get("thumb"),
                })

    # 게시글 검색 — DB에서 커뮤니티 게시글 조회
    if not type or type == "post":
        if storage:
            try:
                from sqlalchemy import select
                from storage.models import Post as PostModel
                with storage.SessionLocal() as session:
                    stmt = select(PostModel).where(PostModel.is_deleted == False)
                    if q_lower:
                        stmt = stmt.where(PostModel.title.contains(q))
                    posts = session.execute(stmt.limit(20)).scalars().all()
                    for p in posts:
                        results.append({
                            "type": "post",
                            "id": p.id,
                            "title": p.title,
                            "description": (p.content or "")[:100],
                            "price": p.deal_price,
                            "image": None,
                        })
            except Exception:
                logger.exception("search: post query error for q=%r", q)

    # 마트/동네 검색
    if not type or type == "mart":
        if storage:
            try:
                mart_data = storage.get_mart_deals()
                for key, data in mart_data.items():
                    for item in data.get("items", []):
                        title = item.get("name") or item.get("title", "")
                        if q_lower and q_lower not in title.lower():
                            continue
                        results.append({
                            "type": "mart",
                            "id": f"{key}_{item.get('id', '')}",
                            "title": title,
                            "description": f"{data['name']} / {item.get('unit', '')}",
                            "price": item.get("price"),
                            "image": item.get("img"),
                         })
            except Exception:
                logger.exception("search: mart query error for q=%r", q)

    if sort == "popular":
        results.sort(key=lambda x: x.get("price") or 0, reverse=True)

    total = len(results)
    start = (page - 1) * per_page
    paginated = results[start:start + per_page]

    return ApiResponse(
        data=paginated,
        meta=PaginationMeta(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=math.ceil(total / per_page) if total > 0 else 0,
        ),
    )


@router.get("/autocomplete")
@limiter.limit("30/minute")
async def autocomplete(
    request: Request,
    q: str = Query("", description="검색어", max_length=200),
    limit: int = Query(10, ge=1, le=50),
):
    """자동완성 — 키워드·동의어·카테고리·상품 4단계 파이프라인."""
    storage = request.app.state.storage
    if not q or not storage:
        return ApiResponse(data=[])

    cache_key = f"ac:{q}:{limit}"
    cached = _autocomplete_cache.get(cache_key)
    if cached is not None:
        return cached

    async def _fetch():
        return storage.search_autocomplete(q, limit=limit)

    try:
        result = await _autocomplete_dedup.deduplicate(cache_key, _fetch)
    except Exception:
        return ApiResponse(data=[])

    # Return structured dict for frontend (keywords + products sections)
    if isinstance(result, dict):
        resp = ApiResponse(data=result)
    elif isinstance(result, list):
        resp = ApiResponse(data=result)
    else:
        resp = ApiResponse(data=[])
    _autocomplete_cache.set(cache_key, resp)
    return resp


@router.get("/trending")
async def trending(
    request: Request,
    limit: int = Query(8, ge=1, le=50),
):
    """인기 검색어 — search_count 기반."""
    storage = request.app.state.storage
    if not storage:
        return ApiResponse(data=[])
    cached = _trending_cache.get(f"trending:{limit}")
    if cached is not None:
        return cached
    keywords = storage.get_trending_keywords(limit)
    resp = ApiResponse(data=keywords)
    _trending_cache.set(f"trending:{limit}", resp)
    return resp


@router.post("/track")
async def track_search(
    request: Request,
    keyword_id: int = Query(..., description="키워드 ID"),
):
    """검색 횟수 추적."""
    storage = request.app.state.storage
    if storage:
        storage.increment_keyword_count(keyword_id)
    return ApiResponse(data={"ok": True})
