"""db_admin_readonly.py — db-admin DB 읽기 전용 접근 서비스.

외부 분류 export가 현재 db-admin 데이터만 읽도록 한다.
이 모듈은 db-admin DB에 절대 쓰지 않는다.
"""
from __future__ import annotations

import json
from threading import Lock
from typing import Any, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_DB_ADMIN_ENGINE_LOCK = Lock()
_db_admin_engine: Optional[Engine] = None


def _get_db_admin_engine() -> Engine:
    """db-admin DB 엔진 싱글턴. 첫 호출 시 config.DB_ADMIN_DATABASE_URL로 생성."""
    global _db_admin_engine
    if _db_admin_engine is None:
        with _DB_ADMIN_ENGINE_LOCK:
            if _db_admin_engine is None:
                import config

                url = config.DB_ADMIN_DATABASE_URL
                connect_args = (
                    {"check_same_thread": False} if url.startswith("sqlite") else {}
                )
                _db_admin_engine = create_engine(url, connect_args=connect_args)
    return _db_admin_engine


def reset_db_admin_engine(new_engine: Optional[Engine] = None) -> None:
    """테스트에서 db-admin 엔진을 교체하거나 초기화할 때 사용."""
    global _db_admin_engine
    with _DB_ADMIN_ENGINE_LOCK:
        if _db_admin_engine is not None and new_engine is None:
            _db_admin_engine.dispose()
        _db_admin_engine = new_engine


def get_db_admin_session() -> Iterator[Session]:
    """FastAPI 의존성 — db-admin 읽기 전용 세션 주입."""
    engine = _get_db_admin_engine()
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_pending_ingestion_records(
    session: Session,
    ingestion_ids: list[int],
) -> list[dict[str, Any]]:
    """현재 PendingIngestion의 원본 items를 외부 분류용 raw record 형태로 펼친다.

    archived ai-admin DB나 raw_crawl_records에 의존하지 않는다. ingestion ID는
    db-admin이 실제로 저장한 대기열 ID이므로 fresh clone에서도 동일한 데이터 흐름을
    사용할 수 있다.
    """
    if not ingestion_ids:
        return []

    rows = []
    for i in range(0, len(ingestion_ids), 900):
        chunk = ingestion_ids[i : i + 900]
        placeholders = ", ".join(f":i{j}" for j in range(len(chunk)))
        params = {f"i{j}": value for j, value in enumerate(chunk)}
        rows.extend(
            session.execute(
                text(
                    "SELECT id, crawler_name, items_json, schema_type, crawled_at "
                    "FROM pending_ingestions "
                    f"WHERE id IN ({placeholders}) ORDER BY id"
                ),
                params,
            ).fetchall()
        )

    records: list[dict[str, Any]] = []
    for ingestion_id, crawler_name, items_json, schema_type, crawled_at in rows:
        try:
            items = json.loads(items_json) if isinstance(items_json, str) else (items_json or [])
        except (TypeError, ValueError, json.JSONDecodeError):
            items = []
        if not isinstance(items, list):
            continue

        crawled_iso = crawled_at.isoformat() if hasattr(crawled_at, "isoformat") else str(crawled_at or "")
        for index, payload in enumerate(items):
            if not isinstance(payload, dict):
                continue
            source_name = (
                payload.get("source")
                or payload.get("mart")
                or payload.get("source_name")
                or crawler_name
            )
            raw_title = (
                payload.get("raw_title")
                or payload.get("title")
                or payload.get("name")
                or payload.get("productName")
                or payload.get("itemName")
            )
            raw_price = (
                payload.get("raw_price")
                if payload.get("raw_price") is not None
                else payload.get("sale_price", payload.get("price"))
            )
            records.append(
                {
                    "raw_record_id": f"ingestion:{ingestion_id}:{index}",
                    "batch_id": f"ingestion-{ingestion_id}",
                    "ingestion_id": ingestion_id,
                    "source_name": str(source_name or crawler_name or "unknown"),
                    "raw_title": raw_title,
                    "raw_price": raw_price,
                    "crawled_at": crawled_iso,
                    "schema_type": schema_type,
                    "raw_payload": payload,
                }
            )
    return records


def bulk_lookup_hit_keys(session: Session, match_keys: list[str]) -> set[str]:
    """Return only keys that resolve through MatchingEntry to an active Product.

    A MatchingEntry row by itself is incomplete knowledge. Rows whose
    ``canonical_product_id`` is missing, malformed, deleted, or inactive stay
    exportable so the external-classification workflow can repair them.

    Resolution is deliberately two-stage instead of joining on a casted Product
    id. The first query uses the unique ``matching_entries.match_key`` index;
    canonical ids are parsed safely in Python; the second query uses the Product
    integer primary key. This keeps 10k-scale exports off full-table scans and is
    the same semantic hit definition used by crawler runtime enrichment.
    """
    if not match_keys:
        return set()

    unique_keys = list(dict.fromkeys(match_keys))
    key_to_product_id: dict[str, int] = {}

    for offset in range(0, len(unique_keys), 900):
        chunk = unique_keys[offset : offset + 900]
        placeholders = ", ".join(f":k{i}" for i in range(len(chunk)))
        params = {f"k{i}": key for i, key in enumerate(chunk)}
        rows = session.execute(
            text(
                "SELECT match_key, canonical_product_id "
                "FROM matching_entries "
                f"WHERE match_key IN ({placeholders})"
            ),
            params,
        ).fetchall()
        for match_key, canonical_product_id in rows:
            if canonical_product_id in (None, ""):
                continue
            try:
                product_id = int(canonical_product_id)
            except (TypeError, ValueError):
                continue
            key_to_product_id[str(match_key)] = product_id

    if not key_to_product_id:
        return set()

    product_ids = list(dict.fromkeys(key_to_product_id.values()))
    active_product_ids: set[int] = set()
    for offset in range(0, len(product_ids), 900):
        chunk = product_ids[offset : offset + 900]
        placeholders = ", ".join(f":p{i}" for i in range(len(chunk)))
        params = {f"p{i}": product_id for i, product_id in enumerate(chunk)}
        rows = session.execute(
            text(
                "SELECT id FROM products "
                f"WHERE id IN ({placeholders}) AND is_active IS TRUE"
            ),
            params,
        ).fetchall()
        active_product_ids.update(int(row[0]) for row in rows)

    return {
        match_key
        for match_key, product_id in key_to_product_id.items()
        if product_id in active_product_ids
    }


def get_all_matching_entries(session: Session) -> list[dict]:
    """matching_entries 전량 조회 — 외부 분류 컨텍스트용."""
    rows = session.execute(
        text(
            "SELECT id, match_key, brand, name_core, pack_qty, pack_unit, "
            "canonical_product_id, category_id, keyword_ids, confidence, source, "
            "created_at, updated_at, last_used_at, hit_count, notes "
            "FROM matching_entries ORDER BY id"
        )
    ).fetchall()
    columns = [
        "id", "match_key", "brand", "name_core", "pack_qty", "pack_unit",
        "canonical_product_id", "category_id", "keyword_ids", "confidence",
        "source", "created_at", "updated_at", "last_used_at", "hit_count", "notes",
    ]
    result = []
    for row in rows:
        d = dict(zip(columns, row))
        if isinstance(d.get("keyword_ids"), str):
            try:
                d["keyword_ids"] = json.loads(d["keyword_ids"])
            except Exception:
                pass
        for dt_col in ("created_at", "updated_at", "last_used_at"):
            v = d.get(dt_col)
            if v is not None and hasattr(v, "isoformat"):
                d[dt_col] = v.isoformat()
            elif v is not None:
                d[dt_col] = str(v)
        result.append(d)
    return result


def get_all_categories(session: Session) -> list[dict]:
    """categories 전량 조회 — 외부 분류 컨텍스트용."""
    rows = session.execute(
        text(
            "SELECT id, name, parent_id, depth, sort_order, icon, is_active "
            "FROM categories ORDER BY depth, sort_order, id"
        )
    ).fetchall()
    columns = ["id", "name", "parent_id", "depth", "sort_order", "icon", "is_active"]
    return [dict(zip(columns, row)) for row in rows]


def get_all_keywords(session: Session) -> list[dict]:
    """keywords 전량 조회 — 외부 분류 컨텍스트용."""
    rows = session.execute(
        text(
            "SELECT id, word, synonyms, category_id, search_count, is_active "
            "FROM keywords ORDER BY search_count DESC, word"
        )
    ).fetchall()
    columns = ["id", "word", "synonyms", "category_id", "search_count", "is_active"]
    result = []
    for row in rows:
        d = dict(zip(columns, row))
        if isinstance(d.get("synonyms"), str):
            try:
                d["synonyms"] = json.loads(d["synonyms"])
            except Exception:
                pass
        result.append(d)
    return result
