"""현재 PendingIngestion 기반 외부 분류 export 통합 테스트."""
from __future__ import annotations

import json
import sys
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _path in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

_PENDING_DDL = """
CREATE TABLE pending_ingestions (
    id INTEGER PRIMARY KEY,
    crawler_name VARCHAR(100) NOT NULL,
    items_json TEXT NOT NULL,
    schema_type VARCHAR(50) NOT NULL,
    crawled_at DATETIME
)
"""
_MATCHING_DDL = """
CREATE TABLE matching_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key TEXT UNIQUE NOT NULL,
    brand VARCHAR(200),
    name_core VARCHAR(500),
    pack_qty FLOAT,
    pack_unit VARCHAR(50),
    canonical_product_id VARCHAR(40),
    category_id VARCHAR(100),
    keyword_ids JSON,
    confidence FLOAT NOT NULL DEFAULT 1.0,
    source VARCHAR(20) NOT NULL DEFAULT 'human',
    created_at DATETIME,
    updated_at DATETIME,
    last_used_at DATETIME,
    hit_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT
)
"""
_PRODUCTS_DDL = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    is_active BOOLEAN NOT NULL DEFAULT 1
)
"""
_CATEGORIES_DDL = """
CREATE TABLE categories (
    id VARCHAR(100) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    parent_id VARCHAR(100),
    depth INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    icon VARCHAR(50),
    is_active BOOLEAN DEFAULT 1
)
"""
_KEYWORDS_DDL = """
CREATE TABLE keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word VARCHAR(100) UNIQUE NOT NULL,
    synonyms JSON,
    category_id VARCHAR(100),
    search_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT 1
)
"""


@pytest.fixture()
def db_admin_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'db_admin.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text(_PENDING_DDL))
        conn.execute(text(_MATCHING_DDL))
        conn.execute(text(_PRODUCTS_DDL))
        conn.execute(text(_CATEGORIES_DDL))
        conn.execute(text(_KEYWORDS_DDL))
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def export_dir(tmp_path, monkeypatch):
    directory = tmp_path / "exports"
    directory.mkdir()
    import api.routes.raw_batch_export as mod

    monkeypatch.setattr(mod, "_EXPORT_BASE_DIR", directory)
    return directory


@pytest.fixture()
def client(db_admin_db, export_dir):
    from api.app import create_app
    from services.db_admin_readonly import get_db_admin_session

    app = create_app()

    def _db_session() -> Iterator[Session]:
        yield db_admin_db

    app.dependency_overrides[get_db_admin_session] = _db_session
    try:
        yield TestClient(
            app,
            headers={"X-API-Key": "walletsavior-dev-crawler-key-2025"},
        )
    finally:
        app.dependency_overrides.clear()


def _items(count: int) -> list[dict]:
    return [
        {
            "brand": f"브랜드{i % 5}",
            "name": f"상품명{i}",
            "sale_price": 1000 + i * 100,
            "pack_qty": float(i + 1),
            "pack_unit": "g",
            "source": "emart",
        }
        for i in range(count)
    ]


def _seed_ingestion(session: Session, ingestion_id: int = 1, count: int = 10) -> None:
    session.execute(
        text(
            "INSERT INTO pending_ingestions "
            "(id, crawler_name, items_json, schema_type, crawled_at) "
            "VALUES (:id, 'emart_crawler', :items, 'DiscountItem', '2026-05-10T00:00:00')"
        ),
        {"id": ingestion_id, "items": json.dumps(_items(count), ensure_ascii=False)},
    )
    session.commit()


def _match_key(index: int) -> str:
    from core.match_key import build_match_key

    return build_match_key(
        f"브랜드{index % 5}",
        f"상품명{index}",
        float(index + 1),
        "g",
    )


def _seed_context(session: Session) -> None:
    # 0,1: complete reusable hits. 2: matching knowledge without Product link.
    # 3: link exists but Product is inactive. 4: malformed soft-link. Only 0 and
    # 1 may count as hits; every incomplete state must remain exportable.
    session.execute(text("INSERT INTO products (id, is_active) VALUES (101, 1), (102, 1), (103, 0)"))
    entries = [
        (_match_key(0), "101"),
        (_match_key(1), "102"),
        (_match_key(2), None),
        (_match_key(3), "103"),
        (_match_key(4), "not-a-product-id"),
    ]
    for match_key, canonical_product_id in entries:
        session.execute(
            text(
                "INSERT INTO matching_entries (match_key, canonical_product_id, source) "
                "VALUES (:key, :product_id, 'human')"
            ),
            {"key": match_key, "product_id": canonical_product_id},
        )
    session.execute(
        text(
            "INSERT INTO categories (id, name, depth, sort_order, is_active) "
            "VALUES ('food', '식품', 0, 1, 1)"
        )
    )
    session.execute(
        text(
            "INSERT INTO keywords (word, category_id, search_count, is_active) "
            "VALUES ('라면', 'food', 10, 1)"
        )
    )
    session.commit()


def test_hit_lookup_requires_active_canonical_product(db_admin_db):
    from services.db_admin_readonly import bulk_lookup_hit_keys

    _seed_context(db_admin_db)
    keys = [_match_key(index) for index in range(6)]
    assert bulk_lookup_hit_keys(db_admin_db, keys) == {_match_key(0), _match_key(1)}


def test_match_status_lookup_distinguishes_incomplete_knowledge(db_admin_db):
    from services.db_admin_readonly import bulk_lookup_match_statuses

    _seed_context(db_admin_db)
    keys = [_match_key(index) for index in range(6)]
    statuses = bulk_lookup_match_statuses(db_admin_db, keys)

    assert statuses[_match_key(0)] == "hit"
    assert statuses[_match_key(1)] == "hit"
    assert statuses[_match_key(2)] == "canonical_product_unavailable"
    assert statuses[_match_key(3)] == "canonical_product_unavailable"
    assert statuses[_match_key(4)] == "canonical_product_unavailable"
    assert _match_key(5) not in statuses


def test_export_reads_pending_ingestion_and_excludes_only_completed_hits(
    client,
    db_admin_db,
    export_dir,
):
    _seed_ingestion(db_admin_db)
    _seed_context(db_admin_db)

    response = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [1]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "db-admin.pending_ingestions"
    assert body["source_ingestions"] == [1]
    assert body["total_rows"] == 10
    assert body["hit_rows"] == 2
    assert body["miss_rows"] == 8
    assert body["exported_rows"] == 8
    assert body["schema_version"] == "walletsaver-raw-batch-v3"
    assert body["ingestion_run_ids"] == ["ingestion-1"]

    jsonl_path = export_dir / body["export_id"] / "raw_products.jsonl"
    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8
    assert all(row["ingestion_id"] == 1 for row in rows)
    assert all(row["raw_record_id"].startswith("ingestion:1:") for row in rows)
    rows_by_id = {row["raw_record_id"]: row for row in rows}
    assert rows_by_id["ingestion:1:2"]["miss_reason"] == "canonical_product_unavailable"
    assert rows_by_id["ingestion:1:3"]["miss_reason"] == "canonical_product_unavailable"
    assert rows_by_id["ingestion:1:4"]["miss_reason"] == "canonical_product_unavailable"
    assert rows_by_id["ingestion:1:5"]["miss_reason"] == "key_not_found"
    assert "ingestion:1:0" not in rows_by_id
    assert "ingestion:1:1" not in rows_by_id


def test_legacy_stored_match_key_is_rebuilt_from_current_ssot(client, db_admin_db):
    item = _items(1)[0]
    item["match_key"] = "legacy-format:stale-key"
    # No matching_status: this is a pre-enrichment/legacy PendingIngestion row.
    db_admin_db.execute(
        text(
            "INSERT INTO pending_ingestions "
            "(id, crawler_name, items_json, schema_type, crawled_at) "
            "VALUES (2, 'emart_crawler', :items, 'DiscountItem', '2026-05-10T00:00:00')"
        ),
        {"items": json.dumps([item], ensure_ascii=False)},
    )
    db_admin_db.execute(text("INSERT INTO products (id, is_active) VALUES (201, 1)"))
    db_admin_db.execute(
        text(
            "INSERT INTO matching_entries (match_key, canonical_product_id, source) "
            "VALUES (:key, '201', 'human')"
        ),
        {"key": _match_key(0)},
    )
    db_admin_db.commit()

    response = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [2]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_rows"] == 1
    assert body["hit_rows"] == 1
    assert body["miss_rows"] == 0
    assert body["exported_rows"] == 0


def test_fresh_enriched_row_keeps_runtime_match_key():
    from api.routes.raw_batch_export import _build_match_key_from_payload

    key, reason = _build_match_key_from_payload(
        {
            "match_key": "runtime-key-must-win",
            "matching_status": "hit",
            # These fields may have been replaced by canonical Product metadata
            # after runtime lookup and therefore must not trigger key rebuilding.
            "brand": "canonical-brand",
            "name_core": "canonical-name",
            "pack_qty": 12,
            "pack_unit": "ea",
        }
    )
    assert key == "runtime-key-must-win"
    assert reason is None


def test_include_matched_exports_all_rows(client, db_admin_db):
    _seed_ingestion(db_admin_db)
    _seed_context(db_admin_db)

    response = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [1], "include_matched": True},
    )
    assert response.status_code == 200
    assert response.json()["exported_rows"] == 10


def test_context_files_are_created(client, db_admin_db, export_dir):
    _seed_ingestion(db_admin_db, count=2)
    _seed_context(db_admin_db)

    body = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [1]},
    ).json()
    context = export_dir / body["export_id"] / "context"

    matching_rows = (context / "matching_entries.jsonl").read_text(encoding="utf-8")
    categories = yaml.safe_load((context / "categories.yaml").read_text(encoding="utf-8"))
    keywords = yaml.safe_load((context / "keywords.yaml").read_text(encoding="utf-8"))

    assert "match_key" in matching_rows
    assert categories["categories"]
    assert keywords["keywords"]


def test_export_requires_explicit_ingestion_ids(client):
    response = client.post("/api/export/raw-batch", json={})
    assert response.status_code == 422


def test_missing_or_empty_ingestion_is_not_silently_exported(client):
    response = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [999]},
    )
    assert response.status_code == 404


def test_recent_and_download_endpoints(client, db_admin_db):
    _seed_ingestion(db_admin_db, count=2)
    _seed_context(db_admin_db)
    body = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [1]},
    ).json()

    recent = client.get("/api/export/raw-batch/recent")
    assert recent.status_code == 200
    assert recent.json()["exports"][0]["export_id"] == body["export_id"]

    download = client.get(f"/api/export/raw-batch/{body['export_id']}/download")
    assert download.status_code == 200
    with zipfile.ZipFile(BytesIO(download.content)) as archive:
        names = set(archive.namelist())
    assert "manifest.json" in names
    assert "raw_products.jsonl" in names
    assert "context/matching_entries.jsonl" in names


def test_export_includes_normalized_ssot_context_and_uses_normalized_hit(
    client, db_admin_db, export_dir
):
    _seed_ingestion(db_admin_db, count=1)
    db_admin_db.execute(text("ALTER TABLE matching_entries ADD COLUMN public_product_id TEXT"))
    db_admin_db.execute(text("ALTER TABLE matching_entries ADD COLUMN public_variant_id TEXT"))
    db_admin_db.execute(text(
        "CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT, name_ko TEXT, level INTEGER)"
    ))
    db_admin_db.execute(text(
        "CREATE TABLE normalized_canonical_products (public_product_id TEXT PRIMARY KEY, unified_category_id TEXT, canonical_name TEXT, aliases JSON, keywords JSON, attributes JSON, is_active BOOLEAN)"
    ))
    db_admin_db.execute(text(
        "CREATE TABLE normalized_product_variants (public_variant_id TEXT PRIMARY KEY, public_product_id TEXT, variant_name TEXT, attributes JSON, is_active BOOLEAN)"
    ))
    db_admin_db.execute(text(
        "CREATE TABLE normalized_source_listings (public_source_listing_id TEXT PRIMARY KEY, public_variant_id TEXT, source_name TEXT)"
    ))
    db_admin_db.execute(text(
        "CREATE TABLE mart_category_mappings (id INTEGER PRIMARY KEY, mart TEXT, mart_native_id TEXT, unified_category_id TEXT)"
    ))
    db_admin_db.execute(text(
        "INSERT INTO unified_categories VALUES ('food.dairy.milk.choco', NULL, '초코우유', 3)"
    ))
    db_admin_db.execute(text(
        "INSERT INTO normalized_canonical_products VALUES ('prod-1', 'food.dairy.milk.choco', '상품명0', '[]', '[]', '{}', 1)"
    ))
    db_admin_db.execute(text(
        "INSERT INTO normalized_product_variants VALUES ('var-1', 'prod-1', '상품명0 1g', '{}', 1)"
    ))
    db_admin_db.execute(text(
        "INSERT INTO matching_entries (match_key, public_product_id, public_variant_id, confidence, source) "
        "VALUES (:key, 'prod-1', 'var-1', 0.95, 'human')"
    ), {"key": _match_key(0)})
    db_admin_db.commit()

    body = client.post(
        "/api/export/raw-batch",
        json={"ingestion_ids": [1], "include_matched": True},
    ).json()

    assert body["hit_rows"] == 1
    context = body["files"]["normalized_context"]
    assert set(context) >= {"unified_categories", "normalized_canonical_products", "normalized_product_variants"}
    exported = Path(context["normalized_canonical_products"]).read_text(encoding="utf-8")
    assert '"public_product_id": "prod-1"' in exported


def test_invalid_export_id_is_rejected(client):
    response = client.get("/api/export/raw-batch/not-an-export-id/download")
    assert response.status_code == 422
