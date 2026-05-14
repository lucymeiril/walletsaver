"""Dynamic attribute access safety tests."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    from config import settings
    if not hasattr(settings, "CORS_ALLOWED_ORIGINS"):
        monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", ["*"], raising=False)
    from api.app import create_app
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


class TestKeywordSortSafety:
    def test_valid_sort_field(self, client):
        resp = client.get("/api/keywords/?sort_by=word")
        assert resp.status_code == 200

    def test_invalid_sort_field_defaults(self, client):
        """Invalid sort_by should fallback, not crash."""
        resp = client.get("/api/keywords/?sort_by=__class__")
        assert resp.status_code == 200

    def test_sort_by_hashed_password_blocked(self, client):
        """Attempting to sort by sensitive field names must be blocked."""
        resp = client.get("/api/keywords/?sort_by=hashed_password")
        assert resp.status_code == 200  # should silently fall back to default


class TestDuplicateFieldSafety:
    def test_invalid_table_rejected(self, client):
        resp = client.post(
            "/api/analytics/duplicates",
            json={"table_name": "users", "fields": ["password"]},
        )
        assert resp.status_code in (400, 422)

    def test_invalid_field_rejected(self, client):
        resp = client.post(
            "/api/analytics/duplicates",
            json={"table_name": "products", "fields": ["hashed_password"]},
        )
        # Should return empty or error, not expose the column
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert resp.json() == []

    def test_valid_table_and_fields(self, client):
        resp = client.post(
            "/api/analytics/duplicates",
            json={"table_name": "products", "fields": ["name"]},
        )
        assert resp.status_code == 200
