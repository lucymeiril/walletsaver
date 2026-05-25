"""rd4-regression: RawExportError.kind → HTTP status 매핑 검증.

사용자 비판: "POST /api/ai-export/raw-records/label HTTP/1.1 422 timed out" 무한 반복.
원인: timeout / connection / silent_drop 모두 422 (validation) 으로 흡수되어 사용자에게
잘못된 신호 (요청 페이로드 잘못) 를 보냈다. rd4 픽스 후:

  - kind="timeout"     → 504 Gateway Timeout
  - kind="connection"  → 502 Bad Gateway
  - kind="silent_drop" → 502 Bad Gateway
  - kind="validation"  → 422 (기본)
  - 그 외 kind        → 422 (안전한 fallback)

이 테스트가 회귀를 막는다. 한 줄이라도 매핑이 바뀌면 즉시 깨진다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes import ai_export as ai_export_routes
from pipeline.ai_export import RawExportError


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    app = create_app()
    return TestClient(app)


def _forward_payload() -> dict:
    return {
        "source_name": "emart",
        "crawler_name": "emart_crawler",
        "schema_type": "mart_discount",
        "items": [{"title": "신라면", "price": 990, "url": "https://e.test/1"}],
        "ai_admin_base_url": "http://ai-admin.test",
        "provider_id": "google-dev",
    }


def test_forward_timeout_raw_export_error_maps_to_504(client, monkeypatch):
    """타임아웃 시 504 — 절대 422 아님 (사용자가 잘못 신호 받지 않도록)."""

    def _raise_timeout(*args, **kwargs):
        raise RawExportError(
            "failed to call ai-admin ingest endpoint: timed out after 600s",
            kind="timeout",
        )

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _raise_timeout
    )
    res = client.post("/api/ai-export/raw-records/label", json=_forward_payload())
    assert res.status_code == 504, res.text
    assert "timed out" in res.json()["detail"]


def test_forward_connection_raw_export_error_maps_to_502(client, monkeypatch):
    def _raise_conn(*args, **kwargs):
        raise RawExportError(
            "failed to call ai-admin ingest endpoint: [Errno 111] Connection refused",
            kind="connection",
        )

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _raise_conn
    )
    res = client.post("/api/ai-export/raw-records/label", json=_forward_payload())
    assert res.status_code == 502, res.text
    assert "Connection" in res.json()["detail"] or "ai-admin" in res.json()["detail"]


def test_forward_silent_drop_raw_export_error_maps_to_502(client, monkeypatch):
    def _raise_silent(*args, **kwargs):
        raise RawExportError(
            "ai-admin silently dropped 3/30 records",
            kind="silent_drop",
        )

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _raise_silent
    )
    res = client.post("/api/ai-export/raw-records/label", json=_forward_payload())
    assert res.status_code == 502


def test_forward_validation_raw_export_error_maps_to_422(client, monkeypatch):
    """validation/default kind 는 기존 422 유지 (회귀 방지)."""

    def _raise_validation(*args, **kwargs):
        raise RawExportError("batch exceeds prompt char limit", kind="validation")

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _raise_validation
    )
    res = client.post("/api/ai-export/raw-records/label", json=_forward_payload())
    assert res.status_code == 422


def test_forward_unknown_kind_falls_back_to_422(client, monkeypatch):
    def _raise_other(*args, **kwargs):
        raise RawExportError("something else", kind="unknown_new_kind")

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _raise_other
    )
    res = client.post("/api/ai-export/raw-records/label", json=_forward_payload())
    assert res.status_code == 422


def test_forward_timeout_seconds_field_accepts_up_to_1800(client, monkeypatch):
    """rd4-timeout-fix: 사용자가 1800s까지 명시 가능. 기존 le=120 회귀 방지."""
    captured = {}

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return {"records_sent": 1, "records_stored": 1, "batches_sent": 1}

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _capture
    )
    payload = _forward_payload()
    payload["timeout_seconds"] = 1800
    res = client.post("/api/ai-export/raw-records/label", json=payload)
    assert res.status_code == 200, res.text
    assert captured.get("timeout_seconds") == 1800


def test_forward_timeout_seconds_above_1800_rejected(client):
    """안전 상한 1800s — 그 위는 422 (FastAPI/pydantic validation)."""
    payload = _forward_payload()
    payload["timeout_seconds"] = 3600
    res = client.post("/api/ai-export/raw-records/label", json=payload)
    assert res.status_code == 422


def test_forward_default_timeout_is_600s(client, monkeypatch):
    """rd4: 기본값 30s → 600s 회귀 방지."""
    captured = {}

    def _capture(*args, **kwargs):
        captured.update(kwargs)
        return {"records_sent": 1, "records_stored": 1, "batches_sent": 1}

    monkeypatch.setattr(
        ai_export_routes, "forward_raw_records_to_ai_admin", _capture
    )
    res = client.post("/api/ai-export/raw-records/label", json=_forward_payload())
    assert res.status_code == 200, res.text
    assert captured.get("timeout_seconds") == 600.0
