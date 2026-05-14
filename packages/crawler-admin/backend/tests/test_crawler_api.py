"""API route 테스트."""

import os

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    app = create_app()
    return TestClient(app)


# ── Health ───────────────────────────────────────────────────


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "crawler-admin"


# ── Crawlers ─────────────────────────────────────────────────


class TestCrawlersAPI:
    def test_list_crawlers(self, client):
        resp = client.get("/api/crawlers")
        assert resp.status_code == 200
        data = resp.json()
        assert "crawlers" in data
        assert isinstance(data["crawlers"], list)

    def test_get_crawler_status_not_found(self, client):
        resp = client.get("/api/crawlers/nonexistent/status")
        assert resp.status_code == 404

    def test_run_crawler_not_found(self, client):
        resp = client.post("/api/crawlers/nonexistent/run")
        assert resp.status_code == 404

    def test_bounded_diagnostics_defaults_to_no_live_network(self, client):
        resp = client.get("/api/crawlers/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["schema"] == "bounded_crawler_diagnostics.v1"
        assert data["live_network_default"] == "disabled"
        rows = {row["crawler_id"]: row for row in data["crawlers"]}
        assert rows["coupang"]["fixture"]["available"] is False
        assert rows["coupang"]["quality_evidence"]["has_quality_evidence"] is False
        assert rows["coupang"]["quality_evidence"]["can_claim_collecting"] is False

    def test_bounded_live_diagnostics_plan_defaults_to_artifact_only(self, client):
        resp = client.get("/api/crawlers/diagnostics/plan")
        assert resp.status_code == 200
        data = resp.json()
        rows = {row["source_id"]: row for row in data["sources"]}

        assert data["schema"] == "bounded_live_diagnostics_plan.v1"
        assert data["live_network_default"] == "disabled"
        assert rows["emart"]["current_collection_status"] == "registered_unverified"
        assert rows["emart"]["allowed_live"] is False
        assert rows["emart"]["max_requests"] == 3
        assert rows["emart"]["max_pages"] == 1
        assert rows["emart"]["timeout_seconds"] == 15
        assert rows["emart"]["fixture_snapshot_status"] == "missing"
        assert "current_collection_status:registered_unverified" in rows["emart"]["blockers"]

        assert rows["coupang"]["current_collection_status"] == "registered_unverified"
        assert rows["coupang"]["allowed_live"] is False
        assert rows["coupang"]["fixture_snapshot_status"] == "contract_fixture_available"
        assert rows["coupang"]["fixture_snapshot_path"].endswith("marketplace_skeleton\\coupang.html")
        assert any(blocker.startswith("marketplace_gate:") for blocker in rows["coupang"]["blockers"])
        assert data["source_coverage"]["collecting_count"] == 0


# ── Schedules ────────────────────────────────────────────────


class TestSchedulesAPI:
    def test_list_schedules(self, client):
        resp = client.get("/api/schedules")
        assert resp.status_code == 200
        data = resp.json()
        assert "schedules" in data

    def test_create_schedule(self, client):
        resp = client.post(
            "/api/schedules",
            json={"crawler_name": "test_cron", "cron": "0 8 * * *"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["crawler_name"] == "test_cron"

    def test_delete_schedule_not_found(self, client):
        resp = client.delete("/api/schedules/nonexistent")
        assert resp.status_code == 404


# ── Logs ─────────────────────────────────────────────────────


class TestLogsAPI:
    def test_get_logs_empty(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "logs" in data
        assert isinstance(data["logs"], list)

    def test_get_logs_with_filters(self, client):
        resp = client.get("/api/logs?limit=10&status=success")
        assert resp.status_code == 200
