"""Pure source/quantity contract shared by recollection, export and offer intake.

The existing runtime validator is kept here unchanged so price writes do not
trust client-provided matching hits or duplicate the guarded source rules.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import math
import re
import unicodedata
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from core.match_key import NO_BRAND_SENTINEL, build_match_key, normalize_pack_identity
from core.product_units import parse_package_quantity
from core.reviewed_source_evidence import (source_review_evidence, source_review_matches,
    nonmeasured_listing_review, valid_nonmeasured_variant, explicit_listing_package,
    valid_explicit_listing_variant, valid_linear_contents_variant, source_observation_eligibility_review,
    count_interval_listing_package, valid_count_interval_variant, listing_title_history,
    valid_listing_title_history, source_component_listing_package, valid_source_component_variant)
from core.catalog_quantity import (normalize_catalog_package, uses_reviewed_quantity_rules,
    component_signature, reviewed_price_basis_identity, uses_reviewed_component_rules, uses_reviewed_residual_quantity_rules,
    uses_approximate_measurement_rules, physical_device_package, valid_physical_device_variant)

def _extract_str(row: dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None



_COUNT_UNITS = {"ea", "개", "개입", "봉지", "인분", "세트", "마리", "회분", "구", "입", "팩", "봉", "병", "캔", "손", "매", "롤", "포", "장", "족", "통", "인", "p", "t", "모", "두", "알", "미", "포기", "단", "망", "박스", "쌍", "켤레"}
_COUNT_UNIT_PATTERN = "(?:" + "|".join(re.escape(unit) for unit in sorted(_COUNT_UNITS, key=len, reverse=True)) + ")"
_COUNT_RANGE_RE = re.compile(rf"(?<![\d.])\d+(?:\.\d+)?\s*(?:{_COUNT_UNIT_PATTERN})?\s*[~～〜–—-]\s*\d+(?:\.\d+)?\s*{_COUNT_UNIT_PATTERN}", re.I)
_UNIT_ALIASES = {"킬로그램": "kg", "그램": "g", "리터": "l", "밀리리터": "ml", "미리리터": "ml"}
_QUANTITY_KEYS = ("package_quantity", "pack_qty", "packQty", "pack_quantity", "packQuantity")
_UNIT_KEYS = ("package_unit", "pack_unit", "packUnit", "unitName", "unit")


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    value = float(number)
    return value if math.isfinite(value) else None


def _package_identity(quantity: Any, unit: Any) -> tuple[float, str] | None:
    quantity = _positive_number(quantity)
    unit = str(unit or "").strip().lower()
    unit = _UNIT_ALIASES.get(unit, unit)
    if unit == "개입":
        unit = "ea"
    if quantity is None or unit not in {"kg", "g", "mg", "l", "ml", "cc", "m", *_COUNT_UNITS}:
        return None
    # Catalog T means a count (tea bags/sticks), not the mass unit ton accepted
    # by the general match-key canonicalizer. Keep all count dimensions intact.
    if unit in _COUNT_UNITS and unit not in {"ea", "개"}:
        return quantity, unit
    return normalize_pack_identity(quantity, unit)


def _source_package(row: dict[str, Any], category_id: str | None = None) -> tuple[tuple[float, str, int] | None, str | None]:
    """Require structured quantity/unit; title text may disprove, not invent it.

    Old DiscountItem rows omitted bundle_count but retained explicit ×N in
    display_unit. Restore only that explicit multiplier, checking all evidence.
    """
    if not isinstance(row, Mapping):
        return None, 'normalized_unit_unresolved'
    layers = [row, *[row[key] for key in ("attributes", "attrs") if isinstance(row.get(key), Mapping)]]
    title = _extract_str(row, ["source_title", "name", "productName", "itemName", "prdtName", "goodsName", "title"]) or ""
    eligibility = source_observation_eligibility_review(row, {}, title)
    if eligibility is not None and eligibility[1]:
        return None, 'normalized_variant_conflict'
    vector = source_component_listing_package(row, {}, title)
    if vector is not None:
        package, issues = vector
        return ((1, '세트', 1), None) if package and not issues else (None, 'normalized_variant_conflict')
    interval = count_interval_listing_package(row, {}, title)
    if interval is not None:
        package, issues = interval
        if package and not issues:
            return (None, 'ea' if package['package_unit'] == '개' else package['package_unit'], 1), None
        reason = ('normalized_variant_conflict' if source_review_evidence(row)['source_urls']
                  else 'normalized_unit_unresolved')
        return None, reason
    explicit = explicit_listing_package(row, {}, title)
    if explicit is not None:
        package, issues = explicit
        if not package or issues:
            return None, 'normalized_variant_conflict'
        from core.reviewed_source_evidence import source_parent_selection, source_outer_set_count, source_nonexact_contents_specification, source_entitlement_specification, source_partial_retail_specification
        if source_parent_selection(package):
            return None, 'source_option_selection_unverified'
        if source_outer_set_count(package):
            return None, 'source_outer_set_contents_unverified'
        if source_nonexact_contents_specification(package):
            return None, 'source_exact_contents_unverified'
        if source_entitlement_specification(package):
            return None, 'source_entitlement_scope_unverified'
        if source_partial_retail_specification(package):
            return None, 'source_whole_sale_scope_unverified'
        canonical = _package_identity(package['package_quantity'],package['package_unit'])
        return (*canonical,package['bundle_count']), None
    nonmeasured = nonmeasured_listing_review(row, {}, title)
    if nonmeasured is not None:
        package, issues = nonmeasured
        return ((None, None, package['bundle_count']), None) if package and not issues else (None, 'normalized_variant_conflict')
    reviewed_quantity = uses_reviewed_quantity_rules(title)
    attrs = {key: value for layer in layers[1:] for key, value in layer.items()}
    if isinstance(category_id, str) and category_id.startswith("services.facility."):
        _, issues = normalize_catalog_package(row, attrs, title, category_id=category_id)
        if any(issue.startswith("unit_service_") for issue in issues):
            return None, "normalized_variant_conflict"
    if uses_reviewed_component_rules(title) or uses_reviewed_residual_quantity_rules(title) or uses_approximate_measurement_rules(title):
        package, issues = normalize_catalog_package(row, {}, title, category_id=category_id)
        if not package or issues:
            return None, 'normalized_variant_conflict'
        canonical = _package_identity(package['package_quantity'], package['package_unit'])
        return (*canonical, package['bundle_count']), None
    quantities = [layer[key] for layer in layers for key in _QUANTITY_KEYS if layer.get(key) not in (None, "")]
    units = [layer[key] for layer in layers for key in _UNIT_KEYS if layer.get(key) not in (None, "")]
    if not quantities or not units:
        if reviewed_quantity:
            package, issues = normalize_catalog_package(row, attrs, title, category_id=category_id)
            if package and not issues:
                canonical = _package_identity(package['package_quantity'], package['package_unit'])
                return (*canonical, package['bundle_count']), None
        return None, "normalized_unit_unresolved"
    identity = next((_package_identity(quantities[0], unit) for unit in units if _package_identity(quantities[0], unit)), None)
    if identity is None:
        return None, "normalized_unit_unresolved"
    # Distinct structured values are conflicts, including a stale legacy pack
    # field alongside a newer package field. Display strings (120ml×24) are
    # validated below rather than being mistaken for a unit vocabulary value.
    structured = []
    for layer in layers:
        qty = next((layer[key] for key in _QUANTITY_KEYS if layer.get(key) not in (None, "")), None)
        unit = next((layer[key] for key in _UNIT_KEYS if layer.get(key) not in (None, "")), None)
        if qty is not None and unit is not None:
            pair = _package_identity(qty, unit)
            if pair is None:
                return None, "normalized_unit_unresolved"
            structured.append(pair)
        for qty_key, unit_key in (("package_quantity", "package_unit"), ("pack_qty", "pack_unit"), ("packQty", "packUnit"), ("pack_quantity", "pack_unit"), ("packQuantity", "packUnit")):
            if layer.get(qty_key) not in (None, ""):
                pair = _package_identity(layer[qty_key], layer.get(unit_key) or unit)
                if pair is None:
                    return None, "normalized_unit_unresolved"
                structured.append(pair)
    if any(pair != identity for pair in structured):
        return None, "normalized_variant_conflict"

    if reviewed_quantity:
        # Preserve independent structured-field conflicts above. Use the same
        # bounded content/container/roll repairs as staging only after exact
        # reviewed source identity is checked by _normalized_source_reason.
        explicit_counts = [layer['bundle_count'] for layer in layers if layer.get('bundle_count') not in (None, '')]
        if any((count := _positive_number(value)) is None or not count.is_integer() for value in explicit_counts):
            return None, 'normalized_unit_unresolved'
        if len({int(float(value)) for value in explicit_counts}) > 1:
            return None, 'normalized_variant_conflict'
        # The shared validator must see original purchased-count units too
        # (e.g. 개입). Canonicalize its verified result, not its source evidence.
        package, issues = normalize_catalog_package(row, attrs, title, category_id=category_id)
        if not package or issues:
            return None, 'normalized_variant_conflict'
        expected = (package['package_quantity'], package['package_unit'], package['bundle_count'])
        for layer in layers:
            for field in ('display_unit', 'unit'):
                value = layer.get(field)
                if value and parse_package_quantity(str(value)):
                    candidate, conflicts = normalize_catalog_package({**row, 'display_unit': value}, attrs, title, category_id=category_id)
                    if not candidate or conflicts or (candidate['package_quantity'], candidate['package_unit'], candidate['bundle_count']) != expected:
                        return None, 'normalized_variant_conflict'
        canonical = _package_identity(package['package_quantity'], package['package_unit'])
        return (*canonical, package['bundle_count']), None

    texts = list(dict.fromkeys(str(layer[key]) for layer in layers for key in ("source_title", "name", "title", "display_unit", "unit") if layer.get(key)))
    parsed = [value for text_value in texts if (value := parse_package_quantity(text_value))]
    counts = []
    for layer in layers:
        if layer.get("bundle_count") not in (None, ""):
            count = _positive_number(layer["bundle_count"])
            if count is None or not count.is_integer():
                return None, "normalized_unit_unresolved"
            counts.append(int(count))
    counts.extend(int(value["bundle_count"]) for value in parsed if value.get("bundle_count"))
    if len(set(counts)) > 1:
        return None, "normalized_variant_conflict"
    if identity[1] not in {"g", "ml"} and any(_COUNT_RANGE_RE.search(text_value) for text_value in texts):
        return None, "normalized_unit_unresolved"
    for text_value in texts:
        # Keep the initial catalog's review boundary on recollection too:
        # the convenience parser only reads the first factor of ×3×2.
        if len(re.findall(r"[x×*]\s*\d+", text_value, re.I)) > 1:
            return None, "normalized_variant_conflict"
        if re.search(r"(?<![A-Za-z0-9])[x×*]\s*\d+", text_value, re.I) and not (parse_package_quantity(text_value) or {}).get("bundle_count"):
            return None, "normalized_variant_conflict"
        if "+" in text_value and len(re.findall(rf"(?<![A-Za-z0-9])\d+\s*{_COUNT_UNIT_PATTERN}(?![A-Za-z])", text_value, re.I)) > 1:
            return None, "normalized_variant_conflict"
    count = counts[0] if counts else 1
    allowed = {identity, (round(identity[0] * count, 6), identity[1])}
    for value in parsed:
        pair = _package_identity(value["package_quantity"], value["package_unit"])
        if pair is not None and pair not in allowed:
            return None, "normalized_variant_conflict"
        if value.get("bundle_count") and pair != identity:
            return None, "normalized_variant_conflict"
    # The shared convenience parser picks one expression. Inspect every weight
    # or volume expression too, so mixed/refill packages cannot hide a conflict.
    for text_value in texts:
        measures = []
        for match in re.finditer(r"(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(kg|킬로그램|그램|g|ml|밀리리터|미리리터|리터|l)(?![A-Za-z])", text_value, re.I):
            if re.match(r"\s*(?:당|기준|/\s*(?:당|[0-9,]+\s*원|원))", text_value[match.end():]):
                continue
            measures.append(_package_identity(match.group(1), match.group(2)))
        if any(measure not in allowed for measure in measures) or ("+" in text_value and len(measures) > 1):
            return None, "normalized_variant_conflict"
    return (*identity, count), None


def _homeplus_declared_url_consistent(row: dict[str, Any], listing: dict[str, Any], native: str) -> bool:
    """Reject contradictory native/store declarations without using price as identity."""
    layers = [row, *[row[field] for field in ("attributes", "attrs") if isinstance(row.get(field), Mapping)]]
    def store(value):
        text = str(value).strip().upper()
        return "EXP" if text in {"EXP", "EXPRESS"} else text
    declared_stores = {store(layer["storeType"]) for layer in layers if layer.get("storeType") not in (None, "")}
    try:
        expected = parse_qs(urlsplit(listing.get("source_url") or "").query, keep_blank_values=True)
        expected_stores = {store(value) for value in expected.get("storeType", [])}
        for source_url in source_review_evidence(row)["source_urls"]:
            parts = urlsplit(source_url)
            if parts.scheme not in {"http", "https"} or parts.hostname not in {
                    "homeplus.co.kr", "www.homeplus.co.kr", "mfront.homeplus.co.kr", "front.homeplus.co.kr"}:
                return False
            query = parse_qs(parts.query, keep_blank_values=True)
            if "itemNo" in query and query["itemNo"] != [native]:
                return False
            actual_stores = {store(value) for value in query.get("storeType", [])}
            if len(actual_stores) > 1 or (actual_stores and expected_stores and actual_stores != expected_stores):
                return False
            declared_stores.update(actual_stores)
    except (ValueError, TypeError):
        return False
    return len(declared_stores) <= 1 and (not declared_stores or not expected_stores or declared_stores == expected_stores)


def _normalized_source_reason(row: dict[str, Any], key: str, entry: dict[str, Any], variants: dict[str, dict[str, Any]]) -> str | None:
    variant_id = str(entry.get("public_variant_id") or "")
    variant = variants.get(variant_id)
    if variant is None:
        return "normalized_variant_unavailable"
    if str(variant.get("public_product_id")) != str(entry.get("public_product_id")):
        return "normalized_variant_product_conflict"
    # Raw names are authoritative. A stale normalized_name/name_core or stored
    # match_key must not conceal a changed source title on the next collection.
    names = [_extract_str(row, [field]) for field in ("source_title", "name", "productName", "itemName", "prdtName", "goodsName", "title")]
    names = [name for name in names if name]
    if not names:
        return "normalized_source_name_unresolved"
    listings = variant.get("source_listings") or []
    variant_attrs = variant.get('attributes')
    if isinstance(variant_attrs, Mapping):
        review = variant_attrs.get('explicit_listing_quantity_review')
        if isinstance(review, Mapping) and 'source_parent_selection' in review:
            from core.reviewed_source_evidence import source_parent_selection
            return ('source_option_selection_unverified' if source_parent_selection(variant)
                    else 'normalized_source_evidence_conflict')
    history = variant_attrs.get('source_title_history') if isinstance(variant_attrs, dict) else None
    if isinstance(variant_attrs, dict) and any(field in variant_attrs for field in
            ('source_evidence_reviews', 'nonmeasured_listing', 'count_interval_listing', 'source_title_history', 'source_component_listing')) and 'source_listings' not in variant:
        return 'normalized_source_listing_unavailable'
    if "source_listings" in variant:
        layers = [row, *[row[field] for field in ("attributes", "attrs") if isinstance(row.get(field), dict)]]
        mart = next((_extract_str(layer, ["source", "source_name", "mart"]) for layer in layers if _extract_str(layer, ["source", "source_name", "mart"])), "")
        mart = {"이마트": "emart", "ssg": "emart", "홈플러스": "homeplus", "롯데마트": "lottemart", "코스트코": "costco"}.get(mart, mart)
        source_key = next((_extract_str(layer, ["source_record_key", "source_product_id", "mart_native_code", "product_id", "id"]) for layer in layers if _extract_str(layer, ["source_record_key", "source_product_id", "mart_native_code", "product_id", "id"])), None)
        matches = [listing for listing in listings if listing["source_name"] == mart and str(listing["source_record_key"]) == source_key]
        if len(matches) != 1 or not matches[0].get("source_title"):
            return "normalized_source_listing_unavailable"
        def source_name(value):
            return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip().casefold()
        expected_name = source_name(matches[0]["source_title"])
        if history is None and valid_physical_device_variant(variant):
            # Physical source title history is additive matching evidence, not
            # a mutation of the historical variant's specification attributes.
            candidate = listing_title_history(mart, source_key, row, names[0])
            proof = variant_attrs['physical_device_specification']
            if (candidate is not None and valid_listing_title_history(candidate)
                    and candidate['category_id'] == proof['category_id']
                    and proof['title'] in {alias['title'] for alias in candidate['aliases']}):
                history = candidate
        if history is not None:
            if (not valid_listing_title_history(history)
                    or history['source_name'] != mart or history['source_record_key'] != source_key
                    or expected_name not in {source_name(alias['title']) for alias in history['aliases']}
                    or any(listing_title_history(mart, source_key, row, name) != history for name in names)):
                return 'normalized_source_evidence_conflict'
        elif any(source_name(name) != expected_name for name in names):
            return "normalized_source_name_conflict"
        attrs = variant.get('attributes')
        if isinstance(attrs, dict) and 'source_evidence_reviews' in attrs:
            reviews = attrs['source_evidence_reviews']
            if not isinstance(reviews, list) or not reviews or any(not isinstance(review, dict) for review in reviews):
                return 'normalized_source_evidence_conflict'
            bound = [review for review in reviews if review.get('source_name') == mart
                     and str(review.get('source_record_key')) == source_key]
            # Several independently reviewed contexts may belong to one SKU.
            # Accept exactly one complete URL/native-field pair, never a mix.
            if not bound or any(not source_review_matches(review, review) for review in bound):
                return 'normalized_source_evidence_conflict'
            matched = [review for review in bound
                       if source_review_matches(source_review_evidence(row), review)]
            if len(matched) != 1:
                return 'normalized_source_evidence_conflict'
    else:
        # Older manually reviewed normalized entries may lack listing evidence.
        # They can use only their exact reviewed key name, never a guessed alias.
        key_name = key.split("|")[1] if len(key.split("|")) == 4 else None
        if any(build_match_key(None, name, None, None).split("|")[1] != key_name for name in names):
            return "normalized_source_name_conflict"
    if isinstance(variant_attrs, dict) and 'source_identity_context' in variant_attrs:
        from core.reviewed_source_evidence import source_identity_context_review, valid_source_identity_context
        proof = variant_attrs['source_identity_context']
        if (not isinstance(proof, dict) or 'source_listings' not in variant
                or not valid_source_identity_context(variant, matches[0], proof.get('category_id'))
                or any(source_identity_context_review(mart, source_key, row, name) != proof for name in names)):
            return 'normalized_source_evidence_conflict'
    if isinstance(variant_attrs, dict) and 'physical_device_specification' in variant_attrs:
        proof = variant_attrs['physical_device_specification']
        title = names[0]
        review = physical_device_package(row, {}, title, proof.get('category_id') if isinstance(proof, dict) else None)
        actual_proof = review[0]['attributes']['physical_device_specification'] if review and review[0] and not review[1] else None
        if (actual_proof and history is not None and isinstance(proof, Mapping)
                and history.get('category_id') == proof.get('category_id')
                and proof.get('title') in {alias['title'] for alias in history['aliases']}):
            # The exact registry history was source/quantity checked above.
            # Keep the historical primary proof and every non-title field:
            # an approved title is not permission to change count or purpose.
            actual_proof = {**actual_proof, 'title': proof['title']}
        if (not valid_physical_device_variant(variant) or not review or not review[0] or review[1]
                or actual_proof != proof):
            return 'normalized_variant_conflict'
        return None
    category_id = variant.get("unified_category_id")
    # The parent leaf comes from the persisted canonical product, never a
    # crawler/client category assertion. Validate target purpose as well as raw
    # source purpose; richer source-bound reviews retain their checks below.
    if isinstance(category_id, str) and category_id.startswith("services.facility."):
        _, issues = normalize_catalog_package(variant, variant_attrs if isinstance(variant_attrs, Mapping) else {}, names[0], category_id=category_id)
        if any(issue.startswith("unit_service_") for issue in issues):
            return "normalized_variant_conflict"
    package, reason = _source_package(row, category_id=category_id)
    if reason:
        return reason
    title = _extract_str(row, ['source_title', 'name', 'productName', 'itemName', 'prdtName', 'goodsName', 'title']) or ''
    if package and package[1] == 'm':
        linear_review = explicit_listing_package(row, {}, title)
        if (linear_review and linear_review[0]
                and valid_linear_contents_variant(linear_review[0])
                and not valid_linear_contents_variant(variant)):
            return 'normalized_variant_conflict'
    if isinstance(variant_attrs, dict) and 'source_component_listing' in variant_attrs:
        review = source_component_listing_package(row, {}, title)
        if (not valid_source_component_variant(variant) or not review or not review[0] or review[1]
                or review[0]['attributes']['source_component_listing'] != variant_attrs['source_component_listing']
                or package != (1, '세트', 1)):
            return 'normalized_variant_conflict'
        return None
    if isinstance(variant_attrs, dict) and 'explicit_listing_quantity_review' in variant_attrs:
        review = explicit_listing_package(row, {}, title)
        if (not valid_explicit_listing_variant(variant) or not review or not review[0] or review[1]
                or review[0]['attributes']['explicit_listing_quantity_review'] != variant_attrs['explicit_listing_quantity_review']):
            return 'normalized_variant_conflict'
    if isinstance(variant_attrs, dict) and 'nonmeasured_listing' in variant_attrs:
        review = nonmeasured_listing_review(row, {}, title)
        if (not valid_nonmeasured_variant(variant) or not review or not review[0] or review[1]
                or review[0]['attributes']['nonmeasured_listing'] != variant_attrs['nonmeasured_listing']
                or package != (None, None, review[0]['bundle_count'])):
            return 'normalized_variant_conflict'
        return None
    if isinstance(variant_attrs, dict) and 'count_interval_listing' in variant_attrs:
        review = count_interval_listing_package(row, {}, title)
        interval_matches = bool(review and review[0] and not review[1]
                                and review[0]['attributes']['count_interval_listing'] == variant_attrs['count_interval_listing'])
        history = variant_attrs.get('source_title_history')
        if (not interval_matches and history and review and review[0] and not review[1]
                and valid_count_interval_variant(variant)):
            # The exact source history was verified above. Its titles may retain
            # different crop wording, but must declare the same sold interval.
            source_interval = review[0]['attributes']['count_interval_listing']
            target_interval = variant_attrs['count_interval_listing']
            approved_titles = {alias['title'] for alias in history['aliases']}
            interval_matches = (source_interval['title'] in approved_titles
                                and target_interval['title'] in approved_titles
                                and source_interval['category_id'] == target_interval['category_id'] == history['category_id']
                                and source_interval['count_interval'] == target_interval['count_interval'])
        if (not valid_count_interval_variant(variant) or not review or not review[0] or review[1]
                or not interval_matches
                or package != (None, 'ea' if variant.get('package_unit') == '개' else variant.get('package_unit'), 1)):
            return 'normalized_variant_conflict'
        return None
    try:
        target_components = component_signature(variant)
        source_components = None
        if uses_reviewed_component_rules(title):
            normalized_source, issues = normalize_catalog_package(row, {}, title, category_id=category_id)
            if not normalized_source or issues:
                return 'normalized_variant_conflict'
            source_components = component_signature(normalized_source)
        if source_components is not None or target_components is not None:
            if source_components is None or source_components != target_components:
                return 'normalized_variant_conflict'
            if variant['attributes'].get('component_basis') != 'reviewed_homogeneous_contents':
                return 'normalized_variant_conflict'
            if (variant.get('package_quantity') != 1 or variant.get('package_unit') != '세트'
                    or variant.get('bundle_count') != 1):
                return 'normalized_variant_conflict'
            if 'standard_unit' in variant and variant['standard_unit'] != source_components[0][1]:
                return 'normalized_variant_conflict'
    except (ValueError, TypeError, OverflowError):
        return 'normalized_variant_conflict'
    target = _package_identity(variant.get("package_quantity"), variant.get("package_unit"))
    target_count = _positive_number(variant.get("bundle_count"))
    if target is None or target_count is None or not target_count.is_integer():
        return "normalized_variant_unavailable"
    if package != (*target, int(target_count)):
        return "normalized_variant_conflict"
    # Rich reviewed contracts above retain their own source/quantity diagnostics.
    # Ordinary scalar identity must also reject supplied URL/native/store contradictions.
    if "source_listings" in variant and mart == "homeplus" and not _homeplus_declared_url_consistent(row, matches[0], source_key):
        return "normalized_source_listing_unavailable"
    return None



def _extract_float(row: dict[str, Any], keys: list[str]) -> Optional[float]:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _match_key_for_row(row: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    brand = _extract_str(row, ["brand", "brandName", "brandNm", "brand_name"])
    name = _extract_str(
        row,
        [
            "name_core",
            "normalized_name",
            "name",
            "nameCore",
            "productName",
            "itemName",
            "prdtName",
            "goodsName",
            "title",
        ],
    )
    pack_qty = _extract_float(
        row,
        ["pack_qty", "packQty", "pack_quantity", "packQuantity"],
    )
    pack_unit = _extract_str(row, ["pack_unit", "packUnit", "unitName", "unit"])
    source_title = _extract_str(row, ["source_title", "name", "productName", "itemName", "prdtName", "goodsName", "title"]) or ""
    reviewed = reviewed_price_basis_identity(row, source_title)
    if reviewed:
        pack_qty, pack_unit = reviewed
        name = source_title

    if not name:
        return None, "no_name"
    if not brand:
        row["brand"] = NO_BRAND_SENTINEL
        brand = NO_BRAND_SENTINEL
    return build_match_key(brand, name, pack_qty, pack_unit), None
