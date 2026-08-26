"""
통합 검색 API — 실제 저장소 결과만 반환한다.

상품/핫딜 저장소가 없거나 결과가 비어 있어도 mock 데이터를 끼워 넣지 않는다.
게시글은 community SQLite에서 직접 검색한다.
"""

import math
from fastapi import APIRouter, HTTPException, Request, Query
from sqlalchemy import or_

from api.schemas.common import ApiResponse, PaginationMeta
from services.board_storage import Post as PostModel, get_board_session_factory

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

    if (not type or type == "product") and storage is not None:
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

    if (not type or type == "hotdeal") and storage is not None:
        hotdeals = storage.get_hotdeals(sort="recent", per_page=50)
        for h in hotdeals:
            if q_lower and q_lower not in h.get("title", "").lower():
                continue
            results.append({
                "type": "hotdeal",
                "id": h["id"],
                "title": h["title"],
                "description": f"{h.get('source', '')} / {h.get('time', '')}",
                "price": h.get("price"),
                "image": h.get("thumb"),
            })

    if not type or type == "post":
        factory = get_board_session_factory()
        with factory() as session:
            query = session.query(PostModel).filter(PostModel.is_deleted.is_(False))
            if q:
                pattern = f"%{q}%"
                query = query.filter(
                    or_(PostModel.title.ilike(pattern), PostModel.content.ilike(pattern))
                )
            posts = query.order_by(PostModel.created_at.desc()).limit(200).all()
            for post in posts:
                results.append({
                    "type": "post",
                    "id": post.id,
                    "title": post.title,
                    "description": post.content[:100],
                    "price": post.deal_price,
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
    """상품 자동완성 — 실제 상품 결과만 반환."""
    if not q:
        return ApiResponse(data={"keywords": [], "products": [], "total_keyword_count": 0, "total_product_count": 0})

    storage = request.app.state.storage
    products = []
    if storage is not None:
        for p in storage.search_products(q)[:limit]:
            products.append({
                "text": p["name"],
                "name": p["name"],
                "type": "product",
                "id": p["id"],
            })

    return ApiResponse(data={
        "keywords": [],
        "products": products[:limit],
        "total_keyword_count": 0,
        "total_product_count": len(products),
    })


@router.get("/trending")
async def trending(limit: int = Query(8, ge=1, le=50)):
    """실제 검색 통계 저장소가 도입되기 전까지 빈 목록을 명시적으로 반환."""
    return ApiResponse(data=[])


@router.post("/track")
async def track_keyword(keyword_id: int | None = Query(None)):
    """검색 추적 저장소가 아직 없으므로 성공한 척하지 않는다."""
    raise HTTPException(status_code=501, detail="검색어 추적 저장소가 아직 구현되지 않았습니다")
