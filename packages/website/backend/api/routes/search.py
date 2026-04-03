"""
통합 검색 API.

엔드포인트:
    GET /api/search             — 통합 검색
    GET /api/search/autocomplete — 자동완성
"""

import math
from fastapi import APIRouter, Request, Query
from api.schemas.common import ApiResponse, PaginationMeta

router = APIRouter()


@router.get("")
async def search(
    request: Request,
    q: str = Query("", description="검색어"),
    type: str = Query(None, description="결과 유형 (product, hotdeal, post, mart)"),
    sort: str = Query("relevant", description="정렬 (relevant, recent, popular)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """통합 검색."""
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
        else:
            from api.mock_responses import MOCK_PRODUCTS
            for p in MOCK_PRODUCTS:
                if q_lower and q_lower not in p["name"].lower() and q_lower not in p.get("cat", "").lower():
                    continue
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
        else:
            from api.mock_responses import MOCK_HOTDEALS
            for h in MOCK_HOTDEALS:
                if q_lower and q_lower not in h["title"].lower():
                    continue
                results.append({
                    "type": "hotdeal",
                    "id": h["id"],
                    "title": h["title"],
                    "description": f"{h['source']} / {h['time']}",
                    "price": h.get("price"),
                    "image": h.get("thumb"),
                })

    # 게시글 검색
    if not type or type == "post":
        from api.mock_responses import MOCK_POSTS
        for p in MOCK_POSTS:
            if q_lower and q_lower not in p["title"].lower() and q_lower not in p.get("content", "").lower():
                continue
            results.append({
                "type": "post",
                "id": p["id"],
                "title": p["title"],
                "description": p["content"][:100],
                "price": p.get("price"),
                "image": None,
            })

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
async def autocomplete(
    request: Request,
    q: str = Query("", description="검색어"),
    limit: int = Query(10, ge=1, le=50),
):
    """자동완성."""
    if not q:
        return ApiResponse(data=[])

    storage = request.app.state.storage
    q_lower = q.lower()
    suggestions = []

    if storage:
        products = storage.search_products(q)
        for p in products[:limit]:
            suggestions.append({
                "text": p["name"],
                "type": "product",
                "id": p["id"],
            })
    else:
        from api.mock_responses import MOCK_PRODUCTS
        for p in MOCK_PRODUCTS:
            if q_lower in p["name"].lower():
                suggestions.append({
                    "text": p["name"],
                    "type": "product",
                    "id": p["id"],
                })
            if len(suggestions) >= limit:
                break

    return ApiResponse(data=suggestions)
