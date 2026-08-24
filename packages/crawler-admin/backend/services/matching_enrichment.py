"""Enrich crawler rows from the persistent MatchingEntry knowledge base.

This is the runtime half of the external-classification workflow:
- known rows reuse matching_entries without calling an AI service;
- unknown rows stay unresolved so they can be exported for external review;
- the db-admin database is read only from this module.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlalchemy import text

from core.match_key import NO_BRAND_SENTINEL, build_match_key
from services.db_admin_readonly import get_db_admin_session

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
        # Persist the same sentinel into PendingIngestion. The raw-batch exporter
        # can then classify this row normally instead of treating it as no_brand.
        row["brand"] = NO_BRAND_SENTINEL
        brand = NO_BRAND_SENTINEL
    return build_match_key(brand, name, pack_qty, pack_unit), None


def _load_matching_entries(session, keys: list[str]) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}

    result: dict[str, dict[str, Any]] = {}
    unique_keys = list(dict.fromkeys(keys))
    for offset in range(0, len(unique_keys), 900):
        chunk = unique_keys[offset : offset + 900]
        placeholders = ", ".join(f":k{i}" for i in range(len(chunk)))
        params = {f"k{i}": key for i, key in enumerate(chunk)}
        rows = session.execute(
            text(
                "SELECT id, match_key, canonical_product_id, category_id, keyword_ids, "
                "confidence, source, brand, name_core, pack_qty, pack_unit "
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
            result[row[1]] = {
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


def enrich_items_with_matching_entries(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate crawler rows with MatchingEntry hits without mutating db-admin."""
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

        for item, key, reason in keyed:
            if key is None:
                item["matching_status"] = "miss"
                item["matching_miss_reason"] = reason
                continue

            item["match_key"] = key
            entry = entries.get(key)
            if entry is None:
                item["matching_status"] = "miss"
                item["matching_miss_reason"] = "key_not_found"
                continue

            item["matching_status"] = "hit"
            item["matching_entry_id"] = entry["id"]
            item["matching_source"] = entry.get("source")
            item["matching_confidence"] = entry.get("confidence")
            if entry.get("category_id"):
                item["category_id"] = entry["category_id"]
            if entry.get("keyword_ids") is not None:
                item["matching_keyword_ids"] = entry["keyword_ids"]

            canonical_id = entry.get("canonical_product_id")
            product = products.get(str(canonical_id)) if canonical_id not in (None, "") else None
            if product is None:
                continue

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
    finally:
        session_iter.close()

    return items
