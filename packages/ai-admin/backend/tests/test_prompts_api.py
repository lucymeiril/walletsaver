"""prompt/rulepack 거버넌스 라우트 테스트.

shared `PromptGovernanceService`의 draft -> review -> active -> rollback 흐름을
HTTP 경계에서 검증한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.prompts import get_db as prompts_get_db
from api.routes.review import get_db as review_get_db
from storage import Database, create_database


@pytest.fixture()
def db(tmp_path) -> Database:
    database = create_database(f"sqlite:///{(tmp_path / 'prompts.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app()
    app.dependency_overrides[prompts_get_db] = lambda: db
    app.dependency_overrides[review_get_db] = lambda: db
    return TestClient(app)


def _draft_payload(version: str = "1.0.0") -> dict:
    return {
        "pack_id": "normalizer-pack",
        "role": "normalizer",
        "version": version,
        "content": "System: normalize the title.\nLine: keep it short.",
        "changelog": "initial",
        "created_by": "lucy",
    }


def test_prompt_lifecycle_draft_review_activate_rollback(client: TestClient) -> None:
    # 1. submit draft
    res = client.post("/api/prompts", json=_draft_payload("1.0.0"))
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "draft"

    # duplicate draft is rejected
    dup = client.post("/api/prompts", json=_draft_payload("1.0.0"))
    assert dup.status_code == 400

    # 2. request review
    res = client.post("/api/prompts/normalizer-pack/1.0.0/request-review")
    assert res.status_code == 200
    assert res.json()["status"] == "in_review"

    # 3. activate
    res = client.post(
        "/api/prompts/normalizer-pack/1.0.0/activate",
        json={"approved_by": "reviewer-1"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "active"
    assert body["approved_by"] == "reviewer-1"

    # 4. submit + activate v2 so v1 is deprecated
    client.post("/api/prompts", json={**_draft_payload("2.0.0"), "content": "v2 content here"})
    client.post("/api/prompts/normalizer-pack/2.0.0/request-review")
    client.post(
        "/api/prompts/normalizer-pack/2.0.0/activate",
        json={"approved_by": "reviewer-1"},
    )

    # listing returns both versions
    listed = client.get("/api/prompts", params={"pack_id": "normalizer-pack"}).json()
    statuses = {item["version"]: item["status"] for item in listed["items"]}
    assert statuses == {"1.0.0": "deprecated", "2.0.0": "active"}

    # 5. rollback to v1
    res = client.post(
        "/api/prompts/normalizer-pack/1.0.0/rollback",
        json={"requested_by": "reviewer-1"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "active"

    listed = client.get("/api/prompts", params={"pack_id": "normalizer-pack"}).json()
    statuses = {item["version"]: item["status"] for item in listed["items"]}
    assert statuses["1.0.0"] == "active"
    assert statuses["2.0.0"] == "rolled_back"


def test_prompt_diff_returns_added_and_removed_lines(client: TestClient) -> None:
    client.post("/api/prompts", json={**_draft_payload("1.0.0"), "content": "alpha\nbeta"})
    client.post("/api/prompts", json={**_draft_payload("2.0.0"), "content": "alpha\ngamma"})

    res = client.get(
        "/api/prompts/normalizer-pack/diff",
        params={"from_version": "1.0.0", "to_version": "2.0.0"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["added_lines"] == ["gamma"]
    assert body["removed_lines"] == ["beta"]


def test_request_review_unknown_pack_returns_404(client: TestClient) -> None:
    res = client.post("/api/prompts/missing/1.0.0/request-review")
    assert res.status_code == 404


def test_activate_requires_in_review_status(client: TestClient) -> None:
    client.post("/api/prompts", json=_draft_payload("1.0.0"))
    res = client.post(
        "/api/prompts/normalizer-pack/1.0.0/activate",
        json={"approved_by": "reviewer-1"},
    )
    assert res.status_code == 400
