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
_PUBLIC_PRICE_EXCLUDED_ROOTS = {"living", "pet"}


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


def _load_category_tree_from_storage(storage) -> list[dict]:
    session_factory = getattr(storage, "SessionLocal", None)
    if session_factory is None:
        return []
    try:
        from sqlalchemy import func
        from storage.models import Category, Product, UnifiedCategory
    except Exception:
        return []

    with session_factory() as session:
        unified_categories = session.query(UnifiedCategory).all()
        if unified_categories:
            product_counts = dict(
                session.query(Product.unified_category_id, func.count(Product.id))
                .filter(Product.is_active == True, Product.unified_category_id.isnot(None))
                .group_by(Product.unified_category_id)
                .all()
            )
            by_id = {
                cat.id: {
                    "id": cat.id,
                    "name": cat.name_ko,
                    "icon": _category_icon(cat.name_ko or ""),
                    "parent_id": cat.parent_id,
                    "count": int(product_counts.get(cat.id, 0) or 0),
                    "children": [],
                    "examples": [],
                }
                for cat in unified_categories
            }
            for cat in unified_categories:
                if cat.parent_id in by_id and cat.id in by_id:
                    by_id[cat.parent_id]["children"].append(by_id[cat.id])

            for node in by_id.values():
                node["children"].sort(key=lambda row: (-row["count"], row["name"]))

            def total_count(node: dict) -> int:
                node["count"] += sum(total_count(child) for child in node["children"])
                return node["count"]

            roots = [
                node
                for node in by_id.values()
                if (not node.get("parent_id") or node.get("parent_id") not in by_id)
                and node.get("id") not in _PUBLIC_PRICE_EXCLUDED_ROOTS
            ]
            for root in roots:
                total_count(root)
            roots.sort(key=lambda row: (-row["count"], row["name"]))
            for node in by_id.values():
                node.pop("parent_id", None)
            return roots

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


def _load_products_for_unified_category(storage, category_id: str, page: int, per_page: int) -> tuple[list[dict], int]:
    session_factory = getattr(storage, "SessionLocal", None)
    if session_factory is None:
        return [], 0
    try:
        from sqlalchemy import desc, select
        from storage.models import DiscountHistory, Product, UnifiedCategory
    except Exception:
        return [], 0

    with session_factory() as session:
        categories = session.query(UnifiedCategory).all()
        by_parent: dict[str | None, list[str]] = {}
        for cat in categories:
            by_parent.setdefault(cat.parent_id, []).append(cat.id)
        selected_ids: set[str] = set()

        def collect(cat_id: str) -> None:
            if cat_id in selected_ids:
                return
            selected_ids.add(cat_id)
            for child_id in by_parent.get(cat_id, []):
                collect(child_id)

        collect(category_id)
        if not selected_ids:
            return [], 0

        base = (
            select(Product)
            .where(Product.is_active == True, Product.unified_category_id.in_(selected_ids))
            .order_by(Product.name)
        )
        total = session.execute(
            select(Product.id).where(Product.is_active == True, Product.unified_category_id.in_(selected_ids))
        ).all()
        products = session.execute(base.offset((page - 1) * per_page).limit(per_page)).scalars().all()
        rows = []
        for product in products:
            latest_discount = session.execute(
                select(DiscountHistory)
                .where(DiscountHistory.product_id == product.id)
                .order_by(desc(DiscountHistory.crawled_at))
                .limit(1)
            ).scalar_one_or_none()
            current = round(latest_discount.price) if latest_discount and latest_discount.price else 0
            original = latest_discount.original_price if latest_discount else None
            discount_pct = round((1 - current / original) * 100) if current and original and original > current else 0
            attrs = product.attributes if isinstance(product.attributes, dict) else {}
            category_name = product.unified_category.name_ko if product.unified_category else category_id
            rows.append({
                "id": product.id,
                "name": product.name,
                "source": latest_discount.source if latest_discount else product.source_type or "",
                "brand": attrs.get("brand", ""),
                "cat": category_name,
                "price": current,
                "cur": current,
                "original_price": original or current,
                "discount_pct": discount_pct,
                "unit_price_display": (
                    attrs.get("unit_price_display")
                    or attrs.get("unit_price_text")
                    or product.unit
                    or ""
                ),
                "unit": product.unit or "",
                "attributes": attrs,
                "image_url": product.image_url or "",
                "img": product.image_url or "",
                "price_tier": "fair",
            })
        return rows, len(total)


def _load_unified_category_children(storage, category_id: str) -> tuple[list[dict], int, str]:
    session_factory = getattr(storage, "SessionLocal", None)
    if session_factory is None:
        return [], 0, category_id
    try:
        from sqlalchemy import func
        from storage.models import Product, UnifiedCategory
    except Exception:
        return [], 0, category_id

    with session_factory() as session:
        categories = session.query(UnifiedCategory).all()
        by_id = {cat.id: cat for cat in categories}
        by_parent: dict[str | None, list[str]] = {}
        for cat in categories:
            by_parent.setdefault(cat.parent_id, []).append(cat.id)

        def collect(cat_id: str) -> set[str]:
            ids = {cat_id}
            for child_id in by_parent.get(cat_id, []):
                ids.update(collect(child_id))
            return ids

        def count_subtree(cat_id: str) -> int:
            ids = collect(cat_id)
            return int(
                session.query(func.count(Product.id))
                .filter(Product.is_active == True, Product.unified_category_id.in_(ids))
                .scalar()
                or 0
            )

        children = []
        for child_id in by_parent.get(category_id, []):
            child = by_id.get(child_id)
            if not child:
                continue
            children.append({
                "id": child.id,
                "name": child.name_ko,
                "count": count_subtree(child.id),
            })
        children.sort(key=lambda row: (-row["count"], row["name"]))

        current = by_id.get(category_id)
        path_names = []
        cursor = current
        while cursor is not None:
            path_names.append(cursor.name_ko)
            cursor = by_id.get(cursor.parent_id) if cursor.parent_id else None
        category_path = " > ".join(reversed(path_names)) if path_names else category_id
        return children, count_subtree(category_id), category_path


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
        return ApiResponse(
            data=[],
            meta=PaginationMeta(
                page=page,
                per_page=per_page,
                total=0,
                total_pages=0,
            ),
        )

    data = storage.search_products(q, category=category, page=page, per_page=per_page)
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
async def get_categories(request: Request):
    """상품 카테고리 목록."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    categories = _load_category_tree_from_storage(storage)
    return ApiResponse(data=categories)


@router.get("/popular")
async def get_popular_products(
    request: Request,
    per_page: int = Query(10, ge=1, le=50),
):
    """인기/트렌딩 상품 목록."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    results = storage.search_products("")
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
    total_rows = 0
    drilldown_subcategories = []
    category_total_count = 0
    category_path = category_id
    if storage is not None:
        try:
            drilldown_subcategories, category_total_count, category_path = _load_unified_category_children(storage, category_id)
            if drilldown_subcategories:
                raw_products = []
                total_rows = 0
            else:
                raw_products, total_rows = _load_products_for_unified_category(storage, category_id, page, per_page)
            if not raw_products and not drilldown_subcategories:
                raw_products = storage.search_products("", category=category_id, page=page, per_page=per_page)
                total_rows = len(raw_products)
        except Exception:
            raw_products = []
    else:
        raw_products = []

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
        "category_path": raw_products[0].get("cat", category_path) if raw_products else category_path,
        "product_count": category_total_count if drilldown_subcategories else len(products),
        "is_leaf": not bool(drilldown_subcategories),
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
        "subcategories": drilldown_subcategories or sorted(subcategory_counts.values(), key=lambda row: (-row["count"], row["name"])),
        "products": products,
        "alternatives": [],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total_rows or len(products),
            "total_pages": math.ceil((total_rows or len(products)) / per_page) if (total_rows or len(products)) else 0,
        },
    })


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    """단일 상품 상세."""
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="상품 DB 연결이 없습니다")

    result = storage.get_product_detail(product_id)
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
        raise HTTPException(status_code=503, detail="상품 DB 연결이 없습니다")

    product = storage.get_product_detail(product_id)
    history = storage.get_price_history(product_id, days) if product else []
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=history)


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    """출처별 가격 비교."""
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="상품 DB 연결이 없습니다")

    product = storage.get_product_detail(product_id)
    compare = storage.get_price_compare(product_id) if product else []
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
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
        detail = "상품 DB 연결이 없습니다" if storage is None else "상품을 찾을 수 없습니다"
        raise HTTPException(status_code=503 if storage is None else 404, detail=detail)
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
