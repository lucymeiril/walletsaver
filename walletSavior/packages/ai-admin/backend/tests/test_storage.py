"""ai-admin control DB 저장소 테스트.

* 테이블 생성 확인
* ProviderConfig는 alias만 저장 (secret value 없음)
* JobQueueSqlRepository가 shared JobQueueService와 통합됨
* PromptPack persistence
* ReviewDecision persistence
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect

from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    ProviderKind,
)
from core.contracts.control_plane import (
    ControlJobContract,
    ControlJobStatus,
    LearnedKnowledgeContract,
    PromptPackContract,
    PromptPackStatus,
    ProviderConfigContract,
    RawCrawlBatchContract,
    ReviewDecision,
    ReviewDecisionContract,
    RetryPolicyContract,
)
from core.job_queue import JobQueueService

from storage import (
    Database,
    FieldProposalRepository,
    JobQueueSqlRepository,
    LearnedKnowledgeRepository,
    PromptPackRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    create_database,
)


EXPECTED_TABLES = {
    "raw_crawl_batches",
    "raw_crawl_records",
    "ai_jobs",
    "worker_attempts",
    "provider_configs",
    "prompt_packs",
    "field_proposals",
    "review_decisions",
    "learned_knowledge",
}


@pytest.fixture()
def db() -> Database:
    database = create_database("sqlite:///:memory:")
    yield database
    database.dispose()


def test_create_all_creates_expected_tables(db: Database) -> None:
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(tables)


def test_provider_config_persists_alias_only(db: Database) -> None:
    contract = ProviderConfigContract(
        provider_id="gemini-prod",
        provider_kind=ProviderKind.GEMINI,
        display_name="Gemini Prod",
        base_url=None,
        default_model="gemini-1.5-pro",
        secret_alias="GEMINI_API_KEY",
        is_enabled=True,
        max_concurrent_jobs=2,
        min_request_interval_seconds=1.5,
        daily_budget_limit=5.0,
    )
    with db.session_scope() as session:
        repo = ProviderConfigRepository(session)
        repo.save(contract)

    with db.session_scope() as session:
        repo = ProviderConfigRepository(session)
        loaded = repo.get("gemini-prod")
        assert loaded is not None
        assert loaded.secret_alias == "GEMINI_API_KEY"
        assert loaded.provider_kind == ProviderKind.GEMINI
        assert loaded.daily_budget_limit == 5.0

        listed = repo.list()
        assert len(listed) == 1
        assert listed[0].provider_id == "gemini-prod"

    # raw row inspection — secret value 컬럼이 존재하지 않음을 확인.
    from storage.models import ProviderConfig

    with db.session_scope() as session:
        row = session.get(ProviderConfig, "gemini-prod")
        assert row is not None
        column_names = {c.name for c in row.__table__.columns}
        for forbidden in {"secret", "api_key", "secret_value", "password", "token"}:
            assert forbidden not in column_names
        # alias is stored, not the secret itself
        assert row.secret_alias == "GEMINI_API_KEY"


def test_prompt_pack_persistence(db: Database) -> None:
    pack = PromptPackContract(
        pack_id="normalizer-v1",
        role=AIWorkerRole.NORMALIZER,
        version="1.0.0",
        status=PromptPackStatus.DRAFT,
        content="System: normalize the title...",
        changelog="initial",
        created_by="lucy",
    )
    with db.session_scope() as session:
        PromptPackRepository(session).save(pack)

    with db.session_scope() as session:
        repo = PromptPackRepository(session)
        loaded = repo.get("normalizer-v1")
        assert loaded is not None
        assert loaded.role == AIWorkerRole.NORMALIZER
        assert loaded.status == PromptPackStatus.DRAFT
        assert loaded.content.startswith("System:")

        # update + filter by role
        activated = loaded.model_copy(
            update={
                "status": PromptPackStatus.ACTIVE,
                "approved_by": "reviewer-1",
                "activated_at": datetime(2024, 1, 1, 12, 0, 0),
            }
        )
        repo.save(activated)

        for_role = repo.list(role=AIWorkerRole.NORMALIZER)
        assert len(for_role) == 1
        assert for_role[0].status == PromptPackStatus.ACTIVE
        assert repo.list(role=AIWorkerRole.CLASSIFIER) == []


def test_review_decision_persistence(db: Database) -> None:
    provenance = FieldProvenance(
        raw_record_id="raw-1",
        evidence_text="원본 제목 텍스트",
        worker_role=AIWorkerRole.NORMALIZER,
        confidence=0.82,
    )
    proposal = FieldProposal(
        proposal_id="p-1",
        proposal_type=ProposalType.NORMALIZED_FIELD,
        target_field="canonical_name",
        proposed_value="삼다수 2L",
        provenance=provenance,
        alternatives=["삼다수 2 L"],
    )
    decision = ReviewDecisionContract(
        decision_id="d-1",
        proposal_id="p-1",
        proposal_type=ProposalType.NORMALIZED_FIELD,
        decision=ReviewDecision.CORRECT,
        reviewer_id="reviewer-1",
        corrected_value="제주삼다수 2L",
        reason="브랜드 명시",
        create_learning_rule=True,
    )

    with db.session_scope() as session:
        FieldProposalRepository(session).save(proposal)
        ReviewDecisionRepository(session).save(decision)

    with db.session_scope() as session:
        prop_repo = FieldProposalRepository(session)
        dec_repo = ReviewDecisionRepository(session)

        loaded_prop = prop_repo.get("p-1")
        assert loaded_prop is not None
        assert loaded_prop.proposed_value == "삼다수 2L"
        assert loaded_prop.provenance.confidence == 0.82
        assert loaded_prop.alternatives == ["삼다수 2 L"]
        assert prop_repo.list(status=PipelineStatus.AI_PROPOSED)[0].proposal_id == "p-1"

        decisions = dec_repo.list_for_proposal("p-1")
        assert len(decisions) == 1
        loaded = decisions[0]
        assert loaded.decision == ReviewDecision.CORRECT
        assert loaded.corrected_value == "제주삼다수 2L"
        assert loaded.create_learning_rule is True


def test_raw_crawl_batch_repository(db: Database) -> None:
    contract = RawCrawlBatchContract(
        batch_id="b-1",
        source_name="emart",
        crawler_name="emart-flyer",
        item_count=3,
        schema_type="flyer.v1",
        status=PipelineStatus.RAW_INGESTED,
        source_url="https://example.com/flyer",
    )
    with db.session_scope() as session:
        RawCrawlBatchRepository(session).save(contract)
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        assert repo.get("b-1") is not None
        assert len(repo.list()) == 1


def test_learned_knowledge_repository(db: Database) -> None:
    item = LearnedKnowledgeContract(
        knowledge_id="k-1",
        knowledge_type="alias",
        source_name="emart",
        pattern="삼다수",
        target_value="제주삼다수",
        positive_examples=["삼다수 2L"],
        negative_examples=[],
    )
    with db.session_scope() as session:
        LearnedKnowledgeRepository(session).save(item)
    with db.session_scope() as session:
        loaded = LearnedKnowledgeRepository(session).list(active_only=True)
        assert len(loaded) == 1
        assert loaded[0].pattern == "삼다수"


def test_job_queue_repository_integrates_with_shared_service(db: Database) -> None:
    """shared JobQueueService가 SQL repository로 lease/heartbeat/complete까지 동작."""
    job = ControlJobContract(
        job_id="job-1",
        batch_id="batch-1",
        role=AIWorkerRole.NORMALIZER,
        status=ControlJobStatus.QUEUED,
        priority=200,
        retry_policy=RetryPolicyContract(),
    )

    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        service = JobQueueService(repo)
        service.enqueue(job)

    now = datetime.now()

    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        service = JobQueueService(repo)
        leased = service.acquire_next(worker_id="worker-A", now=now, lease_seconds=60)
        assert leased is not None
        assert leased.status == ControlJobStatus.RUNNING
        assert leased.lease_owner == "worker-A"

    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        service = JobQueueService(repo)
        beat_at = now + timedelta(seconds=10)
        beat = service.heartbeat(
            job_id="job-1",
            worker_id="worker-A",
            now=beat_at,
            lease_seconds=60,
        )
        assert beat.heartbeat_at == beat_at
        assert beat.lease_expires_at == beat_at + timedelta(seconds=60)

    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        service = JobQueueService(repo)
        done = service.complete(
            job_id="job-1",
            worker_id="worker-A",
            now=now + timedelta(seconds=20),
        )
        assert done.status == ControlJobStatus.COMPLETED
        assert done.lease_owner is None

    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        # 더 이상 ready job 없음
        assert repo.list_ready(datetime.now(), limit=10) == []
        # status 별 조회
        completed = repo.list_by_status(ControlJobStatus.COMPLETED)
        assert len(completed) == 1


def test_job_queue_respects_not_before(db: Database) -> None:
    now = datetime.now()
    future = now + timedelta(minutes=5)
    job = ControlJobContract(
        job_id="job-2",
        batch_id="batch-2",
        role=AIWorkerRole.NORMALIZER,
        status=ControlJobStatus.QUEUED,
        not_before=future,
    )
    with db.session_scope() as session:
        JobQueueSqlRepository(session).save(job)

    with db.session_scope() as session:
        repo = JobQueueSqlRepository(session)
        ready = repo.list_ready(now, limit=10)
        assert ready == []
        ready_later = repo.list_ready(future + timedelta(seconds=1), limit=10)
        assert len(ready_later) == 1
