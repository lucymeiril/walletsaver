"""test_export_unmatched.py — /api/export/unmatched 엔드포인트 RD7 deprecation 테스트.

RD7 변경: 이 엔드포인트들은 모두 410 Gone을 반환한다.
외부 분류 export는 crawler-admin /api/export/raw-batch 로 이전됐다.

원래 시나리오(보존):
    1. 기본 export — raw 10건, matching 3건 hit → miss_count=7, JSONL/CSV/manifest 검증
    2. captured_since 필터 작동 확인
    3. limit 필터 작동 확인
    4. 재호출 시 manifest previous_batch_id 채워짐 (이력 연결)
    5. download 엔드포인트 — jsonl / csv / zip 정상 응답
    6. /recent 정렬(최신 우선) + 개수 제한
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# ── 경로 보정 ──────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from storage.models import Base as AiAdminBase, RawCrawlBatch, RawCrawlRecord
from services.matching_db import get_matching_session


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
)
"""


@pytest.fixture()
def ai_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'ai_admin.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    AiAdminBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def matching_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'matching.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text(_MATCHING_DDL))
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def export_dir(tmp_path, monkeypatch):
    d = tmp_path / "exports"
    d.mkdir()
    import api.routes.export as export_mod
    monkeypatch.setattr(export_mod, "_EXPORT_BASE_DIR", d)
    return d


@pytest.fixture()
def client(ai_db, matching_db, export_dir):
    from api.app import create_app
    from api.deps import get_db_session

    app = create_app()

    def _ai_session() -> Iterator[Session]:
        yield ai_db

    def _matching_session() -> Iterator[Session]:
        yield matching_db

    app.dependency_overrides[get_db_session] = _ai_session
    app.dependency_overrides[get_matching_session] = _matching_session

    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ── RD7: 모든 엔드포인트가 410 Gone 반환 ─────────────────────────────────────

class TestGone410:
    """RD7 deprecation: 모든 엔드포인트가 410 Gone + 이전 안내를 반환해야 한다."""

    def test_post_unmatched_returns_410(self, client):
        r = client.post("/api/export/unmatched", json={})
        assert r.status_code == 410
        assert "crawler-admin" in r.json().get("detail", "")

    def test_get_recent_returns_410(self, client):
        r = client.get("/api/export/unmatched/recent")
        assert r.status_code == 410
        assert "crawler-admin" in r.json().get("detail", "")

    def test_get_download_returns_410(self, client):
        r = client.get("/api/export/unmatched/download?batch_id=exp-test-0000")
        assert r.status_code == 410
        assert "crawler-admin" in r.json().get("detail", "")

    def test_gone_body_has_raw_batch_path(self, client):
        """이전 안내에 /api/export/raw-batch 경로가 포함돼야 한다."""
        r = client.post("/api/export/unmatched", json={})
        detail = r.json().get("detail", "")
        assert "/api/export/raw-batch" in detail