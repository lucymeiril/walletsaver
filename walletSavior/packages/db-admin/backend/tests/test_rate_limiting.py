"""Tests for rate limiting middleware."""
import os
import sys
import importlib

import pytest
from fastapi.testclient import TestClient


def _make_app(global_limit="200/minute", destructive_limit="5/minute"):
    """Create a fresh app with specified rate limits."""
    os.environ["RATE_LIMIT_GLOBAL"] = global_limit
    os.environ["RATE_LIMIT_DESTRUCTIVE"] = destructive_limit
    # Disable auth for rate limiting tests (these test rate limits, not auth)
    os.environ["REQUIRE_AUTH"] = "false"
    for mod in list(sys.modules):
        if mod.startswith(("config", "api.")):
            del sys.modules[mod]
    from api.middleware.rate_limit import limiter
    from api.app import create_app
    app = create_app()
    app.state.limiter = limiter
    return app


def test_rate_limit_returns_429():
    """Exceed global rate limit and verify 429 response."""
    app = _make_app(global_limit="5/minute")
    client = TestClient(app, raise_server_exceptions=False)
    for _ in range(5):
        r = client.get("/health")
        assert r.status_code == 200

    r = client.get("/health")
    assert r.status_code == 429
    body = r.json()
    assert "요청 횟수 제한" in body["detail"]


def test_rate_limit_response_is_json():
    """429 response must be JSON, not plain text."""
    app = _make_app(global_limit="5/minute")
    client = TestClient(app, raise_server_exceptions=False)
    for _ in range(6):
        r = client.get("/health")
    assert r.headers["content-type"] == "application/json"


def test_destructive_endpoint_strict_limit():
    """Admin reset endpoints have tighter limits."""
    app = _make_app(destructive_limit="1/minute")
    c = TestClient(app, raise_server_exceptions=False)

    # First request — wrong confirm, but passes rate limit
    r1 = c.post("/api/admin/reset-all", json={"confirm": "wrong"})
    assert r1.status_code in (400, 500)  # 400 wrong confirm or 500 backup fail

    # Second request — should be rate-limited (429)
    r2 = c.post("/api/admin/reset-all", json={"confirm": "wrong"})
    assert r2.status_code == 429
