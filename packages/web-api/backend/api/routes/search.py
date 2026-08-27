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


def _relevance(title: str, query: str) -> int:
    title_fold = str(title or "").casefold().strip()
    query_fold = str(query or "").casefold().strip()
    if not query_fold:
        return 0
    if title_fold == query_fold:
        return 0
    if title_fold.startswith(query_fold):
        return 1
    if query_fold in title_fold:
        return 2
    return 3


def _product_results(storage, query: str, limit: int) -> tuple[list[dict], int]:
    if storage is None or limit <= 0:
        return [], 0

    search_page = getattr(storage, "search_products_page", None)
    if not callable(search_page):
        rows = storage.search_products(query, page=1, per_page=limit)
        total = len(rows)
    else:
        rows = []
        total = 0
        chunk = min(1000, max(1, limit))
        source_page = 1
        while len(rows) < limit:
            batch, total = search_page(
                query,
                page=source_page,
                per_page=chunk,
            )
            rows.extend(batch)
            if not batch or len(rows) >= total:
                break
            source_page += 1
        rows = rows[:limit]

    results = []
    for product in rows:
        unit = str(product.get("unit") or "").strip()
        current = product.get("cur") or product.get("price") or 0
        description = f"현재가 {current}원"
        if unit:
            description = f"{unit} / {description}"
        results.append({
            "type": "product",
            "id": product["id"],
            "title": product["name"],
            "description": description,
            "price": current,
            "image": product.get("img"),
            "_relevance": _relevance(product.get("name", ""), query),
            "_recent": str(product.get("observed_at") or ""),
            "_popularity": 0,
        })
    return results, int(total)


def _hotdeal_results(storage, query: str, limit: int) -> tuple[list[dict], int]:
    if storage is None or limit <= 0:
        return [], 0
    source_store = getattr(storage, "external_hotdeals", None)
    if source_store is None or not hasattr(source_store, "count_hotdeals"):
        return [], 0

    total = int(source_store.count_hotdeals(query=query))
    rows = []
    chunk = min(100, max(1, limit))
    source_page = 1
    while len(rows) < limit:
        batch = source_store.list_hotdeals(
            query=query,
            sort="recent",
            page=source_page,
            per_page=chunk,
        )
        rows.extend(batch)
        if not batch or len(rows) >= total:
            break
        source_page += 1
    rows = rows[:limit]

    interaction_store = getattr(storage, "interactions", None)
    results = []
    for hotdeal in rows:
        hot = not_ = 0
        if interaction_store is not None and hasattr(interaction_store, "vote_counts"):
            hot, not_ = interaction_store.vote_counts(int(hotdeal["id"]))
        results.append({
            "type": "hotdeal",
            "id": hotdeal["id"],
            "title": hotdeal["title"],
            "description": f"{hotdeal.get('source', '')} / {hotdeal.get('time', '')}".strip(" /"),
            "price": hotdeal.get("price"),
            "image": hotdeal.get("thumb"),
            "_relevance": _relevance(hotdeal.get("title", ""), query),
            "_recent": str(hotdeal.get("posted_at") or hotdeal.get("fetched_at") or ""),
            "_popularity": int(hot) - int(not_),
        })
    return results, total


def _post_results(query_text: str, limit: int) -> tuple[list[dict], int]:
    if limit <= 0:
        return [], 0
    factory = get_board_session_factory()
    with factory() as session:
        query = session.query(PostModel).filter(PostModel.is_deleted.is_(False))
        if query_text:
            pattern = f"%{query_text}%"
            query = query.filter(
                or_(PostModel.title.ilike(pattern), PostModel.content.ilike(pattern))
            )
        total = int(query.count())
        posts = query.order_by(PostModel.created_at.desc()).limit(limit).all()
        results = [{
            "type": "post",
            "id": post.id,
            "title": post.title,
            "description": post.content[:100],
            "price": post.deal_price,
            "image": None,
            "_relevance": _relevance(post.title, query_text),
            "_recent": post.created_at.isoformat() if post.created_at else "",
            "_popularity": int(post.view_count or 0),
        } for post in posts]
    return results, total


def _public_result(item: dict) -> dict:
    return {key: value for key, value in item.items() if not key.startswith("_")}


@router.get("")
async def search(
    request: Request,
    q: str = Query("", description="검색어"),
    type: str = Query(None, description="결과 유형 (product, hotdeal, post)"),
    sort: str = Query("relevant", description="정렬 (relevant, recent, popular)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """통합 검색."""
    storage = request.app.state.storage
    if type not in {None, "product", "hotdeal", "post"}:
        raise HTTPException(status_code=422, detail="지원하지 않는 검색 결과 유형입니다")
    if sort not in {"relevant", "recent", "popular"}:
        raise HTTPException(status_code=422, detail="지원하지 않는 검색 정렬입니다")

    # Each source contributes enough rows to cover the requested global page.
    # This avoids the previous fixed product=20/hotdeal=50/post=200 visibility caps.
    fetch_limit = page * per_page
    results: list[dict] = []
    total = 0

    if type in {None, "product"}:
        product_rows, product_total = _product_results(storage, q, fetch_limit)
        results.extend(product_rows)
        total += product_total

    if type in {None, "hotdeal"}:
        hotdeal_rows, hotdeal_total = _hotdeal_results(storage, q, fetch_limit)
        results.extend(hotdeal_rows)
        total += hotdeal_total

    if type in {None, "post"}:
        post_rows, post_total = _post_results(q, fetch_limit)
        results.extend(post_rows)
        total += post_total

    if sort == "popular":
        results.sort(
            key=lambda item: (item.get("_popularity", 0), item.get("_recent", "")),
            reverse=True,
        )
    elif sort == "recent":
        results.sort(key=lambda item: item.get("_recent", ""), reverse=True)
    else:
        results.sort(
            key=lambda item: (
                item.get("_relevance", 3),
                -int(item.get("_popularity", 0)),
                str(item.get("title") or "").casefold(),
            )
        )

    start = (page - 1) * per_page
    paginated = [_public_result(item) for item in results[start:start + per_page]]

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
    total = 0
    if storage is not None:
        search_page = getattr(storage, "search_products_page", None)
        if callable(search_page):
            rows, total = search_page(q, page=1, per_page=limit)
        else:
            rows = storage.search_products(q, page=1, per_page=limit)
            total = len(rows)
        for product in rows:
            products.append({
                "text": product["name"],
                "name": product["name"],
                "type": "product",
                "id": product["id"],
            })

    return ApiResponse(data={
        "keywords": [],
        "products": products[:limit],
        "total_keyword_count": 0,
        "total_product_count": int(total),
    })


@router.get("/trending")
async def trending(limit: int = Query(8, ge=1, le=50)):
    """실제 검색 통계 저장소가 도입되기 전까지 빈 목록을 명시적으로 반환."""
    return ApiResponse(data=[])


@router.post("/track")
async def track_keyword(keyword_id: int | None = Query(None)):
    """검색 추적 저장소가 아직 없으므로 성공한 척하지 않는다."""
    raise HTTPException(status_code=501, detail="검색어 추적 저장소가 아직 구현되지 않았습니다")
