"""Pure, conservative preparation of a catalog-v2 bundle from pending crawls.

This module neither opens a database nor approves an ingestion. Callers supply
the selected PendingIngestion rows and separately reviewed leaf assignments.
An assignment is keyed by ``(source_name, source_record_key)``. Its required
field is ``unified_category_id``; ``classification_confidence`` defaults to 0,
not 1. Cross-listing product grouping requires an explicit ``product_group_key``.
Unassigned/identity-ambiguous observations remain in ``unresolved`` with their
complete payload. Promotion-only ambiguity is staged as an unknown,
non-comparable pending_review offer, never silently discarded or published.
``included`` in accounting means staged, not reviewed/publicly approved.
The report accounts for every ingestion:index.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping

from core.match_key import build_match_key
from core.product_units import parse_package_quantity
from core.promotion_semantics import comparable_transaction_or_none
from services.initial_numbered_reviews import source_reviews
from core.reviewed_source_evidence import (source_observation_eligibility_review,
                                          source_identity_context_review,
                                          listing_title_history, valid_count_interval_variant,
                                          valid_source_component_variant, source_component_signature,
                                          source_review_evidence, source_review_matches)
from core.catalog_quantity import normalize_catalog_package as _package, _sheet_roll_package, reviewed_price_basis_identity, component_signature, package_pricing_measure, uses_reviewed_component_rules, valid_physical_device_variant

SCHEMA_VERSION = "walletsaver-catalog-v2"
BUILDER_VERSION = "initial-catalog-seed-v1"
KST = timezone(timedelta(hours=9))
MART_ALIASES = {
    "emart": "emart", "이마트": "emart", "ssg": "emart",
    "homeplus": "homeplus", "홈플러스": "homeplus",
    "lottemart": "lottemart", "롯데마트": "lottemart", "롯데마트 제타": "lottemart",
    "costco": "costco", "코스트코": "costco",
}
GENERIC_BRANDS = {
    "__no_brand__", "브랜드없음", "브랜드 없음", "없음", "해당없음", "기타",
    "단독기획", "국내산", "국산", "수입산", "외국산", "미국산", "호주산",
    "중국산", "뉴질랜드산", "태국산", "베트남산", "대한민국", "한국", "미국",
    "호주", "중국", "뉴질랜드", "태국", "베트남", "unknown", "none", "null",
}
BRAND_ALIASES = {"cj": "CJ", "씨제이": "CJ"}
GENERIC_EVENTS = {"이마트 할인", "홈플러스 할인", "롯데마트 할인", "코스트코 가격", "코스트코 할인", "행사상품", "알뜰상품", ""}
PROMOTION_TYPES = {"final_price", "was_now_price", "checkout_discount", "buy_x_get_y", "bundle_price"}
PROMOTION_REVIEW_ISSUES = {"promotion_unresolved", "promotion_conditions_unresolved"}


def _text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _normalized_text(value: Any) -> str:
    # Punctuation remains identity-relevant: e.g. flavor/grade/model changes.
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False)


def stable_id(prefix: str, *parts: Any) -> str:
    """Length-delimited JSON hashing avoids delimiter collisions in source keys."""
    return f"{prefix}-{hashlib.sha256(_json(parts).encode('utf-8')).hexdigest()[:32]}"


def _get(row: Any, name: str, default: Any = None) -> Any:
    return row.get(name, default) if isinstance(row, Mapping) else getattr(row, name, default)


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


def _timestamp(value: Any, *, naive_timezone: timezone = KST) -> str | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # DiscountItem uses datetime.now(); PendingIngestion uses utcnow(). The
    # caller must name the correct clock when normalizing a naive timestamp.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_timezone)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_source_path(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [_text(part) for part in value if _text(part)]
    return [part.strip() for part in re.split(r"\s*>\s*|\s*›\s*", _text(value)) if part.strip()]


def validated_brand(value: Any) -> str | None:
    value = re.sub(r"\s+", " ", _text(value))
    origin_label = re.fullmatch(r"(?:국내|국|미국|호주|중국|뉴질랜드|태국|베트남)산(?:\s*[(/].*)?", value)
    quality_label = re.fullmatch(r"\d+(?:\.\d+)?\s*brix", value, re.I)
    if not value or value.casefold() in GENERIC_BRANDS or origin_label or quality_label or len(value) > 120:
        return None
    return BRAND_ALIASES.get(value.casefold(), value)


def _package_signature(package: Mapping[str, Any] | None) -> tuple[Any, ...] | None:
    if package is None:
        return None
    scalar = (package["package_quantity"], package["package_unit"], package["bundle_count"])
    from core.reviewed_source_evidence import source_selection_alternatives
    alternatives = source_selection_alternatives(package)
    if alternatives:
        return (*scalar, 'source-exclusive-alternatives-v1', alternatives)
    from core.reviewed_source_evidence import source_entitlement_specification, source_partial_retail_specification
    partial_retail = source_partial_retail_specification(package)
    if partial_retail:
        return (*scalar, 'source-partial-retail-package-v1', json.dumps(partial_retail, sort_keys=True, ensure_ascii=False))
    entitlement = source_entitlement_specification(package)
    if entitlement:
        return (*scalar, 'source-incomplete-entitlement-v1', json.dumps(entitlement, sort_keys=True, ensure_ascii=False))
    components = component_signature(package)
    return scalar if components is None else (*scalar, components)




def _price(payload: Mapping[str, Any], attrs: Mapping[str, Any], mart: str, title: str) -> tuple[dict[str, Any], list[str]]:
    if mart == "lottemart" and attrs.get("lottemart_detail_source_fields") is not None:
        from services.native_quote_price_roles import native_lotte_price_roles
        try:
            roles = native_lotte_price_roles(payload, attrs, title)
        except ValueError:
            roles = None  # Retain ordinary quoted evidence, without elevating an unvalidated base role.
        if roles is not None:
            return {"price":roles["source_base_quote"]["amount"], "original_price":None,
                    "discount_rate":None, "price_state":"sale_price_only", "promotion_type":"final_price",
                    "event_name":payload.get("event_name"), "promotion_conditions":roles["promotion_conditions"],
                    "valid_from":_timestamp(payload.get("valid_from")),
                    "valid_to":_timestamp(payload.get("valid_until") or payload.get("valid_to"))}, []
    layers = (payload, attrs)
    price = _positive(_first(layers, ("sale_price", "current_price")))
    original = _positive(_first(layers, ("original_price",)))
    label = _text(_first(layers, ("promo_label", "promotion_text")))
    event_name = _text(_first(layers, ("event_name",)))
    explicit = _text(_first(layers, ("promotion_type", "promo_type")))
    issues: list[str] = []
    if mart == "costco":
        regular = _positive(_first(layers, ("price",)))
        if regular is not None and (label or explicit == "checkout_discount"):
            original = regular
        if label:
            explicit = "checkout_discount"
    elif price is None:
        price = _positive(_first(layers, ("price",)))
    if price is None:
        issues.append("sale_price_missing_or_invalid")
    if original is not None and price is not None:
        if original < price:
            issues.append("original_price_below_sale_price")
        elif original == price:
            original = None
    if explicit in PROMOTION_TYPES:
        promotion = explicit
    elif explicit:
        promotion = "unknown"
        issues.append("promotion_unresolved")
    elif re.fullmatch(r"\d+\s*\+\s*\d+", label):
        promotion = "buy_x_get_y"
    elif not label and (fixed := re.fullmatch(r"(?:과자|균일가)\s*([\d,]+)원", event_name)) and _positive(fixed.group(1)) == price:
        # These are displayed-price badges, not a second discount to subtract.
        # The exact advertised amount must match the independently read price.
        promotion = "was_now_price" if original is not None else "final_price"
    elif label or event_name not in GENERIC_EVENTS:
        promotion = "unknown"
        issues.append("promotion_unresolved")
    else:
        promotion = "was_now_price" if original is not None else "final_price"
    rate = None
    if original and price and promotion == "was_now_price":
        rate = round((original - price) / original, 4)
    conditions = {
        key: deepcopy(value) for key in (
            "is_member_only", "member_only", "coupon_required", "minimum_purchase_quantity",
            "min_purchase_quantity", "promotion_conditions", "coupon_conditions",
        ) if (value := _first(layers, (key,))) is not None
    }
    promotion_text = label or event_name
    buy_get = re.fullmatch(r"\s*(\d+)\s*\+\s*(\d+)\s*", promotion_text)
    from core.reviewed_source_evidence import reviewed_additive_battery_pack
    pack_expression = reviewed_additive_battery_pack(payload, attrs, title)
    if (pack_expression and buy_get and promotion == 'buy_x_get_y'
            and f'{int(buy_get[1])}+{int(buy_get[2])}' == pack_expression['expression']
            and not conditions.get('promotion_conditions')):
        # A fixed-pack badge is not evidence to buy N whole packs for N free.
        # Keep its literal source condition, quote and unknown payable status.
        promotion = 'unknown'
        conditions.update(source_pack_expression=pack_expression['literal'],
                          source_promotion_role='pack_or_purchase_scope_unverified',
                          payable_price_unconfirmed=True)
        issues.append('promotion_conditions_unresolved')
    if promotion == "buy_x_get_y":
        if buy_get:
            buy_quantity, free_quantity = (int(buy_get.group(1)), int(buy_get.group(2)))
            if buy_quantity > 0 and free_quantity > 0:
                conditions.update({
                    "buy_quantity": buy_quantity,
                    "free_quantity": free_quantity,
                    "minimum_quantity": buy_quantity,
                    "condition_text": f"{buy_quantity}+{free_quantity}",
                })
        if "buy_quantity" not in conditions or "free_quantity" not in conditions:
            issues.append("promotion_conditions_unresolved")
    title_purchase_condition = bool(re.search(r"최소\s*구매", title))
    if title_purchase_condition:
        # Some source listings put the minimum order only in their title.
        # Preserve that evidence without inventing a payable total or treating
        # the minimum order as the physical bundle size. No current promotion
        # type establishes that this textual condition has been modelled.
        conditions["source_title_purchase_condition"] = title
        # This partial entitlement review separately proves the purchase
        # condition. Other unreviewed minimum-order listings stay pending.
        from core.reviewed_source_evidence import reviewed_listing_specification
        entitlement = reviewed_listing_specification(payload, title, 'services.vouchers.cafe.monetary')
        minimum = re.search(r"최소\s*구매\s*(?:수량\s*)?[:：]?\s*([1-9]\d*)(?:\s*개)?(?=\s|$|[/,)])", title)
        if entitlement and minimum:
            conditions["minimum_quantity"] = int(minimum[1])
    has_conditions = any(bool(value) for value in conditions.values())
    if title_purchase_condition or (has_conditions and promotion in {"final_price", "was_now_price"}):
        promotion = "unknown"
        rate = None
        issues.append("promotion_conditions_unresolved")
    return {
        "price": price, "original_price": original, "discount_rate": rate,
        "price_state": "normal" if original else "sale_price_only", "promotion_type": promotion,
        "event_name": label or event_name or None,
        "promotion_conditions": conditions,
        "valid_from": _timestamp(_first(layers, ("valid_from",))),
        "valid_to": _timestamp(_first(layers, ("valid_until", "valid_to"))),
    }, issues


def normalize_pending_ingestions(ingestions: Iterable[Any]) -> list[dict[str, Any]]:
    """Normalize raw rows without changing them, retaining every source payload.

    Malformed items are returned with ``issues`` rather than silently omitted.
    Malformed items_json raises ValueError because its original row boundaries
    cannot be accounted for. Repeating the identical ingestion input is safe.
    """
    result: dict[str, dict[str, Any]] = {}
    for ingestion in ingestions:
        ingestion_id = int(_get(ingestion, "id"))
        items = _get(ingestion, "items_json", [])
        if isinstance(items, str):
            items = json.loads(items)
        if not isinstance(items, list):
            raise ValueError(f"ingestion {ingestion_id}: items_json must be an array")
        crawler_name = _text(_get(ingestion, "crawler_name"))
        for index, item in enumerate(items):
            raw_id = f"ingestion:{ingestion_id}:{index}"
            payload = item if isinstance(item, Mapping) else {}
            attrs = payload.get("attributes") if isinstance(payload.get("attributes"), Mapping) else {}
            raw_data = payload.get("raw_data") if isinstance(payload.get("raw_data"), Mapping) else {}
            nested_attrs = raw_data.get("attributes") if isinstance(raw_data.get("attributes"), Mapping) else {}
            attrs = {**nested_attrs, **attrs}
            source_values = [crawler_name, *(_text(_first((payload, attrs, raw_data), (key,))) for key in ("source_name", "source", "mart", "store"))]
            mart = next((MART_ALIASES[value.casefold()] for value in source_values if value.casefold() in MART_ALIASES), "")
            title = _text(_first((attrs, payload, raw_data), ("raw_name", "source_title", "name", "product_name", "title")))
            key = _text(_first((payload, attrs, raw_data), ("source_record_key", "source_product_id", "mart_native_code")))
            path = normalize_source_path(_first((attrs, raw_data, payload), ("mart_native_category_path", "source_category_path", "category_path", "category")))
            brand = next((brand for layer in (attrs, raw_data, payload) for name in ("brand", "brandName", "brandNm", "brand_name") if (brand := validated_brand(layer.get(name)))), None)
            package, unit_issues = _package(payload, attrs, title)
            price, price_issues = _price(payload, attrs, mart, title)
            timestamp = _timestamp(payload.get("crawled_at"))
            timestamp_source = "item_crawled_at"
            time_precision = "item"
            received_at = _timestamp(_get(ingestion, "crawled_at"), naive_timezone=timezone.utc)
            if mart == "costco" and payload.get("crawled_at") in (None, "") and received_at:
                # Legacy Costco records have no item time. The operator permits
                # the stored batch receipt as a labelled proxy, not an invented
                # exact crawl time. PendingIngestion uses datetime.utcnow().
                timestamp = received_at
                timestamp_source = "ingestion_received_at"
                time_precision = "batch"
            issues = unit_issues + price_issues
            if not isinstance(item, Mapping):
                issues.append("raw_item_not_object")
            if not mart:
                issues.append("source_unknown")
            if not key:
                issues.append("source_record_key_missing")
            if not title:
                issues.append("source_title_missing")
            if not timestamp:
                issues.append("item_crawled_at_missing_or_invalid")
            if attrs.get("external_seller") is True:
                issues.append("external_seller")
            row = {
                "raw_record_id": raw_id, "ingestion_id": ingestion_id, "item_index": index,
                "crawler_name": crawler_name, "source_name": mart, "source_record_key": key,
                "source_title": title, "source_category_path": path,
                "mart_native_category_id": _text(_first((attrs, payload, raw_data), ("mart_native_category_id",))),
                "source_url": _text(_first((attrs, payload, raw_data), ("canonical_url", "permanent_url", "detail_url", "source_url"))),
                "image_url": _text(_first((payload, attrs, raw_data), ("image_url",))),
                "brand": brand, "package": package, "crawled_at": timestamp,
                "timestamp_source": timestamp_source, "observed_time_precision": time_precision,
                "ingestion_received_at": received_at,
                "issues": sorted(set(issues)), "raw_payload": deepcopy(item),
                "raw_payload_sha256": hashlib.sha256(_json(item).encode("utf-8")).hexdigest(), **price,
            }
            if raw_id in result and result[raw_id] != row:
                raise ValueError(f"conflicting input for {raw_id}")
            result[raw_id] = row
    return sorted(result.values(), key=lambda row: (row["ingestion_id"], row["item_index"]))


def _leaf_ids(categories: Iterable[Mapping[str, Any]]) -> set[str]:
    categories = list(categories)
    ids = {_text(row.get("id")) for row in categories}
    parents = {_text(row.get("parent_id")) for row in categories if row.get("parent_id")}
    return ids - parents


def _runtime_match_key(row: Mapping[str, Any]) -> str | None:
    payload = row["raw_payload"]
    if not isinstance(payload, Mapping):
        return None
    title = _text(_first((payload,), ("source_title", "name", "productName", "itemName", "prdtName", "goodsName", "title")))
    reviewed = reviewed_price_basis_identity(payload, title)
    if reviewed:
        return build_match_key(_first((payload,), ("brand", "brandName", "brandNm", "brand_name")), title, *reviewed)
    existing = _text(payload.get("match_key"))
    if existing and payload.get("matching_status") == "miss":
        return existing
    # Exactly mirror crawler matching_enrichment/export identity. Do not use
    # the corrected display brand or canonical name to invent a runtime key.
    name = _first((payload,), ("name_core", "normalized_name", "name", "nameCore", "productName", "itemName", "prdtName", "goodsName", "title"))
    if not name:
        return None
    quantity = _number(_first((payload,), ("pack_qty", "packQty", "pack_quantity", "packQuantity")))
    return build_match_key(
        _first((payload,), ("brand", "brandName", "brandNm", "brand_name")), str(name),
        float(quantity) if quantity is not None else None,
        _first((payload,), ("pack_unit", "packUnit", "unitName", "unit")),
    )


def _physical_title_history_alias_keys(history, package, members, category_id):
    """Reconstruct only reviewed source aliases, keeping the primary proof intact.

    Source quote amounts are absent from this identity check. A registered
    title history alone cannot change a physical role, sold count or source.
    """
    proof = package['attributes']['physical_device_specification']
    expected = {key: value for key, value in proof.items() if key != 'title'}
    if proof['category_id'] != category_id or any(
            not valid_physical_device_variant(row['package'])
            or {key: value for key, value in row['package']['attributes']['physical_device_specification'].items()
                if key != 'title'} != expected for row in members):
        return None
    keys = set()
    for alias in history['aliases']:
        source, attrs = {}, {}
        for name, value in {**alias['required_source']['source_fields'], **alias['quantity_fields']}.items():
            layer, field = (attrs, name[11:]) if name.startswith('attributes.') else (source, name)
            if field in {'unit_price_display', 'unit_price_basis', 'unit_price_basis_raw', 'unit_price_text', 'unit_price_unit'} and isinstance(value, list) and len(value) == 2:
                value = f'{value[0] or ""}{value[1]}'
            layer[field] = deepcopy(value)
        urls = alias['required_source']['source_urls']
        if len(urls) > 6:
            return None
        for index, url in enumerate(urls):
            (source if index < 3 else attrs)[('canonical_url', 'detail_url', 'source_url')[index % 3]] = url
        attrs['source_record_key'] = history['source_record_key']
        source.update(name=alias['title'], source=history['source_name'], attributes=attrs)
        derived, issues = _package(source, attrs, alias['title'], category_id=category_id)
        if (issues or not valid_physical_device_variant(derived)
                or {key: value for key, value in derived['attributes']['physical_device_specification'].items()
                    if key != 'title'} != expected):
            return None
        # Use the same raw brand input as the original key, without copying
        # stale match_key/name_core values into an unobserved alias.
        source['brand'] = _first((members[0]['raw_payload'],), ('brand', 'brandName', 'brandNm', 'brand_name'))
        match_key = _runtime_match_key({'raw_payload': source})
        if match_key:
            keys.add(match_key)
    return keys


def _classification_attributes(assignment: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Keep JSON attribute facts exactly; missing/None means not established."""
    value = assignment.get("classification_attributes")
    if value is None:
        return {}, True
    if not isinstance(value, Mapping) or any(not isinstance(key, str) or not key.strip() for key in value):
        return {}, False
    try:
        # Do not stringify unsupported objects or NaN into apparently valid
        # facts. False/0/None remain distinct JSON values for conflict checks.
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return {}, False
    return deepcopy(dict(value)), True


def _merge_classification_attributes(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    """Union non-conflicting evidence without turning an unknown into False."""
    merged = deepcopy(dict(existing))
    for key, value in incoming.items():
        if key not in merged or merged[key] is None:
            merged[key] = deepcopy(value)
        elif value is not None and _json(merged[key]) != _json(value):
            # The prepass must catch this before any product/listing is emitted.
            raise ValueError(f"unchecked classification attribute conflict: {key}")
    return dict(sorted(merged.items()))


def build_initial_catalog_bundle(
    ingestions: Iterable[Any], *, categories: Iterable[Mapping[str, Any]],
    assignments: Mapping[tuple[str, str], Mapping[str, Any]], run_id: str,
    keywords: Iterable[Mapping[str, Any]] = (),
    mart_category_mappings: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build a deterministic, inspectable bundle; no DB/files/network side effects.

    Assignment fields: unified_category_id, classification_confidence,
    review_status, optional canonical_name, product_group_key, brand, aliases,
    keywords, classification_attributes, and ``package`` (reviewed
    quantity/unit/bundle_count override). Attribute values and per-source
    evidence are retained. Conflicting established values in an explicit
    product group hold the whole group; missing/None values do not mean False.
    A low-confidence assignment requires review_status='approved'. A name or
    spec change on one source key is always held for a separate review pass.
    Promotion-only problems remain staged with offer_state='pending_review'.
    Their source price is evidence, not a comparable price or public approval.
    """
    if not _text(run_id):
        raise ValueError("run_id is required")
    rows = normalize_pending_ingestions(ingestions)
    category_rows = sorted((deepcopy(dict(row)) for row in categories), key=lambda row: row["id"])
    leaves = _leaf_ids(category_rows)
    # Classification establishes appliance specification and service-occupancy
    # roles. Recompute only their quantity issues, keeping every
    # raw observation and all price/source diagnostics intact.
    for row in rows:
        category_id = (assignments.get((row['source_name'], row['source_record_key'])) or {}).get('unified_category_id')
        if category_id in leaves:
            payload = row['raw_payload']
            if not isinstance(payload, Mapping):
                continue
            attrs = payload.get('attributes') or {}
            attrs = attrs if isinstance(attrs, Mapping) else {}
            package, issues = _package(payload, attrs, row['source_title'], category_id=category_id)
            measured_scope = ('measured_inner_scope_unresolved' in row['issues']
                              and (category_id == 'food.meals.noodles.cup_ramen'
                                   or category_id.startswith('food.dairy.milk.')))
            if (package and 'physical_device_specification' in package.get('attributes', {})
                    or any(issue.startswith(('physical_device_', 'unit_service_')) for issue in issues)
                    or measured_scope):
                row['package'] = package
                row['issues'] = [issue for issue in row['issues'] if not issue.startswith(
                    ('unit_', 'bundle_', 'mixed_package_', 'multiple_package_', 'count_range_', 'bulk_package_'))
                    and issue != 'measured_inner_scope_unresolved'] + issues
    bundle: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "builder_version": BUILDER_VERSION, "run_id": run_id,
        "source_ingestion_ids": sorted({row["ingestion_id"] for row in rows}),
        "categories": category_rows, "keywords": sorted((deepcopy(dict(row)) for row in keywords), key=lambda row: row["word"]),
        "products": [], "variants": [], "source_listings": [], "offers": [],
        "week_buckets": [], "offer_week_links": [], "match_rules": [],
        "mart_category_mappings": sorted((deepcopy(dict(row)) for row in mart_category_mappings), key=lambda row: (row["mart"], str(row["mart_native_id"]))),
        "unresolved": [], "observation_accounting": [], "review_issues": [],
    }
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["source_name"], row["source_record_key"])
        context = source_identity_context_review(*key, row['raw_payload'], row['source_title'])
        if context and context['partition_key']:
            key += (context['partition_key'],)
        groups[key].append(row)
    assignments = dict(assignments)
    for key in groups:
        if len(key) == 3:
            # A source SKU's old classified form may establish the leaf, but
            # cannot transfer its name, grade, cultivar, package override or
            # cross-mart identity to a separately reviewed context.
            original = assignments.get(key[:2]) or {}
            assignments[key] = {field: deepcopy(original[field]) for field in (
                'unified_category_id', 'classification_confidence', 'classification_reason',
                'review_status') if field in original}
    products: dict[str, dict[str, Any]] = {}
    variants: dict[str, dict[str, Any]] = {}
    weeks: dict[str, dict[str, Any]] = {}
    rule_candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    reason_counts: Counter[str] = Counter()
    assignment_attributes: dict[tuple[str, str], dict[str, Any]] = {}
    invalid_attribute_keys: set[tuple[str, str]] = set()
    attribute_evidence: dict[tuple[str, str], dict[str, Any]] = {}
    group_attribute_values: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    attribute_conflicts: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def hold(row: dict[str, Any], reasons: Iterable[str]) -> None:
        reasons = sorted(set(reasons))
        reason_counts.update(reasons)
        key = (row["source_name"], row["source_record_key"])
        assignment = assignments.get(key) or {}
        group_key = _text(assignment.get("product_group_key"))
        bundle["unresolved"].append({
            **deepcopy(row), "reasons": reasons, "review_status": "pending",
            "classification_attributes": deepcopy(assignment.get("classification_attributes")),
            "classification_attribute_evidence": deepcopy(attribute_evidence.get(key)),
            "classification_attribute_conflicts": deepcopy(attribute_conflicts.get(group_key, {})),
        })
        bundle["observation_accounting"].append({"raw_record_id": row["raw_record_id"], "ingestion_id": row["ingestion_id"], "status": "unresolved", "reasons": reasons})

    # A registered incomplete observation is still accounted for, but cannot
    # erase another independently exact observation of the same source SKU.
    # Every unreviewed conflict continues through the whole-group guards.
    for key, members in list(groups.items()):
        eligible_members = []
        for row in members:
            payload = row['raw_payload']
            eligibility = (source_observation_eligibility_review(
                payload, payload.get('attributes') or {}, row['source_title'])
                if isinstance(payload, Mapping) else None)
            if (eligibility is not None
                    and 'source_observation_factual_hold' in eligibility[1]):
                hold(row, eligibility[1] + row['issues'])
            else:
                eligible_members.append(row)
        if eligible_members:
            groups[key] = eligible_members
        else:
            del groups[key]

    # Detect explicit cross-listing group disagreements before emitting either
    # side; otherwise input order could decide which classification survives.
    identity_definitions: dict[str, set[str]] = defaultdict(set)
    for key, members in sorted(groups.items()):
        assignment = assignments.get(key) or {}
        attributes, attributes_valid = _classification_attributes(assignment)
        assignment_attributes[key] = attributes
        if not attributes_valid:
            invalid_attribute_keys.add(key)
        evidence = {
            "source_name": key[0], "source_record_key": key[1],
            "classification_attributes": deepcopy(assignment.get("classification_attributes", {})),
            "classification_reason": assignment.get("classification_reason"),
            "source_ingestion_ids": sorted({row["ingestion_id"] for row in members}),
            "raw_record_ids": [row["raw_record_id"] for row in members],
        }
        attribute_evidence[key] = evidence
        group_key = _text(assignment.get("product_group_key"))
        if group_key:
            latest_member = max(members, key=lambda row: (row["crawled_at"] or "", row["raw_record_id"]))
            effective_brand = validated_brand(assignment.get("brand")) if "brand" in assignment else latest_member["brand"]
            identity_definitions[group_key].add(_json((assignment.get("unified_category_id"), assignment.get("canonical_name"), effective_brand)))
            for attribute, value in attributes.items():
                if value is None:
                    continue
                value_key = _json(value)
                candidate = group_attribute_values[group_key][attribute].setdefault(value_key, {"value": deepcopy(value), "sources": []})
                candidate["sources"].append(deepcopy(evidence))
    conflicting_groups = {key for key, definitions in identity_definitions.items() if len(definitions) > 1}
    for group_key, definitions in sorted(group_attribute_values.items()):
        conflicts = {
            attribute: [values[key] for key in sorted(values)]
            for attribute, values in sorted(definitions.items()) if len(values) > 1
        }
        if not conflicts:
            continue
        attribute_conflicts[group_key] = conflicts
        members = [row for key, values in groups.items() if _text((assignments.get(key) or {}).get("product_group_key")) == group_key for row in values]
        bundle["review_issues"].append({
            "reason": "product_group_classification_attribute_conflict", "product_group_key": group_key,
            "attribute_conflicts": deepcopy(conflicts), "review_status": "pending", "publication_status": "not_approved",
            "source_ingestion_ids": sorted({row["ingestion_id"] for row in members}),
            "raw_record_ids": sorted(row["raw_record_id"] for row in members),
        })

    for key, members in sorted(groups.items()):
        assignment = dict(assignments.get(key) or {})
        reasons: list[str] = []
        category_id = _text(assignment.get("unified_category_id"))
        confidence = _number(assignment.get("classification_confidence"))
        if not assignment:
            reasons.append("catalog_assignment_missing")
        if category_id not in leaves:
            reasons.append("category_not_resolved_to_leaf")
        if confidence is None or confidence < 0 or confidence > 1:
            reasons.append("classification_confidence_invalid")
        elif confidence < Decimal("0.80") and assignment.get("review_status") != "approved":
            reasons.append("classification_low_confidence")
        if assignment.get("review_status") == "pending":
            reasons.append("classification_pending_review")
        if key in invalid_attribute_keys:
            reasons.append("classification_attributes_invalid")
        title_history = None
        multiple_titles = len({_normalized_text(row["source_title"]) for row in members}) > 1
        physical_members = all(valid_physical_device_variant(row['package']) for row in members)
        if multiple_titles or physical_members:
            histories = [listing_title_history(*key[:2], row['raw_payload'], row['source_title']) for row in members]
            if (histories and histories[0] and all(review == histories[0] for review in histories)
                    and histories[0]['category_id'] == category_id):
                title_history = histories[0]
            elif multiple_titles:
                reasons.append("source_title_changed")
        if len({_json(_package_signature(row["package"])) for row in members}) > 1:
            reasons.append("source_specification_changed")
        group_key = _text(assignment.get("product_group_key"))
        if group_key in conflicting_groups:
            reasons.append("product_group_conflict")
        if group_key in attribute_conflicts:
            reasons.append("product_group_classification_attribute_conflict")
        if group_key and not _text(assignment.get("canonical_name")):
            reasons.append("product_group_name_missing")
        latest = max(members, key=lambda row: (row["crawled_at"] or "", row["raw_record_id"]))
        from services.initial_numbered_reviews import form_reviews
        from services.initial_taxonomy import normalize_source_path as review_source_path
        form_review = form_reviews().get((key[0], review_source_path(latest['source_category_path']), latest['source_title']))
        reviewed_name = ''
        if form_review and isinstance(form_review.get('canonical_name'), str):
            reviewed_name = form_review['canonical_name'].strip()
            required = source_reviews().get((key[0], review_source_path(latest['source_category_path']), latest['source_title']))
            if reviewed_name and (form_review['leaf'] != category_id or not required or any(
                    not source_review_matches(source_review_evidence(row['raw_payload']), required)
                    for row in members)):
                reasons.append('reviewed_product_name_source_conflict')
        package = deepcopy(assignment.get("package") or latest["package"])
        contexts = [source_identity_context_review(*key[:2], row['raw_payload'], row['source_title'])
                    for row in members]
        if any(contexts):
            if (not all(context == contexts[0] for context in contexts)
                    or contexts[0]['category_id'] != category_id
                    or package is None
                    or [package.get('package_quantity'), package.get('package_unit'), package.get('bundle_count')]
                       != contexts[0]['normalized']):
                reasons.append('reviewed_source_identity_context_conflict')
            elif contexts[0]['partition_key']:
                package.setdefault('attributes', {})['source_identity_context'] = deepcopy(contexts[0])
        if assignment.get("package"):
            component_override = "package_components" in (assignment["package"].get("attributes") or {})
            if component_override and not uses_reviewed_component_rules(latest["source_title"]):
                package, override_issues = None, ["unit_component_override_requires_reviewed_title"]
            else:
                package, override_issues = _package(assignment["package"], {}, latest["source_title"] if component_override else "")
            reasons.extend(override_issues)
        from core.reviewed_source_evidence import source_parent_selection, source_outer_set_count, source_observational_raw_hashes, source_nonexact_contents_specification, source_entitlement_specification, source_partial_retail_specification
        parent_selection = source_parent_selection(package) if package else None
        outer_count = source_outer_set_count(package) if package else None
        nonexact = source_nonexact_contents_specification(package) if package else None
        entitlement = source_entitlement_specification(package) if package else None
        partial_retail = source_partial_retail_specification(package) if package else None
        if outer_count or nonexact or entitlement or partial_retail:
            outer_review = package['attributes']['explicit_listing_quantity_review']
            if (assignment.get('package') or group_key or outer_review['category_id'] != category_id
                    or any(row['source_name'] != outer_review['source_name']
                           or row['source_record_key'] != outer_review['source_record_key']
                           or source_observational_raw_hashes(package).get(row['raw_record_id']) != row['raw_payload_sha256']
                           or not row['package'] or source_outer_set_count(row['package']) != outer_count
                           or source_nonexact_contents_specification(row['package']) != nonexact
                           or source_entitlement_specification(row['package']) != entitlement
                           or source_partial_retail_specification(row['package']) != partial_retail
                           for row in members)):
                reasons.append('source_partial_retail_evidence_conflict' if partial_retail else 'source_entitlement_evidence_conflict' if entitlement else 'source_nonexact_contents_evidence_conflict' if nonexact else 'source_outer_set_evidence_conflict')
        if parent_selection:
            parent_review = package['attributes']['explicit_listing_quantity_review']
            if (assignment.get('package') or group_key
                    or parent_review['category_id'] != category_id
                    or any(row['source_name'] != parent_review['source_name']
                           or row['source_record_key'] != parent_review['source_record_key']
                           or parent_selection['original_raw_payload_hashes'].get(row['raw_record_id'])
                              != row['raw_payload_sha256']
                           or not row['package'] or source_parent_selection(row['package']) != parent_selection
                           for row in members)):
                reasons.append('source_option_parent_evidence_conflict')
        if form_review and form_review.get('quantity_hold_reason'):
            quantity_hold = form_review['quantity_hold_reason']
            # The old missing-composition judgment is fulfilled only by a
            # complete reviewed vector validated against every original row.
            # Scalar aggregates, manual overrides and other holds still block.
            complete_vector = (
                quantity_hold in {'mixed_package_component_contents_unresolved',
                                  'distinct_tea_recipe_sold_count_allocation_not_declared'}
                and not assignment.get('package') and package
                and form_review.get('leaf') == category_id
                and valid_source_component_variant(package)
                and package['attributes']['source_component_listing']['category_id'] == category_id
                and all(row['package'] and valid_source_component_variant(row['package'])
                        and row['package']['attributes']['source_component_listing']['category_id'] == category_id
                        and source_component_signature(row['package']['attributes']['source_components'])
                        == source_component_signature(package['attributes']['source_components']) for row in members)
            )
            # Original declared whole contents can also be retained when the
            # recipes are unknown. This does not fulfill recipe allocation or
            # permit homogeneous pricing; every source row must carry the same
            # registered, source-bound scalar comparison hold.
            from core.reviewed_source_evidence import (valid_explicit_listing_variant, package_comparison_reason,
                                                      original_quantity_assertion)
            original_assertion = original_quantity_assertion(package) if package else None
            original_scope = (quantity_hold == 'source_declared_package_quantity_contradiction'
                and original_assertion is not None
                and all(original_assertion['raw_payload_hashes'].get(row['raw_record_id'])
                        == row['raw_payload_sha256'] for row in members))
            complete_scalar = (
                (quantity_hold == 'distinct_recipe_sold_count_allocation_not_declared' or original_scope)
                and not assignment.get('package') and package
                and form_review.get('leaf') == category_id
                and valid_explicit_listing_variant(package)
                and package_comparison_reason(package) == 'contents_identity_and_allocation_unverified'
                and package['attributes']['explicit_listing_quantity_review']['category_id'] == category_id
                and all(row['package'] and valid_explicit_listing_variant(row['package'])
                        and row['package']['attributes']['explicit_listing_quantity_review']
                        == package['attributes']['explicit_listing_quantity_review'] for row in members)
            )
            complete_parent = (parent_selection is not None
                and quantity_hold == parent_selection['original_selection_hold_reason']
                and form_review.get('leaf') == category_id)
            complete_outer = (outer_count is not None
                and quantity_hold == 'mixed_package_component_contents_unresolved'
                and form_review.get('leaf') == category_id)
            complete_entitlement = ((entitlement is not None or partial_retail is not None)
                and quantity_hold == package['attributes']['explicit_listing_quantity_review']['original_quantity_hold_reason']
                and form_review.get('leaf') == category_id)
            if not (complete_vector or complete_scalar or complete_parent or complete_outer or complete_entitlement):
                reasons.append(quantity_hold)
        physical_alias_keys = set()
        if title_history and valid_physical_device_variant(package):
            physical_alias_keys = _physical_title_history_alias_keys(title_history, package, members, category_id)
            if physical_alias_keys is None:
                title_history = None
                physical_alias_keys = set()
                if multiple_titles:
                    reasons.append('source_title_changed')
        if package is None:
            reasons.append("unit_unresolved")
        elif title_history and not valid_physical_device_variant(package):
            # Physical aliases are consumed from the source-bound code registry.
            # Even additive audit attributes would alter the historical variant.
            package.setdefault('attributes', {})['source_title_history'] = deepcopy(title_history)
        if reasons:
            for row in members:
                hold(row, reasons + row["issues"])
            continue
        valid = []
        for row in members:
            issues = row["issues"]
            if assignment.get("package"):
                issues = [issue for issue in issues if not issue.startswith(("unit_", "bundle_", "mixed_package_", "multiple_package_"))]
            blocking_issues = [issue for issue in issues if issue not in PROMOTION_REVIEW_ISSUES]
            if blocking_issues:
                hold(row, issues)
            else:
                from core.reviewed_source_evidence import package_publication_reason
                promotion_reasons = set(issues) & PROMOTION_REVIEW_ISSUES
                publication_reason = package_publication_reason(package)
                review_reasons = sorted(promotion_reasons | ({publication_reason} if publication_reason else set()))
                valid.append({
                    **row,
                    "offer_state": "pending_review" if review_reasons else "active",
                    "offer_review_reasons": review_reasons,
                    "promotion_type": "unknown" if promotion_reasons else row["promotion_type"],
                    "discount_rate": None if promotion_reasons else row["discount_rate"],
                })
        if not valid:
            continue
        canonical_name = _text(assignment.get("canonical_name")) or reviewed_name or latest["source_title"]
        brand = validated_brand(assignment.get("brand")) if "brand" in assignment else latest["brand"]
        # An explicit reviewed group is the only route to a cross-mart merge.
        product_id = stable_id("prod", "reviewed", group_key) if group_key else stable_id("prod", "source", *key)
        components = component_signature(package)
        # Keep all pre-existing scalar IDs byte-for-byte stable. The sold set's
        # exact multiset, not its pricing total, identifies new component variants.
        from core.reviewed_source_evidence import valid_nonmeasured_variant, source_selection_alternatives
        alternatives = source_selection_alternatives(package)
        # Nonexact numbers are descriptive evidence, never exact mass identity.
        # Voucher face value is a known entitlement descriptor, never quote price.
        entitlement_identity = ((entitlement['kind'], entitlement['denomination_amount'],
                                 entitlement['denomination_currency'], entitlement['certificate_medium'])
                                if entitlement and entitlement['kind'] == 'stored_value_voucher'
                                else (entitlement['kind'],) if entitlement else None)
        variant_id = (stable_id('var', product_id, 'source-partial-retail-observation-v1') if partial_retail else
                      stable_id('var', product_id, 'source-incomplete-entitlement-observation-v1', entitlement_identity)
                      if entitlement else
                      stable_id('var', product_id, 'source-nonexact-contents-observation-v1', nonexact['kind'])
                      if nonexact else
                      stable_id('var', product_id, 'source-outer-set-count-v1', outer_count)
                      if outer_count else
                      stable_id('var', product_id, 'source-selectable-alternatives-v1', alternatives)
                      if alternatives else
                      stable_id('var', product_id, 'source-selectable-parent-v1', parent_selection['dimension'],
                               package['package_quantity'], package['package_unit'], package['bundle_count'])
                      if parent_selection else
                      stable_id('var', product_id, 'physical-device-specification-v1', package['attributes']['physical_device_specification'])
                      if valid_physical_device_variant(package) else
                      stable_id('var', product_id, 'nonmeasured-listing-v1', package['attributes']['nonmeasured_listing'])
                      if valid_nonmeasured_variant(package) else
                      stable_id('var', product_id, 'declared-count-interval-unit-v2', package['attributes']['count_interval'])
                      if valid_count_interval_variant(package) and package['attributes']['count_interval_listing'].get('identity_basis') == 'declared_interval_unit_v2' else
                      stable_id('var', product_id, 'declared-count-interval-v1', package['attributes']['count_interval_listing'])
                      if valid_count_interval_variant(package) else
                      stable_id('var', product_id, 'source-component-vector-v1', source_component_signature(package['attributes']['source_components']))
                      if valid_source_component_variant(package) else
                      stable_id("var", product_id, package["package_quantity"], package["package_unit"], package["bundle_count"])
                      if components is None else stable_id("var", product_id, "component-set-v1", components))
        listing_id = stable_id("listing", *key)
        product = products.setdefault(product_id, {
            "public_product_id": product_id, "unified_category_id": category_id,
            "canonical_name": canonical_name, "brand": brand,
            "aliases": sorted(set(assignment.get("aliases") or [])), "keywords": sorted(set(assignment.get("keywords") or [])),
            "classification_confidence": float(confidence), "review_status": assignment.get("review_status") or "classified",
            "primary_image_url": latest["image_url"] or None,
            "is_active": False,
            "attributes": {"identity_basis": "source_partial_retail_observation" if partial_retail else "source_incomplete_entitlement_observation" if entitlement else "source_nonexact_contents_observation" if nonexact else "source_incomplete_set_observation" if outer_count else "source_selectable_parent_observation" if parent_selection else "reviewed_product_group" if group_key else "source_scoped", "product_group_key": group_key or None, "classification_reason": assignment.get("classification_reason"), "classification_attributes": {}, "classification_attribute_evidence": [], "source_ingestion_ids": []},
        })
        product["attributes"]["classification_attributes"] = _merge_classification_attributes(
            product["attributes"]["classification_attributes"], assignment_attributes[key],
        )
        product["attributes"]["classification_attribute_evidence"].append(deepcopy(attribute_evidence[key]))
        product["is_active"] = product["is_active"] or any(row["offer_state"] == "active" for row in valid)
        product["classification_confidence"] = min(product["classification_confidence"], float(confidence))
        if product["classification_confidence"] < 0.80:
            # Every low-confidence contributor already passed its explicit
            # approved check above; retain the warning on the shared product.
            product["review_status"] = "approved"
        product["aliases"] = sorted(set(product["aliases"]) | set(assignment.get("aliases") or []))
        product["keywords"] = sorted(set(product["keywords"]) | set(assignment.get("keywords") or []))
        product["attributes"]["source_ingestion_ids"] = sorted(set(product["attributes"]["source_ingestion_ids"]) | {row["ingestion_id"] for row in valid})
        variant_name = (canonical_name if partial_retail or entitlement or nonexact or alternatives or valid_nonmeasured_variant(package) or valid_count_interval_variant(package) or valid_physical_device_variant(package) else
                        f"{canonical_name} {package['package_quantity']:g}{package['package_unit']}×{package['bundle_count']}") if assignment.get("canonical_name") or reviewed_name else latest["source_title"]
        variants.setdefault(variant_id, {"public_variant_id": variant_id, "public_product_id": product_id, "variant_name": variant_name, **package, "attributes": {**package.get("attributes", {}), "specification_basis": "reviewed_override" if assignment.get("package") else "source_structured_and_explicit_text"}})
        if parent_selection or outer_count or nonexact or entitlement or partial_retail:
            variants[variant_id]['is_active'] = False
        # Every accepted observation may have its own reviewed URL/native path.
        # The listing's common normalized specification was checked above.
        for row in valid:
            review = source_reviews().get((key[0], tuple(row['source_category_path']), row['source_title']))
            if review is None:
                eligibility = source_observation_eligibility_review(
                    row['raw_payload'], row['raw_payload'].get('attributes') or {}, row['source_title'])
                if (eligibility is not None and not eligibility[1]
                        and eligibility[0]['category_id'] == category_id):
                    review = eligibility[0]['required_source']
            if review:
                evidence_review = {'source_name': key[0], 'source_record_key': key[1], **deepcopy(review)}
                reviews = variants[variant_id]['attributes'].setdefault('source_evidence_reviews', [])
                if evidence_review not in reviews:
                    reviews.append(evidence_review)
        bundle["source_listings"].append({
            "public_source_listing_id": listing_id, "public_variant_id": variant_id,
            "source_name": key[0], "source_record_key": key[1], "source_title": latest["source_title"],
            "source_url": latest["source_url"] or None, "image_url": latest["image_url"] or None,
            "source_unit_text": package["display_unit"] or None,
            "source_category_paths": [list(path) for path in sorted({tuple(row["source_category_path"]) for row in members})],
            "source_ingestion_ids": sorted({row["ingestion_id"] for row in members}),
            **({'is_active': False} if parent_selection or outer_count or nonexact or entitlement or partial_retail else {}),
        })
        offers: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in valid:
            offer_id = stable_id("offer", listing_id, row["crawled_at"], row["timestamp_source"], row["observed_time_precision"], *(row[field] for field in ("price", "original_price", "promotion_type", "event_name", "promotion_conditions", "valid_from", "valid_to")))
            offers[offer_id].append(row)
        for offer_id, evidence_rows in sorted(offers.items()):
            first = evidence_rows[0]
            offer = {field: first[field] for field in ("price", "original_price", "discount_rate", "price_state", "promotion_type", "event_name", "promotion_conditions", "valid_from", "valid_to", "crawled_at")}
            offer.update({
                "public_offer_event_id": offer_id, "public_source_listing_id": listing_id,
                "raw_record_id": first["raw_record_id"], "offer_state": first["offer_state"],
                "standard_unit_price": None, "price_per_100g": None,
                "raw_evidence": {
                    "promotion_conditions": deepcopy(first["promotion_conditions"]),
                    "observations": [{field: deepcopy(row[field]) for field in ("raw_record_id", "ingestion_id", "crawled_at", "timestamp_source", "observed_time_precision", "ingestion_received_at", "source_category_path", "mart_native_category_id", "raw_payload_sha256", "raw_payload")} for row in evidence_rows],
                },
                "audit_provenance": {"builder_version": BUILDER_VERSION, "source_ingestion_ids": sorted({row["ingestion_id"] for row in evidence_rows}), "raw_record_ids": [row["raw_record_id"] for row in evidence_rows], "observation_count": len(evidence_rows), "timestamp_source": first["timestamp_source"], "observed_time_precision": first["observed_time_precision"], "naive_timestamp_timezone": "UTC" if first["timestamp_source"] == "ingestion_received_at" else "Asia/Seoul", "review_reasons": first["offer_review_reasons"], "publication_status": "not_approved"},
            })
            transaction = comparable_transaction_or_none(
                current_price=first["price"], promotion_type=first["promotion_type"],
                promotion_conditions=first["promotion_conditions"],
            ) if first["offer_state"] == "active" else None
            measure = package_pricing_measure(package)
            if transaction and measure:
                total_spend, received_packages = transaction
                offer["standard_unit_price"] = round(total_spend * 100 / (measure[0] * received_packages), 4)
                if measure[1] == "g":
                    offer["price_per_100g"] = offer["standard_unit_price"]
            bundle["offers"].append(offer)
            if first["offer_state"] == "pending_review":
                bundle["review_issues"].append({
                    "reason": ("source_selection_pending_review" if parent_selection else
                               "source_version_pending_review" if package_publication_reason(package)
                               else "promotion_pending_review"), "reasons": first["offer_review_reasons"],
                    "public_product_id": product_id, "public_variant_id": variant_id,
                    "public_source_listing_id": listing_id, "public_offer_event_id": offer_id,
                    "source_ingestion_ids": sorted({row["ingestion_id"] for row in evidence_rows}),
                    "raw_record_ids": [row["raw_record_id"] for row in evidence_rows],
                    "review_status": "pending", "publication_status": "not_approved",
                })
            observed = datetime.fromisoformat(first["crawled_at"].replace("Z", "+00:00")).astimezone(KST)
            start = observed.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=observed.weekday())
            week_id = stable_id("week", start.date().isoformat(), "Asia/Seoul")
            weeks[week_id] = {"public_week_bucket_id": week_id, "week_start": _timestamp(start), "week_end": _timestamp(start + timedelta(days=7))}
            comparable = transaction[0] if transaction else None
            bundle["offer_week_links"].append({"public_offer_event_id": offer_id, "public_week_bucket_id": week_id, "observed_min_price": comparable, "observed_max_price": comparable})
            for row in evidence_rows:
                bundle["observation_accounting"].append({"raw_record_id": row["raw_record_id"], "ingestion_id": row["ingestion_id"], "status": "included", "offer_state": row["offer_state"], "reasons": row["offer_review_reasons"], "publication_status": "not_approved", "public_source_listing_id": listing_id, "public_offer_event_id": offer_id})
                match_key = _runtime_match_key(row)
                if match_key and not (parent_selection or outer_count or nonexact or entitlement or partial_retail):
                    rule_candidates[match_key].append({"match_key": match_key, "public_product_id": product_id, "public_variant_id": variant_id, "brand": brand, "name_core": canonical_name, "pack_qty": package["package_quantity"], "pack_unit": package["package_unit"], "confidence": float(confidence), "raw_record_id": row["raw_record_id"]})
        for match_key in sorted(physical_alias_keys):
            for row in valid:
                rule_candidates[match_key].append({"match_key": match_key, "public_product_id": product_id, "public_variant_id": variant_id, "brand": brand, "name_core": canonical_name, "pack_qty": package["package_quantity"], "pack_unit": package["package_unit"], "confidence": float(confidence), "raw_record_id": row["raw_record_id"]})
    for match_key, candidates in sorted(rule_candidates.items()):
        destinations = {(row["public_product_id"], row["public_variant_id"]) for row in candidates}
        if len(destinations) > 1:
            bundle["review_issues"].append({"reason": "runtime_match_key_collision", "match_key": match_key, "raw_record_ids": sorted({row["raw_record_id"] for row in candidates})})
            continue
        if min(row["confidence"] for row in candidates) < 0.80:
            continue
        rule = {key: value for key, value in candidates[0].items() if key != "raw_record_id"}
        rule["confidence"] = min(row["confidence"] for row in candidates)
        rule["notes"] = "initial seed; exact crawler key; " + ",".join(sorted({row["raw_record_id"] for row in candidates}))
        rule["source_raw_record_ids"] = sorted({row["raw_record_id"] for row in candidates})
        bundle["match_rules"].append(rule)
    bundle["products"] = [products[key] for key in sorted(products)]
    bundle["variants"] = [variants[key] for key in sorted(variants)]
    # Reviewed browsing groups preserve source/variant/event IDs. Formal
    # imports consume this same explicit registry, never text similarity.
    from core.catalog_identity import reviewed_product_fields, with_category_keywords
    variant_products = {row['public_variant_id']: row['public_product_id'] for row in bundle['variants']}
    listings_by_product = defaultdict(list)
    for listing in bundle['source_listings']:
        listings_by_product[variant_products.get(listing['public_variant_id'])].append(listing)
    for index, product in enumerate(bundle['products']):
        product = reviewed_product_fields(product, listings_by_product[product['public_product_id']])
        product = with_category_keywords(product, category_rows, bundle['keywords'])
        bundle['products'][index] = product
    bundle["week_buckets"] = [weeks[key] for key in sorted(weeks)]
    bundle["unresolved"].sort(key=lambda row: (row["ingestion_id"], row["item_index"]))
    bundle["observation_accounting"].sort(key=lambda row: row["raw_record_id"])
    classified_keys = set()
    for key, assignment in assignments.items():
        confidence = _number(assignment.get("classification_confidence"))
        if assignment.get("unified_category_id") in leaves and confidence is not None and 0 <= confidence <= 1 and assignment.get("review_status") != "pending":
            if confidence >= Decimal("0.80") or assignment.get("review_status") == "approved":
                classified_keys.add(key)
    classified_rows = [row for row in rows if (row["source_name"], row["source_record_key"]) in classified_keys]
    included_raw_ids = {row["raw_record_id"] for row in bundle["observation_accounting"] if row["status"] == "included"}
    pending_raw_ids = {row["raw_record_id"] for row in bundle["observation_accounting"] if row.get("offer_state") == "pending_review"}
    active_raw_ids = included_raw_ids - pending_raw_ids
    bundle["build_report"] = {
        "source_observations": len(rows), "included_observations": sum(row["status"] == "included" for row in bundle["observation_accounting"]),
        "included_means": "staged_only_not_publicly_approved", "public_approval": False,
        "staged_observations": len(included_raw_ids), "active_offer_observations": len(active_raw_ids),
        "pending_promotion_observations": len(pending_raw_ids),
        "pending_promotion_offers": sum(offer["offer_state"] == "pending_review" for offer in bundle["offers"]),
        "inactive_product_groups": sum(not product["is_active"] for product in bundle["products"]),
        "unresolved_observations": len(bundle["unresolved"]), "source_ingestion_ids": bundle["source_ingestion_ids"],
        "by_mart": dict(sorted(Counter(row["source_name"] or "unknown" for row in rows).items())),
        "classification_coverage": {"observations": len(classified_rows), "source_listings": len(classified_keys & set(groups)), "by_mart": dict(sorted(Counter(row["source_name"] for row in classified_rows).items()))},
        "offer_coverage_by_mart": dict(sorted(Counter(row["source_name"] for row in rows if row["raw_record_id"] in included_raw_ids).items())),
        "active_offer_coverage_by_mart": dict(sorted(Counter(row["source_name"] for row in rows if row["raw_record_id"] in active_raw_ids).items())),
        "pending_promotion_by_mart": dict(sorted(Counter(row["source_name"] for row in rows if row["raw_record_id"] in pending_raw_ids).items())),
        "timestamp_sources": dict(sorted(Counter(row["timestamp_source"] for row in rows).items())),
        "unresolved_reasons": dict(sorted(reason_counts.items())),
        "entity_counts": {key: len(bundle[key]) for key in ("products", "variants", "source_listings", "offers", "match_rules")},
        "runtime_match_key_collisions": sum(issue["reason"] == "runtime_match_key_collision" for issue in bundle["review_issues"]),
        "classification_attribute_conflict_groups": len(attribute_conflicts),
        "exact_retry_observations_collapsed": sum(offer["audit_provenance"]["observation_count"] - 1 for offer in bundle["offers"]),
    }
    assert len(bundle["observation_accounting"]) == len(rows), "source observation was lost"
    return bundle
