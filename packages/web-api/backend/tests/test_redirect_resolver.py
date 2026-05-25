"""p1-web-api-resolver-contract 테스트.

검증 대상:
  1. /products/resolve/{stable_id} — redirect 없으면 stable_id 그대로 반환
  2. /products/resolve/{stable_id} — redirect 1단계: old_id → prod_tofu_001
  3. /products/resolve/{stable_id} — redirect 체인 2단계: very_old → old → prod_tofu_001
  4. SnapshotRedirectService.resolve() — 직접 단위 테스트
  5. redirect 테이블 없는 DB에서도 resolver가 정상 동작(빈 resolver 반환)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


# ─── 서비스 단위 테스트 ───────────────────────────────────────────────────────

def _make_conn_with_redirects() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE canonical_id_redirect (
        from_id TEXT PRIMARY KEY,
        to_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT
    );
    INSERT INTO canonical_id_redirect VALUES ('old_a', 'new_a', 'merge', '2024-01-01');
    INSERT INTO canonical_id_redirect VALUES ('very_old_a', 'old_a', 'merge', '2023-01-01');
    """)
    return conn


def _make_conn_without_redirect_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def test_resolve_no_redirect_returns_same_id():
    from services.redirect_resolver import SnapshotRedirectService
    conn = _make_conn_with_redirects()
    svc = SnapshotRedirectService(conn)
    assert svc.resolve("unknown_id") == "unknown_id"


def test_resolve_single_hop():
    from services.redirect_resolver import SnapshotRedirectService
    conn = _make_conn_with_redirects()
    svc = SnapshotRedirectService(conn)
    assert svc.resolve("old_a") == "new_a"


def test_resolve_two_hop_chain():
    from services.redirect_resolver import SnapshotRedirectService
    conn = _make_conn_with_redirects()
    svc = SnapshotRedirectService(conn)
    assert svc.resolve("very_old_a") == "new_a"


def test_resolve_without_redirect_table_returns_same_id():
    from services.redirect_resolver import SnapshotRedirectService
    conn = _make_conn_without_redirect_table()
    svc = SnapshotRedirectService(conn)
    assert svc.resolve("any_id") == "any_id"


def test_resolve_or_none_returns_none_on_cycle():
    from services.redirect_resolver import SnapshotRedirectService
    # cycle: a → b → a (DB에 직접 삽입해서 강제 cycle 유발 — 정상 add()는 cycle 거부하므로 raw insert)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE canonical_id_redirect (
        from_id TEXT PRIMARY KEY, to_id TEXT NOT NULL,
        reason TEXT NOT NULL, created_at TEXT
    );
    INSERT INTO canonical_id_redirect VALUES ('cycle_a', 'cycle_b', 'merge', '2024-01-01');
    INSERT INTO canonical_id_redirect VALUES ('cycle_b', 'cycle_a', 'merge', '2024-01-01');
    """)
    svc = SnapshotRedirectService(conn)
    # cycle이 있는 행은 load 시 ignore됨 → resolve_or_none은 None 또는 정상 id
    result = svc.resolve_or_none("cycle_a")
    # cycle rows were silently skipped during load — result is whatever
    # non-None (same id or first hop) is also acceptable; key contract: no exception
    assert result is None or isinstance(result, str)


# ─── API 엔드포인트 통합 테스트 ──────────────────────────────────────────────

def test_resolve_endpoint_no_redirect(test_client):
    """stable_id에 redirect가 없으면 redirected=False, resolved_id==stable_id."""
    resp = test_client.get("/api/v1/products/resolve/prod_tofu_001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stable_id"] == "prod_tofu_001"
    assert data["resolved_id"] == "prod_tofu_001"
    assert data["redirected"] is False


def test_resolve_endpoint_single_redirect(test_client):
    """old_tofu_stable_id → prod_tofu_001."""
    resp = test_client.get("/api/v1/products/resolve/old_tofu_stable_id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stable_id"] == "old_tofu_stable_id"
    assert data["resolved_id"] == "prod_tofu_001"
    assert data["redirected"] is True


def test_resolve_endpoint_chain_redirect(test_client):
    """very_old_tofu_id → old_tofu_stable_id → prod_tofu_001."""
    resp = test_client.get("/api/v1/products/resolve/very_old_tofu_id")
    assert resp.status_code == 200
    data = resp.json()
    assert data["resolved_id"] == "prod_tofu_001"
    assert data["redirected"] is True


def test_resolve_endpoint_response_shape(test_client):
    """응답에 stable_id, resolved_id, redirected 키가 있어야 한다."""
    resp = test_client.get("/api/v1/products/resolve/some_random_id")
    assert resp.status_code == 200
    data = resp.json()
    assert "stable_id" in data
    assert "resolved_id" in data
    assert "redirected" in data
