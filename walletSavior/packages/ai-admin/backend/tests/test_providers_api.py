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
from providers import secret_resolver
from storage import Database, create_database


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
        "min_request_interval_seconds": 1.5,
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
    assert "GOOGLE_MISSING_KEY" in str(state)


def test_models_requires_secret_env_alias(client: TestClient) -> None:
    client.post("/api/providers", json=_payload(secret_alias="GOOGLE_MISSING_KEY")).raise_for_status()
    res = client.get("/api/providers/gemini-prod/models")
    assert res.status_code == 400
    assert "GOOGLE_MISSING_KEY" in res.json()["detail"]


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

    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "GOOGLE_MISSING_KEY" in detail
    assert "fake-dotenv-secret-value" not in detail


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
