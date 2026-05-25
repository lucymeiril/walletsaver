"""실패 1-click 재시도 엔드포인트 — POST /api/v1/runs/retry-last-failed/{plugin}."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from services import crawl_orchestrator as orch
from services.crawl_orchestrator import (
    OrchestratorStore,
    PluginRegistry,
    RawBatch,
    reset_run_store_for_tests,
    trigger_run,
)


class _FlakyPlugin:
    """첫 호출은 실패, 두번째부터 성공하는 mock 플러그인."""

    def __init__(self, name: str = "flakymart"):
        self._name = name
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def mart_kind(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._name.title()

    def supports_targeted_search(self, query: str) -> bool:
        return True

    async def crawl(self, targets=None) -> RawBatch:
        self.calls += 1
        if self.calls == 1:
            return RawBatch(
                plugin_name=self._name,
                items=[],
                items_found=0,
                items_saved=0,
                errors=["boom"],
                partial=False,
            )
        return RawBatch(plugin_name=self._name, items=[{"x": 1}], items_found=1, items_saved=1)


@pytest.fixture
def client(monkeypatch):
    # 인증 우회 (테스트 전용)
    monkeypatch.setenv("REQUIRE_AUTH", "false")

    # 격리된 in-memory store + registry를 모듈 헬퍼에 주입
    store = OrchestratorStore(":memory:")
    reset_run_store_for_tests(store)

    registry = PluginRegistry()
    plugin = _FlakyPlugin("flakymart")
    registry.register(plugin)

    monkeypatch.setattr(orch, "_registry_singleton", registry, raising=False)
    monkeypatch.setattr(orch, "get_registry", lambda: registry, raising=False)

    # 첫 실패 run 생성
    trigger_run("flakymart", store=store, registry=registry)

    # 플러그인 등록 헬퍼 가드를 우회 (이미 등록함)
    import api.routes.orchestrator as orch_routes
    monkeypatch.setattr(orch_routes, "_ensure_plugins_registered", lambda: None)

    app = create_app()
    return TestClient(app), store, plugin


def test_retry_last_failed_picks_latest_failed_run(client):
    c, store, plugin = client
    runs_before = store.list_runs()["items"]
    assert len(runs_before) == 1
    assert runs_before[0]["status"] == "failed"

    resp = c.post("/api/v1/runs/retry-last-failed/flakymart")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["plugin_name"] == "flakymart"
    assert body["retried_from"] == runs_before[0]["run_id"]
    assert body["run_id"]

    runs_after = store.list_runs()["items"]
    assert len(runs_after) == 2
    retried = store.get_run(body["run_id"])
    assert retried["status"] == "success"
    assert retried["retried_from"] == runs_before[0]["run_id"]


def test_retry_last_failed_is_idempotent(client):
    c, store, _ = client
    r1 = c.post("/api/v1/runs/retry-last-failed/flakymart").json()
    r2 = c.post("/api/v1/runs/retry-last-failed/flakymart").json()
    # 같은 실패 run에 대한 재시도 → orch.retry_run의 멱등성 보장으로 동일 run_id
    assert r1["run_id"] == r2["run_id"]
    assert len(store.list_runs()["items"]) == 2


def test_retry_last_failed_returns_404_when_no_failure(client, monkeypatch):
    c, store, _ = client
    # 모든 실패 run을 성공으로 표시하여 "실패 run 없음" 상태 만들기
    import sqlite3
    conn = store._connect()
    try:
        conn.execute("UPDATE crawl_runs SET status='success'")
        conn.commit()
    finally:
        if not store._is_memory:
            conn.close()

    resp = c.post("/api/v1/runs/retry-last-failed/flakymart")
    assert resp.status_code == 404
    assert "실패 run" in resp.json()["detail"]


def test_retry_last_failed_unknown_plugin_returns_404(client):
    c, _, _ = client
    resp = c.post("/api/v1/runs/retry-last-failed/no_such_plugin_xyz")
    assert resp.status_code == 404
