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
from api.utils.cache import TTLCache
from api.utils.public_catalog import PublicCatalogReader

router = APIRouter()

# TTL caches for expensive endpoints
_category_summary_cache = TTLCache(ttl_seconds=120, max_size=32)
_search_cache = TTLCache(ttl_seconds=60, max_size=64)
_trending_cache = TTLCache(ttl_seconds=120, max_size=8)


@router.get("")
@router.get("/")
async def list_products(
    request: Request,
    q: str = Query("", description="검색어", max_length=200),
    category: str = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """상품 목록 — /search와 동일하게 작동."""
    return await search_products(request, q=q, category=category, page=page, per_page=per_page)


@router.get("/stats")
async def product_stats(request: Request):
    """상품 통계 요약."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data={"total": 0, "by_category": [], "by_source": {}})
    try:
        products = storage.search_products("")
        total = len(products) if isinstance(products, list) else 0
        categories = storage.get_categories()
        return ApiResponse(data={
            "total": total,
            "categories_count": len(categories) if isinstance(categories, list) else 0,
            "by_category": categories[:10] if isinstance(categories, list) else [],
        })
    except Exception:
        return ApiResponse(data={"total": 0, "by_category": [], "by_source": {}})


@router.get("/search")
async def search_products(
    request: Request,
    q: str = Query("", description="검색어", max_length=200),
    category: str = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """상품 검색 — DB에서 이름/카테고리에 검색어가 포함된 상품 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))

    cache_key = f"search:{q}:{category}:{page}:{per_page}"
    cached = _search_cache.get(cache_key)
    if cached is not None:
        return cached

    data = storage.search_products(q, category=category, page=page, per_page=per_page)
    total = (page - 1) * per_page + len(data) if len(data) < per_page else page * per_page + 1
    total_pages = math.ceil(total / per_page) if per_page else 0
    resp = ApiResponse(data=data, meta=PaginationMeta(page=page, per_page=per_page, total=total, total_pages=total_pages))
    _search_cache.set(cache_key, resp)
    return resp


@router.get("/categories")
async def get_categories(request: Request):
    """상품 카테고리 목록."""
    DEFAULT_CATEGORIES = [
        {"id": "agricultural", "name": "농산물", "icon": "🥬"},
        {"id": "livestock", "name": "축산물", "icon": "🥩"},
        {"id": "seafood", "name": "수산물", "icon": "🐟"},
        {"id": "processed", "name": "가공식품", "icon": "🥫"},
        {"id": "living", "name": "생활용품", "icon": "🧴"},
        {"id": "electronics", "name": "전자제품", "icon": "📱"},
        {"id": "fashion", "name": "패션", "icon": "👕"},
        {"id": "etc", "name": "기타", "icon": "📦"},
    ]
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=DEFAULT_CATEGORIES)

    try:
        categories = storage.get_categories()
        return ApiResponse(data=categories)
    except Exception:
        return ApiResponse(data=DEFAULT_CATEGORIES)


@router.get("/trending")
async def get_trending_keywords(request: Request):
    """인기 검색어 — DB 상품명 기반 트렌딩 키워드 조회."""
    storage = request.app.state.storage
    default_keywords = ["삼겹살", "계란", "양파", "우유", "라면", "사과", "쌀", "배추"]
    if storage is None:
        return ApiResponse(data=default_keywords)

    cached = _trending_cache.get("trending")
    if cached is not None:
        return cached

    try:
        products = storage.search_products("")
        if products:
            keywords = [p["name"] for p in products[:8]]
            resp = ApiResponse(data=keywords if keywords else default_keywords)
            _trending_cache.set("trending", resp)
            return resp
    except Exception:
        pass
    return ApiResponse(data=default_keywords)


@router.get("/popular")
async def get_popular_products(
    request: Request,
    per_page: int = Query(10, ge=1, le=50),
):
    """인기/트렌딩 상품 목록 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    results = storage.search_products("")
    if isinstance(results, dict) and "items" in results:
        return ApiResponse(data=results["items"][:per_page])
    if isinstance(results, list):
        return ApiResponse(data=results[:per_page])
    return ApiResponse(data=results)


@router.get("/category-summary")
async def get_category_summary(
    request: Request,
    per_page: int = Query(8, ge=1, le=20),
):
    """카테고리별 물가 요약 — 평균, 최저, 최고 가격.

    홈페이지 '오늘의 물가' 섹션에서 사용.
    개별 상품 대신 카테고리 단위 집계를 반환한다.
    """
    CATEGORY_META = {
        "livestock":    {"icon": "🥩", "display": "축산물"},
        "meat":         {"icon": "🥩", "display": "축산물"},
        "agriculture":  {"icon": "🥬", "display": "농산물"},
        "agricultural": {"icon": "🥬", "display": "농산물"},
        "seafood":      {"icon": "🐟", "display": "수산물"},
        "processed":    {"icon": "🥫", "display": "가공식품"},
        "living":       {"icon": "🧴", "display": "생활용품"},
        "electronics":  {"icon": "📱", "display": "전자제품"},
        "fashion":      {"icon": "👕", "display": "패션"},
        "dairy":        {"icon": "🥛", "display": "유제품"},
        "eggs":         {"icon": "🥚", "display": "계란/난류"},
        "grain":        {"icon": "🌾", "display": "곡류"},
        "fruit":        {"icon": "🍎", "display": "과일"},
        "vegetable":    {"icon": "🥬", "display": "채소"},
        "snack":        {"icon": "🍪", "display": "과자/간식"},
        "beverage":     {"icon": "🥤", "display": "음료"},
        "alcohol":      {"icon": "🍺", "display": "주류"},
    }

    # Map Korean category names to top-level IDs
    CATNAME_TO_ID = {
        "축산물": "livestock", "농산물": "agriculture", "수산물": "seafood",
        "가공식품": "processed", "생활용품": "living", "유제품": "dairy",
        "계란/난류": "eggs", "곡류": "grain", "과일": "fruit",
        "채소": "vegetable", "과자/간식": "snack", "음료": "beverage", "주류": "alcohol",
    }

    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=_default_category_summary())

    cache_key = f"cat_summary:{per_page}"
    cached = _category_summary_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        # Fetch more products for better category coverage
        all_products = storage.search_products("", per_page=500)
        items = []
        if isinstance(all_products, dict) and "items" in all_products:
            items = all_products["items"]
        elif isinstance(all_products, list):
            items = all_products
        else:
            return ApiResponse(data=_default_category_summary())

        # 유효한 가격만 필터
        items = [p for p in items if _safe_price(p) > 0]
        if not items:
            return ApiResponse(data=_default_category_summary())

        # 카테고리별 그룹핑 — approved category_id/name만 사용 (상품명 추론 금지)
        from collections import defaultdict
        groups = defaultdict(list)
        for p in items:
            cat_id = p.get("category_id") or ""
            cat_name = p.get("cat") or p.get("category") or ""

            if cat_id:
                # 계층형 카테고리 → 최상위 키 사용
                top_cat = cat_id.split(".")[0]
            elif cat_name and cat_name in CATNAME_TO_ID:
                top_cat = CATNAME_TO_ID[cat_name]
            else:
                top_cat = ""

            if not top_cat or top_cat == "etc" or top_cat not in CATEGORY_META:
                continue
            groups[top_cat].append(p)

        summaries = []
        for cat_id, prods in groups.items():
            if cat_id == "etc":
                continue  # Skip uncategorized in summary
            prices = [_safe_price(p) for p in prods]
            prices = [pr for pr in prices if pr > 0]
            if not prices:
                continue

            avg_price = round(sum(prices) / len(prices))
            min_price = min(prices)
            max_price = max(prices)
            min_product = min(prods, key=lambda p: _safe_price(p) if _safe_price(p) > 0 else float('inf'))
            meta = CATEGORY_META.get(cat_id, {"icon": "📦", "display": cat_id})

            summaries.append({
                "category_id": cat_id,
                "name": meta["display"],
                "icon": meta["icon"],
                "avg_price": avg_price,
                "min_price": round(min_price),
                "max_price": round(max_price),
                "min_source": min_product.get("source") or min_product.get("store") or "",
                "unit": min_product.get("unit") or "",
                "count": len(prods),
            })

        summaries.sort(key=lambda x: x["count"], reverse=True)
        resp = ApiResponse(data=summaries[:per_page])
        _category_summary_cache.set(cache_key, resp)
        return resp

    except Exception:
        return ApiResponse(data=_default_category_summary())


def _infer_category_from_name(name: str) -> str:
    """상품명 키워드로 카테고리 추론 — category_id 미분류 보정용"""
    if not name:
        return "etc"
    # 키워드 → 카테고리 매핑 (우선순위: 구체적 키워드부터)
    _KEYWORD_MAP = {
        "livestock": ["삼겹살", "돼지", "소고기", "한우", "닭고기", "닭", "갈비", "목살", "안심", "등심", "차돌"],
        "fruit": ["사과", "배", "포도", "딸기", "수박", "참외", "복숭아", "감", "귤", "오렌지", "바나나", "망고", "블루베리", "키위"],
        "vegetable": ["양파", "감자", "당근", "배추", "무", "시금치", "고추", "파", "마늘", "브로콜리", "토마토", "오이", "호박", "상추", "깻잎", "콩나물"],
        "dairy": ["우유", "치즈", "요거트", "요구르트", "버터", "크림"],
        "eggs": ["계란", "달걀", "난류", "메추리알"],
        "seafood": ["고등어", "갈치", "오징어", "새우", "연어", "참치", "조기", "꽃게", "전복", "홍합", "굴", "멸치"],
        "grain": ["쌀", "현미", "보리", "찹쌀", "잡곡", "밀가루"],
        "processed": ["라면", "과자", "통조림", "소시지", "햄", "두부", "어묵", "만두", "냉동", "즉석"],
        "living": ["세제", "휴지", "샴푸", "치약", "비누", "세정", "수건"],
    }
    name_lower = name.lower()
    for cat_id, keywords in _KEYWORD_MAP.items():
        for kw in keywords:
            if kw in name_lower:
                return cat_id
    return "etc"


def _safe_price(p):
    """상품 딕셔너리에서 유효한 가격을 추출."""
    for key in ("cur", "price", "sale_price", "current_price"):
        val = p.get(key)
        if val and isinstance(val, (int, float)) and val > 0:
            return val
    return 0


def _default_category_summary():
    """DB 미연결 / 빈 데이터일 때 기본 카테고리 요약."""
    return [
        {"category_id": "livestock", "name": "축산물", "icon": "🥩",
         "avg_price": 0, "min_price": 0, "max_price": 0,
         "min_source": "", "unit": "100g", "count": 0},
        {"category_id": "agricultural", "name": "농산물", "icon": "🥬",
         "avg_price": 0, "min_price": 0, "max_price": 0,
         "min_source": "", "unit": "1kg", "count": 0},
        {"category_id": "seafood", "name": "수산물", "icon": "🐟",
         "avg_price": 0, "min_price": 0, "max_price": 0,
         "min_source": "", "unit": "1kg", "count": 0},
        {"category_id": "processed", "name": "가공식품", "icon": "🥫",
         "avg_price": 0, "min_price": 0, "max_price": 0,
         "min_source": "", "unit": "1개", "count": 0},
    ]


@router.get("/prices")
async def get_product_prices(
    request: Request,
    q: str = Query("", description="상품명 필터", max_length=200),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """상품별 가격 목록 — 가격 비교 페이지용."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))

    try:
        products = storage.search_products(q, page=page, per_page=per_page)
        items = []
        if isinstance(products, dict) and "items" in products:
            items = products["items"]
        elif isinstance(products, list):
            items = products

        price_data = []
        for p in items:
            price = _safe_price(p)
            if price > 0:
                price_data.append({
                    "id": p.get("id"),
                    "name": p.get("name", ""),
                    "price": price,
                    "source": p.get("source") or p.get("store") or "",
                    "category": p.get("category_id") or p.get("category") or "",
                    "unit": p.get("unit") or "",
                })

        total = len(price_data)
        return ApiResponse(
            data=price_data,
            meta=PaginationMeta(
                page=page, per_page=per_page, total=total,
                total_pages=math.ceil(total / per_page) if per_page else 0,
            ),
        )
    except Exception:
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))


@router.get("/by-source/{source_type}")
async def get_products_by_source(
    request: Request,
    source_type: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """소스별 상품 조회 (무신사, 지오다노, emart 등)."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))

    try:
        all_products = storage.search_products("", per_page=500)
        items = []
        if isinstance(all_products, dict) and "items" in all_products:
            items = all_products["items"]
        elif isinstance(all_products, list):
            items = all_products

        source_lower = source_type.lower()
        filtered = [
            p for p in items
            if source_lower in (p.get("source") or "").lower()
            or source_lower in (p.get("store") or "").lower()
            or source_lower in (p.get("source_type") or "").lower()
            or source_lower in (p.get("platform") or "").lower()
        ]

        total = len(filtered)
        start = (page - 1) * per_page
        paged = filtered[start:start + per_page]
        return ApiResponse(
            data=paged,
            meta=PaginationMeta(
                page=page, per_page=per_page, total=total,
                total_pages=math.ceil(total / per_page) if per_page else 0,
            ),
        )
    except Exception:
        return ApiResponse(data=[], meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0))


@router.get("/fashion")
async def get_fashion_products(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """패션 상품 조회 — 무신사, 지오다노 등 패션 데이터 전용."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    try:
        all_products = storage.search_products("", category="패션", per_page=200)
        items = []
        if isinstance(all_products, dict) and "items" in all_products:
            items = all_products["items"]
        elif isinstance(all_products, list):
            items = all_products

        # 패션 관련 소스 필터
        fashion_sources = {"무신사", "지오다노", "musinsa", "giordano"}
        fashion_items = [
            p for p in items
            if any(src in (p.get("source") or "").lower() or src in (p.get("store") or "").lower()
                   for src in fashion_sources)
            or (p.get("category") or "").lower() in ("패션", "fashion")
            or (p.get("category_id") or "").lower().startswith("fashion")
        ]

        # 패션 카테고리 상품이 없으면 핫딜에서 패션 검색
        if not fashion_items:
            try:
                hotdeals = storage.get_hotdeals(category="fashion", per_page=per_page)
                if isinstance(hotdeals, dict) and "items" in hotdeals:
                    fashion_items = hotdeals["items"]
                elif isinstance(hotdeals, list):
                    fashion_items = hotdeals
            except Exception:
                pass

        total = len(fashion_items)
        start = (page - 1) * per_page
        paged = fashion_items[start:start + per_page]
        return ApiResponse(
            data=paged,
            meta=PaginationMeta(
                page=page, per_page=per_page, total=total,
                total_pages=math.ceil(total / per_page) if per_page else 0,
            ),
        )
    except Exception:
        return ApiResponse(data=[])


@router.get("/category/{category_id}/compare")
async def compare_category(
    request: Request,
    category_id: str,
    sort: str = Query("price_asc"),
    storage_filter: str = Query(None, alias="storage"),
    origin: str = Query(None),
    usage: str = Query(None),
    source: str = Query(None),
    normalize: str = Query("per_100g"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """카테고리별 상품 비교 — 정규화 가격 + 필터 + 정렬."""
    storage_db = request.app.state.storage
    if storage_db is None:
        return ApiResponse(data={"summary": {}, "products": [], "total": 0})

    try:
        result = storage_db.get_category_comparison(
            category_id,
            filters={"storage": storage_filter, "origin": origin, "usage": usage, "source": source},
            sort=sort, page=page, per_page=per_page,
        )
        return ApiResponse(data=result)
    except Exception:
        return ApiResponse(data={"summary": {}, "products": [], "total": 0})


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    """단일 상품 상세 — public catalog read boundary로 조회."""
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="DB 미연결")

    result = PublicCatalogReader(storage).get_product(product_id)
    if not result:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.get("/{product_id}/price-history")
async def get_price_history(
    request: Request,
    product_id: int,
    days: int = Query(30, ge=7, le=365, description="조회 기간 (일)"),
):
    """가격 추이 — 차트 렌더링용. DB에서 실제 가격 이력 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    data = PublicCatalogReader(storage).get_price_history(product_id, days)
    if not data:
        raise HTTPException(status_code=404, detail="가격 이력을 찾을 수 없습니다.")
    return ApiResponse(data=data)


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    """출처별 가격 비교 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])

    data = PublicCatalogReader(storage).get_price_compare(product_id)
    if not data:
        raise HTTPException(status_code=404, detail="가격 비교 데이터를 찾을 수 없습니다.")
    return ApiResponse(data=data)


@router.get("/{product_id}/trust")
async def get_price_trust(request: Request, product_id: int):
    """상품 상세 모달용 가격 신뢰도 요약."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=None)

    data = PublicCatalogReader(storage).get_price_trust_summary(product_id)
    if not data:
        raise HTTPException(status_code=404, detail="상품 신뢰도 데이터를 찾을 수 없습니다.")
    return ApiResponse(data=data)
