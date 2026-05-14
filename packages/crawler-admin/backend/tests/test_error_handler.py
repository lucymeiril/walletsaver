"""Tests for safe error handling."""

import pytest
from api.error_handler import safe_error_detail


def test_known_exception_returns_safe_message():
    assert safe_error_detail(KeyError("secret_key")) == "Resource not found"
    assert safe_error_detail(ValueError("invalid input")) == "Invalid input provided"
    assert safe_error_detail(TimeoutError()) == "Operation timed out"
    assert safe_error_detail(ConnectionError("http://internal:5432")) == "Service temporarily unavailable"


def test_unknown_exception_returns_generic():
    assert safe_error_detail(RuntimeError("stack trace here")) == "An internal error occurred"


def test_no_internal_info_leaked():
    """Ensure no internal paths, URLs, or credentials in safe messages."""
    exceptions = [
        KeyError("/app/backend/config.py"),
        ConnectionError("postgresql://user:password@db:5432/wallet"),
        FileNotFoundError("/etc/passwd"),
        RuntimeError("Traceback (most recent call last):\n  File ..."),
    ]
    for exc in exceptions:
        msg = safe_error_detail(exc)
        assert "/" not in msg or msg == "Resource not found"
        assert "password" not in msg
        assert "Traceback" not in msg
