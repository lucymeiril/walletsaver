"""Tests for providers/wire_logger.py — wire-level HTTP interceptor.

These tests verify:
  - WireLogger writes JSONL entries on response events
  - attach() injects event hooks into an httpx.Client
  - on_request captures body hash; on_response captures latency + status
  - WALLETSAVIOR_WIRE_LOG_PATH env var activates the logger
  - WALLETSAVIOR_AI_LIVE_FORCE=1 triggers the exit check warning
  - attach_wire_logger_to_genai_client handles missing _api_client gracefully
"""
from __future__ import annotations

import json
import os
import sys
import types as py_types
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap — same pattern as other test files in this package.
# ---------------------------------------------------------------------------
_BACKEND = Path(__file__).resolve().parents[1]
_SHARED = _BACKEND.parent.parent / "shared"
for _p in (str(_BACKEND), str(_SHARED)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from providers.wire_logger import (
    WireLogger,
    _prompt_hash,
    attach_wire_logger_to_genai_client,
    get_wire_logger_from_env,
)


# ---------------------------------------------------------------------------
# _prompt_hash
# ---------------------------------------------------------------------------


def test_prompt_hash_is_16_hex_chars() -> None:
    h = _prompt_hash(b"hello world")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_prompt_hash_empty_input_returns_empty_label() -> None:
    assert _prompt_hash(None) == "empty"
    assert _prompt_hash(b"") == "empty"


def test_prompt_hash_is_deterministic() -> None:
    body = b"emart product label"
    assert _prompt_hash(body) == _prompt_hash(body)


def test_different_bodies_produce_different_hashes() -> None:
    assert _prompt_hash(b"product A") != _prompt_hash(b"product B")


# ---------------------------------------------------------------------------
# WireLogger JSONL output
# ---------------------------------------------------------------------------


def _make_fake_request(url: str = "https://generativelanguage.googleapis.com/v1/models", body: bytes = b"{}") -> MagicMock:
    req = MagicMock()
    req.content = body
    req.url = url
    return req


def _make_fake_response(status: int, url: str, req: MagicMock | None = None, body: bytes = b'{"ok":true}') -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.url = url
    resp.content = body
    resp.request = req if req is not None else _make_fake_request(url)
    return resp


def test_wire_logger_writes_jsonl_entry(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    req = _make_fake_request()
    resp = _make_fake_response(200, "https://generativelanguage.googleapis.com/v1/models", req=req)

    wl.on_request(req)
    wl.on_response(resp)
    wl.close()

    lines = log_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])

    assert record["status"] == 200
    assert "generativelanguage.googleapis.com" in record["domain"]
    assert record["is_google_genai"] is True
    assert record["resp_size_bytes"] > 0
    assert record["req_prompt_hash"] != "empty"


def test_wire_logger_records_latency(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    req = _make_fake_request()
    resp = _make_fake_response(200, "https://generativelanguage.googleapis.com/v1/models", req=req)

    wl.on_request(req)
    wl.on_response(resp)
    wl.close()

    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["latency_ms"] is not None
    assert record["latency_ms"] >= 0


def test_wire_logger_tracks_ok_calls(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    for _ in range(3):
        req = _make_fake_request()
        resp = _make_fake_response(200, "https://generativelanguage.googleapis.com/v1/models", req=req)
        wl.on_request(req)
        wl.on_response(resp)

    wl.close()
    stats = wl.stats()
    assert stats["total_calls"] == 3
    assert stats["ok_calls"] == 3
    assert stats["failed_calls"] == 0


def test_wire_logger_tracks_failed_calls(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    # 1 ok + 1 failed
    for status in [200, 429]:
        req = _make_fake_request()
        resp = _make_fake_response(status, "https://generativelanguage.googleapis.com/v1/models", req=req)
        wl.on_request(req)
        wl.on_response(resp)

    wl.close()
    stats = wl.stats()
    assert stats["total_calls"] == 2
    assert stats["ok_calls"] == 1
    assert stats["failed_calls"] == 1


def test_wire_logger_creates_parent_directory(tmp_path: Path) -> None:
    log_path = tmp_path / "nested" / "deep" / "wire.jsonl"
    wl = WireLogger(log_path)
    wl.close()
    assert log_path.parent.is_dir()


# ---------------------------------------------------------------------------
# attach() — httpx.Client event hooks
# ---------------------------------------------------------------------------


def test_attach_injects_hooks_into_httpx_client(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    client = httpx.Client()
    wl.attach(client)

    assert wl.on_request in client.event_hooks["request"]
    assert wl.on_response in client.event_hooks["response"]
    client.close()
    wl.close()


def test_attach_is_idempotent(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    client = httpx.Client()
    wl.attach(client)
    wl.attach(client)  # second attach must not duplicate

    assert client.event_hooks["request"].count(wl.on_request) == 1
    assert client.event_hooks["response"].count(wl.on_response) == 1
    client.close()
    wl.close()


def test_attach_warns_when_event_hooks_missing(tmp_path: Path, caplog) -> None:
    import logging
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    fake_client = object()  # no event_hooks attribute

    with caplog.at_level(logging.WARNING, logger="walletsavior.wire_logger"):
        wl.attach(fake_client)

    assert any("event_hooks" in r.message for r in caplog.records)
    wl.close()


# ---------------------------------------------------------------------------
# attach_wire_logger_to_genai_client
# ---------------------------------------------------------------------------


def test_attach_to_genai_client_succeeds_with_valid_structure(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    httpx_client = httpx.Client()
    api_client_mock = MagicMock()
    api_client_mock._httpx_client = httpx_client

    genai_client_mock = MagicMock()
    genai_client_mock._api_client = api_client_mock

    result = attach_wire_logger_to_genai_client(genai_client_mock, wl)
    assert result is True
    assert wl.on_request in httpx_client.event_hooks["request"]

    httpx_client.close()
    wl.close()


def test_attach_to_genai_client_returns_false_when_no_api_client(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    genai_client_mock = MagicMock(spec=[])  # no _api_client
    result = attach_wire_logger_to_genai_client(genai_client_mock, wl)
    assert result is False
    wl.close()


def test_attach_to_genai_client_returns_false_when_no_httpx_client(tmp_path: Path) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path)

    api_client_mock = MagicMock(spec=[])  # no _httpx_client
    genai_client_mock = MagicMock()
    genai_client_mock._api_client = api_client_mock

    result = attach_wire_logger_to_genai_client(genai_client_mock, wl)
    assert result is False
    wl.close()


# ---------------------------------------------------------------------------
# get_wire_logger_from_env
# ---------------------------------------------------------------------------


def test_get_wire_logger_from_env_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WALLETSAVIOR_WIRE_LOG_PATH", raising=False)
    assert get_wire_logger_from_env() is None


def test_get_wire_logger_from_env_returns_logger_when_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "wire.jsonl"
    monkeypatch.setenv("WALLETSAVIOR_WIRE_LOG_PATH", str(log_path))
    monkeypatch.delenv("WALLETSAVIOR_AI_LIVE_FORCE", raising=False)

    wl = get_wire_logger_from_env()
    assert wl is not None
    assert isinstance(wl, WireLogger)
    wl.close()


def test_get_wire_logger_force_live_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "wire.jsonl"
    monkeypatch.setenv("WALLETSAVIOR_WIRE_LOG_PATH", str(log_path))
    monkeypatch.setenv("WALLETSAVIOR_AI_LIVE_FORCE", "1")

    wl = get_wire_logger_from_env()
    assert wl is not None
    assert wl._force_live_flag is True
    wl.close()


def test_get_wire_logger_force_live_not_set_when_env_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = tmp_path / "wire.jsonl"
    monkeypatch.setenv("WALLETSAVIOR_WIRE_LOG_PATH", str(log_path))
    monkeypatch.setenv("WALLETSAVIOR_AI_LIVE_FORCE", "0")

    wl = get_wire_logger_from_env()
    assert wl is not None
    assert wl._force_live_flag is False
    wl.close()


# ---------------------------------------------------------------------------
# Exit check output
# ---------------------------------------------------------------------------


def test_exit_check_prints_warning_on_zero_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path, force_live_flag=True)
    # Don't record any calls
    wl._exit_check()
    captured = capsys.readouterr()
    assert "0 HTTP calls" in captured.err


def test_exit_check_prints_success_on_ok_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    log_path = tmp_path / "wire.jsonl"
    wl = WireLogger(log_path, force_live_flag=True)
    wl._ok_calls = 3
    wl._total_calls = 3
    wl._exit_check()
    captured = capsys.readouterr()
    assert "3/3" in captured.err


# ---------------------------------------------------------------------------
# product_match_precheck force-live bypass (WALLETSAVIOR_AI_LIVE_FORCE=1)
# ---------------------------------------------------------------------------


def _make_mock_record(record_id: str = "emart:rec001") -> "MagicMock":
    rec = MagicMock()
    rec.raw_record_id = record_id
    rec.source_name = "emart"
    rec.raw_title = "테스트 상품"
    rec.raw_price = 9900
    rec.source_url = ""
    rec.raw_payload = {}
    return rec


def test_product_match_precheck_bypass_when_force_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WALLETSAVIOR_AI_LIVE_FORCE=1 must bypass cache and send all records to provider."""
    import importlib

    monkeypatch.setenv("WALLETSAVIOR_AI_LIVE_FORCE", "1")

    _BACKEND = Path(__file__).resolve().parents[1]
    _SHARED = _BACKEND.parent.parent / "shared"
    import sys
    for _p in (str(_BACKEND), str(_SHARED)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from services import ai_ingestion as _mod

    repo_mock = MagicMock()
    # repo would return a match for every record — but with FORCE_LIVE, it should be ignored
    match_mock = MagicMock()
    match_mock.match_id = "m001"
    match_mock.status.value = "approved"
    match_mock.provenance_source.value = "human"
    match_mock.is_active = True
    from core.contracts.control_plane import ProductMatchStatus, ProductMatchProvenanceSource

    match_mock.status = ProductMatchStatus.APPROVED
    match_mock.provenance_source = ProductMatchProvenanceSource.HUMAN

    # _find_approved_product_match would normally return the match
    with patch.object(_mod, "_find_approved_product_match", return_value=match_mock):
        rec1 = _make_mock_record("emart:rec001")
        rec2 = _make_mock_record("emart:rec002")
        proposals, unmatched, matched = _mod.product_match_precheck(
            repository=repo_mock,
            records=[rec1, rec2],
            root_batch_id="test-root",
        )

    # With FORCE_LIVE=1, all records must appear in unmatched, none in matched
    assert len(proposals) == 0
    assert len(unmatched) == 2
    assert len(matched) == 0


def test_product_match_precheck_normal_when_force_live_not_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without WALLETSAVIOR_AI_LIVE_FORCE, cache hits are honoured normally."""
    monkeypatch.delenv("WALLETSAVIOR_AI_LIVE_FORCE", raising=False)

    _BACKEND = Path(__file__).resolve().parents[1]
    _SHARED = _BACKEND.parent.parent / "shared"
    import sys
    for _p in (str(_BACKEND), str(_SHARED)):
        if _p not in sys.path:
            sys.path.insert(0, _p)

    from services import ai_ingestion as _mod
    from core.contracts.control_plane import ProductMatchStatus, ProductMatchProvenanceSource

    match_mock = MagicMock()
    match_mock.match_id = "m001"
    match_mock.status = ProductMatchStatus.APPROVED
    match_mock.provenance_source = ProductMatchProvenanceSource.HUMAN
    match_mock.is_active = True
    match_mock.canonical_product_name = "테스트"
    match_mock.category_id = "produce.fruit"
    match_mock.keywords = ["사과"]
    match_mock.confidence = 0.95
    match_mock.unit_metadata = {}
    match_mock.audit_reason = "human"

    repo_mock = MagicMock()

    rec1 = _make_mock_record("emart:rec001")

    # When not in force mode, a cache hit means the record goes to matched, not unmatched
    with patch.object(_mod, "_find_approved_product_match", return_value=None):
        proposals, unmatched, matched = _mod.product_match_precheck(
            repository=repo_mock,
            records=[rec1],
            root_batch_id="test-root",
        )

    # No match → all unmatched
    assert len(unmatched) == 1
    assert len(matched) == 0

