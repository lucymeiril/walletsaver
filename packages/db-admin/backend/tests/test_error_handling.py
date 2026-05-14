"""Error handling tests — verify no information leakage."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # Disable auth for error handling tests (these test error formatting, not auth)
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    # Ensure config has needed attributes
    from config import settings
    if not hasattr(settings, "CORS_ALLOWED_ORIGINS"):
        monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", ["*"], raising=False)
    from api.app import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestGlobalErrorHandler:
    def test_validation_error_format(self, client):
        """Validation errors should return structured error with code."""
        resp = client.post("/api/products", json={"name": ""})
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "VALIDATION_ERROR"
        assert "request_id" in body["error"]

    def test_admin_confirm_no_leak(self, client):
        """Admin endpoints must NOT reveal the expected confirm string."""
        resp = client.post(
            "/api/admin/reset-all",
            json={"confirm": "wrong_string"},
        )
        body = resp.json()
        detail = body.get("detail", body)
        detail_str = str(detail)
        assert "RESET_ALL_DATA" not in detail_str
        assert "DELETE_ALL_PRODUCTS" not in detail_str

    def test_admin_reset_source_no_leak(self, client):
        """reset-source must not reveal DELETE_<SOURCE> pattern."""
        resp = client.post(
            "/api/admin/reset-source",
            json={"source": "emart", "confirm": "wrong"},
        )
        body = resp.json()
        detail_str = str(body)
        assert "DELETE_EMART" not in detail_str


class TestPayloadSizeLimit:
    def test_oversized_payload_rejected(self, client):
        """Payloads exceeding the size limit should return 413."""
        large_payload = {"items": [{"name": "x" * 1000}] * 15_000}
        resp = client.post("/api/ingestions", json=large_payload)
        # Should be either 413 (size middleware) or 422 (Pydantic max_length)
        assert resp.status_code in (413, 422)
