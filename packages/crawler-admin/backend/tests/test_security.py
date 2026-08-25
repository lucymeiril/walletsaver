"""Security contracts for the current crawler-admin runtime."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestAuthentication:
    def setup_method(self):
        os.environ["REQUIRE_AUTH"] = "true"
        os.environ["CRAWLER_ADMIN_API_KEY"] = "test-api-key-for-testing-only"
        os.environ["WALLETSAVIOR_DISABLE_SCHEDULE_LOOP"] = "1"
        from api.app import create_app

        self.app = create_app()
        self.client = TestClient(self.app)
        self.valid_key = "test-api-key-for-testing-only"

    def teardown_method(self):
        os.environ.pop("REQUIRE_AUTH", None)
        os.environ.pop("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", None)

    def test_request_without_api_key_returns_401(self):
        response = self.client.get("/api/crawlers")
        assert response.status_code == 401
        assert "Missing X-API-Key" in response.json()["detail"]

    def test_request_with_wrong_key_returns_403(self):
        response = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": "wrong-key"},
        )
        assert response.status_code == 403

    def test_request_with_valid_key_succeeds(self):
        response = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": self.valid_key},
        )
        assert response.status_code == 200

    def test_health_endpoint_is_public(self):
        response = self.client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] in {"ok", "degraded"}

    def test_auth_can_be_disabled_for_local_development(self):
        os.environ["REQUIRE_AUTH"] = "false"
        from api.app import create_app

        response = TestClient(create_app()).get("/api/crawlers")
        assert response.status_code == 200


class TestCORS:
    def setup_method(self):
        os.environ["WALLETSAVIOR_DISABLE_SCHEDULE_LOOP"] = "1"
        from api.app import create_app

        self.client = TestClient(create_app())

    def teardown_method(self):
        os.environ.pop("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", None)

    def test_allowed_origin_gets_cors_headers(self):
        response = self.client.options(
            "/api/crawlers",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5174"

    def test_disallowed_origin_blocked(self):
        response = self.client.options(
            "/api/crawlers",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_wildcard_origin_not_present(self):
        response = self.client.get(
            "/api/crawlers",
            headers={"Origin": "http://localhost:5174"},
        )
        assert response.headers.get("access-control-allow-origin") != "*"


class TestInputValidation:
    def test_cleanup_request_rejects_invalid_status(self):
        from api.security.input_schemas import CleanupRequest

        with pytest.raises(Exception):
            CleanupRequest(status=["drop_all_tables"])

    def test_cleanup_request_accepts_current_statuses(self):
        from api.security.input_schemas import CleanupRequest

        model = CleanupRequest(status=["approved", "rejected"], older_than_days=30)
        assert model.status == ["approved", "rejected"]


class TestSecurityHeaders:
    def setup_method(self):
        os.environ["WALLETSAVIOR_DISABLE_SCHEDULE_LOOP"] = "1"
        from api.app import create_app

        self.client = TestClient(create_app())

    def teardown_method(self):
        os.environ.pop("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", None)

    def test_health_endpoint_has_security_headers(self):
        response = self.client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"
        assert response.headers.get("x-frame-options") == "DENY"
        assert response.headers.get("x-xss-protection") == "1; mode=block"
        assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in response.headers.get("content-security-policy", "")

    def test_api_response_has_no_cache(self):
        response = self.client.get("/api/crawlers")
        assert "no-store" in response.headers.get("cache-control", "")


class TestSecretsManagement:
    def test_config_has_no_default_db_password(self):
        import pathlib

        config_file = pathlib.Path(__file__).parent.parent / "config.py"
        if config_file.exists():
            content = config_file.read_text(encoding="utf-8")
            assert "user:password@" not in content

    def test_api_key_env_var_required(self):
        with patch.dict(os.environ, {"CRAWLER_ADMIN_API_KEY": ""}):
            from api.security.auth import _get_api_key

            with pytest.raises(RuntimeError, match="required"):
                _get_api_key()
