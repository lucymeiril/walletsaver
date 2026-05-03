"""Deterministic product quantity/unit parsing shared by crawler and AI flows."""
from __future__ import annotations

import re
from typing import Any

_QUANTITY_RE = re.compile(
    r"(?<![\d.])(?:\((?P<paren>\d+(?:\.\d+)?)\s*(?P<paren_unit>kg|g|ml|mL|l|L)\)|(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|ml|mL|l|L))",
    re.IGNORECASE,
)
_DISPLAY_REF_UNIT_RE = re.compile(r"^\s*(?:100\s*g|1\s*kg|100\s*ml|1\s*l)\s*$", re.IGNORECASE)

_STORAGE_HINTS = {
    "냉장": "chilled",
    "냉동": "frozen",
}

_ORIGIN_HINTS = {
    "국산": "domestic",
    "국내산": "domestic",
    "한우": "domestic",
    "베트남": "vietnam",
}

_CUT_HINTS = {
    "불고기": "bulgogi",
    "등심": "sirloin",
    "삼겹살": "pork_belly",
    "목살": "pork_shoulder",
    "새우살": "shrimp_meat",
}


def _normalize_unit(unit: str) -> str:
    normalized = unit.strip()
    if normalized.lower() == "l":
        return "L"
    if normalized.lower() == "ml":
        return "ml"
    return normalized.lower()


def quantity_to_grams(quantity: float, unit: str) -> float | None:
    unit = _normalize_unit(unit)
    if unit == "kg":
        return quantity * 1000
    if unit == "g":
        return quantity
    return None


def quantity_to_standard_total(quantity: float, unit: str, bundle_count: int = 1) -> tuple[float, str] | None:
    unit = _normalize_unit(unit)
    if unit == "kg":
        return quantity * bundle_count, "kg"
    if unit == "g":
        return quantity / 1000 * bundle_count, "kg"
    if unit == "L":
        return quantity * bundle_count, "L"
    if unit == "ml":
        return quantity / 1000 * bundle_count, "L"
    return None


def parse_package_quantity(text: str) -> dict[str, Any] | None:
    """Extract the sold package quantity from title text (e.g. 300g, (200g), 1.5L)."""
    matches = list(_QUANTITY_RE.finditer(text or ""))
    if not matches:
        return None
    match = matches[-1]
    qty_text = match.group("paren") or match.group("qty")
    unit_text = match.group("paren_unit") or match.group("unit")
    quantity = float(qty_text)
    unit = _normalize_unit(unit_text)
    return {
        "raw_match": match.group(0),
        "package_quantity": quantity,
        "package_unit": unit,
        "display_unit": f"{int(quantity) if quantity.is_integer() else quantity:g}{unit}",
    }


def extract_product_attributes(text: str) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    for token, value in _STORAGE_HINTS.items():
        if token in text:
            attributes["storage_type"] = value
            attributes["storage_label"] = token
            break
    for token, value in _ORIGIN_HINTS.items():
        if token in text:
            attributes["origin"] = value
            attributes["origin_label"] = token
            break
    grade_match = re.search(r"(?<!\d)(?:1\+{1,2}|[123])\s*등급", text)
    if grade_match:
        attributes["quality_grade"] = grade_match.group(0).replace(" ", "").replace("등급", "")
    for token, value in _CUT_HINTS.items():
        if token in text:
            attributes["cut"] = value
            attributes["cut_label"] = token
            break
    return attributes


def normalize_unit_metadata(
    *,
    name: str,
    sale_price: int | float | None = None,
    raw_unit: str | None = None,
) -> dict[str, Any]:
    """Return safe display/package/unit-price metadata without treating reference units as pack units."""
    parsed = parse_package_quantity(name)
    result: dict[str, Any] = {
        "display_unit": None,
        "package_quantity": None,
        "package_unit": None,
        "price_per_100g": None,
        "attributes": extract_product_attributes(name),
    }
    if parsed:
        result.update(parsed)
        grams = quantity_to_grams(parsed["package_quantity"], parsed["package_unit"])
        if grams and sale_price is not None:
            result["price_per_100g"] = round(float(sale_price) * 100 / grams, 2)
        return result

    raw = (raw_unit or "").strip()
    if raw and not _DISPLAY_REF_UNIT_RE.match(raw):
        result["display_unit"] = raw
    return result
