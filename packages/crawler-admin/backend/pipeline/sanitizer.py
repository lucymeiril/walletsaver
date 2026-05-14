"""
Data sanitization for crawled content.

All text fields from external sources MUST pass through these functions
before entering the pipeline's transform stage.
"""

import html
import re
from typing import Any, Optional

_TAG_RE = re.compile(r"<[^>]+>")

_UNSAFE_CHARS_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.,;:!?%()\-/&#+@₩$€¥·•–—''""\"' ]")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def sanitize_text(value: Any, max_length: int = 500) -> str:
    """
    Sanitize a text field from crawled data.

    1. Coerce to string
    2. Remove null bytes and control characters
    3. Strip HTML tags
    4. HTML-escape special characters (prevents XSS)
    5. Remove remaining unsafe characters
    6. Collapse whitespace
    7. Truncate to max_length
    """
    if value is None:
        return ""
    text = str(value)

    text = _CONTROL_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = html.escape(text, quote=True)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text[:max_length]


def sanitize_url(value: Any, max_length: int = 2048) -> str:
    """
    Sanitize a URL field.

    1. Coerce to string
    2. Strip whitespace
    3. Reject javascript: / data: / vbscript: schemes
    4. Truncate to max_length
    """
    if value is None:
        return ""
    url = str(value).strip()

    lower = url.lower()
    if any(lower.startswith(s) for s in ("javascript:", "data:", "vbscript:")):
        return ""

    url = _CONTROL_RE.sub("", url)
    return url[:max_length]


def sanitize_number(value: Any, min_val: float = 0, max_val: float = 100_000_000) -> Optional[float]:
    """
    Validate and coerce a numeric value.

    Returns None if the value is not a valid number or out of range.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < min_val or num > max_val:
        return None
    return num


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Apply field-level sanitization to a pipeline record.

    Text fields → sanitize_text()
    URL fields  → sanitize_url()
    Price fields → sanitize_number()
    """
    text_fields = [
        "product_name", "title", "store", "category",
        "event_name", "source", "source_community",
    ]
    url_fields = ["source_url", "url", "detail_url", "image_url"]
    price_fields = [
        "original_price", "sale_price", "price", "discount_percent",
    ]

    sanitized = dict(record)

    for field in text_fields:
        if field in sanitized:
            sanitized[field] = sanitize_text(sanitized[field])

    for field in url_fields:
        if field in sanitized:
            sanitized[field] = sanitize_url(sanitized[field])

    for field in price_fields:
        if field in sanitized:
            sanitized[field] = sanitize_number(sanitized[field])

    return sanitized
