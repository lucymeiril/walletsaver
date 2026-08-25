"""Crawler-admin health endpoint runtime contract."""

import pytest
from httpx import ASGITransport, AsyncClient

from api.app import create_app


@pytest.mark.asyncio
async def test_health_exposes_current_runtime_status():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "crawler-admin"
    assert data["status"] in {"ok", "degraded"}
    assert "scheduler_running" in data
    assert "scheduled_jobs" in data
    assert "last_crawl" in data
    assert "active_crawls" in data
    assert "browser_processes" in data
    assert "memory_mb" in data
