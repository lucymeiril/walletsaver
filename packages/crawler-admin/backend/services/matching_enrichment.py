"""Enrich crawler rows from completed MatchingEntry knowledge.

A runtime hit is deliberately stricter than "matching_entries contains this
key".  The entry must resolve to an active Product; otherwise the row stays a
miss so it can return to the external-classification workflow and be repaired.
The db-admin database is read only from this module.
"""
from __future__ import annotations

import json
import logging
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import text

from core.match_key import NO_BRAND_SENTINEL, build_match_key, normalize_pack_identity
from core.product_units import parse_package_quantity
from services.db_admin_readonly import (
    _table_columns, bulk_lookup_match_statuses, get_db_admin_session,
)

logger = logging.getLogger(__name__)


def _extract_str(row: dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
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

    if not name:
        return None, "no_name"
    if not brand:
        row["brand"] = NO_BRAND_SENTINEL
        brand = NO_BRAND_SENTINEL
    return build_match_key(brand, name, pack_qty, pack_unit), None


def _load_matching_entries(session, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}

    result: dict[str, dict[str, Any]] = {}
    normalized_columns = _table_columns(session, "matching_entries")
    extra_columns = [
        column
        for column in ("public_product_id", "public_variant_id")
        if column in normalized_columns
    ]
    extra_select = (", " + ", ".join(extra_columns)) if extra_columns else ""
    unique_keys = list(dict.fromkeys(keys))
    for offset in range(0, len(unique_keys), 900):
        chunk = unique_keys[offset : offset + 900]
        placeholders = ", ".join(f":k{i}" for i in range(len(chunk)))
        params = {f"k{i}": key for i, key in enumerate(chunk)}
        rows = session.execute(
            text(
                "SELECT id, match_key, canonical_product_id, category_id, keyword_ids, "
                f"confidence, source, brand, name_core, pack_qty, pack_unit{extra_select} "
                "FROM matching_entries "
                f"WHERE match_key IN ({placeholders})"
            ),
            params,
        ).fetchall()
        for row in rows:
            keyword_ids = row[4]
            if isinstance(keyword_ids, str):
                try:
                    keyword_ids = json.loads(keyword_ids)
                except (TypeError, ValueError, json.JSONDecodeError):
                    keyword_ids = None
            entry = {
                "id": row[0],
                "match_key": row[1],
                "canonical_product_id": row[2],
                "category_id": row[3],
                "keyword_ids": keyword_ids,
                "confidence": row[5],
                "source": row[6],
                "brand": row[7],
                "name_core": row[8],
                "pack_qty": row[9],
                "pack_unit": row[10],
            }
            for index, column in enumerate(extra_columns, start=11):
                entry[column] = row[index]
            result[row[1]] = entry
    return result


def _load_products(session, canonical_ids: list[str]) -> dict[str, dict[str, Any]]:
    numeric_ids: list[int] = []
    for value in canonical_ids:
        try:
            numeric_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not numeric_ids:
        return {}

    result: dict[str, dict[str, Any]] = {}
    unique_ids = list(dict.fromkeys(numeric_ids))
    for offset in range(0, len(unique_ids), 900):
        chunk = unique_ids[offset : offset + 900]
        placeholders = ", ".join(f":p{i}" for i in range(len(chunk)))
        params = {f"p{i}": value for i, value in enumerate(chunk)}
        rows = session.execute(
            text(
                "SELECT id, name, display_name, brand, name_core, pack_qty, pack_unit, "
                "category_id, unified_category_id "
                "FROM products "
                f"WHERE id IN ({placeholders}) AND is_active = 1"
            ),
            params,
        ).fetchall()
        for row in rows:
            result[str(row[0])] = {
                "id": row[0],
                "name": row[1],
                "display_name": row[2],
                "brand": row[3],
                "name_core": row[4],
                "pack_qty": row[5],
                "pack_unit": row[6],
                "category_id": row[7],
                "unified_category_id": row[8],
            }
    return result


def _load_normalized_products(session, public_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not public_ids or not _table_columns(session, "normalized_canonical_products"):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(set(public_ids)), 900):
        chunk = list(dict.fromkeys(public_ids))[offset : offset + 900]
        placeholders = ", ".join(f":p{i}" for i in range(len(chunk)))
        params = {f"p{i}": value for i, value in enumerate(chunk)}
        rows = session.execute(text(
            "SELECT public_product_id, canonical_name, brand, unified_category_id "
            "FROM normalized_canonical_products "
            f"WHERE public_product_id IN ({placeholders}) AND is_active=1"
        ), params).mappings().all()
        result.update({str(row["public_product_id"]): dict(row) for row in rows})
    return result


def _load_normalized_variants(session, variant_ids: list[str]) -> dict[str, dict[str, Any]]:
    required = {"public_variant_id", "public_product_id", "package_quantity", "package_unit", "bundle_count", "is_active"}
    if not variant_ids or not required <= _table_columns(session, "normalized_product_variants"):
        return {}
    result: dict[str, dict[str, Any]] = {}
    listing_columns = _table_columns(session, "normalized_source_listings")
    has_listing_evidence = {"public_variant_id", "source_name", "source_record_key", "source_title", "is_active"} <= listing_columns
    unique_ids = list(dict.fromkeys(variant_ids))
    for offset in range(0, len(unique_ids), 900):
        chunk = unique_ids[offset : offset + 900]
        placeholders = ", ".join(f":v{i}" for i in range(len(chunk)))
        params = {f"v{i}": value for i, value in enumerate(chunk)}
        rows = session.execute(text(
            "SELECT public_variant_id, public_product_id, package_quantity, package_unit, bundle_count "
            "FROM normalized_product_variants "
            f"WHERE public_variant_id IN ({placeholders}) AND is_active=1"
        ), params).mappings().all()
        result.update({str(row["public_variant_id"]): dict(row) for row in rows})
        if has_listing_evidence:
            for variant_id in chunk:
                if variant_id in result:
                    result[variant_id]["source_listings"] = []
            listings = session.execute(text(
                "SELECT public_variant_id, source_name, source_record_key, source_title "
                "FROM normalized_source_listings "
                f"WHERE public_variant_id IN ({placeholders}) AND is_active=1"
            ), params).mappings().all()
            for listing in listings:
                variant = result.get(str(listing["public_variant_id"]))
                if variant is not None:
                    variant.setdefault("source_listings", []).append(dict(listing))
    return result


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
    if quantity is None or unit not in {"kg", "g", "mg", "l", "ml", "cc", *_COUNT_UNITS}:
        return None
    # Catalog T means a count (tea bags/sticks), not the mass unit ton accepted
    # by the general match-key canonicalizer. Keep all count dimensions intact.
    if unit in _COUNT_UNITS and unit not in {"ea", "개"}:
        return quantity, unit
    return normalize_pack_identity(quantity, unit)


def _source_package(row: dict[str, Any]) -> tuple[tuple[float, str, int] | None, str | None]:
    """Require structured quantity/unit; title text may disprove, not invent it.

    Old DiscountItem rows omitted bundle_count but retained explicit ×N in
    display_unit. Restore only that explicit multiplier, checking all evidence.
    """
    layers = [row, *[row[key] for key in ("attributes", "attrs") if isinstance(row.get(key), dict)]]
    quantities = [layer[key] for layer in layers for key in _QUANTITY_KEYS if layer.get(key) not in (None, "")]
    units = [layer[key] for layer in layers for key in _UNIT_KEYS if layer.get(key) not in (None, "")]
    if not quantities or not units:
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
        if any(source_name(name) != expected_name for name in names):
            return "normalized_source_name_conflict"
    else:
        # Older manually reviewed normalized entries may lack listing evidence.
        # They can use only their exact reviewed key name, never a guessed alias.
        key_name = key.split("|")[1] if len(key.split("|")) == 4 else None
        if any(build_match_key(None, name, None, None).split("|")[1] != key_name for name in names):
            return "normalized_source_name_conflict"
    package, reason = _source_package(row)
    if reason:
        return reason
    target = _package_identity(variant.get("package_quantity"), variant.get("package_unit"))
    target_count = _positive_number(variant.get("bundle_count"))
    if target is None or target_count is None or not target_count.is_integer():
        return "normalized_variant_unavailable"
    if package != (*target, int(target_count)):
        return "normalized_variant_conflict"
    return None


def lookup_row_match_statuses(session, keyed_rows: list[tuple[dict[str, Any], str]]) -> list[str]:
    """Use the same source/variant contract during export, per row not per key."""
    keys = [key for _, key in keyed_rows]
    statuses = bulk_lookup_match_statuses(session, keys)
    entries = _load_matching_entries(session, keys)
    variants = _load_normalized_variants(session, [str(entry["public_variant_id"]) for entry in entries.values() if entry.get("public_variant_id")])
    result = []
    for row, key in keyed_rows:
        status = statuses.get(key, "key_not_found")
        entry = entries.get(key, {})
        if status == "normalized_source_verification_required":
            status = _normalized_source_reason(row, key, entry, variants) or "hit"
        result.append(status)
    return result


def _mark_miss(item: dict[str, Any], reason: str) -> None:
    item["matching_status"] = "miss"
    item["matching_miss_reason"] = reason
    item.pop("canonical_product_id", None)
    item.pop("canonical_name", None)
    item.pop("public_product_id", None)
    item.pop("public_variant_id", None)


def enrich_items_with_matching_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate rows only when a MatchingEntry resolves to an active Product."""
    if not items:
        return items

    keyed: list[tuple[dict[str, Any], Optional[str], Optional[str]]] = []
    valid_keys: list[str] = []
    for item in items:
        key, reason = _match_key_for_row(item)
        keyed.append((item, key, reason))
        if key is not None:
            valid_keys.append(key)

    session_iter = get_db_admin_session()
    session = next(session_iter)
    try:
        entries = _load_matching_entries(session, valid_keys)
        products = _load_products(
            session,
            [
                str(entry["canonical_product_id"])
                for entry in entries.values()
                if entry.get("canonical_product_id") not in (None, "")
            ],
        )
        normalized_products = _load_normalized_products(
            session,
            [str(entry["public_product_id"]) for entry in entries.values() if entry.get("public_product_id")],
        )
        normalized_variants = _load_normalized_variants(
            session,
            [str(entry["public_variant_id"]) for entry in entries.values() if entry.get("public_variant_id")],
        )

        for item, key, reason in keyed:
            if key is None:
                _mark_miss(item, reason or "unkeyable")
                continue

            item["match_key"] = key
            entry = entries.get(key)
            if entry is None:
                _mark_miss(item, "key_not_found")
                continue

            # Keep provenance for diagnosis, but do not expose partial semantic
            # metadata as a hit until its Product soft-link is usable.
            item["matching_entry_id"] = entry["id"]
            item["matching_source"] = entry.get("source")
            item["matching_confidence"] = entry.get("confidence")

            try:
                confidence = float(entry.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0
            if not math.isfinite(confidence) or confidence < 0.80:
                _mark_miss(item, "low_confidence")
                continue

            public_product_id = entry.get("public_product_id")
            if public_product_id:
                normalized_product = normalized_products.get(str(public_product_id))
                public_variant_id = entry.get("public_variant_id")
                if normalized_product is None:
                    _mark_miss(item, "normalized_product_unavailable")
                    continue
                reason = _normalized_source_reason(item, key, entry, normalized_variants)
                if reason:
                    _mark_miss(item, reason)
                    continue
                original_name = _extract_str(
                    item,
                    ["source_title", "name", "productName", "itemName", "title"],
                )
                if original_name:
                    item.setdefault("source_title", original_name)
                item["matching_status"] = "hit"
                item.pop("matching_miss_reason", None)
                item["public_product_id"] = str(public_product_id)
                if public_variant_id:
                    item["public_variant_id"] = str(public_variant_id)
                item["canonical_name"] = normalized_product.get("canonical_name")
                if normalized_product.get("brand"):
                    item["brand"] = normalized_product["brand"]
                if normalized_product.get("unified_category_id"):
                    item["unified_category_id"] = normalized_product["unified_category_id"]
                continue

            canonical_id = entry.get("canonical_product_id")
            product = products.get(str(canonical_id)) if canonical_id not in (None, "") else None
            if product is None:
                _mark_miss(item, "canonical_product_unavailable")
                continue

            item["matching_status"] = "hit"
            item.pop("matching_miss_reason", None)
            if entry.get("category_id"):
                item["category_id"] = entry["category_id"]
            if entry.get("keyword_ids") is not None:
                item["matching_keyword_ids"] = entry["keyword_ids"]

            original_name = _extract_str(
                item,
                ["source_title", "name", "productName", "itemName", "title"],
            )
            if original_name:
                item.setdefault("source_title", original_name)

            item["canonical_product_id"] = product["id"]
            item["canonical_name"] = product.get("display_name") or product.get("name")
            if product.get("name"):
                item["name"] = product["name"]
            if product.get("brand") and product.get("brand") != NO_BRAND_SENTINEL:
                item["brand"] = product["brand"]
            if product.get("name_core"):
                item["name_core"] = product["name_core"]
            if product.get("pack_qty") is not None:
                item["pack_qty"] = product["pack_qty"]
            if product.get("pack_unit"):
                item["pack_unit"] = product["pack_unit"]
            if product.get("category_id"):
                item["category_id"] = product["category_id"]
            if product.get("unified_category_id"):
                item["unified_category_id"] = product["unified_category_id"]
    except Exception:
        logger.exception("matching enrichment failed; leaving crawler rows unresolved")
        for item, key, reason in keyed:
            if key is not None:
                item["match_key"] = key
            _mark_miss(item, reason or "matching_lookup_unavailable")
    finally:
        session_iter.close()

    return items
