"""Structured JSON logging tests."""

import json
import logging
import pytest
from logging_config import JSONFormatter


class TestJSONFormatter:
    def test_basic_format(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello %s", args=("world",), exc_info=None,
        )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["message"] == "hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert "timestamp" in data

    def test_exception_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=1, msg="fail", args=(), exc_info=sys.exc_info(),
            )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["exception"]["type"] == "ValueError"
        assert "test error" in data["exception"]["message"]

    def test_extra_fields_forwarded(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="crawl done", args=(), exc_info=None,
        )
        record.crawler_name = "emart"
        record.items_found = 45
        line = formatter.format(record)
        data = json.loads(line)
        assert data["crawler_name"] == "emart"
        assert data["items_found"] == 45

    def test_output_is_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.한글", level=logging.WARNING, pathname="test.py",
            lineno=1, msg="한글 메시지", args=(), exc_info=None,
        )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["message"] == "한글 메시지"
