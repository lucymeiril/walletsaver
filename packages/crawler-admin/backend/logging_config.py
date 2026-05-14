"""Structured JSON logging configuration.

Call ``setup_logging()`` once during FastAPI startup to switch all
application loggers from plain text to JSON-formatted output.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Forward extra fields if attached via `logger.info("msg", extra={...})`
        for key in ("crawler_name", "items_found", "items_saved",
                     "duration", "status", "error_type", "correlation_id"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(
    level: str = "INFO",
    log_dir: str | Path | None = None,
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure root logger with JSON formatting.

    - Console handler (stderr): always added.
    - File handler (``logs/app.jsonl``): added when *log_dir* is provided
      or defaults to ``<backend>/logs/``.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove any pre-existing handlers (avoid duplicate output on reload)
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = JSONFormatter()

    # Console
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_dir / "app.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Don't propagate audit logger records to root (already handled by audit.py)
    logging.getLogger("audit").propagate = False
