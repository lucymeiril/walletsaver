"""Security contracts for the current crawler-admin runtime."""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


class TestAuthentication:
    def setup_method(self):
        os.environ["REQUIRE_AUTH"] = "true"
        os.environ["CRAWLER_ADMIN_API_KEY"] = "test-api-key-for-testing-only"
        from api.app import create_app

        self.app = create_app()
        self.client = TestClient(self.app)
        self.valid_key = "test-api-key-for-testing-only"

    def teardown_method(self):
        os.environ.pop("REQUIRE_AUTH", None)

    def test_request_without_api_key_returns_401(self):
        resp = self.client.get("/api/crawlers")
        assert resp.status_code == 401
        assert "Missing X-API-Key" in resp.json()["detail"]

    def test_request_with_wrong_key_returns_403(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_request_with_valid_key_succeeds(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": self.valid_key},
        )
        assert resp.status_code in (200, 404)

    def test_health_endpoint_is_public(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_auth_disabled_by_default(self):
        os.environ["REQUIRE_AUTH"] = "false"
        from api.app import create_app

        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/crawlers")
        assert resp.status_code == 200


class TestCORS:
    def setup_method(self):
        from api.app import create_app

        self.app = create_app()
        self.client = TestClient(self.app)

    def test_allowed_origin_gets_cors_headers(self):
        resp = self.client.options(
            "/api/crawlers",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5174"

    def test_disallowed_origin_blocked(self):
        resp = self.client.options(
            "/api/crawlers",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_wildcard_origin_not_present(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={"Origin": "http://localhost:5174"},
        )
        assert resp.headers.get("access-control-allow-origin") != "*"


class TestSSRFPrevention:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/admin",
            "http://127.0.0.1:8080/secret",
            "http://10.0.0.1/internal",
            "http://172.16.0.1/internal",
            "http://192.168.1.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "ftp://internal.server/data",
            "http://[::1]/admin",
            "http://0.0.0.0/",
            "",
        ],
    )
    def test_blocks_internal_or_unsupported_targets(self, url):
        from api.security.url_validator import validate_target_url

        with pytest.raises(Exception):
            validate_target_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.example.com/products",
            "http://www.example.com/page",
        ],
    )
    def test_allows_public_http_targets(self, url):
        from api.security.url_validator import validate_target_url

        assert validate_target_url(url) == url


class TestInputValidation:
    def test_crawler_settings_rejects_extreme_delay(self):
        from api.security.input_schemas import CrawlerSettingsUpdate

        with pytest.raises(Exception):
            CrawlerSettingsUpdate(delay=1000.0)

    def test_crawler_settings_rejects_negative_delay(self):
        from api.security.input_schemas import CrawlerSettingsUpdate

        with pytest.raises(Exception):
            CrawlerSettingsUpdate(delay=-1.0)

    def test_crawler_settings_accepts_valid(self):
        from api.security.input_schemas import CrawlerSettingsUpdate

        model = CrawlerSettingsUpdate(
            target_url="https://example.com",
            delay=2.5,
            max_items=100,
        )
        assert model.delay == 2.5

    def test_schedule_rejects_every_minute_cron(self):
        from api.security.input_schemas import ScheduleCreate

        with pytest.raises(Exception):
            ScheduleCreate(crawler_name="test", cron="* * * * *")

    def test_schedule_rejects_invalid_cron(self):
        from api.security.input_schemas import ScheduleCreate

        with pytest.raises(Exception):
            ScheduleCreate(crawler_name="test", cron="not-a-cron")

    def test_schedule_accepts_valid_cron(self):
        from api.security.input_schemas import ScheduleCreate

        model = ScheduleCreate(crawler_name="emart", cron="0 */6 * * *")
        assert model.cron == "0 */6 * * *"

    def test_schedule_rejects_special_chars_in_name(self):
        from api.security.input_schemas import ScheduleCreate

        with pytest.raises(Exception):
            ScheduleCreate(crawler_name="../etc/passwd", cron="0 0 * * *")

    def test_bulk_run_limits_crawler_count(self):
        from api.security.input_schemas import BulkRunRequest

        with pytest.raises(Exception):
            BulkRunRequest(crawler_ids=[f"c{i}" for i in range(20)])

    def test_bulk_run_validates_id_format(self):
        from api.security.input_schemas import BulkRunRequest

        with pytest.raises(Exception):
            BulkRunRequest(crawler_ids=["../../etc/passwd"])

    def test_cleanup_request_rejects_invalid_status(self):
        from api.security.input_schemas import CleanupRequest

        with pytest.raises(Exception):
            CleanupRequest(status=["drop_all_tables"])

    def test_cleanup_request_accepts_valid(self):
        from api.security.input_schemas import CleanupRequest

        model = CleanupRequest(status=["processed"], older_than_days=30)
        assert model.status == ["processed"]

    def test_cleanup_request_accepts_approved_rejected(self):
        from api.security.input_schemas import CleanupRequest

        model = CleanupRequest(status=["approved", "rejected"])
        assert model.status == ["approved", "rejected"]

    def test_url_rejects_too_long(self):
        from api.security.input_schemas import CrawlerSettingsUpdate

        with pytest.raises(Exception):
            CrawlerSettingsUpdate(target_url="https://x.com/" + "a" * 3000)


class TestSecurityHeaders:
    def setup_method(self):
        from api.app import create_app

        self.app = create_app()
        self.client = TestClient(self.app)

    def test_health_endpoint_has_security_headers(self):
        resp = self.client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-xss-protection") == "1; mode=block"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in resp.headers.get("content-security-policy", "")

    def test_api_response_has_no_cache(self):
        resp = self.client.get("/api/crawlers")
        cache = resp.headers.get("cache-control", "")
        assert "no-store" in cache


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
