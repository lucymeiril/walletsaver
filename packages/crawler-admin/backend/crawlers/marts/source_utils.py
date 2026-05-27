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


UNIT_PRICE_RE = re.compile(
    r"(?P<basis>\d+)\s*(?P<unit>g|ml|kg|L)\s*당\s*(?P<price>[\d,]+)\s*원",
    re.IGNORECASE,
)


def parse_unit_price(text: str) -> tuple[float | None, str | None]:
    """Parse a Korean displayed unit price into won and raw basis text."""
    match = UNIT_PRICE_RE.search(text or "")
    if not match:
        return None, None
    price = float(match.group("price").replace(",", ""))
    basis_raw = f"{match.group('basis')}{match.group('unit')}"
    return price, basis_raw


def normalize_lottemart_url(ean13_or_code: str) -> str:
    """Return the stable Lottemart OS-code product URL, rejecting UUID paths."""
    code = str(ean13_or_code or "").strip()
    if not code:
        raise ValueError("lottemart code must not be empty")
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", code):
        raise ValueError("lottemart UUID product identifiers are tracking-only")
    if code.upper().startswith("OS"):
        code = code[2:]
    return f"https://lottemartzetta.com/products/OS{code}/details"


def normalize_emart_url(item_id: str | int, store_no: str | int = "7009", salestr_no: str | int | None = None) -> str:
    """Return the canonical Emart item URL with optional salestrNo."""
    base = f"https://emart.ssg.com/item/itemView.ssg?itemId={item_id}&siteNo={store_no}"
    if salestr_no not in (None, ""):
        return f"{base}&salestrNo={salestr_no}"
    return base


def normalize_homeplus_url(item_no: str | int, store_type: str = "HYPER") -> str:
    """Return the canonical Homeplus mobile item URL for HYPER or EXP stores."""
    normalized_store_type = str(store_type).upper()
    if normalized_store_type not in {"HYPER", "EXP"}:
        raise ValueError("homeplus store_type must be one of HYPER or EXP")
    return f"https://mfront.homeplus.co.kr/item?itemNo={item_no}&storeType={normalized_store_type}"


def normalize_costco_url(path_with_slug: str, p_number: str | int) -> str:
    """Return the canonical Costco product URL, forcing an absolute path prefix."""
    path = str(path_with_slug or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    path = path.rstrip("/")
    return f"https://www.costco.co.kr{path}/p/{p_number}"


_MARKER_WORDS = (
    "행사상품",
    "한정판매",
    "신상품",
    "이벤트",
    "EVENT",
    "NEW",
    "기획",
    "특가",
    "핫딜",
    "할인",
    "행사",
    "한정",
    "신상",
    "무배",
)
_MARKER_PATTERN = "|".join(re.escape(word) for word in _MARKER_WORDS)
_BUY_X_GET_Y_PATTERN = r"\d+\s*\+\s*\d+"
_VOLATILE_MARKER_PATTERN = rf"(?:{_MARKER_PATTERN}|{_BUY_X_GET_Y_PATTERN})"
_BRACKET_MARKER_RE = re.compile(
    rf"\s*[\[\(\{{【<]\s*{_VOLATILE_MARKER_PATTERN}\s*[\]\)\}}】>]\s*",
    re.IGNORECASE,
)
_STAR_MARKER_RE = re.compile(
    rf"\s*★\s*{_VOLATILE_MARKER_PATTERN}\s*★\s*",
    re.IGNORECASE,
)
_STANDALONE_MARKER_RE = re.compile(
    rf"(?<![0-9A-Za-z가-힣]){_VOLATILE_MARKER_PATTERN}(?![0-9A-Za-z가-힣])",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")


def normalize_name_core(name: str | None, *, fold_case: bool = False) -> str:
    """Remove volatile event/new-product markers and collapse whitespace."""
    text = str(name or "").strip()
    if not text:
        return ""
    previous = None
    while previous != text:
        previous = text
        text = _BRACKET_MARKER_RE.sub(" ", text)
        text = _STAR_MARKER_RE.sub(" ", text)
    text = _STANDALONE_MARKER_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip(" -_/·|,.")
    return text.casefold() if fold_case else text


def _format_hash_value(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def compute_canon_hash(
    brand: str | None,
    normalized_name: str,
    pack_qty: float | None,
    pack_unit: str | None,
    *,
    fold_case: bool = False,
) -> str:
    """Compute the Round R cross-mart canonical SHA1 key from marker-stable name_core."""
    name_core = normalize_name_core(normalized_name, fold_case=fold_case)
    payload = "|".join(_format_hash_value(value) for value in (brand, name_core, pack_qty, pack_unit))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def classify_external_seller_emart(badge_classes: list[str], salestr_no: str | None) -> bool:
    """Classify Emart external sellers from item badges and non-default salestrNo."""
    has_internal_badge = any("cdtl_ico_item" in str(classes) for classes in (badge_classes or []))
    if has_internal_badge or not salestr_no:
        return False
    return str(salestr_no).strip() != "7009"


def classify_external_seller_homeplus(sidebar_text: str) -> bool:
    """Classify Homeplus external sellers from delivery labels in sidebar text."""
    text = sidebar_text or ""
    if "매직배송" in text or "새벽배송" in text:
        return False
    if "판매자택배" in text:
        return True
    return False


def inject_source_field(record: dict, mart: str) -> dict:
    """Set the crawler source field to the mart name in-place and return record."""
    record["source"] = mart
    return record

