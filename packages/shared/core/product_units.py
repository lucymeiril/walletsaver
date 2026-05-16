"""Deterministic product quantity/unit parsing shared by crawler and AI flows."""
from __future__ import annotations

import re
from typing import Any

_MEASURE_UNIT_PATTERN = r"kg|킬로그램|g|그램|ml|mL|밀리리터|미리리터|l|L|리터"
_QUANTITY_RE = re.compile(
    rf"(?<![\d.])(?:\((?P<paren>\d+(?:\.\d+)?)\s*(?P<paren_unit>{_MEASURE_UNIT_PATTERN})(?![A-Za-z])\)|(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_MEASURE_UNIT_PATTERN})(?![A-Za-z]))",
    re.IGNORECASE,
)
_MEASURE_BUNDLE_RE = re.compile(
    r"(?<![\d.])"
    rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_MEASURE_UNIT_PATTERN})(?![A-Za-z])"
    r"\s*[xX×*]\s*"
    r"(?P<count>\d+)\s*(?:개입|입|개|팩|봉|병|캔|포|장)?",
    re.IGNORECASE,
)
_COUNT_PACKAGE_RE = re.compile(
    r"(?<!\d)(?P<qty>\d+)\s*"
    r"(?P<unit>개입|봉지|인분|세트|마리|입|개|팩|봉|병|캔|손|매|롤|포|장|족|통|인|p|P)"
    r"(?![A-Za-z0-9가-힣])"
)
_COUNT_ONLY_PACKAGE_RE = re.compile(
    r"\(\s*(?P<unit>개입|봉지|인분|세트|마리|입|개|팩|봉|병|캔|손|매|롤|포|장|족|통|인|p|P)\s*\)"
)
_DISPLAY_REF_UNIT_RE = re.compile(r"^\s*(?:100\s*g|1\s*kg|100\s*ml|1\s*l)\s*$", re.IGNORECASE)
_REFERENCE_UNIT_SUFFIX_RE = re.compile(r"^\s*(?:당|/|기준)")

_STORAGE_HINTS = {
    "냉장": "chilled",
    "냉동": "frozen",
}
_AMBIENT_PRODUCE_TOKENS = {
    "망고",
    "사과",
    "바나나",
    "감귤",
    "귤",
    "양파",
    "감자",
    "고구마",
}

_ORIGIN_PATTERNS = (
    (re.compile(r"태국산?|Thailand", re.IGNORECASE), "thailand"),
    (re.compile(r"베트남산?|Vietnam", re.IGNORECASE), "vietnam"),
    (re.compile(r"(?<![가-힣])국내산|(?<![가-힣])국산|(?<![가-힣])한우"), "domestic"),
)

_CUT_HINTS = {
    "불고기": "bulgogi",
    "등심": "sirloin",
    "삼겹살": "pork_belly",
    "목살": "pork_shoulder",
    "새우살": "shrimp_meat",
}


def _normalize_unit(unit: str) -> str:
    """Normalize provider/crawler unit variants to the canonical unit vocabulary."""
    normalized = unit.strip()
    lower = normalized.lower()

    if lower in ("l", "liter", "litre", "리터", "ll"):
        return "L"

    if lower in ("ml", "milliliter", "millilitre", "미리리터", "밀리리터", "mml"):
        return "ml"

    if lower in ("g", "gram", "그램"):
        return "g"

    if lower in ("kg", "kilogram", "킬로그램"):
        return "kg"

    return lower


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


def _is_reference_unit_match(text: str, match: re.Match[str]) -> bool:
    qty_text = match.group("paren") or match.group("qty")
    unit_text = match.group("paren_unit") or match.group("unit")
    if not qty_text or not unit_text:
        return False
    reference_unit = f"{qty_text}{_normalize_unit(unit_text)}"
    return bool(
        _DISPLAY_REF_UNIT_RE.match(reference_unit)
        and _REFERENCE_UNIT_SUFFIX_RE.match(text[match.end():])
    )


def parse_package_quantity(text: str) -> dict[str, Any] | None:
    """Extract the sold package quantity from title text (e.g. 300g, (200g), 1.5L, 5입)."""
    text = text or ""
    bundle_matches = list(_MEASURE_BUNDLE_RE.finditer(text))
    if bundle_matches:
        match = max(bundle_matches, key=lambda item: item.start())
        quantity = float(match.group("qty"))
        if quantity <= 0:
            return None
        unit = _normalize_unit(match.group("unit"))
        bundle_count = int(match.group("count"))
        if bundle_count <= 0:
            return None
        display_qty = f"{int(quantity) if quantity.is_integer() else quantity:g}{unit}"
        return {
            "raw_match": match.group(0),
            "package_quantity": quantity,
            "package_unit": unit,
            "display_unit": f"{display_qty}×{bundle_count}",
            "bundle_count": bundle_count,
        }
    measure_matches = [
        ("measure", match)
        for match in _QUANTITY_RE.finditer(text)
        if not _is_reference_unit_match(text, match)
    ]
    count_matches = [
        ("count", match)
        for match in _COUNT_PACKAGE_RE.finditer(text)
    ] + [
        ("count_one", match)
        for match in _COUNT_ONLY_PACKAGE_RE.finditer(text)
    ]
    matches = measure_matches or count_matches
    if not matches:
        return None
    kind, match = max(matches, key=lambda item: item[1].start())
    if kind == "count":
        qty_text = match.group("qty")
        unit = match.group("unit")
        quantity = float(qty_text)
        if quantity <= 0:
            return None
        return {
            "raw_match": match.group(0),
            "package_quantity": quantity,
            "package_unit": unit,
            "display_unit": f"{int(quantity)}{unit}",
        }
    if kind == "count_one":
        unit = match.group("unit")
        return {
            "raw_match": match.group(0),
            "package_quantity": 1.0,
            "package_unit": unit,
            "display_unit": f"1{unit}",
        }
    qty_text = match.group("paren") or match.group("qty")
    unit_text = match.group("paren_unit") or match.group("unit")
    quantity = float(qty_text)
    if quantity <= 0:
        return None
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
    if "storage_type" not in attributes and any(token in (text or "") for token in _AMBIENT_PRODUCE_TOKENS):
        attributes["storage_type"] = "ambient"
        attributes["storage_label"] = "상온"
    for pattern, value in _ORIGIN_PATTERNS:
        match = pattern.search(text or "")
        if match:
            attributes["origin"] = value
            attributes["origin_label"] = match.group(0)
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
    raw = (raw_unit or "").strip()
    if not parsed and raw and not _DISPLAY_REF_UNIT_RE.match(raw):
        parsed = parse_package_quantity(raw)
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
            result["price_per_100g"] = round(
                float(sale_price) * 100 / (grams * int(parsed.get("bundle_count") or 1)),
                2,
            )
        return result

    if raw and not _DISPLAY_REF_UNIT_RE.match(raw):
        result["display_unit"] = raw
    return result
