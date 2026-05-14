"""Tests for structured logging configuration."""
import json as json_mod
import logging
import pytest

from logging_config import JSONFormatter, TextFormatter, setup_logging


class TestJSONFormatter:
    def test_produces_valid_json(self):
        """JSONFormatter produces valid JSON with required fields."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json_mod.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello"
        assert "timestamp" in parsed
        assert parsed["logger"] == "test"

    def test_includes_extras(self):
        """JSONFormatter includes extra fields when present."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="action", args=(), exc_info=None,
        )
        record.request_id = "abc123"
        record.component = "test_comp"
        output = formatter.format(record)
        parsed = json_mod.loads(output)
        assert parsed["request_id"] == "abc123"
        assert parsed["component"] == "test_comp"

    def test_excludes_none_extras(self):
        """JSONFormatter does not include None extras."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="msg", args=(), exc_info=None,
        )
        output = formatter.format(record)
        parsed = json_mod.loads(output)
        assert "request_id" not in parsed

    def test_includes_exception(self):
        """JSONFormatter includes exception info."""
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="", lineno=0,
            msg="error", args=(), exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json_mod.loads(output)
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]


class TestTextFormatter:
    def test_format_string(self):
        """TextFormatter produces human-readable output."""
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert "test" in output
        assert "hello world" in output
        assert "INFO" in output


class TestSetupLogging:
    def test_json_format(self, monkeypatch):
        """setup_logging() configures JSON output when LOG_FORMAT=json."""
        monkeypatch.setenv("LOG_FORMAT", "json")
        setup_logging()
        handler = logging.root.handlers[0]
        assert isinstance(handler.formatter, JSONFormatter)

    def test_text_format(self, monkeypatch):
        """setup_logging() configures text output when LOG_FORMAT=text."""
        monkeypatch.setenv("LOG_FORMAT", "text")
        setup_logging()
        handler = logging.root.handlers[0]
        assert isinstance(handler.formatter, TextFormatter)

    def test_log_level(self, monkeypatch):
        """setup_logging() sets the correct log level."""
        monkeypatch.setenv("LOG_FORMAT", "text")
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        setup_logging()
        assert logging.root.level == logging.WARNING
