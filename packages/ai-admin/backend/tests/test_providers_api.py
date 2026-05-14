"""/api/providers 라우트 테스트.

* in-memory SQLite를 dependency override로 주입한다.
* secret value를 절대 받지 않는 경계가 강제되는지 검증한다.
"""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes import providers as providers_routes
from providers.google_genai import ProviderResponseError
from providers import secret_resolver
from storage import Database, create_database


FAKE_GOOGLE_KEY = "AIza" + "1" * 25


@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    # SQLite ":memory:"는 connection 단위라 FastAPI testclient의 스레드 풀에서
    # create_all을 했던 connection과 별개의 connection이 사용된다. 테스트에서는
    # 임시 파일 DB를 사용해 모든 connection이 같은 테이블을 보도록 한다.
    database = create_database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> Iterator[TestClient]:
    app = create_app()

    def _override() -> Iterator[Session]:
        session = db.session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _payload(**overrides) -> dict:
    base = {
        "provider_id": "gemini-prod",
        "provider_kind": "gemini",
        "display_name": "Gemini Prod",
        "base_url": None,
        "default_model": "gemini-1.5-pro",
        "secret_alias": "GEMINI_API_KEY",
        "is_enabled": True,
        "max_concurrent_jobs": 2,
        "min_request_interval_seconds": 12.0,
        "max_provider_calls_per_minute": 5,
        "max_provider_calls_per_day": 300,
        "provider_retry_max_attempts": 3,
        "provider_retry_min_delay_seconds": 10.0,
        "provider_retry_max_delay_seconds": 60.0,
        "daily_budget_limit": 5.0,
    }
    base.update(overrides)
    return base


def test_list_empty(client: TestClient) -> None:
    res = client.get("/api/providers")
    assert res.status_code == 200
    body = res.json()
    assert body == {"providers": [], "count": 0}


def test_create_get_and_list(client: TestClient) -> None:
    res = client.post("/api/providers", json=_payload())
    assert res.status_code == 200, res.text
    created = res.json()
    assert created["provider_id"] == "gemini-prod"
    assert created["secret_alias"] == "GEMINI_API_KEY"
    # No raw-secret-shaped fields are returned.
    for forbidden in ("api_key", "secret", "secret_value", "token", "password"):
        assert forbidden not in created

    got = client.get("/api/providers/gemini-prod")
    assert got.status_code == 200
    assert got.json()["display_name"] == "Gemini Prod"

    listed = client.get("/api/providers").json()
    assert listed["count"] == 1
    assert listed["providers"][0]["provider_id"] == "gemini-prod"


def test_upsert_updates_existing(client: TestClient) -> None:
    client.post("/api/providers", json=_payload()).raise_for_status()
    res = client.post(
        "/api/providers",
        json=_payload(display_name="Gemini Prod v2", max_concurrent_jobs=4),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["display_name"] == "Gemini Prod v2"
    assert body["max_concurrent_jobs"] == 4

    listed = client.get("/api/providers").json()
    assert listed["count"] == 1


@pytest.mark.parametrize(
    "alias",
    ["sk-1234567890", "Bearer abc.def.ghi", "key=secret-value"],
)
def test_rejects_inline_secret_in_alias(client: TestClient, alias: str) -> None:
    res = client.post("/api/providers", json=_payload(secret_alias=alias))
    assert res.status_code == 400
    assert "alias" in res.json()["detail"].lower()


def test_get_missing_returns_404(client: TestClient) -> None:
    assert client.get("/api/providers/nope").status_code == 404
    assert client.get("/api/providers/nope/capabilities").status_code == 404
    res = client.post(
        "/api/providers/nope/enabled", json={"is_enabled": False}
    )
    assert res.status_code == 404


def test_set_enabled_toggles(client: TestClient) -> None:
    client.post("/api/providers", json=_payload()).raise_for_status()
    res = client.post(
        "/api/providers/gemini-prod/enabled", json={"is_enabled": False}
    )
    assert res.status_code == 200
    assert res.json()["is_enabled"] is False
    again = client.get("/api/providers/gemini-prod").json()
    assert again["is_enabled"] is False


def test_capabilities_for_provider(client: TestClient) -> None:
    client.post("/api/providers", json=_payload()).raise_for_status()
    res = client.get("/api/providers/gemini-prod/capabilities")
    assert res.status_code == 200
    body = res.json()
    assert body["provider_id"] == "gemini-prod"
    cap = body["capabilities"]
    assert cap["provider_kind"] == "gemini"
    assert cap["supports_json_mode"] is True
    assert cap["supports_local_execution"] is False
    assert cap["max_prompt_chars"] >= 1
    model_cap = body["model_capability"]
    assert model_cap["provider_kind"] == "gemini"
    assert model_cap["model_name"] == "gemini-1.5-pro"
    assert model_cap["supports_json_mode"] is True
    assert model_cap["is_local"] is False
    assert model_cap["availability_status"] == "configured"


def test_setup_state_reports_secret_presence_without_leaking_value(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("GEMINI_API_KEY=super-secret-local-value\n", encoding="utf-8")
    monkeypatch.setattr(secret_resolver, "DEFAULT_ENV_PATHS", (dotenv,))

    client.post(
        "/api/providers", json=_payload(secret_alias="GEMINI_API_KEY")
    ).raise_for_status()
    res = client.get("/api/providers/setup-state")

    assert res.status_code == 200
    body = res.json()
    state = body["providers"][0]
    assert state["provider_id"] == "gemini-prod"
    assert state["secret_alias"] == "GEMINI_API_KEY"
    assert state["secret_resolved"] is True
    assert state["can_call_live"] is True
    assert state["model_capability"]["availability_status"] == "ready"
    assert state["model_capability"]["smoke_status"] == "not_run"
    assert state["live_rate_limits"]["min_request_interval_seconds"] == 12.0
    assert state["live_rate_limits"]["max_provider_calls_per_minute"] == 5
    assert state["live_rate_limits"]["max_provider_calls_per_day"] == 300
    serialized = str(body)
    assert "super-secret-local-value" not in serialized
    assert "/api/ingest/raw-records/label" in state["live_actions"]
    assert "/api/review/audit" in state["offline_actions"]


def test_setup_state_missing_secret_disables_live_hint(client: TestClient) -> None:
    client.post(
        "/api/providers", json=_payload(secret_alias="GOOGLE_MISSING_KEY")
    ).raise_for_status()
    res = client.get("/api/providers/setup-state")

    assert res.status_code == 200
    state = res.json()["providers"][0]
    assert state["secret_resolved"] is False
    assert state["can_call_live"] is False
    assert state["model_capability"]["availability_status"] == "missing_secret"
    assert "GOOGLE_MISSING_KEY" in str(state)


def test_gemma_setup_state_reports_json_mode_fallback(client: TestClient) -> None:
    client.post(
        "/api/providers",
        json=_payload(default_model="gemma-4-26b-a4b-it", secret_alias="GOOGLE_MISSING_KEY"),
    ).raise_for_status()

    state = client.get("/api/providers/setup-state").json()["providers"][0]

    assert state["model_capability"]["model_name"] == "gemma-4-26b-a4b-it"
    assert state["model_capability"]["supports_json_mode"] is False
    assert state["model_capability"]["is_local"] is False


def test_models_missing_secret_returns_static_discovery_without_live_call(
    client: TestClient,
) -> None:
    client.post("/api/providers", json=_payload(secret_alias="GOOGLE_MISSING_KEY")).raise_for_status()
    res = client.get("/api/providers/gemini-prod/models")
    assert res.status_code == 200
    body = res.json()
    assert body["discovery_status"] == "unavailable"
    assert body["discovery_source"] == "static_config"
    assert body["error"]["error"] == "configuration_unavailable"
    assert "GOOGLE_MISSING_KEY" in body["error"]["message"]
    assert body["default_model_capability"]["availability_status"] == "missing_secret"
    model_names = {m["name"] for m in body["models"]}
    assert "gemini-2.5-flash" in model_names
    assert "gemini-3.1-flash-lite-preview" in model_names
    assert "gemma-4-31b-it" in model_names
    assert "gemma-4-26b-a4b-it" in model_names


def test_models_missing_alias_does_not_expose_dotenv_secret(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OTHER_GOOGLE_KEY=fake-dotenv-secret-value\n", encoding="utf-8")
    monkeypatch.setattr(secret_resolver, "DEFAULT_ENV_PATHS", (dotenv,))

    client.post(
        "/api/providers", json=_payload(secret_alias="GOOGLE_MISSING_KEY")
    ).raise_for_status()
    res = client.get("/api/providers/gemini-prod/models")

    assert res.status_code == 200
    body = res.json()
    assert "GOOGLE_MISSING_KEY" in body["error"]["message"]
    assert "fake-dotenv-secret-value" not in str(body)


def test_models_returns_live_sdk_source_when_adapter_lists_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeAdapter:
        def __init__(self, config):
            self.config = config

        def list_models(self):
            return {
                "provider_id": self.config.provider_id,
                "provider_kind": self.config.provider_kind.value,
                "default_model": self.config.default_model,
                "discovery_status": "available",
                "discovery_source": "live_sdk",
                "models": [
                    {
                        "name": "gemini-fake-live",
                        "model_name": "gemini-fake-live",
                        "selectable_model_name": "gemini-fake-live",
                        "api_name": "models/gemini-fake-live",
                        "display_name": "Fake Live",
                        "supported_actions": ["generateContent"],
                        "input_token_limit": 123,
                        "output_token_limit": 45,
                        "supports_json_mode": True,
                        "provider_kind": "gemini",
                        "is_local": False,
                        "availability_status": "listed",
                        "smoke_status": "not_run",
                        "source": "live_sdk",
                    }
                ],
                "error": None,
                "quota_remaining_available": False,
                "quota_status": "not_reported",
                "quota_note": "not reported",
            }

    monkeypatch.setattr(providers_routes, "GoogleGenAIProvider", FakeAdapter)
    client.post("/api/providers", json=_payload()).raise_for_status()

    res = client.get("/api/providers/gemini-prod/models")

    assert res.status_code == 200
    body = res.json()
    assert body["discovery_source"] == "live_sdk"
    assert body["models"][0]["name"] == "gemini-fake-live"
    assert body["default_model_capability"]["model_name"] == "gemini-1.5-pro"


def test_models_quota_error_returns_sanitized_static_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_list_models(self):
        raise ProviderResponseError(
            f"429 quota exhausted api_key={FAKE_GOOGLE_KEY}",
            provider_id=self.config.provider_id,
            model=self.config.default_model,
            error_kind="quota_limited",
        )

    monkeypatch.setattr(providers_routes.GoogleGenAIProvider, "list_models", fake_list_models)
    client.post("/api/providers", json=_payload(default_model="gemini-2.5-flash")).raise_for_status()

    res = client.get("/api/providers/gemini-prod/models")

    assert res.status_code == 200
    body = res.json()
    assert body["discovery_status"] == "quota_limited"
    assert body["discovery_source"] == "static_fallback"
    assert body["error"]["error"] == "quota_limited"
    assert "AIza" not in str(body)
    assert "gemini-2.5-flash" in {m["name"] for m in body["models"]}


def test_smoke_test_endpoint_returns_adapter_provider_mode_attribute(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeAdapter:
        provider_mode = "live"

        def __init__(self, config):
            self.config = config

        def call(self, *, prompt: str, schema=None):
            return {"ok": True, "echo": prompt[:12]}

    monkeypatch.setattr(providers_routes, "GoogleGenAIProvider", FakeAdapter)
    client.post("/api/providers", json=_payload()).raise_for_status()

    res = client.post(
        "/api/providers/gemini-prod/smoke-test",
        json={"prompt": 'Return {"ok": true} as JSON.'},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider_id"] == "gemini-prod"
    assert body["provider_mode"] == "live"
    assert body["result"]["ok"] is True


def test_validation_error_on_bad_payload(client: TestClient) -> None:
    bad = _payload()
    bad["provider_kind"] = "not-a-real-kind"
    res = client.post("/api/providers", json=bad)
    assert res.status_code == 422


def test_min_request_interval_lower_bound(client: TestClient) -> None:
    # contract enforces >= 1.0
    res = client.post(
        "/api/providers", json=_payload(min_request_interval_seconds=0.1)
    )
    assert res.status_code == 422


def test_provider_live_limit_payload_is_validated_and_returned(client: TestClient) -> None:
    res = client.post(
        "/api/providers",
        json=_payload(
            min_request_interval_seconds=2.5,
            max_provider_calls_per_minute=3,
            max_provider_calls_per_day=42,
            provider_retry_max_attempts=4,
            provider_retry_min_delay_seconds=2.0,
            provider_retry_max_delay_seconds=8.0,
        ),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["min_request_interval_seconds"] == 2.5
    assert body["max_provider_calls_per_minute"] == 3
    assert body["max_provider_calls_per_day"] == 42
    assert body["provider_retry_max_attempts"] == 4
    assert body["provider_retry_min_delay_seconds"] == 2.0
    assert body["provider_retry_max_delay_seconds"] == 8.0


def test_provider_retry_max_delay_must_cover_min_delay(client: TestClient) -> None:
    res = client.post(
        "/api/providers",
        json=_payload(
            provider_retry_min_delay_seconds=10.0,
            provider_retry_max_delay_seconds=5.0,
        ),
    )
    assert res.status_code == 422
