"""Disk space monitoring for db-admin backend."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("disk_monitor")

# Thresholds in MB
WARN_THRESHOLD_MB = int(os.getenv("DISK_WARN_MB", "500"))
CRITICAL_THRESHOLD_MB = int(os.getenv("DISK_CRIT_MB", "100"))


class InsufficientDiskSpaceError(RuntimeError):
    """Raised when a disk-space pre-flight check fails."""
    def __init__(self, required_mb: float, available_mb: float, path: str):
        self.required_mb = required_mb
        self.available_mb = available_mb
        self.path = path
        super().__init__(
            f"Insufficient disk space at {path}: "
            f"need {required_mb:.1f} MB, have {available_mb:.1f} MB"
        )


def check_disk_space(path: str | Path) -> dict:
    """
    Check disk space at the given path.

    Returns:
        {
            "free_mb": float,
            "total_mb": float,
            "used_percent": float,
            "status": "ok" | "warn" | "critical"
        }
    """
    usage = shutil.disk_usage(str(path))
    free_mb = usage.free / (1024 * 1024)
    total_mb = usage.total / (1024 * 1024)
    used_pct = usage.used / usage.total * 100

    if free_mb < CRITICAL_THRESHOLD_MB:
        status = "critical"
        logger.critical(
            "Disk space CRITICAL: %.1f MB free at %s (threshold: %d MB)",
            free_mb, path, CRITICAL_THRESHOLD_MB,
            extra={"component": "disk_monitor", "free_mb": free_mb},
        )
    elif free_mb < WARN_THRESHOLD_MB:
        status = "warn"
        logger.warning(
            "Disk space LOW: %.1f MB free at %s (threshold: %d MB)",
            free_mb, path, WARN_THRESHOLD_MB,
            extra={"component": "disk_monitor", "free_mb": free_mb},
        )
    else:
        status = "ok"

    return {
        "free_mb": round(free_mb, 1),
        "total_mb": round(total_mb, 1),
        "used_percent": round(used_pct, 1),
        "status": status,
    }


def require_disk_space(path: str | Path, required_mb: float) -> None:
    """
    Pre-flight check: raise InsufficientDiskSpaceError if not enough space.

    Usage:
        require_disk_space(BACKUP_DIR, db_size_mb * 2)
    """
    usage = shutil.disk_usage(str(path))
    free_mb = usage.free / (1024 * 1024)
    if free_mb < required_mb:
        raise InsufficientDiskSpaceError(required_mb, free_mb, str(path))
    logger.debug(
        "Disk space OK: %.1f MB free, %.1f MB required at %s",
        free_mb, required_mb, path,
    )
