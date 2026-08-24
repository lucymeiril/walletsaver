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
    for index in range(3):
        session.execute(
            text("INSERT INTO matching_entries (match_key, source) VALUES (:key, 'human')"),
            {"key": _match_key(index)},
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


def test_export_reads_pending_ingestion_and_excludes_matching_hits(
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
    assert body["hit_rows"] == 3
    assert body["miss_rows"] == 7
    assert body["exported_rows"] == 7

    jsonl_path = export_dir / body["export_id"] / "raw_products.jsonl"
    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 7
    assert all(row["ingestion_id"] == 1 for row in rows)
    assert all(row["raw_record_id"].startswith("ingestion:1:") for row in rows)


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


def test_invalid_export_id_is_rejected(client):
    response = client.get("/api/export/raw-batch/not-an-export-id/download")
    assert response.status_code == 422
