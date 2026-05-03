"""Shared source normalization for admin filters and ingestion."""

from __future__ import annotations

from collections.abc import Iterable


_SOURCE_ALIASES = {
    "알구몬": "algumon",
    "algumon": "algumon",
    "www.algumon.com": "algumon",
    "algumon.com": "algumon",
    "뽐뿌": "ppomppu",
    "ppomppu": "ppomppu",
    "루리웹": "ruliweb",
    "ruliweb": "ruliweb",
    "에펨코리아": "fmkorea",
    "fmkorea": "fmkorea",
    "fm korea": "fmkorea",
    "clien": "clien",
    "클리앙": "clien",
    "이마트": "emart",
    "emart": "emart",
    "홈플러스": "homeplus",
    "homeplus": "homeplus",
    "롯데마트": "lottemart",
    "lottemart": "lottemart",
    "코스트코": "costco",
    "costco": "costco",
}


def normalize_source_key(raw: object, default: str | None = None) -> str | None:
    """Return the stable DB/admin source key for crawler/admin source values."""
    if raw is None:
        return default
    value = str(raw).strip()
    if not value:
        return default
    lowered = value.lower()
    if "algumon.com" in lowered:
        return "algumon"
    return _SOURCE_ALIASES.get(value) or _SOURCE_ALIASES.get(lowered) or value


def source_aliases(source: object) -> set[str]:
    """Return known DB aliases for a normalized source filter."""
    normalized = normalize_source_key(source)
    if not normalized:
        return set()
    aliases = {normalized}
    aliases.update(alias for alias, canonical in _SOURCE_ALIASES.items() if canonical == normalized)
    return aliases


def normalize_sources(values: Iterable[object]) -> list[str]:
    """Normalize source values and drop unknown/empty entries for filter lists."""
    normalized = {
        value
        for raw in values
        if (value := normalize_source_key(raw)) not in (None, "", "unknown")
    }
    return sorted(normalized)
