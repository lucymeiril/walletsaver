"""
상품(물가비교) API — 프론트엔드 '물가비교' 탭의 데이터 소스.

엔드포인트:
    GET /api/products/search             — 상품 검색
    GET /api/products/categories         — 카테고리 목록
    GET /api/products/popular            — 인기 상품
    GET /api/products/{id}               — 상품 상세
    GET /api/products/{id}/price-history — 가격 이력
    GET /api/products/{id}/price-compare — 출처별 비교
"""

import math
from fastapi import APIRouter, Request, HTTPException, Query
from api.schemas.common import ApiResponse, PaginationMeta

router = APIRouter()


def _category_icon(name: str) -> str:
    if any(token in name for token in ("과일", "사과", "바나나", "딸기")):
        return "🍎"
    if any(token in name for token in ("채소", "야채", "양파", "배추", "감자")):
        return "🧅"
    if any(token in name for token in ("축산", "정육", "고기", "돼지", "소고기", "계란", "닭")):
        return "🥩"
    if any(token in name for token in ("유제품", "우유", "요거트", "치즈")):
        return "🥛"
    if any(token in name for token in ("수산", "생선", "해산물")):
        return "🐟"
    if any(token in name for token in ("곡", "쌀", "잡곡")):
        return "🍚"
    if any(token in name for token in ("가공", "라면", "두부", "통조림", "김치")):
        return "🧊"
    if any(token in name for token in ("생활", "세제", "휴지")):
        return "🧴"
    return "🧺"


def _fallback_categories() -> list[dict]:
    return [
        {"id": "agricultural", "name": "농산물", "icon": "🥬", "count": 0, "children": []},
        {"id": "livestock", "name": "축산물", "icon": "🥩", "count": 0, "children": []},
        {"id": "seafood", "name": "수산물", "icon": "🐟", "count": 0, "children": []},
        {"id": "processed", "name": "가공식품", "icon": "🥫", "count": 0, "children": []},
        {"id": "living", "name": "생활용품", "icon": "🧴", "count": 0, "children": []},
    ]


def _load_category_tree_from_storage(storage) -> list[dict]:
    session_factory = getattr(storage, "SessionLocal", None)
    if session_factory is None:
        return []
    try:
        from sqlalchemy import func
        from storage.models import Category, Product
    except Exception:
        return []

    with session_factory() as session:
        categories = session.query(Category).all()
        if not categories:
            return []
        product_counts = dict(
            session.query(Product.category_id, func.count(Product.id))
            .filter(Product.is_active == True, Product.category_id.isnot(None))
            .group_by(Product.category_id)
            .all()
        )
        by_id = {
            cat.id: {
                "id": cat.id,
                "name": cat.name,
                "icon": getattr(cat, "icon", None) or _category_icon(cat.name or ""),
                "parent_id": cat.parent_id,
                "count": int(product_counts.get(cat.id, 0) or 0),
                "children": [],
                "examples": [],
            }
            for cat in categories
        }
        for cat in categories:
            if cat.parent_id in by_id and cat.id in by_id:
                by_id[cat.parent_id]["children"].append(by_id[cat.id])

        for node in by_id.values():
            node["children"].sort(key=lambda row: (-row["count"], row["name"]))

        def total_count(node: dict) -> int:
            node["count"] += sum(total_count(child) for child in node["children"])
            return node["count"]

        roots = [node for node in by_id.values() if not node.get("parent_id") or node.get("parent_id") not in by_id]
        for root in roots:
            total_count(root)
        roots.sort(key=lambda row: (-row["count"], row["name"]))
        for node in by_id.values():
            node.pop("parent_id", None)
        return roots


@router.get("/search")
async def search_products(
    request: Request,
    q: str = Query("", description="검색어"),
    category: str = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """상품 검색 — 이름/카테고리에 검색어가 포함된 상품."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        results = MOCK_PRODUCTS
        if q:
            q_lower = q.lower()
            results = [p for p in results if q_lower in p["name"] or q_lower in p["cat"]]
        if category:
            results = [p for p in results if category in p.get("cat", "")]

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

    data = storage.search_products(q, category=category, page=page, per_page=per_page)
    total = len(data)
    if not data:
        from api.mock_responses import MOCK_PRODUCTS
        results = MOCK_PRODUCTS
        if q:
            q_lower = q.lower()
            results = [p for p in results if q_lower in p["name"].lower() or q_lower in p.get("cat", "").lower()]
        if category:
            results = [p for p in results if category in p.get("cat", "")]
        total = len(results)
        data = results[(page - 1) * per_page:page * per_page]
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
async def get_categories(request: Request):
    """상품 카테고리 목록."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=_fallback_categories())

    categories = _load_category_tree_from_storage(storage)
    return ApiResponse(data=categories or _fallback_categories())


@router.get("/popular")
async def get_popular_products(
    request: Request,
    per_page: int = Query(10, ge=1, le=50),
):
    """인기/트렌딩 상품 목록."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        results = sorted(MOCK_PRODUCTS, key=lambda p: p.get("cur", 0), reverse=True)
        return ApiResponse(data=results[:per_page])

    results = storage.search_products("")
    if not results:
        from api.mock_responses import MOCK_PRODUCTS
        return ApiResponse(data=MOCK_PRODUCTS[:per_page])
    if isinstance(results, dict) and "items" in results:
        return ApiResponse(data=results["items"][:per_page])
    if isinstance(results, list):
        return ApiResponse(data=results[:per_page])
    return ApiResponse(data=results)


@router.get("/category/{category_id}/compare")
async def compare_category_products(
    request: Request,
    category_id: str,
    sort: str = Query("price_asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """카테고리별 가격 비교 — 구 웹 프론트 CategoryComparePage 호환 응답."""
    storage = request.app.state.storage
    if storage is not None:
        try:
            raw_products = storage.search_products("", category=category_id, page=page, per_page=per_page)
        except Exception:
            raw_products = []
    else:
        raw_products = []

    if not raw_products:
        from api.mock_responses import MOCK_PRODUCTS
        raw_products = [
            p for p in MOCK_PRODUCTS
            if category_id.lower() in p.get("cat", "").lower()
            or category_id.lower() in p.get("name", "").lower()
            or category_id.replace(".", " ").lower() in p.get("cat", "").lower()
        ] or MOCK_PRODUCTS[:per_page]

    products = []
    subcategory_counts = {}
    for p in raw_products:
        path_parts = [part.strip() for part in str(p.get("cat") or "").split(">") if part.strip()]
        current_parts = [part.strip() for part in category_id.split(">") if part.strip()]
        if len(path_parts) > len(current_parts):
            child_name = path_parts[len(current_parts)]
            child_id = " > ".join(path_parts[:len(current_parts) + 1])
            subcategory_counts.setdefault(child_id, {"id": child_id, "name": child_name, "count": 0})
            subcategory_counts[child_id]["count"] += 1
        current = p.get("cur") or p.get("price") or 0
        original = p.get("original_price") or p.get("avg") or current
        discount_pct = p.get("discount_pct")
        if discount_pct is None and current and original and original > current:
            discount_pct = round((1 - current / original) * 100)
        products.append({
            "id": p.get("id"),
            "name": p.get("name", ""),
            "source": p.get("source") or "",
            "brand": p.get("brand") or "",
            "category_path": p.get("cat") or "",
            "price": {
                "current": current,
                "original": original,
                "discount_pct": discount_pct or 0,
            },
            "normalized": {
                "per_100g": current,
                "unit_price_display": p.get("unit_price_display") or p.get("display_unit") or p.get("unit") or "",
            },
            "attributes": p.get("attributes") or {},
            "image_url": p.get("img") or p.get("image_url") or "",
            "price_rank": p.get("price_tier") or "fair",
        })

    prices = [p["normalized"]["per_100g"] for p in products if p["normalized"]["per_100g"]]
    avg = round(sum(prices) / len(prices)) if prices else 0
    summary = {
        "category_id": category_id,
        "category_path": raw_products[0].get("cat", category_id) if raw_products else category_id,
        "product_count": len(products),
        "avg_price_per_100g": avg,
        "min_price_per_100g": min(prices) if prices else 0,
        "max_price_per_100g": max(prices) if prices else 0,
        "hotdeal_threshold": round(avg * 0.85) if avg else 0,
        "ultra_threshold": round(avg * 0.7) if avg else 0,
    }

    if sort == "price_desc":
        products.sort(key=lambda p: p["price"]["current"] or 0, reverse=True)
    elif sort in ("price_asc", "discount"):
        products.sort(key=lambda p: p["price"]["current"] or 0)

    return ApiResponse(data={
        "summary": summary,
        "subcategories": sorted(subcategory_counts.values(), key=lambda row: (-row["count"], row["name"])),
        "products": products,
        "alternatives": [],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": len(products),
            "total_pages": 1,
        },
    })


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    """단일 상품 상세."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        return ApiResponse(data=product)

    result = storage.get_product_detail(product_id)
    if not result:
        from api.mock_responses import MOCK_PRODUCTS
        result = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
    if not result:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.get("/{product_id}/price-history")
async def get_price_history(
    request: Request,
    product_id: int,
    days: int = Query(30, ge=7, le=365, description="조회 기간 (일)"),
):
    """가격 추이 — 차트 렌더링용."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import mock_price_history, MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        return ApiResponse(data=mock_price_history(product_id, days))

    product = storage.get_product_detail(product_id)
    history = storage.get_price_history(product_id, days) if product else []
    if not history:
        from api.mock_responses import MOCK_PRODUCTS, mock_price_history
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        history = mock_price_history(product_id, days)
    return ApiResponse(data=history)


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    """출처별 가격 비교."""
    storage = request.app.state.storage
    if storage is None:
        from api.mock_responses import MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")

        compare = []
        for source, price in product.get("stores", {}).items():
            orig = product["avg"]
            disc = round((1 - price / orig) * 100, 1) if orig else None
            compare.append({
                "source": source,
                "price": price,
                "original_price": orig,
                "discount_rate": disc,
                "url": None,
            })
        compare.sort(key=lambda x: x["price"])
        return ApiResponse(data=compare)

    product = storage.get_product_detail(product_id)
    compare = storage.get_price_compare(product_id) if product else []
    if not compare:
        from api.mock_responses import MOCK_PRODUCTS
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        if not product:
            raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
        compare = [
            {
                "source": source,
                "price": price,
                "original_price": product.get("avg"),
                "discount_rate": round((1 - price / product["avg"]) * 100, 1) if product.get("avg") else None,
                "url": None,
            }
            for source, price in product.get("stores", {}).items()
        ]
        compare.sort(key=lambda row: row["price"])
    return ApiResponse(data=compare)


@router.get("/{product_id}/trust")
async def get_product_trust(request: Request, product_id: int):
    """가격 신뢰도 요약 — 상세 모달 호환용."""
    storage = request.app.state.storage
    product = None
    history = []
    if storage is not None:
        product = storage.get_product_detail(product_id)
        history = storage.get_price_history(product_id, 30)
    if not product:
        from api.mock_responses import MOCK_PRODUCTS, mock_price_history
        product = next((p for p in MOCK_PRODUCTS if p["id"] == product_id), None)
        history = mock_price_history(product_id, 30) if product else []
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    current = product.get("cur") or product.get("price") or 0
    prices = [row.get("price") for row in history if row.get("price")]
    avg = round(sum(prices) / len(prices)) if prices else product.get("avg") or current
    low = min(prices) if prices else product.get("low") or current
    return ApiResponse(data={
        "score": 75 if current and avg and current <= avg else 50,
        "confidence": "보통",
        "current_price": current,
        "historical_average_price": avg,
        "historical_low_price": low,
        "reference_count": len(prices),
        "standard_unit": product.get("unit_price_display") or product.get("display_unit") or product.get("unit") or "100g",
        "rationale": "최근 가격 이력과 현재 관측가를 비교한 임시 신뢰도입니다.",
    })
