"""데이터 검증기 — 크롤링 결과 품질 검증."""

from __future__ import annotations

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
        missing = [f for f in required_fields if not item.get(f)]
        if missing:
            errors.append(f"missing fields: {missing}")

        # 2. Type validation for known fields
        for field, expected_types in FIELD_TYPE_RULES.items():
            val = item.get(field)
            if val is not None and field in item and not isinstance(val, expected_types):
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
        if isinstance(price, (int, float)) and min_price <= price <= max_price:
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


def deduplicate(
    items: list[dict[str, Any]],
    key_fields: list[str],
) -> list[dict[str, Any]]:
    """중복 제거. key_fields 조합이 같으면 첫 번째만 유지.

    None/missing 필드가 포함된 키는 인덱스로 구별하여 false dedup을 방지한다.
    """
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        values = tuple(item.get(f) for f in key_fields)
        # If all key fields are None/missing, use index as tiebreaker
        # to prevent collapsing unrelated items
        if all(v is None for v in values):
            key = (*values, f"__idx_{idx}__")
        else:
            key = values
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


_PRICE_RE = re.compile(r"[\d,]+")


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
            item[price_field] = int(raw)
            continue
        raw_str = str(raw).replace(" ", "")
        match = _PRICE_RE.search(raw_str)
        if match:
            item[price_field] = int(match.group().replace(",", ""))
        else:
            item[price_field] = None
    return items
