"""match_key normalization — the single identity rule for matching_entries.

Rules:
    brand    : lowercase + trim; missing brands use ``__no_brand__``
    name_core: lowercase, punctuation removed, whitespace collapsed
    pack      : equivalent weight/volume units are canonicalized before keying
    separator : ``|``

Every runtime/export/import path must call ``build_match_key`` instead of
assembling matching keys independently.
"""
from __future__ import annotations

import re
from typing import Optional

NO_BRAND_SENTINEL = "__no_brand__"

_SPECIAL_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")

_WEIGHT_TO_G = {
    "kg": 1000.0,
    "g": 1.0,
    "mg": 0.001,
    "t": 1_000_000.0,
    "ton": 1_000_000.0,
}
_VOLUME_TO_ML = {
    "l": 1000.0,
    "ml": 1.0,
    "dl": 100.0,
    "cc": 1.0,
}


def normalize_brand(brand: Optional[str]) -> str:
    value = (brand or "").strip().lower()
    return value or NO_BRAND_SENTINEL


def normalize_pack_identity(
    pack_qty: Optional[float],
    pack_unit: Optional[str],
) -> tuple[Optional[float], str]:
    unit = (pack_unit or "").strip().lower()
    if pack_qty is None:
        return None, unit

    qty = float(pack_qty)
    if unit in _WEIGHT_TO_G:
        return round(qty * _WEIGHT_TO_G[unit], 6), "g"
    if unit in _VOLUME_TO_ML:
        return round(qty * _VOLUME_TO_ML[unit], 6), "ml"
    if unit in {"ea", "개"}:
        return qty, "ea"
    return qty, unit


def build_match_key(
    brand: Optional[str],
    name_core: Optional[str],
    pack_qty: Optional[float],
    pack_unit: Optional[str],
) -> str:
    """Return a deterministic MatchingEntry key.

    Missing brands use one stable sentinel, and equivalent package units share
    an identity. This makes the same product reusable across marts even when one
    source says ``1kg`` and another says ``1000g``.

    Examples:
        >>> build_match_key("CJ", "햇반", 210.0, "g")
        'cj|햇반|210.0|g'
        >>> build_match_key(None, "신라면", 120.0, "G")
        '__no_brand__|신라면|120.0|g'
        >>> build_match_key("brand", "우유", 1.0, "L")
        'brand|우유|1000.0|ml'
        >>> build_match_key("brand", "우유", 1000.0, "ml")
        'brand|우유|1000.0|ml'
    """
    b = normalize_brand(brand)

    n = (name_core or "").lower()
    n = _SPECIAL_RE.sub(" ", n)
    n = _WHITESPACE_RE.sub(" ", n).strip()

    normalized_qty, normalized_unit = normalize_pack_identity(pack_qty, pack_unit)
    q = f"{round(normalized_qty, 1):.1f}" if normalized_qty is not None else ""
    return f"{b}|{n}|{q}|{normalized_unit}"
