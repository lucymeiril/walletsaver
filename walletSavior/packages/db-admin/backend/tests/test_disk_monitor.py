"""Tests for disk space monitoring."""
import pytest

from services.disk_monitor import (
    check_disk_space,
    require_disk_space,
    InsufficientDiskSpaceError,
)


class TestCheckDiskSpace:
    def test_returns_dict_with_expected_keys(self):
        result = check_disk_space(".")
        assert "free_mb" in result
        assert "total_mb" in result
        assert "used_percent" in result
        assert "status" in result
        assert result["status"] in ("ok", "warn", "critical")

    def test_free_mb_is_positive(self):
        result = check_disk_space(".")
        assert result["free_mb"] > 0

    def test_used_percent_in_range(self):
        result = check_disk_space(".")
        assert 0 <= result["used_percent"] <= 100


class TestRequireDiskSpace:
    def test_sufficient_space_no_error(self):
        """No error when enough space."""
        require_disk_space(".", 1)  # 1 MB — should always pass

    def test_insufficient_space_raises(self):
        """Raises InsufficientDiskSpaceError when space is low."""
        with pytest.raises(InsufficientDiskSpaceError) as exc_info:
            require_disk_space(".", 999_999_999)  # 999 TB
        assert exc_info.value.required_mb == 999_999_999
        assert exc_info.value.available_mb > 0


class TestInsufficientDiskSpaceError:
    def test_error_attributes(self):
        err = InsufficientDiskSpaceError(100.0, 50.0, "/data")
        assert err.required_mb == 100.0
        assert err.available_mb == 50.0
        assert err.path == "/data"
        assert "100.0" in str(err)
        assert "50.0" in str(err)
