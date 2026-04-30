"""검수 큐 라우트 테스트.

shared `ReviewQueueService`의 submit -> start -> approve/correct/reject 흐름을
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
    database = create_database(f"sqlite:///{(tmp_path / 'review.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app()
    app.dependency_overrides[prompts_get_db] = lambda: db
    app.dependency_overrides[review_get_db] = lambda: db
    return TestClient(app)


def _proposal(proposal_id: str = "p-1", target_field: str = "name") -> dict:
    return {
        "proposal_id": proposal_id,
        "proposal_type": "normalized_field",
        "target_field": target_field,
        "proposed_value": "Coca-Cola 500ml",
        "status": "ai_proposed",
        "provenance": {
            "raw_record_id": "raw-1",
            "evidence_text": "코카콜라 500ml",
            "worker_role": "normalizer",
        },
        "alternatives": ["Coca Cola 500ml"],
    }


def _submit(client: TestClient, proposal_id: str = "p-1") -> None:
    res = client.post("/api/review/proposals", json=_proposal(proposal_id))
    assert res.status_code == 201, res.text


def test_submit_and_start_review(client: TestClient) -> None:
    _submit(client)

    listed = client.get(
        "/api/review/proposals", params={"status": "ai_proposed"}
    ).json()
    assert len(listed["items"]) == 1

    res = client.post("/api/review/proposals/p-1/start")
    assert res.status_code == 200
    assert res.json()["status"] == "human_reviewing"


def test_approve_records_decision(client: TestClient) -> None:
    _submit(client)

    res = client.post(
        "/api/review/proposals/p-1/approve",
        json={"reviewer_id": "lucy", "create_learning_rule": True},
    )
    assert res.status_code == 200
    assert res.json()["decision"] == "approve"

    detail = client.get("/api/review/proposals/p-1").json()
    assert detail["proposal"]["status"] == "approved"
    assert len(detail["decisions"]) == 1
    assert detail["decisions"][0]["create_learning_rule"] is True


def test_correct_requires_reason(client: TestClient) -> None:
    _submit(client)

    bad = client.post(
        "/api/review/proposals/p-1/correct",
        json={"reviewer_id": "lucy", "corrected_value": "Coca-Cola", "reason": ""},
    )
    # pydantic 검증으로 422 (min_length=1)
    assert bad.status_code == 422

    ok = client.post(
        "/api/review/proposals/p-1/correct",
        json={
            "reviewer_id": "lucy",
            "corrected_value": "Coca-Cola",
            "reason": "정규화 규칙 보정",
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["decision"] == "correct"
    assert body["corrected_value"] == "Coca-Cola"

    detail = client.get("/api/review/proposals/p-1").json()
    assert detail["proposal"]["status"] == "approved"


def test_reject_marks_proposal_rejected(client: TestClient) -> None:
    _submit(client)

    res = client.post(
        "/api/review/proposals/p-1/reject",
        json={"reviewer_id": "lucy", "reason": "신뢰도 부족"},
    )
    assert res.status_code == 200
    assert res.json()["decision"] == "reject"

    detail = client.get("/api/review/proposals/p-1").json()
    assert detail["proposal"]["status"] == "rejected"
    assert detail["decisions"][0]["create_learning_rule"] is False


def test_double_decision_is_blocked(client: TestClient) -> None:
    _submit(client)
    client.post(
        "/api/review/proposals/p-1/approve",
        json={"reviewer_id": "lucy"},
    )
    again = client.post(
        "/api/review/proposals/p-1/approve",
        json={"reviewer_id": "lucy"},
    )
    assert again.status_code == 400


def test_unknown_proposal_returns_404(client: TestClient) -> None:
    res = client.post(
        "/api/review/proposals/missing/approve",
        json={"reviewer_id": "lucy"},
    )
    assert res.status_code == 404


def test_filter_by_proposal_type(client: TestClient) -> None:
    _submit(client, "p-1")
    _submit(client, "p-2")

    listed = client.get(
        "/api/review/proposals",
        params={"proposal_type": "normalized_field"},
    ).json()
    assert len(listed["items"]) == 2

    listed_other = client.get(
        "/api/review/proposals", params={"proposal_type": "category"}
    ).json()
    assert listed_other["items"] == []
