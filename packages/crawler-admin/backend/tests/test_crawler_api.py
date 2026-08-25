"""Focused API regressions for the current crawler-admin runtime."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
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
