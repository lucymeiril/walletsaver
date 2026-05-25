"""p1-ai-admin-evidence-schema 회귀 테스트.

테스트 커버리지:
  1. BrandAliasEvidence 테이블 생성 확인
  2. POST /api/evidence/brand-alias — upsert (신규)
  3. POST /api/evidence/brand-alias — upsert (중복 → trigger_count++, score max)
  4. GET /api/evidence/brand-alias — suggested 목록 필터
  5. POST /api/evidence/brand-alias/{id}/approve — 승인
  6. POST /api/evidence/brand-alias/{id}/reject — 거절
  7. 404 approve/reject on unknown evidence_id
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api.app import create_app
from api.deps import get_db_session
from storage.models import Base, BrandAliasEvidence
from storage.repositories import BrandAliasEvidenceRepository


@pytest.fixture()
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{(tmp_path / 'evidence.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def client(session) -> Iterator[TestClient]:
    app = create_app()

    def _override():
        yield session

    app.dependency_overrides[get_db_session] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ─── 1. 테이블 생성 ──────────────────────────────────────────────────────────

def test_brand_alias_evidence_table_created(engine):
    tables = set(inspect(engine).get_table_names())
    assert "brand_alias_evidence" in tables


# ─── 2. POST 신규 upsert ─────────────────────────────────────────────────────

def test_ingest_brand_alias_new(client):
    r = client.post("/api/evidence/brand-alias", json={
        "brand_alias": "풀무원식품",
        "canonical_brand": "풀무원",
        "source_batch_id": "batch-001",
        "evidence_score": 0.8,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["brand_alias"] == "풀무원식품"
    assert data["canonical_brand"] == "풀무원"
    assert data["trigger_count"] == 1
    assert data["evidence_score"] == 0.8
    assert data["status"] == "suggested"


# ─── 3. POST 중복 → trigger_count 증가 ────────────────────────────────────────

def test_ingest_brand_alias_duplicate_increments_count(client):
    payload = {
        "brand_alias": "CJ제일제당",
        "canonical_brand": "CJ",
        "source_batch_id": "batch-001",
        "evidence_score": 0.5,
    }
    client.post("/api/evidence/brand-alias", json=payload)
    # 두 번째 호출: score 높게
    payload2 = {**payload, "source_batch_id": "batch-002", "evidence_score": 0.9}
    r2 = client.post("/api/evidence/brand-alias", json=payload2)
    assert r2.status_code == 200
    data = r2.json()
    assert data["trigger_count"] == 2
    assert data["evidence_score"] == 0.9  # max(0.5, 0.9)


# ─── 4. GET 목록 필터 ────────────────────────────────────────────────────────

def test_list_suggested_min_score_filter(client):
    client.post("/api/evidence/brand-alias", json={
        "brand_alias": "A-low",
        "canonical_brand": "A",
        "source_batch_id": "b1",
        "evidence_score": 0.2,
    })
    client.post("/api/evidence/brand-alias", json={
        "brand_alias": "B-high",
        "canonical_brand": "B",
        "source_batch_id": "b2",
        "evidence_score": 0.8,
    })
    r = client.get("/api/evidence/brand-alias?min_score=0.5")
    assert r.status_code == 200
    data = r.json()
    aliases = [i["brand_alias"] for i in data["items"]]
    assert "B-high" in aliases
    assert "A-low" not in aliases


# ─── 5. approve ──────────────────────────────────────────────────────────────

def test_approve_evidence(client):
    r_create = client.post("/api/evidence/brand-alias", json={
        "brand_alias": "삼성물산",
        "canonical_brand": "삼성",
        "source_batch_id": "b3",
        "evidence_score": 0.7,
    })
    evidence_id = r_create.json()["evidence_id"]

    r = client.post(f"/api/evidence/brand-alias/{evidence_id}/approve", json={
        "approved_by": "admin-01"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "approved"
    assert data["approved_by"] == "admin-01"


# ─── 6. reject ───────────────────────────────────────────────────────────────

def test_reject_evidence(client):
    r_create = client.post("/api/evidence/brand-alias", json={
        "brand_alias": "롯데쇼핑",
        "canonical_brand": "롯데",
        "source_batch_id": "b4",
        "evidence_score": 0.3,
    })
    evidence_id = r_create.json()["evidence_id"]

    r = client.post(f"/api/evidence/brand-alias/{evidence_id}/reject", json={
        "reason": "different_entity"
    })
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "rejected"
    assert data["rejected_reason"] == "different_entity"


# ─── 7. 404 on unknown ───────────────────────────────────────────────────────

def test_approve_unknown_evidence_returns_404(client):
    r = client.post("/api/evidence/brand-alias/no-such-id/approve", json={"approved_by": "x"})
    assert r.status_code == 404
