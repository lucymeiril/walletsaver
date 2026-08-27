"""Public catalog API backed by the replaceable catalog SQLite snapshot."""
from __future__ import annotations

import math
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas.common import ApiResponse, PaginationMeta
from services.catalog_storage import CatalogUnavailable

router = APIRouter()


_PRICE_SORTS = {"price_asc", "price_desc", "discount", "recent"}


def _storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="상품 DB 연결이 없습니다")
    return storage


def _catalog_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CatalogUnavailable):
        return HTTPException(status_code=503, detail="상품 snapshot을 사용할 수 없습니다")
    return HTTPException(status_code=503, detail="상품 데이터를 불러올 수 없습니다")


def _positive_float(value) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _comparison_metadata(storage, product_ids: list[int]) -> dict[int, dict]:
    """Read only the package/timestamp fields needed for honest unit comparison."""
    catalog = getattr(storage, "catalog", None)
    if catalog is None or not hasattr(catalog, "connection") or not product_ids:
        return {}

    marks = ",".join("?" for _ in product_ids)
    with catalog.connection() as connection:
        rows = connection.execute(
            f"""
            SELECT
                p.id,
                p.pack_qty,
                p.pack_unit,
                p.unit_kind,
                p.unit_price_displayed,
                p.unit_price_basis_raw,
                COALESCE(
                    (SELECT d.crawled_at
                     FROM discount_history d
                     WHERE d.product_id=p.id
                     ORDER BY d.crawled_at DESC, d.id DESC LIMIT 1),
                    (SELECT b.recorded_at
                     FROM baseline_prices b
                     WHERE b.product_id=p.id
                     ORDER BY b.recorded_at DESC, b.id DESC LIMIT 1),
                    ''
                ) AS observed_at
            FROM products p
            WHERE p.id IN ({marks})
            """,
            tuple(product_ids),
        ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def _normalized_unit_price(current: float, metadata: dict) -> tuple[int | None, str | None]:
    """Return current price per 100g/100ml only when the package basis is known."""
    if current <= 0:
        return None, None

    displayed = _positive_float(metadata.get("unit_price_displayed"))
    basis_raw = str(metadata.get("unit_price_basis_raw") or "").lower().replace(" ", "")
    if displayed is not None:
        if "100g" in basis_raw:
            return round(displayed), "100g"
        if "100ml" in basis_raw:
            return round(displayed), "100ml"

    qty = _positive_float(metadata.get("pack_qty"))
    unit = str(metadata.get("pack_unit") or "").strip().lower()
    kind = str(metadata.get("unit_kind") or "").strip().lower()
    if qty is None or not unit:
        return None, None

    if kind == "weight" or unit in {"g", "kg", "mg", "t", "ton"}:
        factors = {"g": 1.0, "kg": 1000.0, "mg": 0.001, "t": 1_000_000.0, "ton": 1_000_000.0}
        factor = factors.get(unit)
        if factor is None:
            return None, None
        total_g = qty * factor
        return (round(current / total_g * 100), "100g") if total_g > 0 else (None, None)

    if kind == "volume" or unit in {"ml", "l", "cc", "dl"}:
        factors = {"ml": 1.0, "l": 1000.0, "cc": 1.0, "dl": 100.0}
        factor = factors.get(unit)
        if factor is None:
            return None, None
        total_ml = qty * factor
        return (round(current / total_ml * 100), "100ml") if total_ml > 0 else (None, None)

    # count/pack products are intentionally not disguised as weight prices.
    return None, None


def _comparison_value(product: dict, common_basis: str | None) -> float:
    normalized = product.get("normalized") or {}
    if (
        common_basis
        and normalized.get("basis") == common_basis
        and normalized.get("unit_price") is not None
    ):
        return float(normalized["unit_price"])
    return float((product.get("price") or {}).get("current") or 0)


@router.get("/search")
async def search_products(
    request: Request,
    q: str = Query("", description="검색어"),
    category: str | None = Query(None, description="카테고리 필터"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    storage = _storage(request)
    try:
        search_page = getattr(storage, "search_products_page", None)
        if callable(search_page):
            data, total = search_page(
                q, category=category, page=page, per_page=per_page
            )
        else:
            data = storage.search_products(
                q, category=category, page=page, per_page=per_page
            )
            total = len(data)
    except Exception as exc:
        raise _catalog_error(exc) from exc
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
    try:
        return ApiResponse(data=_storage(request).get_category_tree())
    except Exception as exc:
        raise _catalog_error(exc) from exc


@router.get("/popular")
async def get_popular_products(
    request: Request,
    per_page: int = Query(10, ge=1, le=50),
):
    try:
        data = _storage(request).search_products("", page=1, per_page=per_page)
    except Exception as exc:
        raise _catalog_error(exc) from exc
    return ApiResponse(data=data[:per_page])


@router.get("/category/{category_id}/compare")
async def compare_category_products(
    request: Request,
    category_id: str,
    sort: Literal["price_asc", "price_desc", "discount", "recent"] = Query("price_asc"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    storage = _storage(request)
    try:
        children, category_total_count, category_path = storage.get_category_children(category_id)
        if children:
            raw_products = []
            total_rows = 0
        else:
            # Sorting must happen before pagination. The existing catalog method
            # pages by name, so load this leaf category once, compute honest
            # comparison values, then sort/page below.
            fetch_count = max(1, int(category_total_count or per_page))
            raw_products, total_rows = storage.get_category_products(
                category_id, page=1, per_page=fetch_count
            )
            if total_rows > len(raw_products):
                raw_products, total_rows = storage.get_category_products(
                    category_id, page=1, per_page=total_rows
                )
            if not raw_products:
                search_page = getattr(storage, "search_products_page", None)
                if callable(search_page):
                    raw_products, total_rows = search_page(
                        "", category=category_id, page=1, per_page=min(fetch_count, 1000)
                    )
                else:
                    raw_products = storage.search_products(
                        "", category=category_id, page=1, per_page=min(fetch_count, 1000)
                    )
                    total_rows = len(raw_products)
    except Exception as exc:
        raise _catalog_error(exc) from exc

    metadata = _comparison_metadata(
        storage,
        [int(row["id"]) for row in raw_products if row.get("id") is not None],
    )

    products = []
    for row in raw_products:
        current = row.get("cur") or row.get("price") or 0
        original = row.get("original_price") or row.get("avg") or current
        discount_pct = row.get("discount_pct")
        if discount_pct is None and current and original and original > current:
            discount_pct = round((1 - current / original) * 100)

        meta = metadata.get(int(row.get("id") or 0), {})
        unit_price, basis = _normalized_unit_price(float(current or 0), meta)
        products.append({
            "id": row.get("id"),
            "name": row.get("name", ""),
            "source": row.get("source") or "",
            "brand": row.get("brand") or "",
            "category_path": row.get("cat") or "",
            "price": {
                "current": current,
                "original": original,
                "discount_pct": discount_pct or 0,
            },
            "normalized": {
                "unit_price": unit_price,
                "basis": basis,
                "per_100g": unit_price if basis == "100g" else None,
                "per_100ml": unit_price if basis == "100ml" else None,
                "unit_price_display": (
                    row.get("unit_price_display")
                    or row.get("display_unit")
                    or row.get("unit")
                    or ""
                ),
            },
            "attributes": row.get("attributes") or {},
            "image_url": row.get("img") or row.get("image_url") or "",
            # The catalog's historical price tier is not the same thing as a
            # cross-product comparison rank, so let the client derive this from
            # the comparison summary instead of mixing the two concepts.
            "price_rank": None,
            "observed_at": meta.get("observed_at") or "",
        })

    bases = {
        product["normalized"]["basis"]
        for product in products
        if product["normalized"].get("unit_price") is not None
        and product["normalized"].get("basis")
    }
    common_basis = next(iter(bases)) if len(bases) == 1 else None

    unit_prices = [
        float(product["normalized"]["unit_price"])
        for product in products
        if common_basis
        and product["normalized"].get("basis") == common_basis
        and product["normalized"].get("unit_price") is not None
    ]
    current_prices = [
        float(product["price"]["current"])
        for product in products
        if product["price"].get("current")
    ]
    comparison_prices = unit_prices if unit_prices else current_prices
    avg = round(sum(comparison_prices) / len(comparison_prices)) if comparison_prices else 0
    minimum = round(min(comparison_prices)) if comparison_prices else 0
    maximum = round(max(comparison_prices)) if comparison_prices else 0

    if sort == "discount":
        products.sort(
            key=lambda item: (
                float(item["price"].get("discount_pct") or 0),
                item.get("observed_at") or "",
            ),
            reverse=True,
        )
    elif sort == "recent":
        products.sort(key=lambda item: item.get("observed_at") or "", reverse=True)
    elif sort == "price_desc":
        products.sort(
            key=lambda item: (
                _comparison_value(item, common_basis) > 0,
                _comparison_value(item, common_basis),
            ),
            reverse=True,
        )
    else:
        products.sort(
            key=lambda item: (
                _comparison_value(item, common_basis) <= 0,
                _comparison_value(item, common_basis) or float("inf"),
            )
        )

    total = len(products) if not children else 0
    start = (page - 1) * per_page
    page_products = products[start:start + per_page]
    product_count = category_total_count if children else (total_rows or total)

    summary = {
        "category_id": category_id,
        "category_path": (
            raw_products[0].get("cat", category_path)
            if raw_products else category_path
        ),
        "product_count": product_count,
        "is_leaf": not bool(children),
        "comparison_basis": common_basis,
        "avg_comparison_price": avg,
        "min_comparison_price": minimum,
        "max_comparison_price": maximum,
        "avg_unit_price": avg if unit_prices else None,
        "min_unit_price": minimum if unit_prices else None,
        "max_unit_price": maximum if unit_prices else None,
        # Compatibility fields remain truthful: they are populated only when
        # the actual common basis really is 100g.
        "avg_price_per_100g": avg if common_basis == "100g" else None,
        "min_price_per_100g": minimum if common_basis == "100g" else None,
        "max_price_per_100g": maximum if common_basis == "100g" else None,
        "hotdeal_threshold": round(avg * 0.85) if avg else 0,
        "ultra_threshold": round(avg * 0.7) if avg else 0,
        "normalized_product_count": len(unit_prices),
        "comparison_product_count": len(comparison_prices),
    }

    return ApiResponse(data={
        "summary": summary,
        "subcategories": children,
        "products": page_products,
        "alternatives": [],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": math.ceil(total / per_page) if total else 0,
        },
    })


@router.get("/{product_id}")
async def get_product(request: Request, product_id: int):
    try:
        result = _storage(request).get_product_detail(product_id)
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=result)


@router.get("/{product_id}/price-history")
async def get_price_history(
    request: Request,
    product_id: int,
    days: int = Query(30, ge=7, le=365),
):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        history = storage.get_price_history(product_id, days) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=history)


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: int):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        compare = storage.get_price_compare(product_id) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=compare)


@router.get("/{product_id}/trust")
async def get_product_trust(request: Request, product_id: int):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        history = storage.get_price_history(product_id, 30) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
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
        "standard_unit": (
            product.get("unit_price_display")
            or product.get("display_unit")
            or product.get("unit")
            or "판매 단위"
        ),
        "rationale": "최근 가격 이력과 현재 관측가를 비교한 임시 신뢰도입니다.",
    })
