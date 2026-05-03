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
from core.contracts.ai_pipeline import PipelineStatus, RawCrawlRecord
from core.contracts.control_plane import RawCrawlBatchContract
from storage import Database, RawCrawlBatchRepository, create_database


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


def _proposal_for_record(
    proposal_id: str,
    raw_record_id: str,
    target_field: str,
    proposed_value,
    *,
    proposal_type: str = "normalized_field",
) -> dict:
    proposal = _proposal(proposal_id, target_field)
    proposal["proposal_type"] = proposal_type
    proposal["proposed_value"] = proposed_value
    proposal["provenance"]["raw_record_id"] = raw_record_id
    proposal["provenance"]["evidence_text"] = f"evidence for {raw_record_id}"
    return proposal


def _submit(client: TestClient, proposal_id: str = "p-1") -> None:
    res = client.post("/api/review/proposals", json=_proposal(proposal_id))
    assert res.status_code == 201, res.text


def _seed_raw_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="raw-good",
            source_name="emart",
            raw_title="오리온 오징어 땅콩 98g",
            raw_price=1980,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "오리온 오징어 땅콩 98g",
                    "category_id": "snack.nut",
                    "package_unit": "g",
                    "keywords": ["오징어땅콩"],
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="raw-missing",
            source_name="emart",
            raw_title="서울우유 1L",
            raw_price=2800,
        ),
        RawCrawlRecord(
            raw_record_id="raw-wrong",
            source_name="emart",
            raw_title="국내산 삼겹살 500g",
            raw_price=9900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "국내산 삼겹살 500g",
                    "category_id": "meat.pork",
                    "package_unit": "g",
                    "keywords": ["삼겹살"],
                }
            },
        ),
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-review",
                source_name="emart",
                crawler_name="seeded-test",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-review", records)


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


def test_update_and_delete_staged_proposal(client: TestClient) -> None:
    _submit(client)

    updated = client.put(
        "/api/review/proposals/p-1",
        json={
            "target_field": "canonical_name",
            "proposed_value": "제주삼다수 2L",
            "alternatives": ["삼다수 2L"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["target_field"] == "canonical_name"
    assert updated.json()["proposed_value"] == "제주삼다수 2L"

    deleted = client.delete("/api/review/proposals/p-1")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    assert client.get("/api/review/proposals/p-1").status_code == 404


def test_raw_records_endpoint_lists_records_with_proposals(
    client: TestClient,
    db: Database,
) -> None:
    _seed_raw_batch(db)
    res = client.post(
        "/api/review/proposals",
        json=_proposal_for_record(
            "p-raw-good-name",
            "raw-good",
            "canonical_name",
            "오리온 오징어 땅콩 98g",
        ),
    )
    assert res.status_code == 201, res.text

    listed = client.get(
        "/api/review/raw-records",
        params={"batch_id": "batch-review", "include_proposals": "true"},
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 3
    raw_good = next(item for item in items if item["raw_record_id"] == "raw-good")
    assert raw_good["proposals"][0]["proposal_id"] == "p-raw-good-name"


def test_raw_vs_ai_audit_detects_missing_and_misclassified_data(
    client: TestClient,
    db: Database,
) -> None:
    _seed_raw_batch(db)
    proposals = [
        _proposal_for_record("good-name", "raw-good", "canonical_name", "오리온 오징어 땅콩 98g"),
        _proposal_for_record("good-cat", "raw-good", "category_id", "snack.nut", proposal_type="category"),
        _proposal_for_record("good-unit", "raw-good", "package_unit", "g"),
        _proposal_for_record("good-kw", "raw-good", "keywords", "오징어땅콩", proposal_type="keyword"),
        _proposal_for_record("missing-name", "raw-missing", "canonical_name", "서울우유 1L"),
        _proposal_for_record("wrong-name", "raw-wrong", "canonical_name", "바나나 1송이"),
        _proposal_for_record("wrong-cat", "raw-wrong", "category_id", "fruit.banana", proposal_type="category"),
        _proposal_for_record("wrong-unit", "raw-wrong", "package_unit", "kg"),
        _proposal_for_record("wrong-kw", "raw-wrong", "keywords", "바나나", proposal_type="keyword"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text

    audit = client.get("/api/review/audit", params={"batch_id": "batch-review"})
    assert audit.status_code == 200, audit.text
    body = audit.json()
    assert body["raw_record_count"] == 3
    assert body["covered_record_count"] == 3
    assert body["status"] == "warning"

    issue_codes = {(issue["raw_record_id"], issue["code"]) for issue in body["issues"]}
    assert ("raw-missing", "missing_category_id_signal") in issue_codes
    assert ("raw-missing", "missing_unit_signal") in issue_codes
    assert ("raw-missing", "missing_keywords_signal") in issue_codes
    assert ("raw-wrong", "mismatched_category_id") in issue_codes
    assert ("raw-wrong", "mismatched_package_unit") in issue_codes
    assert ("raw-wrong", "name_signal_mismatch") in issue_codes
