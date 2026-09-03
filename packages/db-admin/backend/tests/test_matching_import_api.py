"""Focused API tests for the compatibility classified-matching import route."""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).parent.parent
SHARED_ROOT = BACKEND_ROOT.parent.parent / "shared"
for path in (str(BACKEND_ROOT), str(SHARED_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from core.match_key import build_match_key
from storage.models import Category, Keyword, MatchingEntry


MODERATOR_KEY = "test-only-matching-moderator-key"
VIEWER_KEY = "test-only-matching-viewer-key"
SERVICE_KEY = "test-only-matching-service-key"


def _row(
    *,
    brand: str = "CJ",
    name_core: str = "햇반",
    pack_qty: float = 210.0,
    pack_unit: str = "g",
    match_key: str = "LEGACY|KEY|210.000000|g",
    category_id: str = "food.rice",
    confidence: float = 0.9,
    source: str = "external-ai",
    keyword_ids: list[int] | None = None,
) -> dict:
    return {
        "match_key": match_key,
        "brand": brand,
        "name_core": name_core,
        "pack_qty": pack_qty,
        "pack_unit": pack_unit,
        "category_id": category_id,
        "confidence": confidence,
        "source": source,
        "keyword_ids": [1] if keyword_ids is None else keyword_ids,
    }


def _jsonl(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in rows).encode("utf-8")


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        encoded = dict(row)
        encoded["keyword_ids"] = json.dumps(row.get("keyword_ids", []), ensure_ascii=False)
        writer.writerow(encoded)
    return buf.getvalue().encode("utf-8")


@pytest.fixture()
def db_fixture(isolated_service_database, monkeypatch):
    # Reuse the shared temporary DB fixture, including its real service engine
    # reset and FK settings. Route session helpers must never reach a local DB.
    Session = sessionmaker(bind=isolated_service_database)

    with Session() as session:
        session.add_all(
            [
                Category(id="food", name="식품", depth=0, is_active=True),
                Category(id="food.rice", name="쌀/즉석밥", parent_id="food", depth=1, is_active=True),
                Keyword(id=1, word="즉석밥", category_id="food.rice", is_active=True),
            ]
        )
        session.commit()

    import api.routes.matching_import as routes

    monkeypatch.setattr(routes, "_confirmed_traces", {})
    monkeypatch.setattr(routes, "_failure_rows_store", {})

    yield Session


@pytest.fixture()
def api_app(db_fixture, monkeypatch):
    from api import auth
    from config import settings
    from api.routes.matching_import import router

    # Pin the real authentication contract instead of depending on the host's
    # environment or bypassing FastAPI dependencies. The route requires at
    # least moderator; an ordinary crawler service key is insufficient.
    assert auth.settings is settings
    monkeypatch.setattr(settings, "REQUIRE_AUTH", True)
    monkeypatch.setattr(settings, "SERVICE_API_KEYS", {
        MODERATOR_KEY: "moderator", VIEWER_KEY: "viewer", SERVICE_KEY: "service",
    })
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture()
def client(api_app):
    with TestClient(api_app, headers={"X-API-Key": MODERATOR_KEY}) as test_client:
        yield test_client


@pytest.fixture()
def unauthenticated_client(api_app):
    # A separate client avoids accidentally retaining a default API-key header
    # when an individual request supplies headers={}.
    with TestClient(api_app) as test_client:
        yield test_client


def test_jsonl_preview_recomputes_legacy_key(client, db_fixture):
    row = _row(match_key="CJ|햇반|210.000000|g")
    response = client.post(
        "/api/import/classified/preview",
        files={"file": ("matching.jsonl", _jsonl([row]), "application/octet-stream")},
        data={"mode": "strict"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid_rows"] == 1
    assert body["diff"]["added"] == 1
    assert body["diff"]["preview_rows"][0]["match_key"] == build_match_key("CJ", "햇반", 210, "g")
    with db_fixture() as session:
        assert session.query(MatchingEntry).count() == 0  # preview is still read-only


def test_csv_preview_keeps_distinct_compound_identities(client):
    rows = [
        _row(brand="CJ", name_core="햇반", pack_qty=210, match_key="OLD|A|1|g"),
        _row(brand="농심", name_core="신라면", pack_qty=120, match_key="OLD|B|2|g"),
    ]
    response = client.post(
        "/api/import/classified/preview",
        files={"file": ("matching.csv", _csv(rows), "text/csv")},
        data={"mode": "strict"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid_rows"] == 2
    assert body["diff"]["added"] == 2


def test_strict_rejects_invalid_category_and_crawler_auto_source(client):
    invalid_rows = [
        _row(category_id="missing.category"),
        _row(brand="농심", name_core="신라면", pack_qty=120, source="crawler-auto"),
    ]
    response = client.post(
        "/api/import/classified/preview",
        files={"file": ("matching.jsonl", _jsonl(invalid_rows), "application/octet-stream")},
        data={"mode": "strict"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["valid_rows"] == 0
    assert len(body["errors"]) >= 2


def test_lenient_keeps_valid_identity_and_reports_invalid_row(client):
    rows = [
        _row(),
        _row(brand="농심", name_core="신라면", pack_qty=120, confidence=1.5),
    ]
    response = client.post(
        "/api/import/classified/preview",
        files={"file": ("matching.jsonl", _jsonl(rows), "application/octet-stream")},
        data={"mode": "lenient"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valid_rows"] == 1
    assert len(body["errors"]) == 1


def test_confirm_persists_two_distinct_canonical_entries(client, db_fixture):
    rows = [
        _row(brand="CJ", name_core="햇반", pack_qty=210, match_key="OLD|A|1|g"),
        _row(brand="농심", name_core="신라면", pack_qty=120, match_key="OLD|B|2|g", source="human"),
    ]
    payload = _jsonl(rows)
    response = client.post(
        "/api/import/classified/confirm",
        files={"file": ("matching.jsonl", payload, "application/octet-stream")},
        data={"mode": "strict", "trace_id": "two-products"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["inserted"] == 2

    Session = db_fixture
    with Session() as session:
        keys = {entry.match_key for entry in session.query(MatchingEntry).all()}
    assert keys == {
        build_match_key("CJ", "햇반", 210, "g"),
        build_match_key("농심", "신라면", 120, "g"),
    }


def test_confirm_trace_id_is_idempotent(client, db_fixture):
    payload = _jsonl([_row()])
    first = client.post(
        "/api/import/classified/confirm",
        files={"file": ("matching.jsonl", payload, "application/octet-stream")},
        data={"mode": "strict", "trace_id": "same-trace"},
    )
    second = client.post(
        "/api/import/classified/confirm",
        files={"file": ("matching.jsonl", payload, "application/octet-stream")},
        data={"mode": "strict", "trace_id": "same-trace"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["idempotent"] is True
    Session = db_fixture
    with Session() as session:
        assert session.query(MatchingEntry).count() == 1


def test_missing_file_and_empty_file_are_rejected(client):
    assert client.post("/api/import/classified/preview", data={"mode": "strict"}).status_code == 422
    response = client.post(
        "/api/import/classified/preview",
        files={"file": ("matching.jsonl", b"", "application/octet-stream")},
        data={"mode": "strict"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("endpoint", ["preview", "confirm"])
@pytest.mark.parametrize("headers,expected_status", [
    ({}, 401),
    ({"X-API-Key": "invalid-test-key"}, 401),
    ({"Authorization": "Bearer invalid-test-token"}, 401),
    ({"X-API-Key": VIEWER_KEY}, 403),
    ({"X-API-Key": SERVICE_KEY}, 403),
])
def test_import_requires_valid_moderator_identity_before_database_access(
    unauthenticated_client, db_fixture, monkeypatch, endpoint, headers, expected_status,
):
    import api.routes.matching_import as routes

    def forbidden_session_access(*args, **kwargs):
        pytest.fail("Unauthorized import reached a database session")

    monkeypatch.setattr(routes, "get_session", forbidden_session_access)
    monkeypatch.setattr(routes, "managed_session", forbidden_session_access)
    response = unauthenticated_client.post(
        f"/api/import/classified/{endpoint}",
        headers=headers,
        files={"file": ("matching.jsonl", _jsonl([_row()]), "application/octet-stream")},
        data={"mode": "strict", "trace_id": "unauthorized-import"},
    )

    assert response.status_code == expected_status, response.text
    if not headers:
        assert response.headers["www-authenticate"] == "Bearer"
    with db_fixture() as session:
        assert session.query(MatchingEntry).count() == 0
    assert routes._confirmed_traces == {}
    assert routes._failure_rows_store == {}


def test_auth_configuration_is_read_per_request_not_cached_by_test_client(
    unauthenticated_client, monkeypatch, db_fixture,
):
    from config import settings

    def preview(key):
        return unauthenticated_client.post(
            "/api/import/classified/preview",
            headers={"X-API-Key": key},
            files={"file": ("matching.jsonl", _jsonl([_row()]), "application/octet-stream")},
            data={"mode": "strict"},
        )

    assert preview(MODERATOR_KEY).status_code == 200
    rotated_key = "test-only-rotated-moderator-key"
    monkeypatch.setattr(settings, "SERVICE_API_KEYS", {rotated_key: "moderator"})
    assert preview(MODERATOR_KEY).status_code == 401
    assert preview(rotated_key).status_code == 200
    with db_fixture() as session:
        assert session.query(MatchingEntry).count() == 0


def test_route_session_helpers_use_the_isolated_service_database(
    api_app, isolated_service_database, tmp_path,
):
    from config import settings
    import api.routes.matching_import as routes

    expected = (tmp_path / "api-test.sqlite").resolve()
    assert Path(isolated_service_database.url.database).resolve() == expected
    assert settings.DATABASE_URL == f"sqlite:///{expected.as_posix()}"
    with routes.get_session() as session:
        assert session.bind is isolated_service_database
        assert session.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    with routes.managed_session() as session:
        assert session.bind is isolated_service_database
