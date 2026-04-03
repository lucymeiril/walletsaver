"""API route 테스트."""

import pytest
from fastapi.testclient import TestClient

from api.app import create_app


@pytest.fixture
def client():
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
