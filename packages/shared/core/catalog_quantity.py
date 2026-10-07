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
from core.reviewed_content_quantities import COUNTED_CONTENT_TITLES, REVIEWED_CHAIN_TITLES, REVIEWED_COUNT_ONLY, REVIEWED_CORRUPTED_MEASURED, REVIEWED_SOURCE_PACKAGES
from core.reviewed_content_quantities import REVIEWED_SOURCE_DISPLAYS
from core.reviewed_content_quantities import REVIEWED_SOURCE_STRUCTURAL_DISPLAYS, REVIEWED_SOURCE_ORIGINAL_BUNDLES
from core.reviewed_content_quantities import CAPACITY_NOT_CONTENT_TITLES
from core.reviewed_content_quantities import REVIEWED_COMPONENT_PACKAGES
from core.reviewed_content_quantities import REVIEWED_RESIDUAL177_PACKAGES

_REVIEWED_RESIDUAL177_PACKAGES = {_text_title: values for title, values in REVIEWED_RESIDUAL177_PACKAGES.items()
                                for _text_title in (unicodedata.normalize('NFKC', title).strip(),)}

_REVIEWED_COMPONENT_PACKAGES = {unicodedata.normalize('NFKC', title).strip(): values for title, values in REVIEWED_COMPONENT_PACKAGES.items()}

_REVIEWED_SOURCE_PACKAGES = {unicodedata.normalize("NFKC", title).strip(): values for title, values in REVIEWED_SOURCE_PACKAGES.items()}
_REVIEWED_SOURCE_STRUCTURAL_DISPLAYS = {
    unicodedata.normalize("NFKC", title).strip():
    {unicodedata.normalize("NFKC", display).strip() for display in displays}
    for title, displays in REVIEWED_SOURCE_STRUCTURAL_DISPLAYS.items()
}
_REVIEWED_SOURCE_ORIGINAL_BUNDLES = {
    unicodedata.normalize("NFKC", title).strip(): count
    for title, count in REVIEWED_SOURCE_ORIGINAL_BUNDLES.items()
}
_REVIEWED_SOURCE_DISPLAYS = {
    unicodedata.normalize("NFKC", title).strip():
    unicodedata.normalize("NFKC", basis).strip()
    for title, basis in REVIEWED_SOURCE_DISPLAYS.items()
}


def uses_separate_measured_count_rules(title: str) -> bool:
    return bool(_SEPARATE_MEASURED_COUNT_RE.search(unicodedata.normalize('NFKC', title)))


def uses_reviewed_quantity_rules(title: str) -> bool:
    """Only the bounded repairs, not a replacement for legacy matching rules."""
    title = unicodedata.normalize("NFKC", title).strip()
    if uses_separate_measured_count_rules(title):
        # Select validation, not approval: inner-content scope is checked with
        # source fields/category below, never inferred from the two numbers.
        return True
    if title in _REVIEWED_RESIDUAL177_PACKAGES or uses_approximate_measurement_rules(title):
        return True
    parsed = parse_package_quantity(title)
    factors = re.findall(r"[x×*]\s*\d+", title, re.I)
    declared_single = re.search(
        r'\d[\d,]*(?:\.\d+)?\s*(?:kg|g|ml|l)\s*\(\s*'
        r'(\d[\d,]*(?:\.\d+)?\s*(?:kg|g|ml|l)\s*[x×*]\s*\d+\s*(?:입|개|팩|pk|봉|병|캔|통)?)\s*\)',
        title, re.I,
    )
    safe_single = bool(
        len(factors) == 1 and declared_single and parsed
        and re.sub(r'\s+', '', declared_single[1]).casefold()
        == re.sub(r'\s+', '', parsed.get('raw_match', '')).casefold()
        and not re.search(r'[+~～]|혼합|세트|모음|묶음|콤보|선물|특가|할인|증정|행사|기획|덤', title)
    )
    complete_measured_chain = bool(
        parsed and parsed.get('package_unit') in {'g', 'kg', 'ml', 'l'}
        and (len(factors) > 1 or safe_single)
        and re.findall(r"[x×*]\s*\d+", parsed.get('raw_match', ''), re.I) == factors
    )
    # Eligibility selects the shared validator, not approval: structured,
    # mixed-package, incomplete-chain and wholesale guards still run there.
    return (complete_measured_chain or title in _REVIEWED_COMPONENT_PACKAGES or title in CAPACITY_NOT_CONTENT_TITLES or title in _REVIEWED_SOURCE_PACKAGES or title in {"simplus 국물팩(소) 50매입", "유기농 단백질 블랙미숫가루 400g (20gx20입)"} or title in COUNTED_CONTENT_TITLES or title in REVIEWED_CHAIN_TITLES or title in REVIEWED_COUNT_ONLY or title in REVIEWED_CORRUPTED_MEASURED or bool(re.search(r'종이컵|다회용투명(?:소주)?컵', title))
            or "고무장갑" in title and bool(re.search(r"\d+\s*켤레", title))
            or bool(re.search(r"키친타[월올]|종이타[월올]|위생행주", title))
            and bool(re.search(r"\d+\s*매\s*[x×*]\s*\d+\s*롤", title, re.I)))

UNIT_ALIASES = {
    "kg": (1000, "g"), "킬로그램": (1000, "g"), "g": (1, "g"), "그램": (1, "g"),
    "mg": (Decimal("0.001"), "g"), "l": (1000, "ml"), "리터": (1000, "ml"),
    "ml": (1, "ml"), "밀리리터": (1, "ml"), "미리리터": (1, "ml"), "cc": (1, "ml"),
    "ea": (1, "개"), "개": (1, "개"),
    "매": (1, "매"),
}
COUNT_UNITS = {"개입", "봉지", "인분", "세트", "마리", "회분", "구", "입", "팩", "봉", "병", "캔", "손", "매", "롤", "포", "장", "족", "통", "인", "p", "t", "모", "두", "알", "미", "포기", "단", "망", "박스", "쌍", "켤레"}
_COUNT_UNIT_PATTERN = "(?:" + "|".join(re.escape(unit) for unit in sorted(COUNT_UNITS | {"개", "ea"}, key=len, reverse=True)) + ")"
_COUNT_RANGE_RE = re.compile(rf"(?<![\d.])\d+(?:\.\d+)?\s*(?:{_COUNT_UNIT_PATTERN})?\s*[~～〜–—-]\s*\d+(?:\.\d+)?\s*{_COUNT_UNIT_PATTERN}", re.I)
_SEPARATE_MEASURED_COUNT_RE = re.compile(
    r"(?<![A-Za-z\d.,])(\d+(?:\.\d+)?)\s*(kg|g|ml|l)(?![A-Za-z])"
    r"\s*(?:씩\s*)?(?:\(\s*)?(\d+(?:\.\d+)?)\s*"
    r"(개입|입|개|팩|봉|병|캔|포)(?![A-Za-z가-힣\d.])", re.I,
)


def _separate_measured_count(payload, attrs, title, category_id):
    """Validate an inner measure followed by an independent sold count.

    A source-bound cup or liquid milk's matching inner-content fields/display,
    or explicit per-pack wording, supplies scope. Bare mass plus piece count
    may instead describe a whole bag.
    Return a convenience-parser candidate only after all source layers agree.
    """
    milk_form = (isinstance(category_id, str) and category_id.startswith('food.dairy.milk.')
                 and category_id != 'food.dairy.milk.condensed' and '우유' in title
                 and not re.search(r'분유|분말|파우더|가루|우유맛|우유용|우유컵|우유병|세제|세정|용기|계량|텀블러', title))
    if (milk_form and re.search(r'\d+\s*(?:개입|입|개|팩|봉|병|캔|포)', title)
        and re.search(r'약\s*\d|\d(?:\.\d+)?\s*(?:ml|l|개입|입|개|팩|봉|병|캔|포)\s*(?:내외|미만|이상|이하|정도)', title, re.I)):
        return None, ['measured_inner_scope_unresolved']
    matches = list(_SEPARATE_MEASURED_COUNT_RE.finditer(title))
    if not matches:
        if (_COUNT_RANGE_RE.search(title) and
            (category_id == 'food.meals.noodles.cup_ramen' and re.search(r'컵|사발', title)
             or milk_form and re.search(r'\d\s*(?:ml|l)(?![A-Za-z])', title, re.I))):
            return None, ['count_range_unresolved']
        return None, []
    if (len(matches) != 1 or _COUNT_RANGE_RE.search(title)
        or re.search(r'[+~～〜]|[x×*]\s*\d|혼합|세트|모음|콤보|선물|선택|랜덤|추가|증정|덤', title, re.I)):
        return None, ['independent_count_scope_unresolved']
    match = matches[0]
    amount, unit, count = Decimal(match[1]), match[2].casefold(), Decimal(match[3])
    if amount <= 0 or count <= 0 or count != count.to_integral_value():
        return None, ['bundle_count_invalid']
    count = int(count)
    factor, canonical_unit = UNIT_ALIASES[unit]
    inner = (amount * Decimal(str(factor)), canonical_unit)
    total = (inner[0] * count, canonical_unit)
    counts = re.findall(rf'(?<![\d.])\d+(?:\.\d+)?\s*{_COUNT_UNIT_PATTERN}(?![A-Za-z가-힣\d.])', title, re.I)
    if len(counts) != 1:
        return None, ['independent_count_scope_unresolved']
    per_pack = bool(re.search(r'(?:1\s*)?(?:개|팩|봉|병|캔|포|컵)당\s*$', title[:match.start()])
                    or re.search(r'(?:kg|g|ml|l)\s*씩', match[0], re.I))
    cup = category_id == 'food.meals.noodles.cup_ramen' and bool(re.search(r'컵|사발', title))
    milk = milk_form and canonical_unit == 'ml'
    if not per_pack and (not (cup or milk) or re.search(r'총\s*(?:내용량|중량|용량)?|전체|합계', title)):
        return None, ['measured_inner_scope_unresolved']
    layers, visited = [], set()
    def visit(layer):
        if not isinstance(layer, Mapping):
            raise ValueError('invalid source layer')
        if id(layer) in visited:
            return
        visited.add(id(layer)); layers.append(layer)
        for key in ('attributes', 'attrs'):
            if layer.get(key) is not None:
                visit(layer[key])
    inner_field = inner_display = False
    try:
        visit(payload); visit(attrs)
        for layer in layers:
            if milk and not per_pack:
                for key in ('category','category_hint','mart_native_category_path','source_category_path','category_path'):
                    path = _text(layer.get(key))
                    if path and (re.search(r'세제|세정|청소|주방용품|가전|반려|문구|장난감|생활용품|주류|생수|분유|분말|두유|요구르트|요거트|연유', path)
                                 or not re.search(r'우유|유제품|유가공|축산|친환경|유기농|식품|냉장|신선|가공유|음료|milk|dairy', path, re.I)):
                        raise ValueError('incompatible milk source category')
            quantities = [layer[k] for k in ('package_quantity','pack_qty','packQty','pack_quantity','packQuantity') if layer.get(k) not in (None,'')]
            units = [layer[k] for k in ('package_unit','pack_unit','packUnit','unitName') if layer.get(k) not in (None,'')]
            if bool(quantities) != bool(units):
                raise ValueError('incomplete source pair')
            for quantity in quantities:
                quantity = _number(quantity)
                if quantity is None or quantity <= 0:
                    raise ValueError('invalid source quantity')
                for alias in units:
                    multiplier, canonical = UNIT_ALIASES.get(_text(alias).casefold(), (1, None))
                    pair = (quantity * Decimal(str(multiplier)), canonical)
                    if pair not in ({inner, total} if per_pack else {inner}):
                        raise ValueError('conflicting source quantity')
                    inner_field |= pair == inner
            for key in ('bundle_count','bundleCount'):
                if layer.get(key) not in (None,'') and _number(layer[key]) not in {Decimal(1), Decimal(count)}:
                    raise ValueError('conflicting bundle count')
            for key in ('display_unit','unit'):
                display = _text(layer.get(key))
                if not display or display == title:
                    continue
                # A quote basis can never establish inner contents/count. A
                # compatible quote remains offer evidence; other dimensions fail.
                basis = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(kg|g|ml|l)\s*당\s*[0-9,]+(?:\.\d+)?\s*원', display, re.I)
                if basis:
                    if UNIT_ALIASES[basis[2].casefold()][1] != canonical_unit:
                        raise ValueError('incompatible price basis')
                    continue
                separate = list(_SEPARATE_MEASURED_COUNT_RE.finditer(display))
                if (separate and (len(separate) != 1 or Decimal(separate[0][3]) != count)
                    or len(re.findall(rf'(?<![\d.])\d+(?:\.\d+)?\s*{_COUNT_UNIT_PATTERN}(?![A-Za-z가-힣\d.])', display, re.I)) > 1
                    or re.search(r'당|기준', display)):
                    raise ValueError('unresolved display scope')
                parsed = parse_package_quantity(display)
                if not parsed or _COUNT_RANGE_RE.search(display) or re.search(r'[+~～〜]', display):
                    raise ValueError('unresolved display')
                multiplier, canonical = UNIT_ALIASES.get(_text(parsed['package_unit']).casefold(), (1, _text(parsed['package_unit']).casefold()))
                pair = (Decimal(str(parsed['package_quantity'])) * Decimal(str(multiplier)), canonical)
                display_count = parsed.get('bundle_count', 1)
                if canonical in {'개','개입','입','팩','봉','병','캔','포'}:
                    if pair[0] != count or display_count != 1:
                        raise ValueError('conflicting display count')
                elif pair not in {inner, total} or display_count not in {1, count} or display_count != 1 and pair != inner:
                    raise ValueError('conflicting measured display')
                inner_display |= pair == inner
            for key in ('unit_price_basis','unit_price_basis_raw','unit_price_display','unit_price_text','unit_price_unit'):
                basis = _text(layer.get(key))
                if not basis:
                    continue
                quoted = re.fullmatch(r'(?:\d+(?:\.\d+)?\s*)?(kg|g|ml|l)\s*(?:당\s*[0-9,]+(?:\.\d+)?\s*원)?', basis, re.I)
                if not quoted or UNIT_ALIASES[quoted[1].casefold()][1] != canonical_unit:
                    raise ValueError('unresolved price basis')
        if not per_pack and not (inner_field and inner_display):
            return None, ['measured_inner_scope_unresolved']
    except (ValueError, InvalidOperation):
        return None, ['independent_count_source_conflict']
    return {'package_quantity': float(amount), 'package_unit': unit,
            'bundle_count': count, 'raw_match': match[0]}, []

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


def uses_approximate_measurement_rules(title: str) -> bool:
    """An explicit mass upper bound/estimate is not exact purchased mass."""
    return bool(re.search(r'(?<![\d.])\d+(?:\.\d+)?\s*(?:kg|g|킬로그램|그램)\s*(?:미만|내외)', _text(title), re.I))


def _approximate_mass_count_package(payload, attrs, title):
    """Keep estimated mass as source evidence; only a proven sold count is exact.

    Grades, dimensions, ranges and unproven multiplier chains cannot supply it.
    Structured legacy mass may repeat the estimate, never contradict or price it.
    """
    estimates = re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|g|킬로그램|그램)\s*(?:미만|내외)', title, re.I)
    counts = re.findall(r'(?<![\d.])(\d+)\s*(개입|마리|입(?:팩)?|개|미)(?![A-Za-z가-힣])', title, re.I)
    # Unnumbered /봉 is a packaging qualifier. A numbered 2봉/2팩 is a
    # second sold count and cannot disappear from the specification. Include
    # the existing count vocabulary while keeping 입팩 as one primary token.
    sold_count_pattern = rf'(?<![\d.])(\d+(?:\.\d+)?)\s*(입팩|{_COUNT_UNIT_PATTERN})'
    sold_counts = re.findall(sold_count_pattern, title, re.I)
    if len(estimates) != 1 or len(counts) != 1 or len(sold_counts) != 1 or _COUNT_RANGE_RE.search(title) or re.search(r'[+~～〜]|[x×*]\s*\d', re.sub(r'\d+\s*[~～〜]\s*\d+\s*cm', '', title, flags=re.I), re.I):
        return None, ['approximate_measured_quantity_unresolved']
    count = Decimal(counts[0][0])
    if count <= 0:
        return None, ['approximate_measured_quantity_unresolved']
    unit = '마리' if counts[0][1] == '마리' else '미' if counts[0][1] == '미' else '개'
    factor, _ = UNIT_ALIASES[estimates[0][1].casefold()]
    estimate = Decimal(estimates[0][0]) * Decimal(str(factor))
    layers, visited = [], set()
    def visit(layer):
        if not isinstance(layer, Mapping):
            raise ValueError('invalid evidence layer')
        if id(layer) in visited:
            return
        visited.add(id(layer)); layers.append(layer)
        for key in ('attributes', 'attrs'):
            if layer.get(key) is not None:
                visit(layer[key])
    try:
        visit(payload); visit(attrs)
        seen = set()
        for layer in layers:
            quantities = [layer[k] for k in ('package_quantity','pack_qty','packQty','pack_quantity','packQuantity') if layer.get(k) not in (None,'')]
            units = [layer[k] for k in ('package_unit','pack_unit','packUnit','unitName') if layer.get(k) not in (None,'')]
            if bool(quantities) != bool(units):
                raise ValueError('incomplete quantity')
            for amount in quantities:
                amount = _number(amount)
                if amount is None:
                    raise ValueError('invalid quantity')
                for alias in units:
                    alias = _text(alias).casefold()
                    multiplier, canonical = UNIT_ALIASES.get(alias, (1, alias))
                    if canonical in {'개입','입'}:
                        canonical = '개'
                    pair = (amount * Decimal(str(multiplier)), canonical)
                    if pair not in {(estimate, 'g'), (count, unit)}:
                        raise ValueError('conflicting quantity')
                    seen.add(pair)
            for key in ('bundle_count','bundleCount'):
                if layer.get(key) not in (None,'') and _number(layer[key]) != 1:
                    raise ValueError('repeated bundle count')
            for key in ('display_unit','unit'):
                display = _text(layer.get(key))
                if not display or display == title:
                    continue
                display_counts = re.findall(sold_count_pattern, display, re.I)
                if display_counts:
                    display_count, display_unit = display_counts[0]
                    display_unit = '개' if display_unit.casefold() in {'개','ea','입','개입','입팩'} else display_unit.casefold()
                    if len(display_counts) != 1 or (Decimal(display_count), display_unit) != (count, unit):
                        raise ValueError('unproven display sold count')
                parsed = parse_package_quantity(display)
                if not parsed:
                    raise ValueError('unproven display')
                alias = parsed['package_unit'].casefold()
                multiplier, canonical = UNIT_ALIASES.get(alias, (1, alias))
                if canonical in {'개입','입'}:
                    canonical = '개'
                pair = (Decimal(str(parsed['package_quantity'])) * Decimal(str(multiplier)), canonical)
                if pair not in {(estimate, 'g'), (count, unit)} or parsed.get('bundle_count', 1) != 1:
                    raise ValueError('conflicting display')
            for key in ('unit_price_display','unit_price_basis','unit_price_basis_raw','unit_price_text','unit_price_unit'):
                basis = _text(layer.get(key))
                if not basis:
                    continue
                match = re.fullmatch(r'(?:(\d+(?:\.\d+)?)\s*)?(kg|g|개|ea|입|마리|미)\s*(?:당\s*([0-9,]+(?:\.[0-9]+)?)\s*원)?', basis, re.I)
                if not match or (match[1] is not None and (_number(match[1]) or 0) <= 0) or (match[3] is not None and (_number(match[3]) or 0) <= 0):
                    raise ValueError('incompatible price basis')
                basis_unit = match[2].casefold()
                basis_unit = '개' if basis_unit in {'개','ea','입'} else basis_unit
                # Mass quotes remain approximate offer evidence. A generic
                # one-item quote can describe the whole fish listing, as in
                # reviewed Homeplus rows; it never establishes per-fish pricing.
                whole_listing = basis_unit == '개' and unit in {'마리','미'} and (match[1] is None or _number(match[1]) == 1)
                if basis_unit not in {'g','kg',unit} and not whole_listing:
                    raise ValueError('incompatible count price basis')
        if len(seen) != 1:
            raise ValueError('missing or contradictory structured evidence')
    except (ValueError, InvalidOperation):
        return None, ['approximate_count_quantity_conflict']
    return {'package_quantity': float(count), 'package_unit': unit, 'bundle_count': 1,
            'standard_unit': None, 'display_unit': title}, []


def uses_reviewed_residual_quantity_rules(title: str) -> bool:
    return (_text(title) in _REVIEWED_RESIDUAL177_PACKAGES
            or _text(title) == '스카치 방충망 보수테이프 롤타입 5X50cm')


def _reviewed_residual_package(payload, attrs, title, reviewed):
    quantity, unit, bundle = reviewed['normalized']
    normalized = (Decimal(str(quantity)), unit)
    source = (Decimal(str(reviewed['source'][0])), reviewed['source'][1])
    layers, visited = [], set()
    def visit(layer):
        if not isinstance(layer, Mapping):
            raise ValueError('invalid source layer')
        if id(layer) in visited:
            return
        visited.add(id(layer))
        layers.append(layer)
        for key in ('attributes', 'attrs'):
            if layer.get(key) is not None:
                visit(layer[key])
    try:
        visit(payload)
        visit(attrs)
        observed, supplied_counts = set(), []
        quantity_keys = ('package_quantity', 'pack_qty', 'packQty', 'pack_quantity', 'packQuantity')
        unit_keys = ('package_unit', 'pack_unit', 'packUnit', 'unitName')
        for layer in layers:
            quantities = [layer[k] for k in quantity_keys if layer.get(k) not in (None, '')]
            units = [layer[k] for k in unit_keys if layer.get(k) not in (None, '')]
            if bool(quantities) != bool(units):
                raise ValueError('incomplete source pair')
            for amount in quantities:
                amount = _number(amount)
                if amount is None:
                    raise ValueError('invalid source quantity')
                for alias in units:
                    alias = _text(alias).casefold()
                    factor, canonical = UNIT_ALIASES.get(alias, (1, alias))
                    identity = (amount * Decimal(str(factor)), canonical)
                    if identity not in {source, normalized}:
                        raise ValueError('changed source quantity')
                    observed.add(identity)
            for key in ('bundle_count', 'bundleCount'):
                if layer.get(key) not in (None, ''):
                    count = _number(layer[key])
                    if count is None or count <= 0 or count != count.to_integral_value():
                        raise ValueError('invalid count')
                    supplied_counts.append(count)
        if len(observed) != 1:
            raise ValueError('missing or contradictory source evidence')
        identity = next(iter(observed))
        counts = set(reviewed['source_counts']) if identity == source else {bundle}
        if len(set(supplied_counts)) > 1 or any(count not in counts for count in supplied_counts):
            raise ValueError('changed count')
        displays = {title}
        for amount, kind in {source, normalized}:
            displays.add(f'{amount:g}{kind}')
            for alias, (factor, canonical) in UNIT_ALIASES.items():
                if canonical == kind:
                    displays.add(f'{amount / Decimal(str(factor)):g}{alias}')
        for layer in layers:
            for key in ('display_unit', 'unit'):
                display = _text(layer.get(key))
                if display and display != title and display.casefold() not in displays:
                    raise ValueError('changed display')
            for key in ('unit_price_display', 'unit_price_basis', 'unit_price_basis_raw', 'unit_price_text', 'unit_price_unit'):
                display = _text(layer.get(key))
                if not display:
                    continue
                match = re.fullmatch(r'(?:(\d+(?:\.\d+)?)\s*)?(kg|g|mg|l|ml|cc|개|ea|봉|입|팩)\s*(?:당\s*([0-9,]+(?:\.[0-9]+)?)\s*원)?', display, re.I)
                piece_basis = bool(match and match[2].casefold() in reviewed.get('piece_price_units', ())
                                   and (match[1] is None or _number(match[1]) == 1))
                if not match or (not piece_basis and UNIT_ALIASES.get(match[2].casefold(), (1, match[2].casefold()))[1] != unit):
                    raise ValueError('incompatible price basis')
                if match[1] is not None and (_number(match[1]) is None or _number(match[1]) <= 0):
                    raise ValueError('invalid price basis quantity')
                if unit == 'g' and match[1] is None and key != 'unit_price_unit':
                    raise ValueError('missing measured basis quantity')
                if match[3] is not None and (_number(match[3]) is None or _number(match[3]) <= 0):
                    raise ValueError('invalid price quote')
    except (ValueError, InvalidOperation):
        return None, ['unit_reviewed_count_conflict']
    return {'package_quantity': float(quantity), 'package_unit': unit, 'bundle_count': bundle,
            'standard_unit': unit if unit in {'g', 'ml'} else None, 'display_unit': title}, []


def uses_reviewed_component_rules(title: str) -> bool:
    return _text(title) in _REVIEWED_COMPONENT_PACKAGES


def canonical_components(value: Any) -> list[dict[str, Any]]:
    """Canonical homogeneous content multiset, never an aggregate identity."""
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError('package_components must be a nonempty sequence')
    grouped = {}
    identities, dimensions = set(), set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != {'quantity', 'unit', 'count', 'identity', 'presentation'}:
            raise ValueError('invalid component fields')
        amount, count = _number(row['quantity']), _number(row['count'])
        alias = _text(row['unit']).casefold()
        factor, unit = UNIT_ALIASES.get(alias, (None, None))
        if amount is None or amount <= 0 or unit not in {'g', 'ml', '매'}:
            raise ValueError('invalid component measurement')
        if unit == '매' and amount != amount.to_integral_value():
            raise ValueError('nonintegral sheet component')
        amount *= Decimal(str(factor))
        if not Decimal(str(float(amount))).is_finite():
            raise ValueError('component measurement exceeds finite range')
        if count is None or count <= 0 or count != count.to_integral_value():
            raise ValueError('invalid component count')
        if not isinstance(row['identity'], str) or not isinstance(row['presentation'], str):
            raise ValueError('invalid component identity or presentation')
        identity, presentation = _text(row['identity']), _text(row['presentation'])
        if not identity:
            raise ValueError('missing component content identity')
        identities.add(identity)
        dimensions.add(unit)
        key = (amount, unit, identity, presentation)
        grouped[key] = grouped.get(key, 0) + int(count)
    if len(identities) != 1 or len(dimensions) != 1:
        raise ValueError('mixed content identities or dimensions')
    return [dict(quantity=float(amount), unit=unit, count=count, identity=identity, presentation=presentation)
            for (amount, unit, identity, presentation), count in sorted(grouped.items())]


def component_signature(package: Mapping[str, Any]) -> tuple | None:
    attrs = package.get('attributes', {})
    if attrs is None:
        return None
    if not isinstance(attrs, Mapping):
        raise ValueError('invalid package attributes')
    if 'package_components' not in attrs:
        return None
    return tuple((row['quantity'], row['unit'], row['count'], row['identity'], row['presentation'])
                 for row in canonical_components(attrs['package_components']))


def package_pricing_measure(package: Mapping[str, Any]) -> tuple[float, str] | None:
    from core.reviewed_source_evidence import package_comparison_reason
    if package_comparison_reason(package):
        return None
    signature = component_signature(package)
    if signature is not None:
        total = sum((Decimal(str(row[0])) * row[2] for row in signature), Decimal(0))
        if not Decimal(str(float(total))).is_finite():
            raise ValueError('component total exceeds finite range')
        return float(total), signature[0][1]
    unit = package.get('package_unit')
    if unit not in {'g', 'ml'}:
        from core.reviewed_source_evidence import valid_linear_contents_variant
        if unit != 'm' or not valid_linear_contents_variant(package):
            return None
    amount = _number(package.get('package_quantity'))
    count = _number(package.get('bundle_count', 1))
    if amount is None or amount <= 0 or count is None or count <= 0 or count != count.to_integral_value():
        raise ValueError('invalid scalar pricing measurement')
    return float(amount * count), unit


def _reviewed_component_package(payload, attrs, title, reviewed):
    components = canonical_components([
        dict(quantity=q, unit=u, count=c, identity=reviewed['identity'], presentation=p)
        for q, u, c, p in reviewed['components']
    ])
    source = (Decimal(str(reviewed['source'][0])), reviewed['source'][1])
    corrected = (Decimal(1), '세트')
    layers, seen = [], set()
    def visit(layer):
        if not isinstance(layer, Mapping):
            raise ValueError('invalid source attributes')
        if id(layer) in seen:
            return
        seen.add(id(layer))
        layers.append(layer)
        for key in ('attributes', 'attrs'):
            if key in layer and layer[key] is not None:
                visit(layer[key])
    try:
        visit(payload)
        visit(attrs)
        observed, counts = set(), []
        pairs = (('package_quantity', 'package_unit'), ('pack_qty', 'pack_unit'),
                 ('packQty', 'packUnit'), ('pack_quantity', 'pack_unit'), ('packQuantity', 'packUnit'))
        for layer in layers:
            if 'component_basis' in layer and layer['component_basis'] != 'reviewed_homogeneous_contents':
                raise ValueError('changed component basis')
            if 'standard_unit' in layer and layer['standard_unit'] != components[0]['unit']:
                raise ValueError('changed component pricing dimension')
            local = set()
            quantity_keys = {q for q, u in pairs}
            unit_keys = {u for q, u in pairs} | {'unitName'}
            quantities = [layer[k] for k in quantity_keys if layer.get(k) not in (None, '')]
            units = [layer[k] for k in unit_keys if layer.get(k) not in (None, '')]
            if bool(quantities) != bool(units):
                raise ValueError('incomplete source pair')
            for q, u in pairs:
                if layer.get(q) not in (None, '') and layer.get(u) in (None, '') and layer.get('unitName') in (None, ''):
                    raise ValueError('incomplete source alias pair')
            for u in unit_keys:
                if u == 'unitName':
                    continue
                if layer.get(u) not in (None, '') and not any(layer.get(q) not in (None, '') for q, paired_u in pairs if paired_u == u):
                    raise ValueError('incomplete source unit alias')
            # Inspect all alias combinations; a hidden alias cannot overwrite
            # an independently supplied measurement or count.
            for q in quantities:
                amount = _number(q)
                if amount is None or amount <= 0:
                    raise ValueError('invalid source quantity')
                for u in units:
                    alias = _text(u).casefold()
                    factor, unit = UNIT_ALIASES.get(alias, (1, alias))
                    identity = (amount * Decimal(str(factor)), unit)
                    if identity not in {source, corrected}:
                        raise ValueError('changed source measurement')
                    local.add(identity)
            observed.update(local)
            for key in ('bundle_count', 'bundleCount'):
                if layer.get(key) not in (None, ''):
                    count = _number(layer[key])
                    if count is None or count <= 0 or count != count.to_integral_value():
                        raise ValueError('invalid source count')
                    counts.append((count, local))
            if 'package_components' in layer and canonical_components(layer['package_components']) != components:
                raise ValueError('changed component multiset')
        if len(observed) != 1:
            raise ValueError('missing or conflicting source corroboration')
        identity = next(iter(observed))
        permitted_counts = set(reviewed['source_counts']) if identity == source else {1}
        for count, local in counts:
            if count not in permitted_counts:
                raise ValueError('changed source count')
        permitted_displays = {title, '1세트'}
        permitted_displays.add(f'{source[0]:g}{source[1]}')
        for count in reviewed['source_counts']:
            permitted_displays.update(f'{source[0]:g}{source[1]}{mark}{count}' for mark in ('x', '×', '*'))
        for alias, (factor, canonical) in UNIT_ALIASES.items():
            if canonical == source[1]:
                measure = source[0] / Decimal(str(factor))
                permitted_displays.add(f'{measure:g}{alias}')
                for count in reviewed['source_counts']:
                    permitted_displays.update((f'{measure:g}{alias}x{count}', f'{measure:g}{alias}×{count}', f'{measure:g}{alias}*{count}'))
        for layer in layers:
            for key in ('display_unit', 'unit'):
                display = _text(layer.get(key))
                if display and display != title and re.sub(r'\s+', '', display.casefold()) not in permitted_displays:
                    raise ValueError('changed source display')
            for key in ('unit_price_display', 'unit_price_basis', 'unit_price_basis_raw', 'unit_price_text', 'unit_price_unit'):
                display = _text(layer.get(key))
                if not display:
                    continue
                match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(kg|g|mg|l|ml|cc|매)\s*(?:당\s*([0-9,]+(?:\.[0-9]+)?)\s*원)?', display, re.I)
                if not match or _number(match[1]) is None or _number(match[1]) <= 0 or UNIT_ALIASES[match[2].casefold()][1] != components[0]['unit']:
                    raise ValueError('incompatible price basis')
                if match[3] is not None and (_number(match[3]) is None or _number(match[3]) <= 0):
                    raise ValueError('invalid price quote')
    except (ValueError, InvalidOperation, OverflowError):
        return None, ['unit_reviewed_component_conflict']
    return {'package_quantity': 1.0, 'package_unit': '세트', 'bundle_count': 1,
            'standard_unit': components[0]['unit'], 'display_unit': title,
            'attributes': {'package_components': components, 'component_basis': 'reviewed_homogeneous_contents'}}, []


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


def _reviewed_source_package(payload, attrs, title, boundary):
    """Exact reviewed correction, rejecting contradictions in either layer.

    Source purchased-count fields may coexist with the corrected content fields.
    No dose or secondary count is stripped from the retained display title.
    """
    quantity, unit, bundle, source_quantity, source_unit = boundary
    reviewed_cm_roll = title == '스카치 방충망 보수테이프 롤타입 5X50cm'
    normalized_identity = (Decimal(str(quantity)), unit)
    identities = {normalized_identity}
    if source_quantity is not None:
        identities.add((Decimal(str(source_quantity)), source_unit))
    displays = {title} | _REVIEWED_SOURCE_STRUCTURAL_DISPLAYS.get(title, set())
    if reviewed_cm_roll:
        displays |= {'50cm', '5X50cm', '5x50cm'}
    basis = _REVIEWED_SOURCE_DISPLAYS.get(title)
    def approved_price_quote(display):
        if not basis:
            return False
        # This exact-title exception recognizes a full offer quote, never a
        # bare measurement or arbitrary text. Its monetary value is mutable.
        quote = re.fullmatch(r"(\d+)\s*(g|ml|m)\s*당\s*([1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\s*원", display, re.I)
        return bool(quote and quote.group(1) + quote.group(2).casefold() == basis)
    for amount, kind in identities:
        displays.add(f"{amount:g}{kind}")
    measured_displays = {f"{amount:g}{kind}".casefold() for amount, kind in identities}
    for amount, kind in identities:
        for alias, (factor, canonical) in UNIT_ALIASES.items():
            if canonical == kind:
                measured_displays.add(f"{amount / Decimal(str(factor)):g}{alias}")
    observed_identities = []
    supplied_bundles = []
    layers = [payload, attrs]
    if reviewed_cm_roll:
        seen = set()
        for layer in layers:
            if not isinstance(layer, Mapping):
                return None, ['unit_reviewed_count_conflict']
            if id(layer) in seen:
                continue
            seen.add(id(layer))
            for key in ('attributes', 'attrs'):
                if layer.get(key) is not None:
                    layers.append(layer[key])
    for layer in layers:
        quantity_keys = ('package_quantity', 'pack_qty', 'packQty', 'pack_quantity', 'packQuantity') if reviewed_cm_roll else ('package_quantity', 'pack_qty')
        unit_keys = ('package_unit', 'pack_unit', 'packUnit', 'unitName') if reviewed_cm_roll else ('package_unit', 'pack_unit')
        quantities = [layer[key] for key in quantity_keys if layer.get(key) not in (None, "")]
        units = [_text(layer[key]).casefold() for key in unit_keys if layer.get(key) not in (None, "")]
        # Every supplied alias must agree, including aliases hidden by _first.
        layer_identities = []
        if bool(quantities) != bool(units):
            return None, ["unit_reviewed_count_conflict"]
        for kind in units:
            factor, canonical = UNIT_ALIASES.get(kind, (1, kind))
            if reviewed_cm_roll and kind == 'cm':
                factor, canonical = Decimal('0.01'), 'm'
            for amount in quantities:
                identity = (_number(amount) * factor if _number(amount) is not None else None, canonical)
                if identity not in identities:
                    return None, ["unit_reviewed_count_conflict"]
                layer_identities.append(identity)
        observed_identities.extend(layer_identities)
        for key in (('bundle_count', 'bundleCount') if reviewed_cm_roll else ('bundle_count',)):
            if layer.get(key) not in (None, ''):
                supplied_bundles.append((_number(layer[key]), layer_identities))
        for key in ("display_unit", "unit"):
            display = _text(layer.get(key))
            if display and display not in displays and display.casefold() not in measured_displays and not approved_price_quote(display):
                return None, ["unit_text_conflict"]
        if title in _REVIEWED_SOURCE_DISPLAYS:
            price_display = _text(layer.get("unit_price_display"))
            if price_display and not approved_price_quote(price_display):
                return None, ["unit_text_conflict"]
        if reviewed_cm_roll:
            for key in ('unit_price_display', 'unit_price_basis', 'unit_price_basis_raw', 'unit_price_text', 'unit_price_unit'):
                value = _text(layer.get(key))
                if not value:
                    continue
                quote = re.fullmatch(r'(?:(\d+(?:\.\d+)?)\s*)?(cm|m)\s*(?:당\s*([0-9,]+(?:\.[0-9]+)?)\s*원)?', value, re.I)
                if not quote or quote[1] is None and key != 'unit_price_unit':
                    return None, ['unit_text_conflict']
                if quote[1] is not None and (_number(quote[1]) is None or _number(quote[1]) <= 0):
                    return None, ['unit_text_conflict']
                if quote[3] is not None and (_number(quote[3]) is None or _number(quote[3]) <= 0):
                    return None, ['unit_text_conflict']
    if source_quantity is not None and not observed_identities:
        return None, ["reviewed_source_measurement_changed"]
    for count, local_identities in supplied_bundles:
        permitted = {bundle if identity == normalized_identity else _REVIEWED_SOURCE_ORIGINAL_BUNDLES.get(title, 1)
                     for identity in (local_identities or observed_identities)} or {bundle}
        if len(permitted) != 1 or count not in permitted:
            return None, ["bundle_count_conflict"]
    return {"package_quantity": float(quantity), "package_unit": unit, "bundle_count": bundle,
            "standard_unit": unit if unit in {"g", "ml"} else None, "display_unit": title}, []


def reviewed_price_basis_identity(payload: Mapping[str, Any], title: str) -> tuple[float | None, str | None] | None:
    """Stable key measurement for exact reviewed price-quote listings only."""
    title = _text(title)
    if not isinstance(payload, Mapping):
        return None
    # Source-bound reference-role repairs key on independent sold counts, or
    # an unknown content basis. Monetary reference text never enters identity.
    from core.reviewed_source_evidence import explicit_listing_package, nonmeasured_listing_review
    for candidate, field, role in (
        (explicit_listing_package(payload, {}, title), 'explicit_listing_quantity_review',
         'independent_count_after_price_reference_correction'),
        (nonmeasured_listing_review(payload, {}, title), 'nonmeasured_listing',
         'price_reference_not_sold_contents'),
    ):
        if candidate and candidate[0] and not candidate[1]:
            package = candidate[0]
            if package['attributes'][field].get('measurement_role') == role:
                return package['package_quantity'], package['package_unit']
    if title not in _REVIEWED_SOURCE_DISPLAYS:
        # A source-bound net-content declaration can have monetary quotes in
        # unit/display_unit. The exact reviewed contents, not quote money,
        # supply its stable lookup key; no unbound title obtains an exception.
        from core.reviewed_source_evidence import explicit_listing_package, _quoted_display_basis
        reviewed = explicit_listing_package(payload, {}, title)
        if not reviewed or not reviewed[0] or reviewed[1]:
            return None
        package = reviewed[0]
        evidence = package['attributes']['explicit_listing_quantity_review']['quantity_fields']
        if not any(key.rsplit('.', 1)[-1] in {'unit', 'display_unit'}
                   and _quoted_display_basis(value) is not None for key, value in evidence.items()):
            return None
        return package['package_quantity'], package['package_unit']
    layers = [payload, *[payload[key] for key in ("attributes", "attrs") if isinstance(payload.get(key), Mapping)]]
    package = None
    for layer in layers:
        package, issues = normalize_catalog_package(payload, layer, title)
        if not package or issues:
            return None
    return package["package_quantity"], package["package_unit"]


def physical_specification_role(category_id):
    category = str(category_id or '')
    if category.startswith('appliances.') or category == 'office.equipment.shredder.standard':
        return 'device_capacity_or_load'
    if category in {'household.security.storage.safe', 'household.outdoor.bags.cooler_tote'}:
        return 'storage_capacity_or_weight'
    if category == 'household.bath.textiles.towel':
        return 'textile_item_weight'
    if category == 'stationery.office.paper.copy':
        return 'paper_specification'
    if (category.startswith('household.kitchen.drinkware.') or category in {
            'household.kitchen.cookware.kettle', 'household.kitchen.coffee.drip_kettle',
            'household.kitchen.coffee.server', 'household.kitchen.storage.stainless_container',
            'household.kitchen.storage.food_bottle', 'household.kitchen.consumables.paper_cup',
            'household.kitchen.consumables.paper_cup_lid_set',
            'household.cleaning.waste.bin'}):
        return 'empty_vessel_capacity'
    return None


def physical_device_package(payload, attrs, title, category_id):
    """Separate declared physical specifications from sold pieces or sheets.

    Classification supplies the role; a word such as 세탁기 in detergent text
    cannot supply it. Retain literal capacity/weight for recollection without
    asserting paper g/m² or multiplying textile weight into sale contents.
    Consumable paper requires an independently declared sold sheet count.
    """
    category_role = physical_specification_role(category_id)
    if category_role is None:
        return None
    if not isinstance(payload, Mapping) or not isinstance(attrs, Mapping):
        return None, ['physical_device_evidence_conflict']
    from core.reviewed_source_evidence import listing_quantity_evidence, source_review_evidence, source_review_matches
    layers = [payload, attrs, *[payload[k] for k in ('attributes', 'attrs') if isinstance(payload.get(k), Mapping)]]
    identities, other_units = [], []
    for layer in layers:
        for qkey, ukey in (('package_quantity', 'package_unit'), ('pack_qty', 'pack_unit'),
                           ('packQty', 'packUnit'), ('packQuantity', 'packUnit')):
            q, u = layer.get(qkey), _text(layer.get(ukey)).casefold()
            if q in (None, '') and not u:
                continue
            factor, canonical = UNIT_ALIASES.get(u, (1, u))
            if canonical not in {'g', 'ml'}:
                other_units.append((q, u))
                continue
            amount = _positive(q)
            if amount is None:
                return None, ['physical_device_evidence_conflict']
            identities.append((Decimal(str(amount)) * Decimal(str(factor)), canonical))
    role = category_role
    if role in {'textile_item_weight', 'paper_specification'} and any(unit != 'g' for _, unit in identities):
        return None, ['physical_device_evidence_conflict']
    if role == 'empty_vessel_capacity' and (not identities or any(unit != 'ml' for _, unit in identities)):
        return None
    declared_counts = []
    if not identities and role in {'paper_specification', 'textile_item_weight'}:
        count_unit = '매' if role == 'paper_specification' else '개'
        for quantity, unit in other_units:
            amount = _positive(quantity)
            canonical = UNIT_ALIASES.get(unit, (1, unit))[1]
            if canonical != count_unit or amount is None or amount != int(amount):
                return None, ['physical_device_evidence_conflict']
            declared_counts.append(int(amount))
        if not declared_counts:
            return None
    elif not identities:
        # Providers can parse a model suffix (e.g. WF25DG8250BW2T) as
        # tea-bag counts. An appliance model is specification, never proof
        # of sold pieces. Require the actual alias value inside a model token.
        if role != 'device_capacity_or_load' or not any(u == 't' for _, u in other_units):
            return None
        if any(u != 't' for _, u in other_units):
            return None, ['physical_device_evidence_conflict']
        amounts = [_positive(q) for q, _ in other_units]
        if any(q is None for q in amounts) or len(set(amounts)) != 1:
            return None, ['physical_device_evidence_conflict']
        amount = format(amounts[0], 'f').rstrip('0').rstrip('.') if amounts[0] % 1 else str(int(amounts[0]))
        model = rf'(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*{re.escape(amount)}t(?![A-Za-z0-9])'
        if not re.search(model, _text(title), re.I) or re.search(r'(?<![A-Za-z0-9.])\d+(?:\.\d+)?\s*t(?![A-Za-z0-9])', _text(title), re.I):
            return None, ['physical_device_sold_count_unresolved']
        role = 'device_model_code'
    elif len(set(identities)) != 1 or other_units:
        return None, ['physical_device_evidence_conflict']
    source = source_review_evidence(payload)
    if not source_review_matches(source, source):
        return None, ['physical_device_source_unresolved']
    try:
        fields = listing_quantity_evidence(payload, attrs)
    except (ValueError, TypeError, OverflowError):
        return None, ['physical_device_evidence_conflict']
    title = _text(title)
    count_unit = '매' if role == 'paper_specification' else '개'
    if role in {'paper_specification', 'textile_item_weight'}:
        # Retain the literal g specification without asserting a g/m² ratio.
        # Only independently stated sheets/pieces can supply the sold amount.
        count_title = re.sub(r'(\d+(?:\.\d+)?\s*(?:kg|g))(?=\d+\s*(?:P|매|장|개))', r'\1 ', title, flags=re.I)
        units = r'(?:매|장)' if role == 'paper_specification' else r'(?:P|개입|개)'
        counts = re.findall(r'(?<![A-Za-z\d.])(\d+)\s*' + units + r'(?![A-Za-z가-힣\d])', count_title, re.I)
        extra_bundle = any(layer.get(k) not in (None, '', 1) for layer in layers for k in ('bundle_count', 'bundleCount'))
        unexplained_multiplier = (bool(re.search(r'[x×*]\s*\d', title, re.I))
                                  or bool(re.search(r'\d+\s*(?:팩|봉|박스|세트|묶음)', title)))
    elif role in {'empty_vessel_capacity', 'storage_capacity_or_weight'}:
        # PK/P declares primary vessel pieces. A bare multiplication count is
        # accepted only after a literal capacity, never for size/model digits.
        count_title = re.sub(r'(\d+(?:\.\d+)?\s*(?:ml|l))(?=\d+\s*(?:PK|P|개|입|잔|병))', r'\1 ', title, flags=re.I)
        matches = list(re.finditer(r'(?<![A-Za-z\d.])(\d+)\s*(?:PK|P|개입|개|대|입|잔|병)(?![A-Za-z가-힣\d])', count_title, re.I))
        counts = [match[1] for match in matches]
        recognized_starts = {match.start(1) for match in matches}
        for match in re.finditer(r'(?:ml|l)\s*[x×*]\s*(\d+)(?![A-Za-z가-힣\d])', count_title, re.I):
            if role == 'empty_vessel_capacity' and not any(part.start(1) == match.start(1) for part in matches):
                counts.append(match[1])
                recognized_starts.add(match.start(1))
        extra_bundle = any(layer.get(k) not in (None, '', 1, int(counts[0]) if len(counts) == 1 else None)
                           for layer in layers for k in ('bundle_count', 'bundleCount'))
        unexplained_multiplier = (any(match.start(1) not in recognized_starts
                                      for match in re.finditer(r'[x×*]\s*(\d+)', count_title, re.I))
                                  or bool(re.search(r'\d+\s*(?:팩|봉|박스|세트|조|묶음)', count_title)))
    else:
        counts = re.findall(r'(?<![A-Za-z\d.])(\d+)\s*(?:개입|개|대)(?![A-Za-z가-힣\d])', title)
        extra_bundle = any(layer.get(k) not in (None, '', 1) for layer in layers for k in ('bundle_count', 'bundleCount'))
        unexplained_multiplier = (bool(re.search(r'(?<![A-Za-z0-9])[x×*]\s*\d', title, re.I))
                                  or bool(re.search(r'\d+\s*(?:팩|봉|박스|세트|묶음)', title)))
    if len(counts) > 1 or _COUNT_RANGE_RE.search(title) or unexplained_multiplier:
        return None, ['physical_device_sold_count_unresolved']
    count = int(counts[0]) if counts else None
    if declared_counts and any(amount != count for amount in declared_counts):
        return None, ['physical_device_evidence_conflict']
    if count is not None and count < 1:
        return None, ['physical_device_sold_count_unresolved']
    if extra_bundle or (role == 'paper_specification' and count is None):
        # Paper is consumable: its unknown sheet count cannot use the physical
        # non-consumable NULL allowance.
        return None, ['physical_device_sold_count_unresolved']
    if role == 'empty_vessel_capacity' and count is not None:
        # An existing count parser may already have separated capacity from
        # sold pieces. Keep its scalar identity; a new role proof is needed
        # only when correcting a capacity/unknown quantity representation.
        # Omitting category here prevents re-entry into this role branch.
        existing, existing_issues = normalize_catalog_package(payload, attrs, title)
        if (existing and not existing_issues
                and existing.get('package_quantity') == count
                and existing.get('package_unit') == '개'
                and existing.get('bundle_count') == 1
                and existing.get('standard_unit') is None):
            return existing, []
    # A pinned category-only refinement must not regenerate a proven physical
    # specification's identity. Keep the original proof leaf only where its
    # physical role is unchanged and this exact source/title was reviewed.
    from core.catalog_identity import reviewed_registry, reviewed_leaf_compatible
    original_leaves = {review['old_leaf'] for review in reviewed_registry().get('leaf_reviews', [])
                       if review['new_leaf'] == category_id
                       and physical_specification_role(review['old_leaf']) == category_role
                       and reviewed_leaf_compatible(review['old_leaf'], category_id,
                                                    title, source['source_urls'])}
    proof_category = next(iter(original_leaves)) if len(original_leaves) == 1 else category_id
    proof = {'title': title, 'category_id': proof_category, 'required_source': source,
             'quantity_fields': fields, 'specification_role': role,
             'sold_piece_count': count}
    if count_unit != '개':
        proof['sold_count_unit'] = count_unit
    return {'package_quantity': float(count) if count is not None else None,
            'package_unit': count_unit if count is not None else None, 'bundle_count': 1,
            'standard_unit': None, 'display_unit': title,
            'attributes': {'quantity_basis': 'physical_device_specification_v1',
                           'physical_device_specification': proof}}, []


def valid_physical_device_variant(variant):
    if not isinstance(variant, Mapping):
        return False
    attrs = variant.get('attributes') or {}
    proof = attrs.get('physical_device_specification') if isinstance(attrs, Mapping) else None
    if not isinstance(proof, Mapping) or attrs.get('quantity_basis') != 'physical_device_specification_v1':
        return False
    from core.reviewed_source_evidence import source_review_matches
    count = proof.get('sold_piece_count')
    expected_role = physical_specification_role(proof.get('category_id'))
    valid = (expected_role is not None
            and (proof.get('specification_role') == expected_role
                 or expected_role == 'device_capacity_or_load' and proof.get('specification_role') == 'device_model_code')
            and bool(proof.get('title')) and isinstance(proof.get('quantity_fields'), Mapping)
            and source_review_matches(proof.get('required_source', {}), proof.get('required_source', {}))
            and (count is None or isinstance(count, int) and not isinstance(count, bool) and count > 0)
            and (expected_role != 'paper_specification' or count is not None)
            and variant.get('package_quantity') == count
            and proof.get('sold_count_unit', '개') == ('매' if expected_role == 'paper_specification' else '개')
            and variant.get('package_unit') == (proof.get('sold_count_unit', '개') if count is not None else None)
            and variant.get('bundle_count') == 1 and variant.get('standard_unit') is None
            and not attrs.get('package_components') and not attrs.get('source_components'))
    if not valid:
        return False
    # Count and role must follow from the retained literal evidence, not just
    # from agreement between two mutable count fields in an incoming bundle.
    source, nested = {}, {}
    for name, value in {**proof['required_source'].get('source_fields', {}),
                        **proof['quantity_fields']}.items():
        if not isinstance(name, str):
            return False
        target, key = (nested, name[11:]) if name.startswith('attributes.') else (source, name)
        if key in {'unit_price_display', 'unit_price_basis', 'unit_price_basis_raw', 'unit_price_text', 'unit_price_unit'} and isinstance(value, list) and len(value) == 2:
            value = f'{value[0] or ""}{value[1]}'
        target[key] = value
    urls = proof['required_source']['source_urls']
    if len(urls) > 6:
        return False
    for index, url in enumerate(urls):
        (source if index < 3 else nested)[('canonical_url', 'detail_url', 'source_url')[index % 3]] = url
    source['attributes'] = nested
    derived = physical_device_package(source, nested, proof['title'], proof['category_id'])
    return bool(derived and not derived[1] and derived[0]
                and derived[0].get('attributes', {}).get('physical_device_specification') == proof)


def additive_battery_pack_specification(title, category_id):
    """Retain literal fixed-pack addition, independently of purchase benefits.

    A terminal count unit names cells; `기획팩` alone names a pack, not its
    counted entity. Neither quoted money nor an unqualified N+N badge bridges
    that missing unit. Source-bound reviewed records approve its interpretation.
    """
    if category_id != 'household.utilities.batteries.alkaline':
        return None
    title = _text(title)
    matches = list(re.finditer(r'(?<![\d.])(\d+)\s*\+\s*(\d+)\s*(개입|입|기획팩)(?![가-힣\d])', title))
    if len(matches) != 1:
        return None
    match = matches[0]
    a, b = int(match[1]), int(match[2])
    residual = title[:match.start()] + title[match.end():]
    if (not a or not b or re.search(r'[+~～×*]|[xX]\s*\d|선택|랜덤|혼합|증정|덤', residual)
            or re.search(r'\d+\s*(?:입|개|팩|세트|kg|g|ml|l)(?![A-Za-z])', residual, re.I)):
        return None
    unit = '입' if match[3] in {'입', '개입'} else None
    return {'literal': match[0], 'expression': f'{a}+{b}', 'terms': [a, b],
            'count_unit': unit, 'counted_entity': 'battery_cells' if unit else None,
            'total_count': a + b if unit else None,
            'scope': 'fixed_pack_contents' if unit else 'pack_count_unit_unverified'}


def normalize_catalog_package(payload: Mapping[str, Any], attrs: Mapping[str, Any], title: str, *, category_id=None) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(payload, Mapping) or not isinstance(attrs, Mapping):
        return None, ['unit_source_invalid']
    title = _text(title)
    from core.reviewed_source_evidence import (source_observation_eligibility_review,
                                              nonmeasured_listing_review, explicit_listing_package,
                                              count_interval_listing_package, source_component_listing_package)
    eligibility = source_observation_eligibility_review(payload, attrs, title)
    if eligibility is not None and eligibility[1]:
        return None, eligibility[1]
    vector = source_component_listing_package(payload, attrs, title)
    if vector is not None:
        return vector
    if re.search(r'(?:\+\s*(?:쇼퍼백|쇼핑백)(?!\s*(?:미포함|별도|없음|미동봉))|(?:쇼퍼백|쇼핑백)\s*(?:동봉|포함|증정))', title):
        # Declared edible contents cannot price a whole food/carrier-bag set.
        # Approved vectors above retain known food amounts and physical NULLs.
        return None, ['mixed_package_unresolved']
    interval = count_interval_listing_package(payload, attrs, title)
    if interval is not None:
        return interval
    explicit = explicit_listing_package(payload, attrs, title)
    if explicit is not None:
        if (explicit[0] and explicit[0]['attributes'].get('explicit_listing_quantity_review', {}).get('measurement_role') == 'declared_additive_battery_pack'
                and category_id is not None and category_id != 'household.utilities.batteries.alkaline'):
            return None, ['additive_pack_category_conflict']
        return explicit
    nonmeasured = nonmeasured_listing_review(payload, attrs, title)
    if nonmeasured is not None:
        if (nonmeasured[0] and nonmeasured[0]['attributes']['nonmeasured_listing'].get('measurement_role') == 'declared_additive_battery_pack'
                and category_id is not None and category_id != 'household.utilities.batteries.alkaline'):
            return None, ['additive_pack_category_conflict']
        # A failed source-bound vessel review remains a capacity rejection.
        # Keep that existing diagnostic; a valid bound review still wins above.
        if nonmeasured[0] is None and title in CAPACITY_NOT_CONTENT_TITLES and any(
            UNIT_ALIASES.get(_text(layer.get(key)).casefold(), (1, None))[1] == "ml"
            for layer in (payload, attrs) for key in ("package_unit", "pack_unit")
        ):
            return None, ["unit_container_capacity_not_contents"]
        return nonmeasured
    if additive_battery_pack_specification(title, category_id) is not None:
        # A partial/default crawler quantity cannot approve a new fixed pack.
        # Explicit/nonmeasured source reviews above retain the original fields.
        return None, ['additive_pack_source_review_required']
    physical = physical_device_package(payload, attrs, title, category_id)
    if physical is not None:
        return physical
    if re.search(r'유리컵\s*기획팩', title):
        # A separately included glass is not edible mass. Only an explicitly
        # source-bound complete vector above can establish this gift's contents.
        return None, ['mixed_package_unresolved']
    if isinstance(category_id, str) and category_id.startswith("services.facility."):
        # Occupancy is not the number of sold service entitlements. An explicit
        # source-bound entitlement review above may establish that separately.
        if any(_text(layer.get(key)).casefold() in {"인", "인분"}
               for layer in (payload, attrs) for key in ("package_unit", "pack_unit", "packUnit", "unitName", "unit")):
            return None, ["unit_service_occupancy_not_entitlement"]
    if uses_approximate_measurement_rules(title):
        return _approximate_mass_count_package(payload, attrs, title)
    if title in _REVIEWED_RESIDUAL177_PACKAGES:
        return _reviewed_residual_package(payload, attrs, title, _REVIEWED_RESIDUAL177_PACKAGES[title])
    if title in _REVIEWED_COMPONENT_PACKAGES:
        return _reviewed_component_package(payload, attrs, title, _REVIEWED_COMPONENT_PACKAGES[title])
    if title in _REVIEWED_SOURCE_PACKAGES:
        return _reviewed_source_package(payload, attrs, title, _REVIEWED_SOURCE_PACKAGES[title])
    if title in CAPACITY_NOT_CONTENT_TITLES and any(
        UNIT_ALIASES.get(_text(layer.get(key)).casefold(), (1, None))[1] == "ml"
        for layer in (payload, attrs) for key in ("package_unit", "pack_unit")
    ):
        return None, ["unit_container_capacity_not_contents"]
    # Exact reviewed count, not a generic interpretation of Korean 매입 or
    # an assumed singleton. Inspect both layers so conflicting attrs cannot hide.
    if title == "simplus 국물팩(소) 50매입":
        for layer in (payload, attrs):
            for key in ("package_quantity", "pack_qty"):
                if layer.get(key) not in (None, "") and _number(layer[key]) != 50:
                    return None, ["unit_reviewed_count_conflict"]
            for key in ("package_unit", "pack_unit"):
                if _text(layer.get(key)).casefold() not in {"", "매", "매입", "개", "ea"}:
                    return None, ["unit_reviewed_count_conflict"]
            if layer.get("bundle_count") not in (None, "") and _number(layer["bundle_count"]) != 1:
                return None, ["bundle_count_conflict"]
            for key in ("display_unit", "unit"):
                if _text(layer.get(key)) not in {"", title, "50매입", "50매", "50개"}:
                    return None, ["unit_text_conflict"]
        return {"package_quantity": 50.0, "package_unit": "개", "bundle_count": 1,
                "standard_unit": None, "display_unit": title}, []
    if (sheet_roll := _sheet_roll_package(payload, attrs, title)) is not None:
        return sheet_roll
    issues: list[str] = []
    quantity = _positive(_first((payload, attrs), ("package_quantity", "pack_qty")))
    unit = _text(_first((payload, attrs), ("package_unit", "pack_unit"))).casefold()
    if title in REVIEWED_CORRUPTED_MEASURED:
        bad_quantity,bad_unit,bad_display,content,content_unit,count=REVIEWED_CORRUPTED_MEASURED[title]
        display=_text(_first((payload, attrs), ("display_unit", "unit")))
        actual_identity=(float(quantity), UNIT_ALIASES.get(unit,(1,unit))[1]) if quantity is not None else None
        bad_identity=(float(bad_quantity), UNIT_ALIASES.get(bad_unit,(1,bad_unit))[1])
        if actual_identity!=bad_identity or display!=bad_display:
            return None,["reviewed_source_measurement_changed"]
        return {"package_quantity": float(content), "package_unit": content_unit, "bundle_count": count,
                "standard_unit": content_unit, "display_unit": title}, []
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
    if re.search(r'종이컵|다회용투명(?:소주)?컵', title):
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
    independent, independent_issues = _separate_measured_count(payload, attrs, title, category_id)
    if independent_issues:
        return None, independent_issues
    parsed_candidates = ([independent] if independent else [parsed for text in (title,) if (parsed := parse_package_quantity(text))])
    if display_unit and (display_parsed := parse_package_quantity(display_unit)):
        parsed_candidates.append(display_parsed)
    if independent and count_number == 1:
        # This schema default is not another outer pack. Only this source-
        # validated independent-count syntax may replace it; x-chains retain
        # the existing stricter explicit bundle agreement below.
        count_number = None
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
