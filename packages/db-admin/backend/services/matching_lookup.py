"""MatchingEntry lookup service with a small in-process LRU cache."""
from __future__ import annotations

import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

_backend_dir = Path(__file__).resolve().parent.parent
_shared_dir = _backend_dir.parent.parent / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from core.match_key import build_match_key  # noqa: E402
from storage.models import MatchingEntry  # noqa: E402

_CACHE_MAX_SIZE = 1000
_cache: OrderedDict[str, Optional[MatchingEntry]] = OrderedDict()


def _cache_get(key: str) -> tuple[bool, Optional[MatchingEntry]]:
    if key in _cache:
        _cache.move_to_end(key)
        return True, _cache[key]
    return False, None


def _cache_put(key: str, value: Optional[MatchingEntry]) -> None:
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


def invalidate() -> None:
    _cache.clear()


def lookup_one(session: Session, match_key: str) -> Optional[MatchingEntry]:
    found, cached = _cache_get(match_key)
    if found:
        return cached
    entry = session.query(MatchingEntry).filter_by(match_key=match_key).first()
    _cache_put(match_key, entry)
    return entry


def lookup_bulk(session: Session, match_keys: list[str]) -> dict[str, MatchingEntry]:
    result: dict[str, MatchingEntry] = {}
    miss_keys: list[str] = []

    for key in match_keys:
        found, cached = _cache_get(key)
        if found:
            if cached is not None:
                result[key] = cached
        else:
            miss_keys.append(key)

    if miss_keys:
        rows = session.query(MatchingEntry).filter(MatchingEntry.match_key.in_(miss_keys)).all()
        found_set: set[str] = set()
        for row in rows:
            result[row.match_key] = row
            _cache_put(row.match_key, row)
            found_set.add(row.match_key)
        for key in miss_keys:
            if key not in found_set:
                _cache_put(key, None)
    return result


def record_hit(session: Session, entry_id: int) -> None:
    record_hits_batch(session, [entry_id])


def record_hits_batch(session: Session, entry_ids: list[int]) -> None:
    if not entry_ids:
        return
    now = datetime.now(timezone.utc)
    session.execute(
        update(MatchingEntry)
        .where(MatchingEntry.id.in_(entry_ids))
        .values(
            last_used_at=now,
            hit_count=MatchingEntry.hit_count + 1,
        )
        .execution_options(synchronize_session="fetch")
    )
    stale = [key for key, value in list(_cache.items()) if value is not None and value.id in entry_ids]
    for key in stale:
        del _cache[key]


def classify_raw_record(
    session: Session,
    raw_record_dict: dict,
) -> tuple[Optional[MatchingEntry], Optional[str]]:
    """Resolve a raw row with the same identity policy used by import/export.

    Brandless rows are valid and use the shared ``__no_brand__`` sentinel.
    Only a missing product name prevents key construction.
    """
    brand = _extract_str(raw_record_dict, ["brand", "brandName", "brandNm", "brand_name"])
    name = _extract_str(
        raw_record_dict,
        ["name", "name_core", "nameCore", "productName", "itemName", "prdtName", "goodsName", "title"],
    )
    pack_qty = _extract_float(
        raw_record_dict,
        ["pack_qty", "packQty", "pack_quantity", "packQuantity"],
    )
    pack_unit = _extract_str(raw_record_dict, ["pack_unit", "packUnit", "unitName", "unit"])

    if not name:
        return None, "no_name"

    key = build_match_key(brand, name, pack_qty, pack_unit)
    entry = lookup_one(session, key)
    if entry is None:
        return None, "key_not_found"

    record_hit(session, entry.id)
    return entry, None


def _extract_str(data: dict, keys: list[str]) -> Optional[str]:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _extract_float(data: dict, keys: list[str]) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None
