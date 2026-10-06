"""데이터 검증기 — 크롤링 결과 품질 검증."""

from __future__ import annotations

import math
import re
from typing import Any
from urllib.parse import urlparse


# Expected types per field. Fields not listed here skip type checking.
FIELD_TYPE_RULES: dict[str, tuple[type, ...]] = {
    "name": (str,),
    "title": (str,),
    "url": (str,),
    "source_url": (str,),
    "detail_url": (str,),
    "store": (str,),
    "price": (int, float, str, type(None)),
    "original_price": (int, float, str, type(None)),
    "sale_price": (int, float, str, type(None)),
    "discount_percent": (int, float, type(None)),
    "attributes": (dict, type(None)),
}


def validate_items(
    items: list[dict[str, Any]],
    required_fields: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """필수 필드 존재 및 타입 확인. (valid, invalid) 튜플 반환."""
    valid, invalid = [], []
    for item in items:
        errors: list[str] = []

        # 1. Required field presence
        missing = [
            f for f in required_fields
            if item.get(f) is None
            or (isinstance(item.get(f), str) and not item[f].strip())
        ]
        if missing:
            errors.append(f"missing fields: {missing}")

        # 2. Type validation for known fields
        for field, expected_types in FIELD_TYPE_RULES.items():
            val = item.get(field)
            if val is not None and field in item and (
                not isinstance(val, expected_types)
                or (isinstance(val, bool) and int in expected_types)
            ):
                errors.append(
                    f"field '{field}': expected {expected_types}, got {type(val).__name__}"
                )

        if errors:
            item["_validation_error"] = "; ".join(errors)
            invalid.append(item)
        else:
            valid.append(item)
    return valid, invalid


def validate_price_range(
    items: list[dict[str, Any]],
    min_price: int = 0,
    max_price: int = 10_000_000,
    price_field: str = "price",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """가격 범위 검증. 범위 밖이면 invalid."""
    valid, invalid = [], []
    for item in items:
        price = item.get(price_field)
        if price is None:
            valid.append(item)
            continue
        if not isinstance(price, bool) and isinstance(price, (int, float)) and math.isfinite(price) and min_price <= price <= max_price:
            valid.append(item)
        else:
            item["_validation_error"] = (
                f"price {price} out of range [{min_price}, {max_price}]"
            )
            invalid.append(item)
    return valid, invalid


def validate_urls(
    items: list[dict[str, Any]],
    url_fields: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """URL 형식 검증."""
    url_fields = url_fields or ["url", "source_url", "detail_url"]
    valid, invalid = [], []
    for item in items:
        ok = True
        for field in url_fields:
            url = item.get(field)
            if url:
                parsed = urlparse(str(url))
                if not parsed.scheme or not parsed.netloc:
                    item["_validation_error"] = f"invalid url in '{field}': {url}"
                    ok = False
                    break
        (valid if ok else invalid).append(item)
    return valid, invalid


def observation_key(value: Any) -> tuple:
    """Exact observation identity, including native IDs, nested spec and offer facts.

    Dictionary order is incidental; list order and scalar types remain distinct.
    No URL alias, display-name matching or sale-amount inference is performed.
    """
    if isinstance(value, dict):
        return ("dict", frozenset((observation_key(k), observation_key(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(observation_key(v) for v in value))
    return (type(value).__name__, value)


def deduplicate(
    items: list[dict[str, Any]],
    key_fields: list[str],
) -> list[dict[str, Any]]:
    """Remove only exact repeated observations, retaining full source contexts.

    If every key field is missing/None, retain each otherwise anonymous row.
    """
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        values = tuple(item.get(f) for f in key_fields)
        # If all key fields are None/missing, use index as tiebreaker
        # to prevent collapsing unrelated items
        if all(v is None for v in values):
            key = ("missing_identity", idx)
        else:
            key = observation_key(item)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


_PRICE_RE = re.compile(r"(?:₩)?([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:원)?")


def normalize_prices(
    items: list[dict[str, Any]],
    price_field: str = "price",
) -> list[dict[str, Any]]:
    """한국 원화 정규화. '12,500원' → 12500, 문자열 → int 변환."""
    for item in items:
        raw = item.get(price_field)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            # Keep the actual amount, including invalid/nonfinite values for validation.
            continue
        if not isinstance(raw, str):
            continue
        raw_str = raw.strip().replace(" ", "")
        match = _PRICE_RE.fullmatch(raw_str)
        if match:
            amount = match.group(1).replace(",", "")
            item[price_field] = float(amount) if "." in amount else int(amount)
        # Malformed nonempty quotes stay invalid, rather than becoming unknown prices.
    return items
