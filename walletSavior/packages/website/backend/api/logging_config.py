"""
Structured logging configuration for the website backend.

JSON format in production, human-readable in development.
"""

import logging
import logging.config
import os
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    """Configure logging based on environment."""
    env = os.getenv("ENV", "development").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    if env == "production":
        formatter_class = "api.logging_config.JSONFormatter"
        format_str = None
    else:
        formatter_class = None
        format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    config: dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": (
                {"()": formatter_class}
                if formatter_class
                else {"format": format_str, "datefmt": "%H:%M:%S"}
            ),
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.access": {"level": "WARNING"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "playwright": {"level": "WARNING"},
        },
    }

    logging.config.dictConfig(config)
