"""
Structured audit logger for security-relevant events.

Emits JSON-formatted log records to a dedicated audit log file.
Each record includes: timestamp, event type, actor (IP), target resource,
action, result, and optional details.

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
        maxBytes=50 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(handler)


class AuditEventType:
    """Audit events emitted by the current crawler-admin runtime."""

    CRAWLER_RUN = "crawler.run"
    CRAWLER_BULK_RUN = "crawler.bulk_run"
    CRAWL_COMPLETED = "crawler.completed"
    CRAWL_FAILED = "crawler.failed"
    DATA_SUBMISSION = "data.submission"
    DATA_INGESTION = "data.ingestion"
    OPERATOR_BROWSER_SESSION_OPEN = "operator_browser.session_open"
    OPERATOR_BROWSER_SESSION_ACTION = "operator_browser.session_action"
    OPERATOR_BROWSER_SESSION_CLOSE = "operator_browser.session_close"


def audit_log(
    event_type: str,
    *,
    request: Optional[Request] = None,
    actor_ip: Optional[str] = None,
    resource: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    result: str = "success",
) -> None:
    """Emit one structured audit log entry."""
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
