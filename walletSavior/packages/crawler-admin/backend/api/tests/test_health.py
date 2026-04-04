"""Tests for enriched /health endpoint.

HC-1: Verifies health response includes all required fields.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from api.app import create_app


@pytest.mark.asyncio
async def test_health_returns_required_fields():
    """HC-1: /health must return scheduler, memory, crawl info."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()

    # Required fields
    assert "status" in data
    assert "service" in data
    assert data["service"] == "crawler-admin"
    assert "scheduler_running" in data
    assert "active_crawls" in data
    assert "browser_processes" in data
    assert "memory_mb" in data


@pytest.mark.asyncio
async def test_health_status_ok_when_healthy():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
