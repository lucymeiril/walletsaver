"""
Structured audit logger for security-relevant events.

Emits JSON-formatted log records to a dedicated audit log file.
Each record includes: timestamp, event type, actor (IP), target resource,
action, result, and a request hash for non-repudiation.

Log file: logs/audit.jsonl (append-only)
"""

import json
import logging
import os
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from fastapi import Request

_AUDIT_LOG_DIR = Path(os.getenv(
    "AUDIT_LOG_DIR",
    str(Path(__file__).resolve().parent / "logs")
))
_AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

_audit_logger = logging.getLogger("audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

if not _audit_logger.handlers:
    handler = RotatingFileHandler(
        _AUDIT_LOG_DIR / "audit.jsonl",
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(handler)


class AuditEventType:
    CRAWLER_RUN = "crawler.run"
    CRAWLER_BULK_RUN = "crawler.bulk_run"
    CRAWLER_SETTINGS_UPDATE = "crawler.settings_update"
    SCHEDULE_CREATE = "schedule.create"
    SCHEDULE_DELETE = "schedule.delete"
    SCHEDULE_TOGGLE = "schedule.toggle"
    PLUGIN_TOGGLE = "plugin.toggle"
    PLUGIN_SETTINGS_UPDATE = "plugin.settings_update"
    DATA_SUBMISSION = "data.submission"
    DATA_INGESTION = "data.ingestion"
    CRAWL_COMPLETED = "crawler.completed"
    CRAWL_FAILED = "crawler.failed"
    SOURCE_WORKBENCH_CAPTURE = "source_workbench.capture"
    SOURCE_WORKBENCH_REGISTER = "source_workbench.register"


def audit_log(
    event_type: str,
    *,
    request: Optional[Request] = None,
    actor_ip: Optional[str] = None,
    resource: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    result: str = "success",
) -> None:
    """
    Emit a structured audit log entry.

    Args:
        event_type: One of AuditEventType constants.
        request: The incoming FastAPI Request (extracts IP, method, path).
        actor_ip: Override IP if request is not available.
        resource: The target resource identifier (e.g., crawler_id).
        detail: Additional context (will be JSON-serialized).
        result: "success", "failure", "denied", or "error".
    """
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "result": result,
        "resource": resource,
    }

    if request:
        entry["actor_ip"] = request.client.host if request.client else "unknown"
        entry["method"] = request.method
        entry["path"] = str(request.url.path)
    elif actor_ip:
        entry["actor_ip"] = actor_ip

    if detail:
        entry["detail"] = detail

    _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
