"""Health check probes for the db-admin backend."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import psutil
import shutil
from sqlalchemy import text

logger = logging.getLogger("health")

_START_TIME = time.monotonic()

# Thresholds (configurable via env)
DISK_WARN_MB = int(os.getenv("HEALTH_DISK_WARN_MB", "500"))
DISK_CRIT_MB = int(os.getenv("HEALTH_DISK_CRIT_MB", "100"))
MEMORY_WARN_MB = int(os.getenv("HEALTH_MEMORY_WARN_MB", "512"))


def _check_db(get_session_fn) -> dict[str, Any]:
    """Probe DB connectivity with a lightweight query."""
    try:
        session = get_session_fn()
        try:
            session.execute(text("SELECT 1"))
            return {"status": "ok"}
        finally:
            session.close()
    except Exception as e:
        logger.error("Health: DB probe failed: %s", e, exc_info=True)
        return {"status": "fail", "error": str(e)}


def _check_disk(path: str) -> dict[str, Any]:
    """Check free disk space on the partition containing *path*."""
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free / (1024 * 1024)
        status = "ok"
        if free_mb < DISK_CRIT_MB:
            status = "fail"
        elif free_mb < DISK_WARN_MB:
            status = "warn"
        return {
            "status": status,
            "free_mb": round(free_mb, 1),
            "total_mb": round(usage.total / (1024 * 1024), 1),
            "used_percent": round(usage.used / usage.total * 100, 1),
        }
    except Exception as e:
        logger.error("Health: disk probe failed: %s", e)
        return {"status": "fail", "error": str(e)}


def _check_memory() -> dict[str, Any]:
    """Report process RSS memory usage."""
    try:
        proc = psutil.Process()
        mem = proc.memory_info()
        rss_mb = mem.rss / (1024 * 1024)
        status = "warn" if rss_mb > MEMORY_WARN_MB else "ok"
        return {
            "status": status,
            "rss_mb": round(rss_mb, 1),
            "vms_mb": round(mem.vms / (1024 * 1024), 1),
        }
    except Exception as e:
        logger.error("Health: memory probe failed: %s", e)
        return {"status": "unknown", "error": str(e)}


def run_health_check(get_session_fn, db_path: str) -> tuple[int, dict]:
    """
    Execute all probes and return (http_status_code, payload).

    Returns 200 if all critical probes pass, 503 otherwise.
    """
    db = _check_db(get_session_fn)
    disk = _check_disk(db_path)
    memory = _check_memory()

    uptime_s = round(time.monotonic() - _START_TIME, 1)

    # Overall status: fail if DB or disk is "fail"
    overall = "healthy"
    http_status = 200
    if db["status"] == "fail" or disk["status"] == "fail":
        overall = "unhealthy"
        http_status = 503
    elif db["status"] == "warn" or disk["status"] == "warn" or memory["status"] == "warn":
        overall = "degraded"
        http_status = 200

    payload = {
        "status": overall,
        "service": "db-admin",
        "uptime_seconds": uptime_s,
        "checks": {
            "database": db,
            "disk": disk,
            "memory": memory,
        },
    }
    return http_status, payload
