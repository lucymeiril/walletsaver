"""Stable ASCII identifiers for raw records sent to AI providers."""

from __future__ import annotations

import hashlib
import re


_ASCII_ID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._:-]*$")
_ASCII_SEGMENT_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]*$")
_ASCII_SLUG_RE = re.compile(r"[^0-9A-Za-z]+")

_KNOWN_SOURCE_SLUGS = {
    "이마트": "emart",
    "emart": "emart",
    "e-mart": "emart",
    "e mart": "emart",
}


def _digest(value: str, length: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def stable_ascii_source_slug(source_name: str, *, fallback: str = "source") -> str:
    """Return a deterministic provider-safe source slug without changing display names."""
    value = str(source_name or "").strip()
    known = _KNOWN_SOURCE_SLUGS.get(value.casefold())
    if known:
        return known
    slug = _ASCII_SLUG_RE.sub("-", value.lower()).strip("-")
    if slug:
        return slug
    return f"{fallback}-{_digest(value or fallback, 10)}"


def stable_ascii_record_component(value: str, *, fallback: str = "key") -> str:
    """Return an ASCII-safe record-id component, preserving already-safe components."""
    text = str(value or "").strip()
    if _ASCII_SEGMENT_RE.fullmatch(text):
        return text
    return f"{fallback}-{_digest(text or fallback)}"


def build_stable_raw_record_id(
    *,
    source_name: str,
    kind: str,
    value: str,
) -> str:
    source_slug = stable_ascii_source_slug(source_name)
    if kind == "key":
        return f"{source_slug}:{stable_ascii_record_component(value)}"
    return f"{source_slug}:{stable_ascii_record_component(kind, fallback='kind')}:{value}"


def provider_facing_raw_record_id(raw_record_id: str) -> str:
    """Map legacy/non-ASCII raw IDs to deterministic ASCII IDs for provider prompts."""
    text = str(raw_record_id or "").strip()
    if _ASCII_ID_RE.fullmatch(text):
        return text
    parts = text.split(":")
    if len(parts) >= 2:
        source_slug = stable_ascii_source_slug(parts[0])
        safe_parts = [
            stable_ascii_record_component(part, fallback=f"part{index}")
            for index, part in enumerate(parts[1:], start=1)
        ]
        return ":".join([source_slug, *safe_parts])
    return f"raw-{_digest(text or 'raw')}"


def provider_facing_raw_record_id_map(raw_record_ids: list[str]) -> dict[str, str]:
    """Build original -> provider-facing ID map and resolve rare batch collisions."""
    result: dict[str, str] = {}
    used: set[str] = set()
    for raw_record_id in raw_record_ids:
        provider_id = provider_facing_raw_record_id(raw_record_id)
        if provider_id in used:
            provider_id = f"{provider_id}:rid:{_digest(raw_record_id, 8)}"
        result[raw_record_id] = provider_id
        used.add(provider_id)
    return result
