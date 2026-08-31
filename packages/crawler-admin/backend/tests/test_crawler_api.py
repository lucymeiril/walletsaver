"""Focused API regressions for the current crawler-admin runtime."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes import crawlers as crawler_routes
from services import crawl_orchestrator as orch


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    monkeypatch.setenv("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", "1")
    orch.reset_run_store_for_tests(orch.OrchestratorStore(":memory:"))
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_current_service(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "crawler-admin"
    assert data["status"] in {"ok", "degraded"}


def test_list_crawlers_exposes_four_current_marts(client):
    response = client.get("/api/crawlers")
    assert response.status_code == 200
    data = response.json()
    rows = data.get("crawlers", [])
    names = {row.get("name") for row in rows}
    assert {"emart", "homeplus", "lottemart", "costco"}.issubset(names)


def test_unknown_crawler_routes_return_not_found(client):
    assert client.get("/api/crawlers/nonexistent/status").status_code == 404
    assert client.post("/api/crawlers/nonexistent/run").status_code == 404


def test_emart_category_endpoints_only_run_allowlisted_ids(client, monkeypatch):
    async def fake_run_and_store(crawler_id, pipeline, *, crawl_method="crawl"):
        crawler = crawler_routes._require_crawler(crawler_id)
        crawler._selected_category_request = None
        await crawler_routes.release_crawler_slot(crawler_id)

    monkeypatch.setattr(crawler_routes, "_run_and_store", fake_run_and_store)

    listed = client.get("/api/crawlers/emart/categories")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["crawler_id"] == "emart"
    assert payload["count"] == 29
    assert any(row["category_hint"] == "우유/유제품" for row in payload["categories"])

    rejected = client.post(
        "/api/crawlers/emart/run-category",
        json={"category_id": "not-allowlisted"},
    )
    assert rejected.status_code == 404

    selected = payload["categories"][0]
    started = client.post(
        "/api/crawlers/emart/run-category",
        json={"category_id": selected["category_id"]},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["category"]["category_id"] == selected["category_id"]


def test_category_request_bodies_reach_route_validation(client):
    lotte = client.post(
        "/api/crawlers/lottemart/run-category",
        json={"query": "not-allowlisted"},
    )

    assert lotte.status_code == 404
    assert "롯데마트 카테고리" in lotte.json()["detail"]
    schema = client.app.openapi()
    assert "/api/crawlers/emart/run-category" in schema["paths"]
    assert "/api/crawlers/lottemart/run-category" in schema["paths"]


def test_orchestrator_rejects_unknown_schedule_plugin(client):
    response = client.post(
        "/api/v1/schedules",
        json={"plugin_name": "nonexistent", "cron_expr": "0 8 * * *"},
    )
    assert response.status_code == 404


def test_orchestrator_rejects_invalid_cron(client):
    response = client.post(
        "/api/v1/schedules",
        json={"plugin_name": "emart", "cron_expr": "not a cron"},
    )
    assert response.status_code == 400


def test_orchestrator_schedule_crud_uses_current_api(client):
    created = client.post(
        "/api/v1/schedules",
        json={"plugin_name": "emart", "cron_expr": "0 8 * * *"},
    )
    assert created.status_code == 201
    schedule = created.json()
    schedule_id = schedule["id"]
    assert schedule["plugin_name"] == "emart"

    listed = client.get("/api/v1/schedules")
    assert listed.status_code == 200
    assert any(row["id"] == schedule_id for row in listed.json()["schedules"])

    updated = client.patch(
        f"/api/v1/schedules/{schedule_id}",
        json={"cron_expr": "0 9 * * *", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["cron_expr"] == "0 9 * * *"
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/v1/schedules/{schedule_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


def test_logs_endpoint_returns_list_contract(client):
    response = client.get("/api/logs?limit=10&status=success")
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)


def test_logs_endpoint_reads_canonical_orchestrator_runs(client):
    store = orch.get_run_store()
    run_id = store.create_run("emart", triggered_by="manual")
    store.update_run_status(
        run_id,
        status="success",
        items_found=4,
        items_saved=3,
    )

    response = client.get("/api/logs?job_id=emart&status=success")

    assert response.status_code == 200
    [entry] = response.json()["logs"]
    assert entry["job_id"] == "emart"
    assert entry["run_id"] == run_id
    assert entry["result"]["items_found"] == 4
    assert entry["result"]["items_saved"] == 3
