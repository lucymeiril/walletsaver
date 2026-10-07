"""Public catalog API backed by the replaceable catalog SQLite snapshot."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas.common import ApiResponse, PaginationMeta
from services.catalog_storage import CatalogUnavailable, rank_normalized_offers

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


def _comparison_value(product: dict, common_basis: str | None) -> float | None:
    normalized = product.get("normalized") or {}
    if (
        common_basis
        and normalized.get("basis") == common_basis
        and _positive_float(normalized.get("unit_price")) is not None
    ):
        return float(normalized["unit_price"])
    return None


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
    comparison_basis: str | None = Query(None, description="입증된 동일 단위 또는 동일 규격 비교 그룹"),
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
            fetch_count = min(1000, max(1, int(category_total_count or per_page)))
            fetch_page = lambda page, size: storage.get_category_products(category_id, page=page, per_page=size)
            raw_products, total_rows = storage.get_category_products(
                category_id, page=1, per_page=fetch_count
            )
            if not raw_products:
                search_page = getattr(storage, "search_products_page", None)
                if callable(search_page):
                    fetch_page = lambda page, size: search_page("", category=category_id, page=page, per_page=size)
                    raw_products, total_rows = search_page(
                        "", category=category_id, page=1, per_page=fetch_count
                    )
                else:
                    fetch_page = lambda page, size: (
                        storage.search_products("", category=category_id, page=page, per_page=size),
                        category_total_count,
                    )
                    raw_products = storage.search_products(
                        "", category=category_id, page=1, per_page=fetch_count
                    )
                    total_rows = category_total_count or len(raw_products)
            # Resolve the comparison basis across the complete leaf before
            # sorting/paging: later rows can contain a different unit basis.
            if total_rows > len(raw_products):
                chunk_size = len(raw_products)
                if not chunk_size:
                    raise CatalogUnavailable("category comparison rows are incomplete")
                for fetch_number in range(2, math.ceil(total_rows / chunk_size) + 1):
                    chunk, _ = fetch_page(fetch_number, chunk_size)
                    raw_products.extend(chunk)
                if len(raw_products) != total_rows or len({row.get("id") for row in raw_products}) != total_rows:
                    raise CatalogUnavailable("category comparison rows are incomplete")
    except Exception as exc:
        raise _catalog_error(exc) from exc

    legacy_ids: list[int] = []
    for row in raw_products:
        if row.get("public_product_id"):
            continue
        try:
            legacy_ids.append(int(row["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    metadata = _comparison_metadata(storage, legacy_ids)

    products = []
    for row in raw_products:
        best_offer = row.get("best_offer") or {}
        selected_variant = next((variant for variant in row.get("variants", []) if variant.get("id") == best_offer.get("variant_id")), {})
        current = best_offer.get("comparable_price") if row.get("public_product_id") else (
            best_offer.get("comparable_price")
            or best_offer.get("total_price")
            or row.get("cur")
            or row.get("price")
            or None
        )
        current = _positive_float(current)
        original = _positive_float(best_offer.get("original_price") or row.get("original_price"))
        discount_pct = row.get("discount_pct")
        if discount_pct is None and current and original and original > current:
            discount_pct = round((1 - current / original) * 100)

        meta = {}
        if not row.get("public_product_id"):
            try:
                meta = metadata.get(int(row.get("id") or 0), {})
            except (TypeError, ValueError):
                meta = {}
        if current is not None and _positive_float(best_offer.get("per_100g")) is not None:
            unit_price, basis = best_offer["per_100g"], "100g"
        elif current is not None and _positive_float(best_offer.get("per_100ml")) is not None:
            unit_price, basis = best_offer["per_100ml"], "100ml"
        elif current is not None and _positive_float(best_offer.get("per_100m")) is not None:
            unit_price, basis = best_offer["per_100m"], "100m"
        else:
            unit_price, basis = _normalized_unit_price(float(current or 0), meta)
        products.append({
            "id": row.get("id"),
            "variant_id": best_offer.get("variant_id"),
            "listing_id": best_offer.get("listing_id"),
            "offer_id": best_offer.get("id"),
            "best_offer": dict(best_offer) if best_offer else None,
            "name": row.get("name", ""),
            "source": row.get("source") or "",
            "brand": row.get("brand") or "",
            "category_path": row.get("cat") or "",
            "price": {
                "current": current,
                "original": original,
                "discount_pct": discount_pct,
            },
            "normalized": {
                "unit_price": unit_price,
                "basis": basis,
                "per_100g": unit_price if basis == "100g" else None,
                "per_100ml": unit_price if basis == "100ml" else None,
                "per_100m": unit_price if basis == "100m" else None,
                "unit_price_display": (
                    row.get("unit_price_display")
                    or row.get("display_unit")
                    or row.get("unit")
                    or ""
                ),
            },
            "attributes": row.get("attributes") or {},
            "image_url": row.get("img") or row.get("image_url") or "",
            "promotion": {
                **{key: best_offer.get(key) for key in (
                    "variant_id", "listing_id", "listed_price", "total_price", "total_quantity",
                    "quantity_unit", "received_package_count", "promotion_condition", "promotion_conditions", "promotion_type",
                    "per_100m",
                    "quantity_basis", "scalar_basis", "received_package_count_scope",
                    "pricing_measure_quantity", "pricing_measure_unit", "pricing_measure_basis", "quantity_components",
                )},
                "offer_id": best_offer.get("id"),
                "display_unit": selected_variant.get("display_unit") or row.get("unit") or None,
                "package_quantity": selected_variant.get("package_quantity"),
                "package_unit": selected_variant.get("package_unit"),
                "bundle_count": selected_variant.get("bundle_count", best_offer.get("bundle_count")),
                "condition": best_offer.get("promotion_condition"),
                "minimum_quantity": best_offer.get("minimum_quantity"),
                "membership_required": best_offer.get("membership_required"),
                "coupon_required": best_offer.get("coupon_required"),
                "total_spend": best_offer.get("total_price"),
            } if best_offer else None,
            "classification_warning": bool(row.get("classification_warning")),
            # The catalog's historical price tier is not the same thing as a
            # cross-product comparison rank, so let the client derive this from
            # the comparison summary instead of mixing the two concepts.
            "price_rank": None,
            "observed_at": best_offer.get("crawled_at") or row.get("observed_at") or meta.get("observed_at") or "",
        })

    # Count prices may compare only the same explicit variant, including in a
    # leaf that also contains measured offers. Never mix them with g/ml prices.
    for product in products:
        if not product["normalized"].get("basis") and product["variant_id"]:
            per_item = _positive_float((product["best_offer"] or {}).get("per_item"))
            if product["price"]["current"] is not None and per_item is not None:
                product["normalized"].update(unit_price=per_item, basis=f"variant:{product['variant_id']}")

    bases = {
        product["normalized"]["basis"]
        for product in products
        if _positive_float(product["normalized"].get("unit_price")) is not None
        and product["normalized"].get("basis")
    }
    common_basis = next(iter(bases)) if len(bases) == 1 else None
    comparison_groups = []
    for basis in sorted(bases):
        group = [product for product in products if _comparison_value(product, basis) is not None]
        values = [_comparison_value(product, basis) for product in group]
        group_avg = sum(values) / len(values)
        comparison_groups.append({
            "basis": basis, "product_count": len(group), "comparable_count": len(group),
            "avg_comparison_price": group_avg, "min_comparison_price": min(values),
            "max_comparison_price": max(values),
            "hotdeal_threshold": group_avg * 0.85, "ultra_threshold": group_avg * 0.7,
        })
    if comparison_basis is not None:
        if comparison_basis not in bases:
            raise HTTPException(status_code=422, detail="이 카테고리에서 확인된 비교 그룹이 아닙니다")
        common_basis = comparison_basis
        # Group selection precedes sorting, count and pagination. The group
        # summary above always represents the full leaf, never a visible page.
        products = [product for product in products if _comparison_value(product, common_basis) is not None]

    unit_prices = [
        float(product["normalized"]["unit_price"])
        for product in products
        if common_basis
        and product["normalized"].get("basis") == common_basis
        and _positive_float(product["normalized"].get("unit_price")) is not None
    ]
    comparison_prices = unit_prices
    avg = sum(comparison_prices) / len(comparison_prices) if comparison_prices else None
    minimum = min(comparison_prices) if comparison_prices else None
    maximum = max(comparison_prices) if comparison_prices else None

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
    elif common_basis:
        comparable = [item for item in products if _comparison_value(item, common_basis) is not None]
        unranked = [item for item in products if _comparison_value(item, common_basis) is None]
        comparable.sort(key=lambda item: _comparison_value(item, common_basis), reverse=sort == "price_desc")
        products = comparable + unranked

    total = len(products) if not children else 0
    start = (page - 1) * per_page
    page_products = products[start:start + per_page]
    product_count = category_total_count if children else (total if comparison_basis else (total_rows or total))

    summary = {
        "category_id": category_id,
        "category_path": (
            raw_products[0].get("cat", category_path)
            if raw_products else category_path
        ),
        "product_count": product_count,
        "is_leaf": not bool(children),
        "comparison_basis": common_basis,
        "comparison_groups": comparison_groups,
        "category_product_count": category_total_count if children else (total_rows or total),
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
        "hotdeal_threshold": avg * 0.85 if avg is not None else None,
        "ultra_threshold": avg * 0.7 if avg is not None else None,
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


def _normalized_events(product: dict, *, latest_only: bool = False) -> list[dict]:
    events = []
    for variant in product.get("variants") or []:
        for listing in variant.get("listings") or []:
            offers = listing.get("offers") or []
            # Catalog storage orders each listing's observations newest first.
            selected = offers
            if latest_only:
                selected = ([offer for offer in offers if offer.get("is_latest") is True][:1]
                            if any("is_latest" in offer for offer in offers) else offers[:1])
            for offer in selected:
                events.append({**offer, "source": listing.get("source"), "source_url": listing.get("url"), "variant_id": variant.get("id"), "variant_name": variant.get("name")})
    return events


def _observed_in_period(event: dict, start: datetime, end: datetime) -> bool:
    try:
        observed = datetime.fromisoformat(str(event.get("crawled_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return start <= observed <= end


@router.get("/{product_id}")
async def get_product(request: Request, product_id: str):
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
    product_id: str,
    days: int = Query(30, ge=7, le=365),
):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        if product and product.get("public_product_id"):
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)
            history = [
                {
                    "id": event.get("id"),
                    "listing_id": event.get("listing_id"),
                    "offer_state": event.get("offer_state"),
                    "is_latest": event.get("is_latest"),
                    "current_eligible": event.get("current_eligible"),
                    "valid_from": event.get("valid_from"), "valid_to": event.get("valid_to"),
                    "availability_reason": event.get("availability_reason"),
                    "listed_price": event.get("listed_price"),
                    "date": event.get("crawled_at"),
                    "observed_at": event.get("crawled_at"),
                    "price": event.get("listed_price"),
                    "total_price": event.get("total_price"),
                    "comparable_price": event.get("comparable_price"),
                    "source": event.get("source"),
                    "source_url": event.get("source_url"),
                    "variant_id": event.get("variant_id"),
                    "promotion_condition": event.get("promotion_condition"),
                    "promotion_conditions": event.get("promotion_conditions"),
                    "minimum_quantity": event.get("minimum_quantity"),
                    "received_package_count": event.get("received_package_count"),
                    "membership_required": event.get("membership_required"),
                    "coupon_required": event.get("coupon_required"),
                    "total_quantity": event.get("total_quantity"),
                    "quantity_unit": event.get("quantity_unit"),
                    "per_100m": event.get("per_100m"),
                    "per_100g": event.get("per_100g"),
                    "per_100ml": event.get("per_100ml"),
                    "per_item": event.get("per_item"),
                    "observation_receipt_eligible": event.get("observation_receipt_eligible"),
                    "observation_receipt_reason": event.get("observation_receipt_reason"),
                    "observation_kind": event.get("observation_kind"),
                    "source_correction_lineage": event.get("source_correction_lineage"),
                    "source_correction_verified": event.get("source_correction_verified") is True,
                    "quantity_comparison_reason": event.get("quantity_comparison_reason"),
                    "quantity_basis": event.get("quantity_basis"),
                    "scalar_basis": event.get("scalar_basis"),
                    "received_package_count_scope": event.get("received_package_count_scope"),
                    "pricing_measure_quantity": event.get("pricing_measure_quantity"),
                    "pricing_measure_unit": event.get("pricing_measure_unit"),
                    "pricing_measure_basis": event.get("pricing_measure_basis"),
                    "quantity_components": event.get("quantity_components"),
                }
                for event in _normalized_events(product)
                if _observed_in_period(event, start, end)
            ]
        else:
            history = storage.get_price_history(int(product_id), days) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=history)


@router.get("/{product_id}/price-compare")
async def get_price_compare(request: Request, product_id: str):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        if product and product.get("public_product_id"):
            compare = rank_normalized_offers(
                [event for event in _normalized_events(product, latest_only=True)
                 if event.get("comparable_price") is not None and event.get("current_eligible") is True],
                reference_group=(product.get("comparison_reference") or {}).get("group"),
            )
        else:
            compare = storage.get_price_compare(int(product_id)) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    return ApiResponse(data=compare)


@router.get("/{product_id}/trust")
async def get_product_trust(request: Request, product_id: str):
    storage = _storage(request)
    try:
        product = storage.get_product_detail(product_id)
        if product and product.get("public_product_id"):
            history = [
                {"price": event.get("comparable_price") or event.get("total_price")}
                for event in _normalized_events(product)
            ]
        else:
            history = storage.get_price_history(int(product_id), 30) if product else []
    except Exception as exc:
        raise _catalog_error(exc) from exc
    if product is None:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")

    current = product.get("cur") if product.get("public_product_id") else product.get("cur") or product.get("price") or 0
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
