"""Integration tests for /api/v1/feedback — web-api → ai-admin forwarding."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import httpx

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PACKAGES_DIR = _BACKEND_DIR.parent.parent
for _p in (str(_BACKEND_DIR), str(_PACKAGES_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


@pytest.fixture
def feedback_test_client(mini_snapshot_path, monkeypatch):
    """TestClient with AI_ADMIN_URL overridden."""
    monkeypatch.setenv("WALLETSAVIOR_PUBLIC_DB", mini_snapshot_path)
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.create_app(), raise_server_exceptions=False)


class TestFeedbackForwarding:
    def test_feedback_forwards_to_ai_admin(self, feedback_test_client, monkeypatch, respx_mock=None):
        """POST /api/v1/feedback should forward payload to ai-admin."""
        # Patch httpx.AsyncClient to mock the ai-admin side
        captured = {}

        import httpx as _httpx

        original_post = _httpx.AsyncClient.post

        async def _mock_post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs.get("json", {})
            return _httpx.Response(
                201,
                json={"feedback_id": "fb-test-001", "status": "received"},
            )

        monkeypatch.setattr(_httpx.AsyncClient, "post", _mock_post)

        resp = feedback_test_client.post(
            "/api/v1/feedback",
            json={
                "proposal_id": "prop-123",
                "feedback_type": "wrong_category",
                "reviewer_id": "user1",
                "details": {"note": "테스트"},
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body.get("feedback_id") == "fb-test-001"
        assert "ai-admin" in captured.get("url", "") or "feedback" in captured.get("url", "")

    def test_feedback_502_on_connection_error(self, feedback_test_client, monkeypatch):
        """If ai-admin is unreachable, return 502."""
        import httpx as _httpx

        async def _raise_error(self, url, **kwargs):
            raise _httpx.ConnectError("refused")

        monkeypatch.setattr(_httpx.AsyncClient, "post", _raise_error)

        resp = feedback_test_client.post(
            "/api/v1/feedback",
            json={
                "proposal_id": "prop-xyz",
                "feedback_type": "wrong_price",
                "reviewer_id": "user2",
            },
        )
        assert resp.status_code == 502

    def test_feedback_endpoint_exists(self, feedback_test_client):
        """Ensure the feedback route is registered (not 404/405)."""
        # Use a controlled mock for this existence check
        import httpx as _httpx

        async def _noop_post(self, url, **kwargs):
            return _httpx.Response(201, json={"feedback_id": "x"})

        from unittest.mock import patch
        with patch.object(_httpx.AsyncClient, "post", _noop_post):
            resp = feedback_test_client.post(
                "/api/v1/feedback",
                json={"proposal_id": "p", "feedback_type": "t"},
            )
        assert resp.status_code != 404
        assert resp.status_code != 405
