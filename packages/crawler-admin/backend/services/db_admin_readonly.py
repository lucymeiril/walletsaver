"""db_admin_readonly.py — db-admin DB 읽기 전용 접근 서비스.

외부 분류 export가 현재 db-admin 데이터만 읽도록 한다.
이 모듈은 db-admin DB에 절대 쓰지 않는다.
"""
from __future__ import annotations

import json
import math
from threading import Lock
from typing import Any, Iterator, Optional
from collections.abc import Mapping

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_DB_ADMIN_ENGINE_LOCK = Lock()
_db_admin_engine: Optional[Engine] = None


def _table_columns(session: Session, table_name: str) -> set[str]:
    """Return columns for an explicitly named catalog table."""
    try:
        return {
            str(column["name"])
            for column in inspect(session.get_bind()).get_columns(table_name)
        }
    except Exception:
        return set()


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

    archived control DB나 raw_crawl_records에 의존하지 않는다. ingestion ID는
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


def load_normalized_identity_products(session: Session, public_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Resolve reviewed identity separately from a pending catalog offer.

    Legacy/manual inactive products remain unavailable. A source-built product
    whose complete listings have only pending offers may still resolve identity;
    every caller must subsequently verify the source and exact variant. This
    does not activate the product or make its offers comparable.
    """
    columns = _table_columns(session, "normalized_canonical_products")
    if not public_ids or not {"public_product_id", "is_active"} <= columns:
        return {}
    result, pending = {}, {}
    ids = list(dict.fromkeys(public_ids))
    for offset in range(0, len(ids), 900):
        chunk = ids[offset:offset + 900]
        placeholders = ", ".join(f":n{i}" for i in range(len(chunk)))
        params = {f"n{i}": value for i, value in enumerate(chunk)}
        attrs = ", attributes" if "attributes" in columns else ""
        details = ", ".join(field if field in columns else f"NULL AS {field}"
                            for field in ("canonical_name", "brand", "unified_category_id"))
        rows = session.execute(text(
            f"SELECT public_product_id, {details}, is_active"
            f"{attrs} FROM normalized_canonical_products WHERE public_product_id IN ({placeholders})"
        ), params).mappings().all()
        for row in rows:
            item = dict(row)
            key = str(item["public_product_id"])
            if item["is_active"] in (True, 1):
                result[key] = item
                continue
            if item["is_active"] not in (False, 0):
                continue
            attributes = item.get("attributes")
            if isinstance(attributes, str):
                try:
                    attributes = json.loads(attributes)
                except (ValueError, TypeError):
                    continue
            if not isinstance(attributes, Mapping) or not item["unified_category_id"]:
                continue
            evidence = attributes.get("classification_attribute_evidence")
            if (attributes.get("identity_basis") not in {"source_scoped", "reviewed_product_group"}
                    or not isinstance(evidence, list) or not evidence
                    or any(not isinstance(e, Mapping) or not e.get("source_name")
                           or not e.get("source_record_key") or not e.get("raw_record_ids")
                           or not e.get("classification_reason") for e in evidence)):
                continue
            pending[key] = item
    required = {
        "normalized_product_variants": {"public_product_id", "public_variant_id", "is_active", "attributes"},
        "normalized_source_listings": {"public_variant_id", "public_source_listing_id", "source_name",
                                       "source_record_key", "source_title", "source_url", "is_active"},
        "normalized_offer_events": {"public_source_listing_id", "offer_state"},
    }
    if not pending or any(not fields <= _table_columns(session, table) for table, fields in required.items()):
        return result
    pending_ids = list(pending)
    from core.reviewed_source_evidence import source_review_matches
    for offset in range(0, len(pending_ids), 900):
        chunk = pending_ids[offset:offset + 900]
        placeholders = ", ".join(f":p{i}" for i in range(len(chunk)))
        params = {f"p{i}": value for i, value in enumerate(chunk)}
        # An inactive identity must never fall through the legacy unbound-row
        # path. Require its stored complete source proofs; the existing per-row
        # validator below then checks the actual URL/context/quantity inputs.
        proof_valid = dict.fromkeys(chunk, True)
        variants = session.execute(text(
            "SELECT public_product_id, attributes FROM normalized_product_variants "
            f"WHERE public_product_id IN ({placeholders})"
        ), params).fetchall()
        for product_id, attributes in variants:
            if isinstance(attributes, str):
                try:
                    attributes = json.loads(attributes)
                except (ValueError, TypeError):
                    attributes = None
            reviews = attributes.get("source_evidence_reviews") if isinstance(attributes, Mapping) else None
            scalar = (isinstance(attributes, Mapping) and 'source_evidence_reviews' not in attributes
                      and attributes.get('specification_basis') in
                      {'source_structured_and_explicit_text', 'reviewed_override'})
            if (not scalar and (not isinstance(reviews, list) or not reviews
                    or any(not isinstance(review, Mapping) or not review.get("source_name")
                           or not review.get("source_record_key") or not source_review_matches(review, review)
                           for review in reviews))):
                proof_valid[str(product_id)] = False
        rows = session.execute(text(
            "SELECT v.public_product_id FROM normalized_product_variants v "
            "JOIN normalized_source_listings l ON l.public_variant_id=v.public_variant_id "
            "JOIN normalized_offer_events o ON o.public_source_listing_id=l.public_source_listing_id "
            f"WHERE v.public_product_id IN ({placeholders}) GROUP BY v.public_product_id "
            "HAVING COUNT(*)>0 AND SUM(CASE WHEN o.offer_state='pending_review' "
            "AND v.is_active=1 AND l.is_active=1 AND l.source_name IS NOT NULL "
            "AND l.source_record_key IS NOT NULL AND l.source_title IS NOT NULL "
            "AND TRIM(l.source_url)<>'' THEN 0 ELSE 1 END)=0"
        ), params).fetchall()
        for row in rows:
            key = str(row[0])
            if proof_valid[key]:
                result[key] = {**pending[key], "identity_only_pending_offer": True}
    return result


def bulk_lookup_match_statuses(session: Session, match_keys: list[str]) -> dict[str, str]:
    """Return MatchingEntry runtime status for keys that exist in the knowledge base.

    Key-only lookup can establish reference integrity, not source specification:
    - ``hit``: a legacy MatchingEntry resolves to an active Product;
    - ``normalized_source_verification_required``: reviewed normalized identity
      and active variant references agree; callers must still validate each raw
      row. An offer-pending identity does not imply offer availability;
    - ``canonical_product_unavailable``: the MatchingEntry exists, but its
      canonical Product link is missing, malformed, deleted, or inactive.

    Keys absent from the returned mapping are true ``key_not_found`` misses.
    Resolution is deliberately two-stage so both match_key and Product PK indexes
    remain usable at 10k-scale instead of joining through a casted Product id.
    """
    if not match_keys:
        return {}

    unique_keys = list(dict.fromkeys(match_keys))
    statuses: dict[str, str] = {}
    key_to_product_id: dict[str, int] = {}
    key_to_public_product_id: dict[str, str] = {}
    key_to_public_variant_id: dict[str, str] = {}
    matching_columns = _table_columns(session, "matching_entries")
    normalized_matching = "public_product_id" in matching_columns

    for offset in range(0, len(unique_keys), 900):
        chunk = unique_keys[offset : offset + 900]
        placeholders = ", ".join(f":k{i}" for i in range(len(chunk)))
        params = {f"k{i}": key for i, key in enumerate(chunk)}
        selected = "match_key, canonical_product_id, confidence"
        if normalized_matching:
            selected += ", public_product_id, public_variant_id"
        rows = session.execute(
            text(
                f"SELECT {selected} "
                "FROM matching_entries "
                f"WHERE match_key IN ({placeholders})"
            ),
            params,
        ).fetchall()
        for row in rows:
            match_key, canonical_product_id, confidence = row[0], row[1], row[2]
            key = str(match_key)
            statuses[key] = "canonical_product_unavailable"
            try:
                numeric_confidence = float(confidence if confidence is not None else 0)
                if not math.isfinite(numeric_confidence) or numeric_confidence < 0.80:
                    statuses[key] = "low_confidence"
                    continue
            except (TypeError, ValueError):
                statuses[key] = "low_confidence"
                continue
            if normalized_matching and row[3] not in (None, ""):
                key_to_public_product_id[key] = str(row[3])
                if row[4] not in (None, ""):
                    key_to_public_variant_id[key] = str(row[4])
                statuses[key] = "normalized_product_unavailable"
                continue
            if canonical_product_id in (None, ""):
                continue
            try:
                product_id = int(canonical_product_id)
            except (TypeError, ValueError):
                continue
            key_to_product_id[key] = product_id

    if key_to_public_product_id:
        public_ids = list(dict.fromkeys(key_to_public_product_id.values()))
        active_public_ids = set(load_normalized_identity_products(session, public_ids))

        active_variants: dict[str, str] = {}
        variant_ids = list(dict.fromkeys(key_to_public_variant_id.values()))
        variant_columns = _table_columns(session, "normalized_product_variants")
        if not {"public_variant_id", "public_product_id", "is_active"} <= variant_columns:
            variant_ids = []
        for offset in range(0, len(variant_ids), 900):
            chunk = variant_ids[offset : offset + 900]
            placeholders = ", ".join(f":v{i}" for i in range(len(chunk)))
            params = {f"v{i}": value for i, value in enumerate(chunk)}
            rows = session.execute(text(
                "SELECT public_variant_id, public_product_id FROM normalized_product_variants "
                f"WHERE public_variant_id IN ({placeholders}) AND is_active IS TRUE"
            ), params).fetchall()
            active_variants.update({str(row[0]): str(row[1]) for row in rows})

        for key, public_id in key_to_public_product_id.items():
            variant_id = key_to_public_variant_id.get(key)
            if public_id not in active_public_ids:
                continue
            if not variant_id or variant_id not in active_variants:
                statuses[key] = "normalized_variant_unavailable"
            elif active_variants[variant_id] != public_id:
                statuses[key] = "normalized_variant_product_conflict"
            else:
                statuses[key] = "normalized_source_verification_required"

    if not key_to_product_id:
        return statuses

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

    for match_key, product_id in key_to_product_id.items():
        if product_id in active_product_ids:
            statuses[match_key] = "hit"
    return statuses


def bulk_lookup_hit_keys(session: Session, match_keys: list[str]) -> set[str]:
    """Compatibility helper returning only completed reusable matching keys."""
    return {
        key
        for key, status in bulk_lookup_match_statuses(session, match_keys).items()
        if status == "hit"
    }


def get_all_matching_entries(session: Session) -> list[dict]:
    """matching_entries 전량 조회 — 외부 분류 컨텍스트용."""
    extra_columns = []
    available = _table_columns(session, "matching_entries")
    for column in ("public_product_id", "public_variant_id"):
        if column in available:
            extra_columns.append(column)
    extra_select = (", " + ", ".join(extra_columns)) if extra_columns else ""
    rows = session.execute(
        text(
            "SELECT id, match_key, brand, name_core, pack_qty, pack_unit, "
            "canonical_product_id, category_id, keyword_ids, confidence, source, "
            f"created_at, updated_at, last_used_at, hit_count, notes{extra_select} "
            "FROM matching_entries ORDER BY id"
        )
    ).fetchall()
    columns = [
        "id", "match_key", "brand", "name_core", "pack_qty", "pack_unit",
        "canonical_product_id", "category_id", "keyword_ids", "confidence",
        "source", "created_at", "updated_at", "last_used_at", "hit_count", "notes",
    ] + extra_columns
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


def get_normalized_catalog_context(session: Session) -> dict[str, list[dict[str, Any]]]:
    """Read the normalized SSOT context used by external classification."""
    table_names = (
        "unified_categories",
        "normalized_canonical_products",
        "normalized_product_variants",
        "normalized_source_listings",
        "mart_category_mappings",
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for table_name in table_names:
        if not _table_columns(session, table_name):
            result[table_name] = []
            continue
        rows = session.execute(text(f"SELECT * FROM {table_name}")).mappings().all()
        payload = []
        for row in rows:
            item = dict(row)
            for key, value in list(item.items()):
                if hasattr(value, "isoformat"):
                    item[key] = value.isoformat()
                elif isinstance(value, str) and key in {"aliases", "keywords", "attributes"}:
                    try:
                        item[key] = json.loads(value)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        pass
            payload.append(item)
        result[table_name] = payload
    return result
