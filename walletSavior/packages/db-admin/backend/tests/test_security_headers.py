"""Tests for security headers middleware."""
import sys
import importlib

import pytest
from fastapi.testclient import TestClient


def _reload_and_create_app():
    """Flush cached config/app modules and create a fresh app."""
    for mod in list(sys.modules):
        if mod.startswith(("config", "api.app", "api.middleware")):
            del sys.modules[mod]
    from api.app import create_app
    return create_app()


@pytest.fixture
def client():
    import config
    importlib.reload(config)
    from api.app import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_x_content_type_options(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_x_frame_options(client):
    r = client.get("/health")
    assert r.headers["X-Frame-Options"] == "DENY"


def test_content_security_policy(client):
    r = client.get("/health")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_referrer_policy(client):
    r = client.get("/health")
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_api_cache_control(client):
    r = client.get("/api/dashboard/stats")
    assert r.headers.get("Cache-Control") == "no-store"


def test_non_api_no_cache_control(client):
    """Non-API paths should not get Cache-Control: no-store."""
    r = client.get("/health")
    assert r.headers.get("Cache-Control") != "no-store"


def test_hsts_disabled_in_debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    app = _reload_and_create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/health")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_enabled_in_production(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    app = _reload_and_create_app()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/health")
    assert "Strict-Transport-Security" in r.headers
