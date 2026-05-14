"""DB-admin readiness checks use safe GET-only fakes and sanitize secrets."""
from __future__ import annotations

import asyncio

import httpx

from services import db_admin_adapter
from services.db_admin_adapter import (
    ai_safe_final_approve_db_admin,
    check_db_admin_mutation_preflight,
    check_db_admin_readiness,
)


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def json(self):
        import json

        return json.loads(self.text or "{}")


class _FakeAsyncClient:
    calls: list[dict] = []
    responses: list[_FakeResponse | Exception] = []

    def __init__(self, *, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, *, headers: dict[str, str]):
        self.calls.append({"method": "GET", "url": url, "headers": headers, "timeout": self.timeout})
        next_response = self.responses.pop(0)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response


def _run_readiness(**kwargs):
    _FakeAsyncClient.calls = []
    return asyncio.run(
        check_db_admin_readiness(
            client_factory=_FakeAsyncClient,
            paths=("/api/ingestions/stats",),
            **kwargs,
        )
    )


def test_ai_safe_final_approve_export_delegates_without_network(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _FakeAdapter:
        async def ai_safe_final_approve(self, ingestion_id, *, notes=None):
            calls.append({"ingestion_id": ingestion_id, "notes": notes})
            return {"status": "approved", "ingestion_id": ingestion_id}

    monkeypatch.setattr(db_admin_adapter.DBAdminAdapter, "from_env", classmethod(lambda cls: _FakeAdapter()))

    result = asyncio.run(ai_safe_final_approve_db_admin("ing-123", notes="validated"))

    assert result == {"status": "approved", "ingestion_id": "ing-123"}
    assert calls == [{"ingestion_id": "ing-123", "notes": "validated"}]


def test_ai_admin_app_imports_review_route_with_db_admin_adapter() -> None:
    from api.app import create_app

    app = create_app()

    assert any(route.path == "/api/review/publish-approved" for route in app.routes)


def test_db_admin_readiness_ready_from_dotenv(tmp_path) -> None:
    secret = "test-db-admin-key-ready"
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"DB_ADMIN_URL=https://admin.example.local/base?token=drop-me\nDB_ADMIN_API_KEY={secret}\n",
        encoding="utf-8",
    )
    _FakeAsyncClient.responses = [_FakeResponse(200, '{"ok": true}')]

    result = _run_readiness(env_paths=(dotenv,), timeout_seconds=2.5)

    assert result["status"] == "ready"
    assert result["key_present"] is True
    assert result["url"] == "https://admin.example.local/base"
    assert result["endpoint"] == "/api/ingestions/stats"
    assert isinstance(result["latency_ms"], float)
    assert _FakeAsyncClient.calls == [
        {
            "method": "GET",
            "url": "https://admin.example.local/base/api/ingestions/stats",
            "headers": {"X-API-Key": secret},
            "timeout": 2.5,
        }
    ]


def test_db_admin_readiness_server_down_is_sanitized() -> None:
    secret = "server-down-secret"
    request = httpx.Request("GET", "https://admin.example.local/api/ingestions/stats")
    _FakeAsyncClient.responses = [httpx.ConnectError(f"boom api_key={secret}", request=request)]

    result = _run_readiness(base_url="https://admin.example.local", api_key=secret)
    serialized = str(result)

    assert result["status"] == "server_unreachable"
    assert result["error"]["class"] == "ConnectError"
    assert secret not in serialized
    assert "[REDACTED]" in result["error"]["message"]


def test_db_admin_readiness_auth_failed() -> None:
    _FakeAsyncClient.responses = [_FakeResponse(401, "invalid")]

    result = _run_readiness(base_url="https://admin.example.local", api_key="bad-key")

    assert result["status"] == "auth_failed"
    assert result["key_present"] is True
    assert result["error"]["message"] == "DB-admin returned HTTP 401 for readiness endpoint"


def test_db_admin_readiness_key_missing(tmp_path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("DB_ADMIN_URL=https://admin.example.local\n", encoding="utf-8")
    _FakeAsyncClient.responses = [_FakeResponse(200)]

    result = _run_readiness(env_paths=(dotenv,))

    assert result["status"] == "key_missing"
    assert result["key_present"] is False
    assert _FakeAsyncClient.calls == []


def test_db_admin_readiness_does_not_leak_key_from_error_body() -> None:
    secret = "body-secret-value"
    _FakeAsyncClient.responses = [_FakeResponse(500, f"unexpected X-API-Key: {secret}")]

    result = _run_readiness(base_url="https://admin.example.local", api_key=secret)
    serialized = str(result)

    assert result["status"] == "unexpected_error"
    assert secret not in serialized
    assert "[REDACTED]" in result["error"]["message"]


def test_db_admin_mutation_preflight_requires_existing_snapshot_without_mutation() -> None:
    secret = "preflight-secret"
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.responses = [
        _FakeResponse(200, '{"total_pending": 1}'),
        _FakeResponse(200, '{"total_pending": 1}'),
        _FakeResponse(200, '{"backups": []}'),
    ]

    result = asyncio.run(
        check_db_admin_mutation_preflight(
            base_url="https://admin.example.local",
            api_key=secret,
            client_factory=_FakeAsyncClient,
        )
    )

    serialized = str(result)
    assert result["status"] == "blocked"
    assert result["ready_to_mutate"] is False
    assert result["error"]["class"] == "SnapshotMissing"
    assert secret not in serialized
    assert [call["method"] for call in _FakeAsyncClient.calls] == ["GET", "GET", "GET"]
    assert all("backup" not in call["url"].split("/api/admin/", 1)[-1] for call in _FakeAsyncClient.calls[:2])


def test_db_admin_mutation_preflight_passes_with_readonly_state_and_backup_listing() -> None:
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.responses = [
        _FakeResponse(200, '{"total_pending": 2, "status_counts": {"pending": 2}}'),
        _FakeResponse(200, '{"total_pending": 2, "status_counts": {"pending": 2}}'),
        _FakeResponse(200, '{"backups": [{"filename": "walletguardian_manual_20260101_000000.db"}]}'),
    ]

    result = asyncio.run(
        check_db_admin_mutation_preflight(
            base_url="https://admin.example.local",
            api_key="preflight-secret",
            client_factory=_FakeAsyncClient,
        )
    )

    assert result["status"] == "ready"
    assert result["ready_to_mutate"] is True
    assert result["current_state"]["total_pending"] == 2
    assert result["snapshot"]["verified"] is True
    assert "walletguardian_manual_20260101_000000.db" in result["snapshot"]["latest_backup"]

