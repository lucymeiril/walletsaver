"""matching_lookup.py — MatchingEntry lookup 서비스 + in-memory LRU 캐시.

공개 API:
    lookup_one(session, match_key)            → Optional[MatchingEntry]
    lookup_bulk(session, match_keys)          → dict[str, MatchingEntry]
    record_hit(session, entry_id)             → None
    record_hits_batch(session, entry_ids)     → None
    classify_raw_record(session, raw_record)  → (MatchingEntry|None, reason|None)
    invalidate()                              → None  (캐시 전체 무효화)

캐시 정책:
    모듈-레벨 OrderedDict 기반 LRU (maxsize 1000).
    None (miss) 도 캐시에 저장해 반복 DB 왕복을 방지한다.
    hit_count/last_used_at 업데이트 후 해당 키는 캐시에서 제거된다.
    sync/import 작업 완료 후 호출자가 invalidate()를 직접 호출해야 한다.
"""

from __future__ import annotations

import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

# shared 패키지 경로 보장 — conftest.py가 먼저 추가하지만 직접 import 시에도 안전하게 처리
_backend_dir = Path(__file__).resolve().parent.parent
_shared_dir = _backend_dir.parent / "shared"
if str(_shared_dir) not in sys.path:
    sys.path.insert(0, str(_shared_dir))

from core.match_key import build_match_key  # noqa: E402
from storage.models import MatchingEntry  # noqa: E402

# ─────────────────────────────────────────────
# LRU 캐시 (모듈-레벨 싱글턴)
# ─────────────────────────────────────────────

_CACHE_MAX_SIZE = 1000
# value: MatchingEntry instance or None (miss sentinel)
_cache: OrderedDict[str, Optional[MatchingEntry]] = OrderedDict()


def _cache_get(key: str) -> tuple[bool, Optional[MatchingEntry]]:
    """캐시 조회. (found, value) 반환. found=False 이면 캐시 미존재."""
    if key in _cache:
        _cache.move_to_end(key)
        return True, _cache[key]
    return False, None


def _cache_put(key: str, value: Optional[MatchingEntry]) -> None:
    """캐시 저장. maxsize 초과 시 가장 오래된 항목 제거."""
    _cache[key] = value
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX_SIZE:
        _cache.popitem(last=False)


def invalidate() -> None:
    """캐시 전체 무효화 — sync/import 작업 완료 후 호출자 책임."""
    _cache.clear()


# ─────────────────────────────────────────────
# 공개 lookup API
# ─────────────────────────────────────────────

def lookup_one(session: Session, match_key: str) -> Optional[MatchingEntry]:
    """match_key 단건 조회.

    캐시 hit 시 DB 쿼리 없이 반환한다.
    miss(DB 포함)이면 None을 반환하고 None도 캐시에 저장한다.
    """
    found, cached = _cache_get(match_key)
    if found:
        return cached

    entry = session.query(MatchingEntry).filter_by(match_key=match_key).first()
    _cache_put(match_key, entry)
    return entry


def lookup_bulk(session: Session, match_keys: list[str]) -> dict[str, MatchingEntry]:
    """복수 match_key 조회 — 단일 IN 쿼리.

    캐시 hit 된 키는 DB 조회에서 제외한다.
    반환값에는 실제로 발견된(non-None) 항목만 포함된다.
    """
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
        rows = (
            session.query(MatchingEntry)
            .filter(MatchingEntry.match_key.in_(miss_keys))
            .all()
        )
        found_set: set[str] = set()
        for row in rows:
            result[row.match_key] = row
            _cache_put(row.match_key, row)
            found_set.add(row.match_key)
        # miss 항목도 None으로 캐시에 저장 (반복 DB 왕복 방지)
        for key in miss_keys:
            if key not in found_set:
                _cache_put(key, None)

    return result


# ─────────────────────────────────────────────
# hit 기록
# ─────────────────────────────────────────────

def record_hit(session: Session, entry_id: int) -> None:
    """단건 hit 기록 — record_hits_batch 위임."""
    record_hits_batch(session, [entry_id])


def record_hits_batch(session: Session, entry_ids: list[int]) -> None:
    """복수 hit 기록 — 단일 UPDATE로 last_used_at, hit_count 갱신.

    업데이트된 entry의 캐시 항목은 즉시 무효화한다.
    """
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

    # 갱신된 항목을 캐시에서 제거 (stale 방지)
    stale = [k for k, v in list(_cache.items()) if v is not None and v.id in entry_ids]
    for k in stale:
        del _cache[k]


# ─────────────────────────────────────────────
# raw record → lookup adapter
# ─────────────────────────────────────────────

def classify_raw_record(
    session: Session,
    raw_record_dict: dict,
) -> tuple[Optional[MatchingEntry], Optional[str]]:
    """raw record dict → MatchingEntry 조회.

    반환: (entry, None) 성공 / (None, miss_reason) 실패
    miss_reason 값: "no_brand" | "no_name" | "key_not_found"

    hit 시 record_hit을 호출해 last_used_at, hit_count를 갱신한다.
    """
    brand = _extract_str(raw_record_dict, ["brand", "brandName", "brandNm", "brand_name"])
    name = _extract_str(raw_record_dict, [
        "name", "name_core", "nameCore",
        "productName", "itemName", "prdtName", "goodsName",
    ])
    pack_qty = _extract_float(raw_record_dict, [
        "pack_qty", "packQty", "pack_quantity", "packQuantity",
    ])
    pack_unit = _extract_str(raw_record_dict, ["pack_unit", "packUnit", "unitName"])

    if not brand:
        return None, "no_brand"
    if not name:
        return None, "no_name"

    key = build_match_key(brand, name, pack_qty, pack_unit)
    entry = lookup_one(session, key)
    if entry is None:
        return None, "key_not_found"

    record_hit(session, entry.id)
    return entry, None


# ─────────────────────────────────────────────
# 내부 헬퍼
# ─────────────────────────────────────────────

def _extract_str(d: dict, keys: list[str]) -> Optional[str]:
    """키 후보 목록 순서대로 dict에서 비어있지 않은 문자열 값을 반환한다."""
    for k in keys:
        val = d.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _extract_float(d: dict, keys: list[str]) -> Optional[float]:
    """키 후보 목록 순서대로 dict에서 float으로 변환 가능한 값을 반환한다."""
    for k in keys:
        val = d.get(k)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None
