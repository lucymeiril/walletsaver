"""Tests for health check probes."""
import pytest
from unittest.mock import MagicMock, patch
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from api.health import run_health_check, _check_db, _check_disk, _check_memory


class TestCheckDb:
    def test_db_ok(self):
        """DB probe returns ok when session works."""
        mock_session = MagicMock()
        result = _check_db(lambda: mock_session)
        assert result["status"] == "ok"
        mock_session.execute.assert_called_once()
        mock_session.close.assert_called_once()

    def test_db_fail(self):
        """DB probe returns fail when session raises."""
        def bad_session():
            raise OperationalError("unable to open database", None, None)
        result = _check_db(bad_session)
        assert result["status"] == "fail"
        assert "error" in result


class TestCheckDisk:
    def test_disk_ok(self):
        """Disk probe returns status dict with expected keys."""
        result = _check_disk(".")
        assert "status" in result
        assert result["status"] in ("ok", "warn", "fail")
        assert "free_mb" in result
        assert "total_mb" in result
        assert "used_percent" in result

    def test_disk_invalid_path(self):
        """Disk probe returns fail for nonexistent path."""
        result = _check_disk("Z:\\nonexistent_path_xyz_12345")
        assert result["status"] == "fail"
        assert "error" in result


class TestCheckMemory:
    def test_memory_returns_status(self):
        """Memory probe returns expected keys."""
        result = _check_memory()
        assert result["status"] in ("ok", "warn")
        assert "rss_mb" in result
        assert "vms_mb" in result


class TestRunHealthCheck:
    def test_healthy(self):
        """Health check returns 200 when all probes pass."""
        mock_session = MagicMock()
        status, payload = run_health_check(lambda: mock_session, ".")
        assert status == 200
        assert payload["status"] == "healthy"
        assert payload["service"] == "db-admin"
        assert "uptime_seconds" in payload
        assert payload["checks"]["database"]["status"] == "ok"

    def test_unhealthy_db_fail(self):
        """Health check returns 503 when DB is unreachable."""
        def bad_session():
            raise OperationalError("unable to open database", None, None)
        status, payload = run_health_check(bad_session, ".")
        assert status == 503
        assert payload["status"] == "unhealthy"
        assert payload["checks"]["database"]["status"] == "fail"

    def test_degraded_on_memory_warn(self):
        """Health check returns 200 degraded on memory warning."""
        # Reimport to avoid stale reference from module cache cleanup
        from api.health import run_health_check as _rhc
        mock_session = MagicMock()
        with patch("api.health.MEMORY_WARN_MB", 0):
            status, payload = _rhc(lambda: mock_session, ".")
        assert status == 200
        assert payload["status"] == "degraded"

    def test_response_structure(self):
        """Health check response has correct structure."""
        mock_session = MagicMock()
        status, payload = run_health_check(lambda: mock_session, ".")
        assert "checks" in payload
        assert "database" in payload["checks"]
        assert "disk" in payload["checks"]
        assert "memory" in payload["checks"]
