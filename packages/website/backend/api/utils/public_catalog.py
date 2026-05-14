"""Public catalog read adapter for website APIs.

The website should read published catalog/pricing data through a public read
boundary instead of depending on private admin ORM internals. The current
implementation adapts the existing storage object, so the API can move to a
separate public catalog DB later without changing route handlers.
"""

from __future__ import annotations

from statistics import mean
from typing import Any


PRICE_KEYS = ("cur", "price", "sale_price", "current_price", "item_price")


def safe_price(item: dict[str, Any] | None) -> float:
    if not item or not isinstance(item, dict):
        return 0
    for key in PRICE_KEYS:
        value = item.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return 0


class PublicCatalogReader:
    """Read-only adapter over the current product storage."""

    def __init__(self, storage: Any):
        self.storage = storage

    def get_product(self, product_id: int) -> dict[str, Any] | None:
        getter = getattr(self.storage, "get_public_product_detail", None) or self.storage.get_product_detail
        return normalize_public_product_detail(getter(product_id), product_id=product_id)

    def get_price_history(self, product_id: int, days: int) -> list[dict[str, Any]]:
        data = self.storage.get_price_history(product_id, days)
        if isinstance(data, dict) and "history" in data:
            data = data["history"]
        if not isinstance(data, list):
            return []
        points = [_normalize_history_point(item) for item in data]
        return [point for point in points if safe_price(point) > 0]

    def get_price_history_summary(
        self,
        product_id: int,
        days: int,
        product: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        product = product if product is not None else self.get_product(product_id)
        history = self.get_price_history(product_id, days)
        compare = self.get_price_compare(product_id)
        compare_items = _compare_items(compare)
        current_offer = _current_offer(product or {}, history, compare_items)
        prices = [safe_price(row) for row in history if safe_price(row) > 0]

        return {
            "product_id": product_id,
            "days": days,
            "history": history,
            "points": history,
            "point_count": len(history),
            "has_history": bool(history),
            "is_sparse": len(history) < 2,
            "current_offer": current_offer,
            "latest_offer": current_offer,
            "average_price": round(mean(prices)) if prices else None,
            "min_price": min(prices) if prices else None,
            "max_price": max(prices) if prices else None,
            "message": _history_message(history, current_offer),
        }

    def get_price_compare(self, product_id: int) -> list[dict[str, Any]] | dict[str, Any]:
        data = self.storage.get_price_compare(product_id)
        if not data:
            return []
        if isinstance(data, list):
            return [_normalize_offer(item) for item in data]
        if isinstance(data, dict):
            normalized = dict(data)
            for key in ("sources", "stores", "other_stores", "items"):
                if isinstance(normalized.get(key), list):
                    normalized[key] = [_normalize_offer(item) for item in normalized[key]]
            return normalized
        return []

    def get_price_trust_summary(self, product_id: int, days: int = 365) -> dict[str, Any] | None:
        product = self.get_product(product_id)
        if not product:
            return None

        history = self.get_price_history(product_id, days)
        compare = self.get_price_compare(product_id)
        compare_items = _compare_items(compare)

        current_price = _current_price(product, compare_items)
        history_prices = [float(row["price"]) for row in history if safe_price(row) > 0]
        compare_prices = [safe_price(row) for row in compare_items if safe_price(row) > 0]
        all_reference_prices = [*history_prices, *compare_prices]

        historical_low = min(history_prices) if history_prices else None
        historical_avg = round(mean(history_prices)) if history_prices else None
        source_low = min(compare_prices) if compare_prices else None
        source_avg = round(mean(compare_prices)) if compare_prices else None

        discount_history = [
            {
                "date": row.get("date") or row.get("recorded_at") or row.get("valid_from"),
                "source": row.get("source") or row.get("store") or "",
                "price": safe_price(row),
                "original_price": row.get("original_price"),
                "valid_from": row.get("valid_from"),
                "valid_to": row.get("valid_to") or row.get("valid_until"),
            }
            for row in history[-12:]
            if safe_price(row) > 0
        ]

        hotdeal_score, rationale = _score_hotdeal(
            current_price=current_price,
            historical_low=historical_low,
            historical_avg=historical_avg,
            source_low=source_low,
            references=all_reference_prices,
        )

        return {
            "product_id": product_id,
            "current_price": current_price,
            "standard_unit_price": product.get("standard_unit_price") or product.get("unit_price"),
            "unit": product.get("unit") or product.get("spec") or "",
            "original_quantity": product.get("unit") or product.get("spec") or "",
            "historical_low_price": historical_low,
            "historical_average_price": historical_avg,
            "source_low_price": source_low,
            "source_average_price": source_avg,
            "reference_count": len(all_reference_prices),
            "hotdeal_score": hotdeal_score,
            "rationale": rationale,
            "source_prices": compare_items,
            "discount_history": discount_history,
        }


def normalize_public_product_detail(data: Any, *, product_id: int | None = None) -> dict[str, Any] | None:
    """Flatten approved public catalog product/variant/offer shapes for website rendering."""
    data = _asdict(data)
    if not isinstance(data, dict):
        return None

    product = _asdict(data.get("product")) if "product" in data else data
    variant = _asdict(data.get("variant")) or {}
    offer = _asdict(data.get("offer") or data.get("best_offer") or _first(data.get("offers"))) or {}

    normalized = {**product, **{k: v for k, v in variant.items() if v is not None}, **{k: v for k, v in offer.items() if v is not None}}
    if product_id is not None:
        normalized.setdefault("id", product_id)
        normalized.setdefault("product_id", product_id)

    canonical_name = product.get("canonical_name") or normalized.get("canonical_name")
    source_title = offer.get("source_title") or normalized.get("source_title")
    normalized.setdefault("name", canonical_name or source_title or normalized.get("title") or "")
    normalized.setdefault("category", product.get("category_id") or normalized.get("category_id") or "")
    normalized.setdefault("keywords", product.get("keywords") or [])
    normalized.setdefault("source", offer.get("source_name") or normalized.get("source_name") or normalized.get("store") or "")
    normalized.setdefault("store_name", normalized.get("source"))
    normalized.setdefault("image_url", offer.get("image_url") or normalized.get("image") or "")
    normalized.setdefault("source_url", offer.get("source_url") or normalized.get("detail_url") or "")
    _apply_observation_metadata(normalized, offer)

    if "price" not in normalized and offer.get("price") is not None:
        normalized["price"] = offer["price"]
    if "original_price" not in normalized and offer.get("original_price") is not None:
        normalized["original_price"] = offer["original_price"]

    if not normalized.get("unit"):
        qty = variant.get("package_quantity")
        package_unit = variant.get("package_unit")
        if qty and package_unit:
            normalized["unit"] = f"{qty:g}{package_unit}" if isinstance(qty, (int, float)) else f"{qty}{package_unit}"
    if variant.get("standard_unit"):
        normalized.setdefault("standard_unit", variant["standard_unit"])
    return normalized


def _asdict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return value


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else None


def _normalize_offer(item: Any) -> dict[str, Any]:
    item = _asdict(item)
    if not isinstance(item, dict):
        return {}
    normalized = dict(item)
    source = normalized.get("source") or normalized.get("source_name") or normalized.get("store") or normalized.get("store_name") or ""
    normalized.setdefault("source", source)
    normalized.setdefault("store_name", source)
    normalized.setdefault("store_key", source.lower() if isinstance(source, str) else "")
    _apply_observation_metadata(normalized, item)
    return normalized


def _normalize_history_point(item: Any) -> dict[str, Any]:
    item = _asdict(item)
    if not isinstance(item, dict):
        return {}
    price_observation_only = bool(_nested_first(item, "price_observation_only", default=False))
    original_price = _nested_first(item, "original_price")
    discount_rate = _nested_first(item, "discount_rate", "discount_percent")
    has_discount_metadata = bool(item.get("has_discount_metadata")) or (
        original_price is not None and discount_rate is not None and not price_observation_only
    )
    return {
        "date": item.get("date") or item.get("recorded_at") or item.get("valid_from") or item.get("crawled_at") or "",
        "price": safe_price(item),
        "source": item.get("source") or item.get("source_name") or item.get("store") or item.get("store_name") or "",
        "original_price": original_price if has_discount_metadata else None,
        "discount_rate": discount_rate if has_discount_metadata else None,
        "url": _nested_first(item, "url", "source_url", default=""),
        "source_url": _nested_first(item, "source_url", "url", default=""),
        "unit": _nested_first(item, "unit", default=""),
        "display_unit": _nested_first(item, "display_unit", "unit", default=""),
        "observed_at": _nested_first(item, "observed_at", "crawled_at", "recorded_at", default=""),
        "crawled_at": item.get("crawled_at") or "",
        "record_kind": _nested_first(item, "record_kind", default="price_observation"),
        "publication_kind": _nested_first(item, "publication_kind", "record_kind", default="price_observation"),
        "price_observation_only": price_observation_only,
        "discount_claim_status": _nested_first(item, "discount_claim_status", default="unknown"),
        "claim_basis": _nested_first(item, "claim_basis", "claim_source", default=""),
        "claim_blockers": _nested_first(item, "claim_blockers", default=[]),
        "has_discount_metadata": has_discount_metadata,
        "record_label": _nested_first(item, "record_label", default=("관측 가격" if price_observation_only else "가격 정보")),
        "claim_status_label": _nested_first(item, "claim_status_label", default=("할인 여부 미확인" if price_observation_only else "가격 정보")),
        "observation_type": _nested_first(item, "observation_type", default=""),
    }


def _nested_metadata_sources(item: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [item]
    raw = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    if raw:
        sources.append(raw)
        for key in ("publication", "price_observation", "discount_claim", "published_item"):
            nested = raw.get(key)
            if isinstance(nested, dict):
                sources.append(nested)
    return sources


def _nested_first(item: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for source in _nested_metadata_sources(item):
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return default


def _apply_observation_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
    price_observation_only = bool(_nested_first(source, "price_observation_only", default=False))
    has_discount_metadata = bool(_nested_first(source, "has_discount_metadata", default=False))
    target.setdefault("record_kind", _nested_first(source, "record_kind", default="price_observation"))
    target.setdefault("publication_kind", _nested_first(source, "publication_kind", default="price_observation"))
    target.setdefault("price_observation_only", price_observation_only)
    target.setdefault("discount_claim_status", _nested_first(source, "discount_claim_status", default="unknown"))
    target.setdefault("claim_basis", _nested_first(source, "claim_basis", "claim_source", default=""))
    target.setdefault("claim_blockers", _nested_first(source, "claim_blockers", default=[]))
    target.setdefault("has_discount_metadata", has_discount_metadata)
    target.setdefault("record_label", _nested_first(source, "record_label", default=("관측 가격" if price_observation_only else "가격 정보")))
    target.setdefault("claim_status_label", _nested_first(source, "claim_status_label", default=("할인 여부 미확인" if price_observation_only else "가격 정보")))
    target.setdefault("observed_at", _nested_first(source, "observed_at", "crawled_at", "recorded_at", default=""))


def _current_offer(
    product: dict[str, Any],
    history: list[dict[str, Any]],
    compare_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    product_price = safe_price(product)
    if product_price > 0:
        has_discount_metadata = bool(product.get("has_discount_metadata"))
        return {
            "price": product_price,
            "source": product.get("source") or product.get("source_name") or product.get("store") or product.get("store_name") or "",
            "original_price": product.get("original_price") if has_discount_metadata else None,
            "discount_rate": (product.get("discount_rate") or product.get("discount_pct")) if has_discount_metadata else None,
            "url": product.get("source_url") or product.get("url"),
            "date": product.get("updated_at") or product.get("crawled_at") or product.get("recorded_at"),
            "record_kind": product.get("record_kind"),
            "publication_kind": product.get("publication_kind"),
            "price_observation_only": product.get("price_observation_only"),
            "discount_claim_status": product.get("discount_claim_status"),
            "claim_basis": product.get("claim_basis"),
            "has_discount_metadata": has_discount_metadata,
            "record_label": product.get("record_label"),
            "claim_status_label": product.get("claim_status_label"),
        }

    compare_prices = [item for item in compare_items if safe_price(item) > 0]
    if compare_prices:
        best = min(compare_prices, key=safe_price)
        return {
            "price": safe_price(best),
            "source": best.get("source") or best.get("source_name") or best.get("store") or best.get("store_name") or "",
            "original_price": best.get("original_price"),
            "discount_rate": best.get("discount_rate"),
            "url": best.get("url") or best.get("source_url"),
            "date": best.get("date") or best.get("crawled_at") or best.get("recorded_at"),
        }

    if history:
        latest = history[-1]
        return {
            "price": safe_price(latest),
            "source": latest.get("source") or "",
            "original_price": latest.get("original_price"),
            "discount_rate": latest.get("discount_rate"),
            "url": latest.get("url") or latest.get("source_url"),
            "date": latest.get("observed_at") or latest.get("date"),
            "record_kind": latest.get("record_kind"),
            "publication_kind": latest.get("publication_kind"),
            "price_observation_only": latest.get("price_observation_only"),
            "discount_claim_status": latest.get("discount_claim_status"),
            "claim_basis": latest.get("claim_basis"),
            "has_discount_metadata": latest.get("has_discount_metadata"),
            "record_label": latest.get("record_label"),
            "claim_status_label": latest.get("claim_status_label"),
        }
    return None


def _history_message(history: list[dict[str, Any]], current_offer: dict[str, Any] | None) -> str:
    if len(history) >= 2:
        return ""
    if len(history) == 1:
        return "가격 이력이 1건뿐이라 추세 판단은 제한적입니다."
    if current_offer:
        return "아직 기간별 가격 이력은 없지만 현재 확인된 가격을 표시합니다."
    return "아직 수집된 가격 이력이 없습니다."


def _compare_items(compare: list[dict[str, Any]] | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(compare, list):
        return compare
    if isinstance(compare, dict):
        for key in ("sources", "stores", "other_stores", "items"):
            value = compare.get(key)
            if isinstance(value, list):
                return value
    return []


def _current_price(product: dict[str, Any], compare_items: list[dict[str, Any]]) -> float:
    price = safe_price(product)
    if price > 0:
        return price
    compare_prices = [safe_price(item) for item in compare_items if safe_price(item) > 0]
    return min(compare_prices) if compare_prices else 0


def _score_hotdeal(
    *,
    current_price: float,
    historical_low: float | None,
    historical_avg: float | None,
    source_low: float | None,
    references: list[float],
) -> tuple[int, str]:
    if current_price <= 0 or len(references) < 2:
        return 0, "판단할 가격 데이터가 아직 부족합니다."

    score = 50
    reasons: list[str] = []
    if historical_low and current_price <= historical_low:
        score += 30
        reasons.append("최근 이력 기준 최저가 수준입니다.")
    elif historical_avg and current_price <= historical_avg * 0.85:
        score += 20
        reasons.append("과거 평균보다 15% 이상 저렴합니다.")
    elif historical_avg and current_price > historical_avg:
        score -= 15
        reasons.append("과거 평균보다 비싼 편입니다.")

    if source_low and current_price <= source_low:
        score += 15
        reasons.append("현재 비교 가능한 출처 중 최저가입니다.")
    elif source_low and current_price > source_low * 1.05:
        score -= 10
        reasons.append("다른 출처에 더 저렴한 가격이 있습니다.")

    score = max(0, min(100, score))
    if not reasons:
        reasons.append("기준가와 큰 차이가 없어 보통 수준입니다.")
    return score, " ".join(reasons)
