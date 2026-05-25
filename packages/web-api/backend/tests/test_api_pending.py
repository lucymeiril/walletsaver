"""wb1-pending-card: GET /api/v1/products/search?include_pending=true 통합 테스트.

published 5건 + pending 3건 시드 → 8건 응답, status 필드 정확.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def _seed_pending(db_path: str) -> None:
    """raw_crawl_record 테이블에 미분류 3건 삽입."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO raw_crawl_record (id, raw_title, raw_price, mart, captured_at) "
        "VALUES (?,?,?,?,?)",
        [
            ("raw_001", "이마트 미분류 과자 A", 3500, "EMART", "2024-06-01T10:00:00"),
            ("raw_002", "홈플러스 신규 음료 B", 1200, "HOMEPLUS", "2024-06-02T11:00:00"),
            ("raw_003", "롯데마트 정체불명 냉동식품 C", None, "LOTTEMART", "2024-06-03T12:00:00"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture
def pending_client(mini_snapshot_path, monkeypatch):
    """pending 레코드가 추가된 테스트 클라이언트."""
    _seed_pending(mini_snapshot_path)
    monkeypatch.setenv("WALLETSAVIOR_PUBLIC_DB", mini_snapshot_path)
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.create_app())


def test_search_without_pending_default(pending_client):
    """include_pending 미지정 시 published 5건만 반환 (기존 동작 유지)."""
    r = pending_client.get("/api/v1/products/search")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    statuses = {item["status"] for item in data["items"]}
    assert statuses == {"published"}


def test_search_include_pending_returns_8(pending_client):
    """include_pending=true 시 published 5 + pending 3 = 8건."""
    r = pending_client.get("/api/v1/products/search", params={"include_pending": "true"})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 8
    assert len(data["items"]) == 8


def test_search_pending_status_fields(pending_client):
    """pending 항목의 status 및 필드 검증."""
    r = pending_client.get(
        "/api/v1/products/search",
        params={"include_pending": "true", "page_size": 50},
    )
    assert r.status_code == 200
    items = r.json()["items"]

    published = [i for i in items if i["status"] == "published"]
    pending = [i for i in items if i["status"] == "pending_classification"]

    assert len(published) == 5
    assert len(pending) == 3

    for p in pending:
        assert p["canonical_id"].startswith("pending_raw_")
        assert p["category_id"] is None
        assert p["p10"] is None
        assert p["p50"] is None
        assert p["grade_label"] == "INSUFFICIENT_DATA"
        assert "pending_raw_id" in p

    # 가격이 있는 항목 확인
    raw_001 = next(p for p in pending if p["pending_raw_id"] == "raw_001")
    assert raw_001["price"] == 3500
    assert raw_001["marts"] == ["EMART"]

    # 가격 null 항목 확인
    raw_003 = next(p for p in pending if p["pending_raw_id"] == "raw_003")
    assert raw_003["price"] is None


def test_search_published_status_field(pending_client):
    """published 항목에 status='published' 필드가 있음을 확인."""
    r = pending_client.get("/api/v1/products/search")
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["status"] == "published"
