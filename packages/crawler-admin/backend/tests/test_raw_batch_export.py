"""test_raw_batch_export.py — POST /api/export/raw-batch 통합 테스트.

시나리오:
    1. matching miss 정확히 골라내는지 (10건 raw, 3건 hit → miss=7)
    2. context 파일 3종 모두 생성되고 비어있지 않은지
    3. manifest sha256 검증
    4. 빈 batch 처리 (raw_batch_ids=[], 레코드 없음)
    5. matching_entries 비어있을 때도 동작
    6. include_matched=True 시 hit 포함 여부
    7. /recent 엔드포인트
    8. /{export_id}/download ZIP 다운로드
    9. 잘못된 export_id → 422
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ── sys.path 보정 ─────────────────────────────────────────────────────────────
import sys

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── DDL ───────────────────────────────────────────────────────────────────────

_AI_ADMIN_DDL_1 = """
CREATE TABLE IF NOT EXISTS raw_crawl_batches (
    batch_id    VARCHAR(120) PRIMARY KEY,
    source_name VARCHAR(120) NOT NULL,
    crawler_name VARCHAR(120) NOT NULL,
    item_count  INTEGER NOT NULL DEFAULT 0,
    schema_type VARCHAR(120) NOT NULL,
    status      VARCHAR(40) NOT NULL,
    source_url  TEXT,
    raw_artifact_uri TEXT,
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_AI_ADMIN_DDL_2 = """
CREATE TABLE IF NOT EXISTS raw_crawl_records (
    raw_record_id   VARCHAR(120) PRIMARY KEY,
    batch_id        VARCHAR(120) NOT NULL REFERENCES raw_crawl_batches(batch_id),
    source_name     VARCHAR(120) NOT NULL,
    source_record_key VARCHAR(255),
    source_url      TEXT,
    raw_title       TEXT NOT NULL,
    raw_price       INTEGER,
    raw_payload     JSON NOT NULL DEFAULT '{}',
    crawled_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_MATCHING_DDL = """
CREATE TABLE IF NOT EXISTS matching_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_key   TEXT    UNIQUE NOT NULL,
    brand       VARCHAR(200),
    name_core   VARCHAR(500),
    pack_qty    FLOAT,
    pack_unit   VARCHAR(50),
    canonical_product_id VARCHAR(40),
    category_id VARCHAR(100),
    keyword_ids JSON,
    confidence  FLOAT   NOT NULL DEFAULT 1.0,
    source      VARCHAR(20) NOT NULL DEFAULT 'human',
    created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at DATETIME,
    hit_count   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);
"""

_CATEGORIES_DDL = """
CREATE TABLE IF NOT EXISTS categories (
    id          VARCHAR(100) PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    parent_id   VARCHAR(100),
    depth       INTEGER DEFAULT 0,
    sort_order  INTEGER DEFAULT 0,
    icon        VARCHAR(50),
    is_active   BOOLEAN DEFAULT 1
);
"""

_KEYWORDS_DDL = """
CREATE TABLE IF NOT EXISTS keywords (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        VARCHAR(100) UNIQUE NOT NULL,
    synonyms    JSON,
    category_id VARCHAR(100),
    search_count INTEGER DEFAULT 0,
    is_active   BOOLEAN DEFAULT 1
);
"""


# ── 픽스처 ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def ai_admin_db(tmp_path):
    """ai-admin control DB (raw_crawl_batches + raw_crawl_records)."""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'ai_admin.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text(_AI_ADMIN_DDL_1))
        conn.execute(text(_AI_ADMIN_DDL_2))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def db_admin_db(tmp_path):
    """db-admin DB (matching_entries + categories + keywords)."""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'db_admin.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text(_MATCHING_DDL))
        conn.execute(text(_CATEGORIES_DDL))
        conn.execute(text(_KEYWORDS_DDL))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def export_dir(tmp_path, monkeypatch):
    """export 아티팩트 경로를 tmp_path로 리다이렉트."""
    d = tmp_path / "exports"
    d.mkdir()
    import api.routes.raw_batch_export as mod
    monkeypatch.setattr(mod, "_EXPORT_BASE_DIR", d)
    return d


@pytest.fixture()
def client(ai_admin_db, db_admin_db, export_dir):
    """FastAPI TestClient — ai-admin / db-admin DB 세션을 모두 override."""
    from api.app import create_app
    from services.ai_admin_readonly import get_ai_admin_session
    from services.db_admin_readonly import get_db_admin_session

    app = create_app()

    def _ai_session() -> Iterator[Session]:
        yield ai_admin_db

    def _db_session() -> Iterator[Session]:
        yield db_admin_db

    app.dependency_overrides[get_ai_admin_session] = _ai_session
    app.dependency_overrides[get_db_admin_session] = _db_session

    headers = {"X-API-Key": "walletsavior-dev-crawler-key-2025"}
    try:
        yield TestClient(app, headers=headers)
    finally:
        app.dependency_overrides.clear()


# ── 시드 헬퍼 ────────────────────────────────────────────────────────────────

_BASE_TIME = datetime(2026, 5, 10, 0, 0, 0)


def _seed_batch(session: Session, batch_id: str = "batch-001", source: str = "emart") -> None:
    session.execute(
        text(
            "INSERT INTO raw_crawl_batches "
            "(batch_id, source_name, crawler_name, item_count, schema_type, status) "
            "VALUES (:bid, :src, 'test_crawler', 0, 'mart_discount', 'raw_ingested')"
        ),
        {"bid": batch_id, "src": source},
    )
    session.flush()


def _seed_records(
    session: Session,
    batch_id: str,
    count: int,
    source_name: str = "emart",
) -> list[str]:
    """raw_crawl_records 시드. brand/name 포함한 raw_payload."""
    ids = []
    for i in range(count):
        rec_id = f"{batch_id}-rec-{i:03d}"
        crawled_at = _BASE_TIME + timedelta(minutes=i)
        payload = json.dumps(
            {"brand": f"브랜드{i % 5}", "name": f"상품명{i}", "pack_qty": float(i + 1), "pack_unit": "g"},
            ensure_ascii=False,
        )
        session.execute(
            text(
                "INSERT INTO raw_crawl_records "
                "(raw_record_id, batch_id, source_name, raw_title, raw_price, raw_payload, crawled_at) "
                "VALUES (:rid, :bid, :src, :title, :price, :payload, :cat)"
            ),
            {
                "rid": rec_id,
                "bid": batch_id,
                "src": source_name,
                "title": f"테스트상품{i}",
                "price": 1000 + i * 100,
                "payload": payload,
                "cat": crawled_at.isoformat(),
            },
        )
        ids.append(rec_id)
    session.flush()
    return ids


def _compute_match_key(brand: str, name: str, qty: float, unit: str) -> str:
    from core.match_key import build_match_key
    return build_match_key(brand, name, qty, unit)


def _seed_matching_entries(session: Session, match_keys: list[str]) -> None:
    for key in match_keys:
        session.execute(
            text("INSERT INTO matching_entries (match_key, source) VALUES (:k, 'human')"),
            {"k": key},
        )
    session.flush()


def _seed_categories(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO categories (id, name, parent_id, depth, sort_order, is_active) VALUES "
            "('food', '식품', NULL, 0, 1, 1), "
            "('food.snack', '과자', 'food', 1, 1, 1)"
        )
    )
    session.flush()


def _seed_keywords(session: Session) -> None:
    session.execute(
        text(
            "INSERT INTO keywords (word, synonyms, category_id, search_count, is_active) VALUES "
            "('오징어땅콩', NULL, 'food.snack', 10, 1), "
            "('신라면', '[\"라면\"]', 'food', 5, 1)"
        )
    )
    session.flush()


# ── 테스트 1: 기본 miss 분류 ─────────────────────────────────────────────────

class TestBasicMissClassification:
    """raw 10건, matching 3건 hit → miss=7."""

    def _setup(self, ai_admin_db, db_admin_db):
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=10)
        ai_admin_db.commit()

        hit_keys = [
            _compute_match_key(f"브랜드{i % 5}", f"상품명{i}", float(i + 1), "g")
            for i in range(3)
        ]
        _seed_matching_entries(db_admin_db, hit_keys)
        db_admin_db.commit()

    def test_miss_count_is_seven(self, client, ai_admin_db, db_admin_db):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["hit_rows"] == 3
        assert body["miss_rows"] == 7
        assert body["exported_rows"] == 7

    def test_jsonl_excludes_hit_records(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        assert r.status_code == 200
        export_id = r.json()["export_id"]
        jsonl_path = export_dir / export_id / "raw_products.jsonl"
        assert jsonl_path.exists()
        lines = [json.loads(ln) for ln in jsonl_path.read_text(encoding="utf-8").strip().splitlines()]
        assert len(lines) == 7
        # hit 레코드(rec-000~002)는 포함 안 됨
        ids = [ln["raw_record_id"] for ln in lines]
        for i in range(3):
            assert f"batch-001-rec-{i:03d}" not in ids

    def test_csv_file_created(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        csv_path = export_dir / export_id / "raw_products.csv"
        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8")
        # 한글 헤더 확인
        assert "마트" in content
        assert "상품명" in content

    def test_include_matched_true(self, client, ai_admin_db, db_admin_db):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post(
            "/api/export/raw-batch",
            json={"raw_batch_ids": ["batch-001"], "include_matched": True},
        )
        body = r.json()
        assert body["exported_rows"] == 10  # hit(3) + miss(7)


# ── 테스트 2: context 파일 3종 ───────────────────────────────────────────────

class TestContextFiles:
    """context/ 디렉토리에 3종 파일이 모두 생성되고 비어있지 않은지 검증."""

    def _setup(self, ai_admin_db, db_admin_db):
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=5)
        ai_admin_db.commit()
        _seed_matching_entries(db_admin_db, ["CJ|햇반|210.0|g"])
        _seed_categories(db_admin_db)
        _seed_keywords(db_admin_db)
        db_admin_db.commit()

    def test_matching_entries_jsonl_exists_and_nonempty(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        me_path = export_dir / export_id / "context" / "matching_entries.jsonl"
        assert me_path.exists(), "context/matching_entries.jsonl 이 없음"
        lines = [json.loads(ln) for ln in me_path.read_text(encoding="utf-8").strip().splitlines()]
        assert len(lines) >= 1
        assert "match_key" in lines[0]

    def test_categories_yaml_exists_and_nonempty(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        cat_path = export_dir / export_id / "context" / "categories.yaml"
        assert cat_path.exists(), "context/categories.yaml 이 없음"
        data = yaml.safe_load(cat_path.read_text(encoding="utf-8"))
        assert "categories" in data
        assert len(data["categories"]) >= 1

    def test_keywords_yaml_exists_and_nonempty(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        kw_path = export_dir / export_id / "context" / "keywords.yaml"
        assert kw_path.exists(), "context/keywords.yaml 이 없음"
        data = yaml.safe_load(kw_path.read_text(encoding="utf-8"))
        assert "keywords" in data
        assert len(data["keywords"]) >= 1
        words = [k["word"] for k in data["keywords"]]
        assert "오징어땅콩" in words


# ── 테스트 3: manifest sha256 검증 ───────────────────────────────────────────

class TestManifestSha256:
    def _setup(self, ai_admin_db, db_admin_db):
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=5)
        ai_admin_db.commit()
        db_admin_db.commit()

    def test_manifest_sha256_jsonl(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        manifest = json.loads((export_dir / export_id / "manifest.json").read_text(encoding="utf-8"))
        jsonl_path = export_dir / export_id / "raw_products.jsonl"
        expected = hashlib.sha256(jsonl_path.read_bytes()).hexdigest()
        assert manifest["file_sha256s"]["raw_products.jsonl"] == expected

    def test_manifest_sha256_csv(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        manifest = json.loads((export_dir / export_id / "manifest.json").read_text(encoding="utf-8"))
        csv_path = export_dir / export_id / "raw_products.csv"
        expected = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        assert manifest["file_sha256s"]["raw_products.csv"] == expected

    def test_manifest_sha256_matching_entries(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        manifest = json.loads((export_dir / export_id / "manifest.json").read_text(encoding="utf-8"))
        me_path = export_dir / export_id / "context" / "matching_entries.jsonl"
        expected = hashlib.sha256(me_path.read_bytes()).hexdigest()
        assert manifest["file_sha256s"]["context/matching_entries.jsonl"] == expected

    def test_manifest_schema_version(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        manifest = json.loads((export_dir / export_id / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["schema_version"] == 1
        assert "source_batches" in manifest
        assert "total_rows" in manifest
        assert "miss_rows" in manifest

    def test_previous_export_id_linked(self, client, ai_admin_db, db_admin_db, export_dir):
        self._setup(ai_admin_db, db_admin_db)
        first = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]}).json()
        second = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]}).json()
        manifest2 = json.loads(
            (export_dir / second["export_id"] / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest2["previous_export_id"] == first["export_id"]


# ── 테스트 4: 빈 batch 처리 ──────────────────────────────────────────────────

class TestEmptyBatch:
    def test_empty_batch_ids_exports_all(self, client, ai_admin_db, db_admin_db, export_dir):
        """raw_batch_ids=[] → 전체 records 대상."""
        _seed_batch(ai_admin_db, "b1")
        _seed_records(ai_admin_db, "b1", count=3)
        ai_admin_db.commit()
        db_admin_db.commit()

        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": []})
        assert r.status_code == 200
        body = r.json()
        assert body["total_rows"] == 3

    def test_no_records_in_db(self, client, ai_admin_db, db_admin_db, export_dir):
        """DB가 완전히 비어있어도 정상 동작해야 한다."""
        ai_admin_db.commit()
        db_admin_db.commit()
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": []})
        assert r.status_code == 200
        body = r.json()
        assert body["total_rows"] == 0
        assert body["miss_rows"] == 0
        assert body["exported_rows"] == 0

    def test_nonexistent_batch_id_returns_empty(self, client, ai_admin_db, db_admin_db):
        """존재하지 않는 batch_id → 레코드 0건."""
        ai_admin_db.commit()
        db_admin_db.commit()
        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["no-such-batch"]})
        assert r.status_code == 200
        assert r.json()["total_rows"] == 0


# ── 테스트 5: matching_entries 비어있을 때 ───────────────────────────────────

class TestEmptyMatchingEntries:
    def test_all_records_become_miss(self, client, ai_admin_db, db_admin_db, export_dir):
        """matching_entries가 비어있으면 모든 레코드가 miss다."""
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=5)
        ai_admin_db.commit()
        # matching_entries에 아무것도 삽입 안 함
        db_admin_db.commit()

        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        assert r.status_code == 200
        body = r.json()
        assert body["hit_rows"] == 0
        assert body["miss_rows"] == 5

    def test_context_matching_entries_jsonl_empty_but_exists(
        self, client, ai_admin_db, db_admin_db, export_dir
    ):
        """matching_entries 빈 상태에서도 context/matching_entries.jsonl은 생성돼야 한다."""
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=2)
        ai_admin_db.commit()
        db_admin_db.commit()

        r = client.post("/api/export/raw-batch", json={"raw_batch_ids": ["batch-001"]})
        export_id = r.json()["export_id"]
        me_path = export_dir / export_id / "context" / "matching_entries.jsonl"
        assert me_path.exists()
        # 비어있어도 파일 자체는 존재해야 함
        content = me_path.read_text(encoding="utf-8")
        assert content == ""  # 빈 파일


# ── 테스트 6: /recent 엔드포인트 ─────────────────────────────────────────────

class TestRecentExports:
    def test_recent_empty_on_no_exports(self, client, export_dir):
        r = client.get("/api/export/raw-batch/recent")
        assert r.status_code == 200
        body = r.json()
        assert body["exports"] == []
        assert body["total"] == 0

    def test_recent_returns_exports(self, client, ai_admin_db, db_admin_db, export_dir):
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=2)
        ai_admin_db.commit()
        db_admin_db.commit()

        client.post("/api/export/raw-batch", json={"raw_batch_ids": []})
        client.post("/api/export/raw-batch", json={"raw_batch_ids": []})

        r = client.get("/api/export/raw-batch/recent")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert len(body["exports"]) == 2

    def test_recent_sorted_newest_first(self, client, ai_admin_db, db_admin_db, export_dir):
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=1)
        ai_admin_db.commit()
        db_admin_db.commit()

        first = client.post("/api/export/raw-batch", json={"raw_batch_ids": []}).json()
        second = client.post("/api/export/raw-batch", json={"raw_batch_ids": []}).json()

        body = client.get("/api/export/raw-batch/recent").json()
        ids = [e["export_id"] for e in body["exports"]]
        assert ids[0] == second["export_id"]
        assert ids[1] == first["export_id"]

    def test_recent_limit(self, client, ai_admin_db, db_admin_db, export_dir):
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=1)
        ai_admin_db.commit()
        db_admin_db.commit()

        for _ in range(5):
            client.post("/api/export/raw-batch", json={"raw_batch_ids": []})

        body = client.get("/api/export/raw-batch/recent?limit=3").json()
        assert len(body["exports"]) == 3
        assert body["total"] == 5


# ── 테스트 7: /{export_id}/download ─────────────────────────────────────────

class TestDownload:
    def _create_export(self, client, ai_admin_db, db_admin_db) -> str:
        _seed_batch(ai_admin_db)
        _seed_records(ai_admin_db, "batch-001", count=3)
        ai_admin_db.commit()
        db_admin_db.commit()
        return client.post("/api/export/raw-batch", json={"raw_batch_ids": []}).json()["export_id"]

    def test_download_zip_success(self, client, ai_admin_db, db_admin_db, export_dir):
        export_id = self._create_export(client, ai_admin_db, db_admin_db)
        r = client.get(f"/api/export/raw-batch/{export_id}/download")
        assert r.status_code == 200
        assert "application/zip" in r.headers.get("content-type", "")
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert "raw_products.jsonl" in names
        assert "raw_products.csv" in names
        assert "manifest.json" in names
        assert "context/matching_entries.jsonl" in names
        assert "context/categories.yaml" in names
        assert "context/keywords.yaml" in names

    def test_download_invalid_export_id_format(self, client, export_dir):
        r = client.get("/api/export/raw-batch/not-valid-id/download")
        assert r.status_code == 422

    def test_download_nonexistent_export_id(self, client, export_dir):
        r = client.get("/api/export/raw-batch/exp-20260101000000-abcdef12/download")
        assert r.status_code == 404
