"""Shared mart source collection helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any


def absolute_url(url: str | None, base_url: str) -> str:
    if not url:
        return ""
    value = str(url).strip()
    if value.startswith("//"):
        return f"https:{value}"
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{base_url.rstrip('/')}{value}"
    return value


def normalize_source_key(source_id: str, *values: Any) -> str:
    """Return a stable source-owned key for incremental/dedup updates."""
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    digest_input = "|".join(str(value or "") for value in values)
    digest = hashlib.sha1(digest_input.encode("utf-8")).hexdigest()[:16]
    return f"{source_id}:{digest}"


def source_dedup_key(item: Any) -> tuple[str, str, str]:
    attrs = getattr(item, "attributes", {}) or {}
    source_key = attrs.get("source_record_key")
    source_url = attrs.get("source_url") or getattr(item, "detail_url", "")
    if source_key:
        return ("source_record_key", str(source_key), "")
    if source_url:
        return ("source_url", str(source_url), "")
    return ("name_price", getattr(item, "name", ""), str(getattr(item, "sale_price", "")))


def parse_period_fields(data: dict[str, Any]) -> tuple[datetime | None, datetime | None, str]:
    """Extract common source event period fields without inventing dates."""
    start = _first_value(
        data,
        "validFrom",
        "valid_from",
        "startDate",
        "startDt",
        "eventStartDate",
        "eventStartDt",
        "dispStartDate",
        "dispStartDt",
    )
    end = _first_value(
        data,
        "validUntil",
        "validTo",
        "valid_until",
        "endDate",
        "endDt",
        "eventEndDate",
        "eventEndDt",
        "dispEndDate",
        "dispEndDt",
    )
    valid_from = _parse_datetime(start)
    valid_until = _parse_datetime(end)
    if valid_from or valid_until:
        period = f"{valid_from.date().isoformat() if valid_from else ''}~{valid_until.date().isoformat() if valid_until else ''}"
        return valid_from, valid_until, period
    period_text = str(_first_value(data, "period", "eventPeriod", "validPeriod") or "").strip()
    return None, None, period_text


def build_source_attributes(
    source_id: str,
    *,
    source_record_key: str = "",
    detail_url: str = "",
    image_url: str = "",
    category: str = "",
    category_path: list[str] | None = None,
    period: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    attrs = {
        "source_name": source_id,
        **(extra or {}),
    }
    if source_record_key:
        attrs["source_record_key"] = source_record_key
    if detail_url:
        attrs["source_url"] = detail_url
    if image_url:
        attrs["image_url"] = image_url
    if category:
        attrs["category_hint"] = category
    if category_path:
        attrs["category_path"] = category_path
    if period:
        attrs["period"] = period
    return attrs


MART3_REQUIRED_PRODUCT_CLASSES: dict[str, list[str]] = {
    "produce_fruit": ["과일"],
    "produce_vegetable": ["채소"],
    "meat": ["정육", "축산"],
    "seafood": ["수산", "생선"],
    "dairy": ["유제품", "우유"],
    "water_beverage": ["생수", "음료"],
    "eggs": ["계란", "달걀"],
    "ready_meal": ["간편식", "밀키트"],
}


def build_source_map_manifest(
    source_id: str,
    *,
    search_queries: list[str] | tuple[str, ...] = (),
    category_queries: list[str] | tuple[str, ...] = (),
    max_pages: int | None = None,
    max_requests: int | None = None,
    max_items: int | None = None,
    parser_contract: str = "",
    request_strategy: str = "",
    dedupe_key: str = "source_record_key_or_source_url",
    parser_inputs: list[str] | tuple[str, ...] = (),
    quality: dict[str, Any] | None = None,
    blocker: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe public mart source breadth without probing or bypassing a site."""
    search = [str(query) for query in search_queries]
    categories = [str(query) for query in category_queries]
    pages = max(1, int(max_pages or 1))
    planned_request_count = (len(search) + len(categories)) * pages
    bounded_request_count = min(planned_request_count, max_requests) if max_requests is not None else planned_request_count
    counts = (quality or {}).get("item_counts") or {}
    coverage = (quality or {}).get("coverage") or {}
    class_coverage = _product_class_coverage([*search, *categories])
    live_blocker = blocker or ((quality or {}).get("fetch") or {} if ((quality or {}).get("fetch") or {}).get("blocked") else None)
    return {
        "schema": "mart3_source_map_manifest.v1",
        "source_id": source_id,
        "request_strategy": request_strategy,
        "parser_contract": parser_contract,
        "parser_inputs": [str(value) for value in parser_inputs],
        "collection_surfaces": {
            "search_queries": search,
            "category_queries": categories,
            "pagination": {"max_pages": max_pages, "planned_pages_per_query": pages},
            "bounded_limits": {"max_requests": max_requests, "max_items": max_items},
        },
        "breadth_plan": {
            "planned_request_count": planned_request_count,
            "bounded_request_count": bounded_request_count,
            "dedupe_key": dedupe_key,
            "required_product_classes": list(MART3_REQUIRED_PRODUCT_CLASSES),
            "covered_product_classes": [name for name, covered in class_coverage.items() if covered],
            "missing_product_classes": [name for name, covered in class_coverage.items() if not covered],
        },
        "count_breadth": {
            "source_raw": counts.get("source_raw"),
            "parsed": counts.get("parsed"),
            "valid": counts.get("valid"),
            "invalid_or_dropped": counts.get("invalid_or_dropped"),
            "duplicates_after_validation": counts.get("duplicates_after_validation"),
            "counts_recorded": all(name in counts for name in ("source_raw", "parsed", "valid")),
        },
        "field_breadth": {
            "source_url_or_detail_url": coverage.get("source_url") or coverage.get("detail_url"),
            "image_url": coverage.get("image_url"),
            "period": coverage.get("period"),
            "unit": coverage.get("unit"),
            "category_hint": coverage.get("category_hint"),
        },
        "live_blocker": live_blocker,
        "claim_policy": (
            "This manifest is an audit map only. It records public source surfaces, bounded limits, "
            "counts, dedupe, and blockers; it is not a live-service readiness pass threshold."
        ),
    }


def _product_class_coverage(queries: list[str]) -> dict[str, bool]:
    haystack = " ".join(queries)
    return {
        product_class: any(marker in haystack for marker in markers)
        for product_class, markers in MART3_REQUIRED_PRODUCT_CLASSES.items()
    }


def _first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    digits = re.sub(r"\D", "", text)
    candidates = []
    if len(digits) >= 8:
        candidates.append(digits[:8])
    candidates.append(text[:10])
    for candidate in candidates:
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return None
