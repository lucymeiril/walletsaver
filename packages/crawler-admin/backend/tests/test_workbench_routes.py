"""workbench 라우트 smoke 테스트 — overview / runs / samples / run-all."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from api.app import create_app
from services import crawl_orchestrator as orch
from services.ai_admin_readonly import get_ai_admin_session
from services.crawl_orchestrator import (
    OrchestratorStore,
    PluginRegistry,
    RawBatch,
    reset_run_store_for_tests,
    trigger_run,
)


class _StubPlugin:
    def __init__(self, name: str, items: int = 5):
        self._name = name
        self._items = items

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
        return RawBatch(
            plugin_name=self._name,
            items=[{"i": i} for i in range(self._items)],
            items_found=self._items,
            items_saved=self._items,
        )


@pytest.fixture
def workbench_client(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "false")

    # in-memory orchestrator store
    store = OrchestratorStore(":memory:")
    reset_run_store_for_tests(store)

    # 4사 stub plugin 등록
    registry = PluginRegistry()
    for n in ("emart", "homeplus", "lottemart", "costco"):
        # capSuspect 테스트용: emart는 200건(round) — cap 의심.
        cnt = 200 if n == "emart" else 17
        registry.register(_StubPlugin(n, items=cnt))
    monkeypatch.setattr(orch, "_registry_singleton", registry, raising=False)
    monkeypatch.setattr(orch, "get_registry", lambda: registry, raising=False)

    # 각 마트 1회씩 트리거하여 last_run 시뮬레이션
    for n in ("emart", "homeplus", "lottemart", "costco"):
        trigger_run(n, store=store, registry=registry)

    # workbench의 _ensure_plugins는 실제 플러그인 모듈 import 시도 — stub만 등록한 상태로
    # 두려면 우회.
    import api.routes.workbench as wb
    monkeypatch.setattr(wb, "_ensure_plugins", lambda: None)

    # ai-admin DB(raw_crawl_records)는 in-memory SQLite로 모의.
    # in-memory SQLite는 연결마다 별개의 DB이므로 StaticPool로 단일 연결을 공유한다.
    from sqlalchemy.pool import StaticPool
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE raw_crawl_records ("
            " raw_record_id TEXT PRIMARY KEY,"
            " batch_id TEXT, source_name TEXT,"
            " raw_title TEXT, raw_price REAL,"
            " crawled_at TEXT, raw_payload TEXT)"
        ))
        # emart 5건(중복 1쌍), homeplus 1건, 나머지 0건.
        for i in range(5):
            conn.execute(text(
                "INSERT INTO raw_crawl_records VALUES (:r,:b,:s,:t,:p,:c,:pl)"
            ), {"r": f"e{i}", "b": "b1", "s": "emart",
                  "t": "삼다수 2L" if i < 2 else f"상품{i}",
                  "p": 1000.0 + i, "c": f"2024-01-0{i+1}T00:00:00",
                  "pl": '{"brand":"제주","name":"삼다수"}'})
        conn.execute(text(
            "INSERT INTO raw_crawl_records VALUES (:r,:b,:s,:t,:p,:c,:pl)"
        ), {"r": "h1", "b": "b2", "s": "homeplus",
              "t": "콜라", "p": 1500.0, "c": "2024-01-02T00:00:00",
              "pl": '{"brand":"코카","name":"콜라"}'})

    SessionLocal = sessionmaker(bind=eng, autoflush=False, autocommit=False)

    def _override():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app = create_app()
    app.dependency_overrides[get_ai_admin_session] = _override
    return TestClient(app)


def test_overview_returns_4_marts(workbench_client):
    r = workbench_client.get("/api/workbench/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [m["key"] for m in body["marts"]]
    assert keys == ["emart", "homeplus", "lottemart", "costco"]
    assert body["liveReady"] is True
    assert body["registeredCount"] == 4


def test_overview_cap_suspect_flag(workbench_client):
    body = workbench_client.get("/api/workbench/overview").json()
    emart = next(m for m in body["marts"] if m["key"] == "emart")
    assert emart["itemsFound"] == 200
    assert emart["capSuspect"] is True
    assert emart["rawRecordCount"] == 5
    assert emart["dupTitles"] == 1  # "삼다수 2L"가 2번
    homeplus = next(m for m in body["marts"] if m["key"] == "homeplus")
    assert homeplus["capSuspect"] is False  # 17건
    assert homeplus["rawRecordCount"] == 1


def test_runs_endpoint(workbench_client):
    r = workbench_client.get("/api/workbench/mart/emart/runs?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["mart"] == "emart"
    assert len(body["runs"]) == 1
    assert body["runs"][0]["items_found"] == 200


def test_runs_unknown_mart(workbench_client):
    r = workbench_client.get("/api/workbench/mart/notamart/runs")
    assert r.status_code == 404


def test_samples_endpoint(workbench_client):
    r = workbench_client.get("/api/workbench/mart/emart/samples?limit=3")
    assert r.status_code == 200
    body = r.json()
    assert body["mart"] == "emart"
    assert len(body["samples"]) == 3
    # raw_payload는 dict로 파싱되어야 함
    assert isinstance(body["samples"][0]["raw_payload"], dict)
    assert body["samples"][0]["raw_payload"].get("brand") == "제주"


def test_run_all_endpoint(workbench_client):
    r = workbench_client.post("/api/workbench/run-all")
    assert r.status_code == 202
    body = r.json()
    assert len(body["results"]) == 4
    assert all(it["status"] == "started" for it in body["results"])
