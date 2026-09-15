"""Shared conservative catalog quantity contract; pure, no DB or network.

Used for initial staging and reviewed source recollection. Not an approval or
fuzzy matching rule: callers still require exact approved source/listing identity.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any, Iterable, Mapping
from core.product_units import parse_package_quantity
from core.reviewed_content_quantities import COUNTED_CONTENT_TITLES, REVIEWED_CHAIN_TITLES, REVIEWED_COUNT_ONLY


def uses_reviewed_quantity_rules(title: str) -> bool:
    """Only the bounded repairs, not a replacement for legacy matching rules."""
    title = unicodedata.normalize("NFKC", title).strip()
    return (title in COUNTED_CONTENT_TITLES or title in REVIEWED_CHAIN_TITLES or title in REVIEWED_COUNT_ONLY or "종이컵" in title
            or "고무장갑" in title and bool(re.search(r"\d+\s*켤레", title))
            or bool(re.search(r"키친타[월올]|종이타[월올]|위생행주", title))
            and bool(re.search(r"\d+\s*매\s*[x×*]\s*\d+\s*롤", title, re.I)))

UNIT_ALIASES = {
    "kg": (1000, "g"), "킬로그램": (1000, "g"), "g": (1, "g"), "그램": (1, "g"),
    "mg": (Decimal("0.001"), "g"), "l": (1000, "ml"), "리터": (1000, "ml"),
    "ml": (1, "ml"), "밀리리터": (1, "ml"), "미리리터": (1, "ml"), "cc": (1, "ml"),
    "ea": (1, "개"), "개": (1, "개"),
}
COUNT_UNITS = {"개입", "봉지", "인분", "세트", "마리", "회분", "구", "입", "팩", "봉", "병", "캔", "손", "매", "롤", "포", "장", "족", "통", "인", "p", "t", "모", "두", "알", "미", "포기", "단", "망", "박스", "쌍", "켤레"}
_COUNT_UNIT_PATTERN = "(?:" + "|".join(re.escape(unit) for unit in sorted(COUNT_UNITS | {"개", "ea"}, key=len, reverse=True)) + ")"
_COUNT_RANGE_RE = re.compile(rf"(?<![\d.])\d+(?:\.\d+)?\s*(?:{_COUNT_UNIT_PATTERN})?\s*[~～〜–—-]\s*\d+(?:\.\d+)?\s*{_COUNT_UNIT_PATTERN}", re.I)

def _text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _first(layers: Iterable[Mapping[str, Any]], names: Iterable[str]) -> Any:
    for layer in layers:
        for name in names:
            value = layer.get(name)
            if value is not None and value != "":
                return value
    return None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _positive(value: Any) -> int | float | None:
    number = _number(value)
    if number is None or number <= 0:
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _sheet_roll_package(payload: Mapping[str, Any], attrs: Mapping[str, Any], title: str) -> tuple[dict[str, Any] | None, list[str]] | None:
    """One explicit sheet-per-roll chain, not an arbitrary count multiplier.

    A 200-sheet roll sold as six rolls is quantity=200 sheets, bundle=6.
    Providers may store either sheets per roll or total purchased rolls; both
    must agree with the complete title, including independent display evidence.
    """
    if not re.search(r"키친타[월올]|종이타[월올]|위생행주", title):
        return None
    matches = list(re.finditer(r"(?<![\d.])(\d+)\s*매\s*[x×*]\s*(\d+)\s*롤(?![가-힣A-Za-z\d])", title, re.I))
    if not matches:
        return None
    # Partial/multi-product chains remain under the existing conservative
    # parser. Never interpret another pack factor or promotional + as quantity.
    if (len(matches) != 1 or len(re.findall(r"(?<![A-Za-z])[x×*]\s*\d+", title, re.I)) != 1
        or re.search(r"[+~～]|세트|혼합|특가", title) or _COUNT_RANGE_RE.search(title)
        or len(re.findall(r"\d+\s*(?:매|롤|팩|개|입)(?![가-힣])", title)) != 2):
        return None
    sheets, rolls = map(int, matches[0].groups())
    if not sheets or not rolls or rolls > 500:
        return None, ["unit_sheet_roll_unresolved"]
    quantity = _positive(_first((payload, attrs), ("package_quantity", "pack_qty")))
    unit = _text(_first((payload, attrs), ("package_unit", "pack_unit"))).casefold()
    count = _first((payload, attrs), ("bundle_count",))
    count = _number(count) if count is not None else None
    if quantity is not None and (unit, quantity) not in {("매", sheets), ("롤", rolls)}:
        return None, ["unit_sheet_roll_conflict"]
    if count is not None and count not in ({1} if unit == "롤" else {rolls}):
        return None, ["bundle_count_conflict"]
    if _first((payload, attrs), ("bundle_count",)) is not None and count is None:
        return None, ["bundle_count_invalid"]
    display = _text(_first((payload, attrs), ("display_unit", "unit")))
    if display and display != title:
        display_chain = list(re.finditer(r"(\d+)\s*매\s*[x×*]\s*(\d+)\s*롤", display, re.I))
        if display_chain:
            if len(display_chain) != 1 or tuple(map(int, display_chain[0].groups())) != (sheets, rolls) or display.strip() != display_chain[0].group():
                return None, ["unit_text_conflict"]
        elif not re.fullmatch(rf"\s*(?:{sheets}\s*매|{rolls}\s*롤)\s*", display):
            return None, ["unit_text_conflict"]
    return {"package_quantity": float(sheets), "package_unit": "매", "bundle_count": rolls,
            "standard_unit": None, "display_unit": title}, []


def normalize_catalog_package(payload: Mapping[str, Any], attrs: Mapping[str, Any], title: str) -> tuple[dict[str, Any] | None, list[str]]:
    title = _text(title)
    if (sheet_roll := _sheet_roll_package(payload, attrs, title)) is not None:
        return sheet_roll
    issues: list[str] = []
    quantity = _positive(_first((payload, attrs), ("package_quantity", "pack_qty")))
    unit = _text(_first((payload, attrs), ("package_unit", "pack_unit"))).casefold()
    if title in REVIEWED_COUNT_ONLY and quantity is None and not unit:
        return {"package_quantity": float(REVIEWED_COUNT_ONLY[title]), "package_unit": "개", "bundle_count": 1,
                "standard_unit": None, "display_unit": ""}, []
    if title in COUNTED_CONTENT_TITLES and unit in {"개", "ea", "개입", "입", "팩", "봉", "병", "캔", "포"}:
        parsed = parse_package_quantity(title)
        expected_count = parsed.get("bundle_count") if parsed else None
        raw_count = _first((payload, attrs), ("bundle_count",))
        if quantity != expected_count or raw_count is not None and _number(raw_count) != 1:
            return None, ["unit_counted_content_conflict"]
        display = _text(_first((payload, attrs), ("display_unit", "unit")))
        display_package = parse_package_quantity(display) if display else None
        if display and (not display_package or (
            UNIT_ALIASES.get(display_package["package_unit"].casefold(), (1, None))[1] not in {"g", "ml"}
            and (display_package["package_quantity"] != quantity or display_package.get("bundle_count"))
        )):
            return None, ["unit_text_conflict"]
        # Change only local normalized fields, never the source payload. The
        # ordinary validator below still checks every weight/volume, display
        # boundary and promotion-independent quantity conflict.
        quantity, unit = parsed["package_quantity"], parsed["package_unit"].casefold()
        payload = {**payload, "package_quantity": quantity, "package_unit": unit, "bundle_count": expected_count}
    # A paper cup's ml label is vessel capacity, never edible contents.
    # Recover only one explicit sold count; retain original capacity in raw
    # evidence/display text. Lids, kits and incomplete multiplications wait.
    if "종이컵" in title:
        counts = re.findall(r"(?<![\d.])(\d+)\s*(개입|개|[pP])(?![A-Za-z가-힣])", title)
        capacities = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*ml(?![A-Za-z])", title, re.I)
        count = int(counts[0][0]) if len(counts) == 1 else 0
        raw_bundle = _first((payload, attrs), ("bundle_count",))
        structured_count = _number(raw_bundle) if raw_bundle is not None else None
        if (not count or len(capacities) > 1 or _COUNT_RANGE_RE.search(title) or re.search(r"뚜껑|세트|혼합|특가|[+~～]|[x×*]\s*\d+\s*(?!ml)(?:롤|팩)", title, re.I)
            or len(re.findall(r"[x×*]\s*\d+", title, re.I)) > (1 if capacities else 0)
            or structured_count is not None and structured_count not in {1, count}):
            return None, ["unit_container_count_unresolved"]
        if unit in {"ml", "cc"}:
            if len(capacities) != 1 or quantity != float(capacities[0]):
                return None, ["unit_container_capacity_conflict"]
        elif quantity is not None and (unit not in {"개", "개입", "p", "ea"} or quantity != count):
            return None, ["unit_container_count_conflict"]
        display = _text(_first((payload, attrs), ("display_unit", "unit")))
        if display and display != title:
            display_package = parse_package_quantity(display)
            if not display_package:
                return None, ["unit_text_conflict"]
            display_quantity = display_package["package_quantity"]
            display_kind = display_package["package_unit"].casefold()
            display_count = display_package.get("bundle_count")
            if display_kind in {"ml", "cc"}:
                if len(capacities) != 1 or display_quantity != float(capacities[0]) or display_count not in {None, 1, count}:
                    return None, ["unit_container_capacity_conflict"]
            elif display_kind not in {"개", "개입", "p", "ea"} or display_quantity != count or display_count not in {None, 1}:
                return None, ["unit_container_count_conflict"]
        return {"package_quantity": float(count), "package_unit": "개", "bundle_count": 1,
                "standard_unit": None, "display_unit": title}, []
    # Missing crawler quantity is not proof of a singleton. A literal pair
    # count can establish rubber glove quantity without guessing sizes.
    if (quantity is None or not unit) and "고무장갑" in title:
        pair = re.search(r"(?<![\d.])(\d+)\s*켤레(?![가-힣])", title)
        if pair and not re.search(r"[+x×*~～]|세트|혼합", title, re.I):
            quantity, unit = int(pair.group(1)), "켤레"
    if quantity is None or not unit:
        return None, ["unit_unresolved"]
    if unit not in UNIT_ALIASES and unit not in COUNT_UNITS:
        return None, ["unit_unknown"]
    multiplier, canonical_unit = UNIT_ALIASES.get(unit, (1, unit))
    canonical_quantity = Decimal(str(quantity)) * Decimal(str(multiplier))
    raw_count = _first((payload, attrs), ("bundle_count",))
    count_number = _number(raw_count) if raw_count is not None else None
    if raw_count is not None and (count_number is None or count_number < 1 or count_number != count_number.to_integral_value()):
        return None, ["bundle_count_invalid"]
    display_unit = _text(_first((payload, attrs), ("display_unit", "unit")))
    parsed_candidates = [parsed for text in (title, display_unit) if (parsed := parse_package_quantity(text))]
    explicit_counts = {int(parsed["bundle_count"]) for parsed in parsed_candidates if parsed.get("bundle_count")}
    if len(explicit_counts) > 1:
        issues.append("bundle_count_conflict")
    # A count interval does not establish a fixed sold quantity. A separately
    # explicit weight/volume remains usable (e.g. 1.5kg with 5~6 tomatoes).
    if canonical_unit not in {"g", "ml"} and any(_COUNT_RANGE_RE.search(text) for text in (title, display_unit)):
        issues.append("count_range_unresolved")
    if any(re.search(r"(?<![A-Za-z0-9])[x×*]\s*\d+", text, re.I) and not (parse_package_quantity(text) or {}).get("bundle_count") for text in (title, display_unit)):
        # The convenience parser cannot resolve (5개입) x 5 / 160매 x 12롤.
        # Neither a crawler default of one nor another numeric field proves
        # that an otherwise unparsed multiplication has been interpreted.
        issues.append("bundle_multiplier_unresolved")
    if any(
        len(factors := re.findall(r"[x×*]\s*\d+", text, re.I)) > 1
        and len(re.findall(r"[x×*]\s*\d+", (parse_package_quantity(text) or {}).get("raw_match", ""), re.I)) != len(factors)
        for text in (title, display_unit)
    ):
        # Only a single fully parsed chain proves every factor. Separate
        # products, unsupported suffixes and partial chains remain unresolved.
        issues.append("bundle_multiplier_unresolved")
    if "+" in title and len(re.findall(rf"(?<![A-Za-z0-9])\d+\s*{_COUNT_UNIT_PATTERN}(?![A-Za-z])", title, re.I)) > 1:
        issues.append("mixed_package_unresolved")
    parsed = next((parsed for parsed in parsed_candidates if parsed.get("bundle_count")), parsed_candidates[0] if parsed_candidates else None)
    # The DiscountItem schema previously dropped bundle_count, but display_unit
    # retained it. Recover only an explicit multiplication confirmed by the
    # structured per-package quantity; never interpret 100ml+100ml as ×2.
    parsed_count = int(parsed.get("bundle_count", 1)) if parsed else 1
    if parsed_count > 500 and parsed and len(re.findall(r"[x×*]\s*\d+", parsed["raw_match"], re.I)) > 1:
        # Review unusually large wholesale/pallet packages before comparing
        # them with retail packs; the arithmetic alone does not prove scope.
        issues.append("bulk_package_review_required")
    if parsed and parsed.get("bundle_count"):
        parsed_unit = _text(parsed["package_unit"]).casefold()
        factor, parsed_unit = UNIT_ALIASES.get(parsed_unit, (1, parsed_unit))
        parsed_quantity = Decimal(str(parsed["package_quantity"])) * Decimal(str(factor))
        # Some providers store the total (210g) while the title gives the
        # comparable package boundary (30g×7). Recover that boundary only
        # when the exact multiplication proves the same total and no separate
        # structured bundle count claims otherwise.
        if (
            parsed_unit == canonical_unit
            and count_number is None
            and canonical_quantity == parsed_quantity * parsed_count
        ):
            canonical_quantity = parsed_quantity
        elif (parsed_quantity, parsed_unit) != (canonical_quantity, canonical_unit):
            issues.append("unit_title_conflict")
        if count_number is not None and int(count_number) != parsed_count:
            issues.append("bundle_count_conflict")
    count = int(count_number) if count_number is not None else parsed_count
    for candidate in parsed_candidates:
        candidate_unit = _text(candidate["package_unit"]).casefold()
        factor, candidate_unit = UNIT_ALIASES.get(candidate_unit, (1, candidate_unit))
        candidate_quantity = Decimal(str(candidate["package_quantity"])) * Decimal(str(factor))
        if candidate_unit == canonical_unit and candidate_quantity not in {canonical_quantity, canonical_quantity * count}:
            issues.append("unit_text_conflict")
        elif candidate.get("bundle_count") and candidate_unit != canonical_unit:
            issues.append("unit_text_conflict")
    measures = []
    for match in re.finditer(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(kg|킬로그램|그램|g|ml|밀리리터|미리리터|리터|l)(?![A-Za-z])", title, re.I):
        if re.match(r"\s*(?:당|기준|/\s*(?:당|[0-9,]+\s*원|원))", title[match.end():]):
            continue
        factor, measure_unit = UNIT_ALIASES[match.group(2).casefold()]
        measures.append((Decimal(match.group(1).replace(",", "")) * Decimal(str(factor)), measure_unit))
    if "+" in title and len(measures) > 1:
        issues.append("mixed_package_unresolved")
    allowed_measures = {(canonical_quantity, canonical_unit)}
    if count > 1:
        allowed_measures.add((canonical_quantity * count, canonical_unit))
    if any(measure not in allowed_measures for measure in measures):
        issues.append("multiple_package_quantities")
    if parsed and not parsed.get("bundle_count"):
        parsed_unit = _text(parsed["package_unit"]).casefold()
        factor, parsed_unit = UNIT_ALIASES.get(parsed_unit, (1, parsed_unit))
        parsed_quantity = Decimal(str(parsed["package_quantity"])) * Decimal(str(factor))
        if parsed_unit == canonical_unit and parsed_quantity != canonical_quantity:
            issues.append("unit_title_conflict")
    return {
        "package_quantity": float(canonical_quantity), "package_unit": canonical_unit,
        "bundle_count": count, "standard_unit": canonical_unit if canonical_unit in {"g", "ml"} else None,
        "display_unit": display_unit,
    }, sorted(set(issues))
