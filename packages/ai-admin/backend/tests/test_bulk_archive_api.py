"""POST /api/review/proposals/bulk-archive (+ preview, undo) 테스트.

사용자 요구: "AI 제안 비우기" 가 미리보기 → 일괄 archive → 30초 undo 까지 동작해야 한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.review import get_db as review_get_db
from api.routes.prompts import get_db as prompts_get_db
from storage import Database, create_database


@pytest.fixture()
def db(tmp_path) -> Database:
    database = create_database(f"sqlite:///{(tmp_path / 'bulk.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database) -> TestClient:
    app = create_app()
    app.dependency_overrides[prompts_get_db] = lambda: db
    app.dependency_overrides[review_get_db] = lambda: db
    return TestClient(app)


def _proposal(pid: str, *, ptype: str = "normalized_field", field: str = "canonical_name") -> dict:
    return {
        "proposal_id": pid,
        "proposal_type": ptype,
        "target_field": field,
        "proposed_value": "값",
        "status": "ai_proposed",
        "provenance": {
            "raw_record_id": f"raw-{pid}",
            "evidence_text": "evidence",
            "worker_role": "normalizer",
        },
        "alternatives": [],
    }


def _submit(client: TestClient, payload: dict) -> None:
    r = client.post("/api/review/proposals", json=payload)
    assert r.status_code == 201, r.text


def test_bulk_archive_preview_counts_matched_without_deleting(client: TestClient) -> None:
    for i in range(3):
        _submit(client, _proposal(f"p{i}"))
    res = client.post("/api/review/proposals/bulk-archive/preview", json={"reviewer_id": "op"})
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] == 3
    assert len(body["sample"]) == 3
    # nothing actually deleted
    listing = client.get("/api/review/proposals").json()
    assert len(listing["items"]) == 3


def test_bulk_archive_with_filter_archives_only_matching_then_undo_restores(client: TestClient) -> None:
    _submit(client, _proposal("a", ptype="normalized_field"))
    _submit(client, _proposal("b", ptype="keyword"))
    _submit(client, _proposal("c", ptype="keyword"))

    res = client.post(
        "/api/review/proposals/bulk-archive",
        json={"reviewer_id": "op", "filters": {"proposal_types": ["keyword"]}},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["archived"] == 2
    token = body["undo_token"]
    assert token

    remaining = client.get("/api/review/proposals").json()["items"]
    assert {p["proposal_id"] for p in remaining} == {"a"}

    undo = client.post("/api/review/proposals/bulk-archive/undo", json={"undo_token": token})
    assert undo.status_code == 200
    assert undo.json()["restored"] == 2

    after = client.get("/api/review/proposals").json()["items"]
    assert {p["proposal_id"] for p in after} == {"a", "b", "c"}


def test_bulk_archive_undo_token_can_only_be_used_once(client: TestClient) -> None:
    _submit(client, _proposal("x"))
    body = client.post(
        "/api/review/proposals/bulk-archive", json={"reviewer_id": "op"}
    ).json()
    token = body["undo_token"]
    assert client.post(
        "/api/review/proposals/bulk-archive/undo", json={"undo_token": token}
    ).status_code == 200
    second = client.post(
        "/api/review/proposals/bulk-archive/undo", json={"undo_token": token}
    )
    assert second.status_code == 410


def test_bulk_archive_skips_published_and_approved_status(client: TestClient, db: Database) -> None:
    """approved/published 같은 상태는 절대 비우지 않는다."""
    from storage import FieldProposalRepository
    from core.contracts.ai_pipeline import (
        FieldProposal as FP,
        FieldProvenance,
        PipelineStatus,
        ProposalType,
        AIWorkerRole,
    )

    with db.session_scope() as s:
        repo = FieldProposalRepository(s)
        repo.save(FP(
            proposal_id="approved-1",
            proposal_type=ProposalType.NORMALIZED_FIELD,
            target_field="canonical_name",
            proposed_value="값",
            status=PipelineStatus.APPROVED,
            provenance=FieldProvenance(
                raw_record_id="r1",
                evidence_text="e",
                worker_role=AIWorkerRole.NORMALIZER,
            ),
            alternatives=[],
        ))
        repo.save(FP(
            proposal_id="aiprop-1",
            proposal_type=ProposalType.NORMALIZED_FIELD,
            target_field="canonical_name",
            proposed_value="값",
            status=PipelineStatus.AI_PROPOSED,
            provenance=FieldProvenance(
                raw_record_id="r2",
                evidence_text="e",
                worker_role=AIWorkerRole.NORMALIZER,
            ),
            alternatives=[],
        ))

    preview = client.post("/api/review/proposals/bulk-archive/preview", json={"reviewer_id": "op"}).json()
    assert preview["matched"] == 1

    body = client.post("/api/review/proposals/bulk-archive", json={"reviewer_id": "op"}).json()
    assert body["archived"] == 1

    remaining = client.get("/api/review/proposals").json()["items"]
    assert {p["proposal_id"] for p in remaining} == {"approved-1"}


def _seed_proposal(db: Database, *, pid: str, status):
    """헬퍼: 직접 status로 proposal 시드 (API 통하지 않고)."""
    from storage import FieldProposalRepository
    from core.contracts.ai_pipeline import (
        FieldProposal as FP,
        FieldProvenance,
        ProposalType,
        AIWorkerRole,
    )

    with db.session_scope() as s:
        FieldProposalRepository(s).save(FP(
            proposal_id=pid,
            proposal_type=ProposalType.NORMALIZED_FIELD,
            target_field="canonical_name",
            proposed_value="값",
            status=status,
            provenance=FieldProvenance(
                raw_record_id=f"r-{pid}",
                evidence_text="e",
                worker_role=AIWorkerRole.NORMALIZER,
            ),
            alternatives=[],
        ))


def test_bulk_archive_include_published_opt_in_archives_published(
    client: TestClient, db: Database,
) -> None:
    """rd4-bulk-archive-expand: include_published=True 명시 시 published 도 비워진다.

    사용자 비판: "발행대기 못 비움, 발행됨 못 비움" — 위험 상태도 비울 수 있어야 한다.
    단 기본은 False (안전), 명시적 opt-in 시에만 동작.
    """
    from core.contracts.ai_pipeline import PipelineStatus

    _seed_proposal(db, pid="pub-1", status=PipelineStatus.PUBLISHED)
    _seed_proposal(db, pid="pub-2", status=PipelineStatus.PUBLISHED)
    _seed_proposal(db, pid="aiprop-x", status=PipelineStatus.AI_PROPOSED)

    # 기본 (opt-in 없음) — published 는 제외
    body = client.post(
        "/api/review/proposals/bulk-archive",
        json={"reviewer_id": "op"},
    ).json()
    assert body["archived"] == 1  # aiprop-x 만
    remaining = client.get("/api/review/proposals").json()["items"]
    assert {p["proposal_id"] for p in remaining} == {"pub-1", "pub-2"}

    # 두 번째 호출: include_published=True — published 도 archive
    body2 = client.post(
        "/api/review/proposals/bulk-archive",
        json={"reviewer_id": "op", "include_published": True},
    ).json()
    assert body2["archived"] == 2  # pub-1, pub-2
    after = client.get("/api/review/proposals").json()["items"]
    assert after == []


def test_bulk_archive_include_publishing_and_approved_opt_in(
    client: TestClient, db: Database,
) -> None:
    """rd4: include_publishing/include_approved 도 명시 opt-in 시 archive 대상."""
    from core.contracts.ai_pipeline import PipelineStatus

    _seed_proposal(db, pid="publishing-1", status=PipelineStatus.PUBLISHING)
    _seed_proposal(db, pid="approved-1", status=PipelineStatus.APPROVED)
    _seed_proposal(db, pid="aiprop-y", status=PipelineStatus.AI_PROPOSED)

    body = client.post(
        "/api/review/proposals/bulk-archive",
        json={
            "reviewer_id": "op",
            "include_publishing": True,
            "include_approved": True,
        },
    ).json()
    # 3건 전부 archive 됨 (aiprop 기본 + publishing/approved opt-in)
    assert body["archived"] == 3
    after = client.get("/api/review/proposals").json()["items"]
    assert after == []


def test_bulk_archive_preview_respects_include_published_flag(
    client: TestClient, db: Database,
) -> None:
    """preview 응답도 opt-in 플래그를 반영해야 한다 — UI가 사전 경고를 띄울 수 있도록."""
    from core.contracts.ai_pipeline import PipelineStatus

    _seed_proposal(db, pid="pub-a", status=PipelineStatus.PUBLISHED)
    _seed_proposal(db, pid="ai-a", status=PipelineStatus.AI_PROPOSED)

    default = client.post(
        "/api/review/proposals/bulk-archive/preview", json={"reviewer_id": "op"},
    ).json()
    assert default["matched"] == 1

    with_pub = client.post(
        "/api/review/proposals/bulk-archive/preview",
        json={"reviewer_id": "op", "include_published": True},
    ).json()
    assert with_pub["matched"] == 2
