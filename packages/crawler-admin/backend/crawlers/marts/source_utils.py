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
