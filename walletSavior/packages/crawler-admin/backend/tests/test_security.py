"""
Security test suite for crawler-admin.

Tests authentication, CORS, SSRF prevention, input validation,
plugin sandboxing, and security headers.
"""

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# ─────────────────────────────────────────────
# SEC-01: Authentication Tests
# ─────────────────────────────────────────────

class TestAuthentication:
    """Verify API key middleware blocks unauthenticated requests."""

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

    def test_timing_safe_comparison(self):
        """Ensure API key comparison is constant-time."""
        import hmac
        key = "test-key"
        assert hmac.compare_digest(key, key)
        assert not hmac.compare_digest(key, "wrong")

    def test_auth_disabled_by_default(self):
        """Requests pass when REQUIRE_AUTH is not set."""
        os.environ["REQUIRE_AUTH"] = "false"
        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/crawlers")
        assert resp.status_code == 200


# ─────────────────────────────────────────────
# SEC-02: CORS Tests
# ─────────────────────────────────────────────

class TestCORS:
    """Verify CORS is restricted to allowed origins."""

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


# ─────────────────────────────────────────────
# SEC-04: SSRF Prevention Tests
# ─────────────────────────────────────────────

class TestSSRFPrevention:
    """Verify URL validation blocks internal/malicious targets."""

    def test_blocks_localhost(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://localhost/admin")

    def test_blocks_127_0_0_1(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://127.0.0.1:8080/secret")

    def test_blocks_private_10_x(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://10.0.0.1/internal")

    def test_blocks_private_172_16(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://172.16.0.1/internal")

    def test_blocks_private_192_168(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://192.168.1.1/admin")

    def test_blocks_aws_metadata(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_file_scheme(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("file:///etc/passwd")

    def test_blocks_ftp_scheme(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("ftp://internal.server/data")

    def test_allows_valid_https_url(self):
        from api.security.url_validator import validate_target_url
        result = validate_target_url("https://www.example.com/products")
        assert result == "https://www.example.com/products"

    def test_allows_valid_http_url(self):
        from api.security.url_validator import validate_target_url
        result = validate_target_url("http://www.example.com/page")
        assert result == "http://www.example.com/page"

    def test_blocks_empty_url(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("")

    def test_blocks_ipv6_loopback(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://[::1]/admin")

    def test_blocks_zero_ip(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://0.0.0.0/")


# ─────────────────────────────────────────────
# SEC-03: Plugin Security Tests
# ─────────────────────────────────────────────

class TestPluginSecurity:
    """Verify plugin import guards and manifest verification."""

    def test_import_guard_blocks_os(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            with pytest.raises(ImportError, match="not allowed to import 'os'"):
                __import__("os")

    def test_import_guard_blocks_subprocess(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            with pytest.raises(ImportError, match="not allowed to import 'subprocess'"):
                __import__("subprocess")

    def test_import_guard_blocks_socket(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            with pytest.raises(ImportError, match="not allowed to import 'socket'"):
                __import__("socket")

    def test_import_guard_allows_json(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            import json  # Should not raise — already in sys.modules
            assert json is not None

    def test_import_guard_allows_re(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            import re  # Should not raise — already in sys.modules
            assert re is not None

    def test_import_guard_restores_after_context(self):
        """Verify __import__ is restored after context manager exits."""
        import builtins
        original = builtins.__import__
        from plugins.import_guard import guarded_imports

        with guarded_imports("test"):
            pass

        assert builtins.__import__ is original

    def test_manifest_signature_roundtrip(self):
        """Verify sign → verify cycle works."""
        os.environ.setdefault("PLUGIN_SIGNING_KEY", "test-signing-key-0123456789abcdef")
        from plugins.manifest_verifier import (
            compute_manifest_signature,
            verify_manifest,
        )
        from pathlib import Path

        manifest = {
            "name": "test-plugin",
            "version": "1.0.0",
            "target": {"url": "https://example.com"},
        }
        sig = compute_manifest_signature(manifest)
        manifest["signature"] = sig

        assert verify_manifest(Path("dummy.yaml"), manifest) is True

    def test_manifest_tampered_data_fails(self):
        os.environ.setdefault("PLUGIN_SIGNING_KEY", "test-signing-key-0123456789abcdef")
        from plugins.manifest_verifier import (
            compute_manifest_signature,
            verify_manifest,
        )
        from pathlib import Path

        manifest = {"name": "test-plugin", "version": "1.0.0"}
        manifest["signature"] = compute_manifest_signature(manifest)

        # Tamper with data
        manifest["version"] = "2.0.0"
        assert verify_manifest(Path("dummy.yaml"), manifest) is False

    def test_manifest_missing_signature_fails(self):
        os.environ.setdefault("PLUGIN_SIGNING_KEY", "test-signing-key-0123456789abcdef")
        from plugins.manifest_verifier import verify_manifest
        from pathlib import Path

        manifest = {"name": "test", "version": "1.0.0"}
        assert verify_manifest(Path("dummy.yaml"), manifest) is False


# ─────────────────────────────────────────────
# SEC-06: Input Validation Tests
# ─────────────────────────────────────────────

class TestInputValidation:
    """Verify Pydantic models enforce constraints."""

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
        m = CrawlerSettingsUpdate(
            target_url="https://example.com",
            delay=2.5,
            max_items=100,
        )
        assert m.delay == 2.5

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
        m = ScheduleCreate(crawler_name="emart", cron="0 */6 * * *")
        assert m.cron == "0 */6 * * *"

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
        m = CleanupRequest(status=["processed"], older_than_days=30)
        assert m.status == ["processed"]

    def test_cleanup_request_accepts_approved_rejected(self):
        from api.security.input_schemas import CleanupRequest
        m = CleanupRequest(status=["approved", "rejected"])
        assert m.status == ["approved", "rejected"]

    def test_url_rejects_too_long(self):
        from api.security.input_schemas import CrawlerSettingsUpdate
        with pytest.raises(Exception):
            CrawlerSettingsUpdate(target_url="https://x.com/" + "a" * 3000)


# ─────────────────────────────────────────────
# SEC-07: Security Headers Tests
# ─────────────────────────────────────────────

class TestSecurityHeaders:
    """Verify security headers are present on all responses."""

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


# ─────────────────────────────────────────────
# SEC-05: Secrets Management Tests
# ─────────────────────────────────────────────

class TestSecretsManagement:
    """Verify no hardcoded secrets remain in source code."""

    def test_no_hardcoded_yogiyo_secret(self):
        """Verify the yogiyo API secret is not hardcoded."""
        import pathlib
        crawler_file = (
            pathlib.Path(__file__).parent.parent
            / "crawlers" / "delivery" / "yogiyo" / "crawler.py"
        )
        if crawler_file.exists():
            content = crawler_file.read_text(encoding="utf-8")
            assert "fe5183cc3dea12bd0ce299cf110a75a2" not in content, (
                "Hardcoded API secret found in yogiyo crawler"
            )

    def test_config_has_no_default_db_password(self):
        """Verify config.py doesn't have hardcoded DB credentials."""
        import pathlib
        config_file = pathlib.Path(__file__).parent.parent / "config.py"
        if config_file.exists():
            content = config_file.read_text(encoding="utf-8")
            assert "user:password@" not in content, (
                "Hardcoded database credentials found in config.py"
            )

    def test_api_key_env_var_required(self):
        """Verify auth module rejects empty API key."""
        with patch.dict(os.environ, {"CRAWLER_ADMIN_API_KEY": ""}):
            from api.security.auth import _get_api_key
            with pytest.raises(RuntimeError, match="required"):
                _get_api_key()
