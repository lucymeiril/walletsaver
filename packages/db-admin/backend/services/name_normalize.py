"""Product name normalization helpers for mart-native matching."""
from __future__ import annotations

import hashlib
import re
import unicodedata

_MARKER_WORDS = (
    "행사상품",
    "한정판매",
    "신상품",
    "이벤트",
    "EVENT",
    "NEW",
    "기획",
    "특가",
    "핫딜",
    "할인",
    "행사",
    "한정",
    "신상",
    "무배",
)
_MARKER_PATTERN = "|".join(re.escape(word) for word in _MARKER_WORDS)
_BUY_X_GET_Y_PATTERN = r"\d+\s*\+\s*\d+"
_VOLATILE_MARKER_PATTERN = rf"(?:{_MARKER_PATTERN}|{_BUY_X_GET_Y_PATTERN})"
_BRACKET_MARKER_RE = re.compile(
    rf"\s*[\[\(\{{【<]\s*{_VOLATILE_MARKER_PATTERN}\s*[\]\)\}}】>]\s*",
    re.IGNORECASE,
)
_STAR_MARKER_RE = re.compile(
    rf"\s*★\s*{_VOLATILE_MARKER_PATTERN}\s*★\s*",
    re.IGNORECASE,
)
_STANDALONE_MARKER_RE = re.compile(
    rf"(?<![0-9A-Za-z가-힣]){_VOLATILE_MARKER_PATTERN}(?![0-9A-Za-z가-힣])",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")


def normalize_match_text(value: str) -> str:
    """Normalize source titles for exact, case-insensitive matching."""
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    return _SPACE_RE.sub(" ", normalized)


def normalize_package_signature(value: str) -> str:
    """Normalize a package signature while preserving variant distinctions."""
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-_.")
    if not normalized:
        raise ValueError("package signature must contain at least one searchable token")
    return normalized


def normalize_name_core(name: str | None, *, fold_case: bool = False) -> str:
    """Remove volatile event/new-product markers and collapse whitespace."""
    text = str(name or "").strip()
    if not text:
        return ""
    previous = None
    while previous != text:
        previous = text
        text = _BRACKET_MARKER_RE.sub(" ", text)
        text = _STAR_MARKER_RE.sub(" ", text)
    text = _STANDALONE_MARKER_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip(" -_/·|,.")
    return text.casefold() if fold_case else text


def _format_hash_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def compute_canon_hash(
    brand: str | None,
    normalized_name: str,
    pack_qty: float | None,
    pack_unit: str | None,
    *,
    fold_case: bool = False,
) -> str:
    """Compute SHA1 over brand, marker-stripped name_core, pack quantity, and unit."""
    name_core = normalize_name_core(normalized_name, fold_case=fold_case)
    payload = "|".join(_format_hash_value(value) for value in (brand, name_core, pack_qty, pack_unit))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
