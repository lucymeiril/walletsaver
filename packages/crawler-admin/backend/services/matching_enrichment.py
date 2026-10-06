"""Enrich crawler rows from completed MatchingEntry knowledge.

A runtime hit is deliberately stricter than "matching_entries contains this
key". The entry must resolve to a usable identity and the verified variant.
Reviewed offer-pending normalized identities stay distinct from available
offers; legacy/manual inactive products remain misses.
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
from collections.abc import Mapping

from sqlalchemy import text

from core.match_key import NO_BRAND_SENTINEL, build_match_key, normalize_pack_identity
from core.product_units import parse_package_quantity
from core.reviewed_source_evidence import source_review_evidence, source_review_matches, nonmeasured_listing_review, valid_nonmeasured_variant, explicit_listing_package, valid_explicit_listing_variant, source_observation_eligibility_review
from core.reviewed_source_evidence import (count_interval_listing_package, valid_count_interval_variant,
                                          listing_title_history, valid_listing_title_history,
                                          source_component_listing_package, valid_source_component_variant)
from core.catalog_quantity import normalize_catalog_package, uses_reviewed_quantity_rules, reviewed_price_basis_identity
from core.catalog_quantity import component_signature, uses_reviewed_component_rules
from core.catalog_quantity import uses_reviewed_residual_quantity_rules, uses_approximate_measurement_rules
from core.catalog_quantity import physical_device_package, valid_physical_device_variant
from services.db_admin_readonly import (
    _table_columns, bulk_lookup_match_statuses, get_db_admin_session, load_normalized_identity_products,
)

logger = logging.getLogger(__name__)


def _extract_str(row: dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


from core.catalog_matching import _extract_float, _match_key_for_row


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
    return load_normalized_identity_products(session, public_ids)


def _load_normalized_variants(session, variant_ids: list[str], pending_product_ids: set[str] | None = None) -> dict[str, dict[str, Any]]:
    required = {"public_variant_id", "public_product_id", "package_quantity", "package_unit", "bundle_count", "is_active"}
    if not variant_ids or not required <= _table_columns(session, "normalized_product_variants"):
        return {}
    result: dict[str, dict[str, Any]] = {}
    variant_columns = _table_columns(session, 'normalized_product_variants')
    optional_columns = [column for column in ('attributes', 'standard_unit') if column in variant_columns]
    optional_select = ''.join(', v.' + column for column in optional_columns)
    parent_columns = _table_columns(session, 'normalized_canonical_products')
    has_parent_category = {'public_product_id', 'unified_category_id'} <= parent_columns
    parent_select = ', p.unified_category_id' if has_parent_category else ', NULL AS unified_category_id'
    parent_join = (' LEFT JOIN normalized_canonical_products p ON p.public_product_id=v.public_product_id '
                   if has_parent_category else ' ')
    listing_columns = _table_columns(session, "normalized_source_listings")
    has_listing_evidence = {"public_variant_id", "source_name", "source_record_key", "source_title", "is_active"} <= listing_columns
    unique_ids = list(dict.fromkeys(variant_ids))
    for offset in range(0, len(unique_ids), 900):
        chunk = unique_ids[offset : offset + 900]
        placeholders = ", ".join(f":v{i}" for i in range(len(chunk)))
        params = {f"v{i}": value for i, value in enumerate(chunk)}
        rows = session.execute(text(
            "SELECT v.public_variant_id, v.public_product_id, v.package_quantity, v.package_unit, v.bundle_count " + optional_select + parent_select + ' '
            "FROM normalized_product_variants v" + parent_join +
            f"WHERE v.public_variant_id IN ({placeholders}) AND v.is_active=1"
        ), params).mappings().all()
        result.update({str(row["public_variant_id"]): dict(row) for row in rows})
        for row in rows:
            variant = result[str(row['public_variant_id'])]
            if 'attributes' in variant and isinstance(variant['attributes'], str):
                try:
                    variant['attributes'] = json.loads(variant['attributes'])
                except (ValueError, TypeError):
                    variant['attributes'] = None  # malformed component data must miss
        if has_listing_evidence:
            for variant_id in chunk:
                if variant_id in result:
                    result[variant_id]["source_listings"] = []
            listings = session.execute(text(
                "SELECT public_variant_id, source_name, source_record_key, source_title "
                + (", source_url " if 'source_url' in listing_columns else '') +
                "FROM normalized_source_listings "
                f"WHERE public_variant_id IN ({placeholders}) AND is_active=1"
            ), params).mappings().all()
            for listing in listings:
                variant = result.get(str(listing["public_variant_id"]))
                if variant is not None:
                    variant.setdefault("source_listings", []).append(dict(listing))
            # Old scalar variants retain reviewed classification and native
            # listing URLs rather than the later source_evidence_reviews field.
            # Bind only offer-pending identities to those exact persisted URLs;
            # existing richer reviews retain their native-context requirements.
            for variant_id in chunk:
                variant = result.get(variant_id)
                if not variant or str(variant['public_product_id']) not in (pending_product_ids or set()):
                    continue
                attrs = variant.get('attributes')
                if isinstance(attrs, dict) and 'source_evidence_reviews' not in attrs:
                    attrs['source_evidence_reviews'] = [
                        {'source_name': listing['source_name'], 'source_record_key': listing['source_record_key'],
                         'source_urls': [listing.get('source_url')], 'source_fields': {}}
                        for listing in variant.get('source_listings', [])]
    return result


from core.catalog_matching import (
    _positive_number, _package_identity, _source_package, _normalized_source_reason,
)


def lookup_row_match_statuses(session, keyed_rows: list[tuple[dict[str, Any], str]]) -> list[str]:
    """Use the same source/variant contract during export, per row not per key."""
    keys = [key for _, key in keyed_rows]
    statuses = bulk_lookup_match_statuses(session, keys)
    entries = _load_matching_entries(session, keys)
    products = load_normalized_identity_products(session, [str(entry['public_product_id']) for entry in entries.values() if entry.get('public_product_id')])
    pending = {key for key, product in products.items() if product.get('identity_only_pending_offer')}
    variants = _load_normalized_variants(session, [str(entry["public_variant_id"]) for entry in entries.values() if entry.get("public_variant_id")], pending)
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
    item.pop("matching_catalog_offer_state", None)
    item.pop("matching_catalog_offer_available", None)


def enrich_items_with_matching_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate verified identity references without approving catalog offers."""
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
            {key for key, product in normalized_products.items() if product.get('identity_only_pending_offer')},
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
                if normalized_product.get("identity_only_pending_offer"):
                    item["matching_catalog_offer_state"] = "pending_review"
                    item["matching_catalog_offer_available"] = False
                else:
                    item.pop("matching_catalog_offer_state", None)
                    item.pop("matching_catalog_offer_available", None)
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
