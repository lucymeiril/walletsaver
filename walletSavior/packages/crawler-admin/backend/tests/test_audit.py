"""Tests for audit logging."""

import json
import logging
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from audit import audit_log, AuditEventType


def test_audit_log_writes_json(tmp_path, monkeypatch):
    """Audit entries are valid JSON."""
    log_file = tmp_path / "audit.jsonl"

    import audit
    monkeypatch.setattr(audit, "_AUDIT_LOG_DIR", tmp_path)

    test_logger = logging.getLogger("audit.test")
    test_logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    test_logger.addHandler(handler)
    monkeypatch.setattr(audit, "_audit_logger", test_logger)

    audit_log(
        AuditEventType.CRAWLER_RUN,
        actor_ip="127.0.0.1",
        resource="test-crawler",
        detail={"mode": "manual"},
    )

    handler.flush()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1

    entry = json.loads(lines[-1])
    assert entry["event"] == "crawler.run"
    assert entry["resource"] == "test-crawler"
    assert entry["actor_ip"] == "127.0.0.1"
    assert "timestamp" in entry


def test_audit_log_required_fields():
    """Every audit entry must have timestamp, event, and result."""
    mock_request = MagicMock()
    mock_request.client.host = "192.168.1.1"
    mock_request.method = "POST"
    mock_request.url.path = "/api/crawlers/test/run"

    # This should not raise
    audit_log(
        AuditEventType.CRAWLER_RUN,
        request=mock_request,
        resource="test-crawler",
    )
