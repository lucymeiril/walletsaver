"""match_key normalization — the single identity rule for matching_entries.

Rules:
    brand    : lowercase + trim; missing brands use ``__no_brand__``
    name_core: lowercase, punctuation removed, whitespace collapsed
    pack_qty : rounded to one decimal; None -> ""
    pack_unit: lowercase + trim; None -> ""
    separator: ``|``

Every runtime/export/import path must call ``build_match_key`` instead of
assembling matching keys independently.
"""
from __future__ import annotations

import re
from typing import Optional

NO_BRAND_SENTINEL = "__no_brand__"

_SPECIAL_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_brand(brand: Optional[str]) -> str:
    value = (brand or "").strip().lower()
    return value or NO_BRAND_SENTINEL


def build_match_key(
    brand: Optional[str],
    name_core: Optional[str],
    pack_qty: Optional[float],
    pack_unit: Optional[str],
) -> str:
    """Return a deterministic MatchingEntry key.

    Missing brand is not a reason to discard an otherwise stable product
    identity. A fixed sentinel is used instead of a mart name so the same
    unbranded product can match across stores.

    Examples:
        >>> build_match_key("CJ", "햇반", 210.0, "g")
        'cj|햇반|210.0|g'
        >>> build_match_key(None, "신라면", 120.0, "G")
        '__no_brand__|신라면|120.0|g'
        >>> build_match_key("  Nongshim  ", "  신라면  ", 120.0, "g")
        'nongshim|신라면|120.0|g'
    """
    b = normalize_brand(brand)

    n = (name_core or "").lower()
    n = _SPECIAL_RE.sub(" ", n)
    n = _WHITESPACE_RE.sub(" ", n).strip()

    if pack_qty is not None:
        q = f"{round(float(pack_qty), 1):.1f}"
    else:
        q = ""

    u = (pack_unit or "").strip().lower()
    return f"{b}|{n}|{q}|{u}"
