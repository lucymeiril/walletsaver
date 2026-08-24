"""Normalize identity across the three-file external classification bundle.

matching_updates.jsonl may contain a legacy/hand-built match_key while
products.jsonl refers to that exact legacy string. Matching validation now
canonicalizes keys, so product rows must be remapped in the same request or the
matching row can insert successfully while its product row is silently skipped.
"""
from __future__ import annotations

from typing import Optional

from core.match_key import NO_BRAND_SENTINEL
from services.import_validator import _normalize_identity

_NO_BRAND_ALIASES = {
    "",
    "no_brand",
    "no-brand",
    "none",
    "null",
    "브랜드없음",
    "브랜드 없음",
    NO_BRAND_SENTINEL,
}


def _normalize_brand_alias(row: dict) -> dict:
    normalized = dict(row)
    brand = normalized.get("brand")
    if brand is None or str(brand).strip().lower() in _NO_BRAND_ALIASES:
        normalized["brand"] = NO_BRAND_SENTINEL
    return normalized


def normalize_bundle_identity(
    matching_rows: Optional[list[dict]],
    products_rows: Optional[list[dict]],
) -> tuple[Optional[list[dict]], Optional[list[dict]]]:
    """Return canonical matching/product rows without mutating upload objects.

    The mapping deliberately includes both the incoming key and canonical key,
    making repeated normalization idempotent. Product rows with their own
    identity fields are canonicalized directly; otherwise their match_key is
    translated through the matching-file mapping.
    """
    if not matching_rows and not products_rows:
        return matching_rows, products_rows

    canonical_matching: list[dict] | None = None
    key_map: dict[str, str] = {}

    if matching_rows is not None:
        canonical_matching = []
        for source_row in matching_rows:
            incoming = _normalize_brand_alias(source_row)
            old_key = str(incoming.get("match_key") or "").strip()
            canonical = _normalize_identity(incoming)
            canonical_key = str(canonical.get("match_key") or "").strip()
            if old_key and canonical_key:
                key_map[old_key] = canonical_key
            if canonical_key:
                key_map[canonical_key] = canonical_key
            canonical_matching.append(canonical)

    canonical_products: list[dict] | None = None
    if products_rows is not None:
        canonical_products = []
        for source_row in products_rows:
            row = dict(source_row)
            old_key = str(row.get("match_key") or "").strip()

            # Some producers include compound identity fields in products.jsonl.
            # Use them when available; otherwise translate through matching rows.
            if row.get("name_core") not in (None, "") and row.get("pack_qty") not in (None, "") and row.get("pack_unit") not in (None, ""):
                identity = _normalize_identity(_normalize_brand_alias(row))
                canonical_key = str(identity.get("match_key") or "").strip()
                if canonical_key:
                    row["match_key"] = canonical_key
            elif old_key in key_map:
                row["match_key"] = key_map[old_key]

            canonical_products.append(row)

    return canonical_matching, canonical_products
