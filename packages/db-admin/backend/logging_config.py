"""Structured logging configuration for db-admin backend."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach extras that callers passed via `extra={...}`
        for key in ("request_id", "action", "entity_type", "entity_id",
                     "user_id", "ip", "method", "path", "status_code",
                     "duration_ms", "error", "component"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable formatter for development."""

    FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"

    def __init__(self):
        super().__init__(fmt=self.FORMAT, datefmt="%Y-%m-%d %H:%M:%S")


def setup_logging() -> None:
    """
    Configure root logger. Call once at application startup.

    Env vars:
      LOG_FORMAT: "json" (default in production) or "text" (default in debug)
      LOG_LEVEL: "DEBUG", "INFO" (default), "WARNING", "ERROR"
    """
    debug = os.getenv("DEBUG", "false").lower() == "true"
    log_format = os.getenv("LOG_FORMAT", "text" if debug else "json")
    log_level = os.getenv("LOG_LEVEL", "DEBUG" if debug else "INFO").upper()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove any existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
