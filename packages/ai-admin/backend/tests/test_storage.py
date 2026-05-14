"""ai-admin control DB 저장소 테스트.

* 테이블 생성 확인
* ProviderConfig는 alias만 저장 (secret value 없음)
* JobQueueSqlRepository가 shared JobQueueService와 통합됨
* PromptPack persistence
* ReviewDecision persistence
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import sqlite3

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
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProductMatchTargetType,
    PromptPackContract,
    PromptPackStatus,
    ProviderConfigContract,
    RawCrawlBatchContract,
    ReviewDecision,
    ReviewDecisionContract,
    RetryPolicyContract,
    normalize_product_signature_key,
)
from core.job_queue import JobQueueService

from storage import (
    Database,
    FieldProposalRepository,
    JobQueueSqlRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
    PromptPackRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    create_database,
)
from storage.database import get_default_database, reset_default_database


EXPECTED_TABLES = {
    "raw_crawl_batches",
    "raw_crawl_records",
    "ai_jobs",
    "worker_attempts",
    "provider_configs",
    "prompt_packs",
    "field_proposals",
    "review_decisions",
    "ai_publish_records",
    "learned_knowledge",
    "product_matches",
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


def test_default_database_initializes_once_under_parallel_requests(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "ai_control.db"
    monkeypatch.setenv("AI_CONTROL_DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    reset_default_database()

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            databases = list(pool.map(lambda _: get_default_database(), range(16)))
        assert len({id(database) for database in databases}) == 1
        inspector = inspect(databases[0].engine)
        assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))
    finally:
        reset_default_database()


def test_existing_provider_config_schema_gets_safe_live_limit_defaults(tmp_path) -> None:
    db_path = tmp_path / "old_control.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE provider_configs (
                provider_id VARCHAR(120) PRIMARY KEY,
                provider_kind VARCHAR(64) NOT NULL,
                display_name VARCHAR(255) NOT NULL,
                base_url TEXT,
                default_model VARCHAR(120) NOT NULL,
                secret_alias VARCHAR(120),
                is_enabled BOOLEAN NOT NULL DEFAULT 1,
                max_concurrent_jobs INTEGER NOT NULL DEFAULT 1,
                min_request_interval_seconds FLOAT NOT NULL DEFAULT 1.0,
                daily_budget_limit FLOAT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO provider_configs (
                provider_id, provider_kind, display_name, default_model,
                is_enabled, max_concurrent_jobs, min_request_interval_seconds
            ) VALUES ('gemini-prod', 'gemini', 'Gemini Prod', 'gemini-test', 1, 1, 1.0)
            """
        )
        connection.commit()
    finally:
        connection.close()

    database = create_database(f"sqlite:///{db_path.as_posix()}")
    try:
        with database.session_scope() as session:
            loaded = ProviderConfigRepository(session).get("gemini-prod")
        assert loaded is not None
        assert loaded.min_request_interval_seconds == 12.0
        assert loaded.max_provider_calls_per_minute == 5
        assert loaded.max_provider_calls_per_day == 300
        assert loaded.provider_retry_max_attempts == 3
        assert loaded.provider_retry_min_delay_seconds == 10.0
        assert loaded.provider_retry_max_delay_seconds == 60.0
    finally:
        database.dispose()


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
        min_request_interval_seconds=12.0,
        max_provider_calls_per_minute=5,
        max_provider_calls_per_day=300,
        provider_retry_max_attempts=3,
        provider_retry_min_delay_seconds=10.0,
        provider_retry_max_delay_seconds=60.0,
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
        assert loaded.min_request_interval_seconds == 12.0
        assert loaded.max_provider_calls_per_minute == 5
        assert loaded.max_provider_calls_per_day == 300
        assert loaded.provider_retry_max_attempts == 3
        assert loaded.provider_retry_min_delay_seconds == 10.0
        assert loaded.provider_retry_max_delay_seconds == 60.0
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


def test_product_match_store_persists_and_reads_exact_source_signature(db: Database) -> None:
    match = ProductMatchContract(
        source_id="emart",
        source_name="Emart Flyer",
        signature_key="  EMART :: Pulmuone Tofu 300G  ",
        canonical_product_id="prod-tofu-300g",
        canonical_product_name="풀무원 두부 300g",
        category_id="processed.tofu.firm",
        keywords=["두부", "풀무원", "300g"],
        unit_metadata={
            "package_quantity": 300,
            "package_unit": "g",
            "standard_unit": "100g",
        },
        provenance_source=ProductMatchProvenanceSource.AI,
        provider_name="gemini",
        model_name="gemini-1.5-pro",
        raw_record_id="raw-1",
        batch_id="batch-1",
        confidence=0.91,
        status=ProductMatchStatus.PROPOSED,
        audit_reason="AI proposed exact source title match during batch-1 labeling.",
        audit_metadata={"prompt_pack_id": "canonical-match-v1", "review_note": "awaiting approval"},
    )

    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(match)

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        loaded = repo.get_by_source_signature(
            source_id="emart",
            source_name="Emart Flyer",
            signature_key="emart :: pulmuone tofu 300g",
        )
        assert loaded is not None
        assert loaded.signature_key == "emart-pulmuone-tofu-300g"
        assert loaded.canonical_product_name == "풀무원 두부 300g"
        assert loaded.category_id == "processed.tofu.firm"
        assert loaded.keywords == ["두부", "풀무원", "300g"]
        assert loaded.unit_metadata["standard_unit"] == "100g"
        assert loaded.provenance_source == ProductMatchProvenanceSource.AI
        assert loaded.raw_record_id == "raw-1"
        assert loaded.batch_id == "batch-1"
        assert loaded.confidence == 0.91
        assert loaded.status == ProductMatchStatus.PROPOSED
        assert "batch-1" in loaded.audit_reason

        assert repo.get_by_source_signature(
            source_id="lotte",
            source_name="Emart Flyer",
            signature_key="emart :: pulmuone tofu 300g",
        ) is None


def test_product_match_store_exports_imports_and_rebuilds_readback(
    db: Database,
) -> None:
    payload = {
        "match_id": "legacy-import-id",
        "source_id": "emart",
        "source_name": "Emart Flyer",
        "signature_key": "  SKU=ABC-123; NAME=Tofu 300G  ",
        "canonical_product_name": "풀무원 두부 300g",
        "category_id": "processed.tofu.firm",
        "keywords": ["두부"],
        "unit_metadata": {"package_quantity": 300, "package_unit": "g"},
        "provenance_source": "human",
        "confidence": 0.99,
        "status": "approved",
        "audit_reason": "human-approved exact source signature import",
        "audit_metadata": {"ticket": "ops-123"},
        "reviewed_by": "reviewer-1",
    }

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        assert repo.import_records([payload], rebuild_match_ids=True) == {
            "inserted": 1,
            "updated": 0,
            "skipped": 0,
        }
        assert repo.import_records([payload], rebuild_match_ids=True) == {
            "inserted": 0,
            "updated": 0,
            "skipped": 1,
        }
        provider_payload = {
            **payload,
            "match_id": "provider-approved-id",
            "source_id": "homeplus",
            "signature_key": "source-sku=provider-approved",
            "provenance_source": ProductMatchProvenanceSource.PROVIDER.value,
            "audit_reason": "provider-approved row still requires human review before skip reuse",
            "reviewed_by": None,
        }
        repo.import_records([provider_payload], rebuild_match_ids=True)
        exported = repo.export_records(approved_only=True)
        skip_safe_exported = repo.export_records(skip_safe_only=True)

    assert len(exported) == 2
    assert len(skip_safe_exported) == 1
    exported_row = skip_safe_exported[0]
    assert exported_row["match_id"] != "legacy-import-id"
    assert exported_row["signature_key"] == "sku-abc-123-name-tofu-300g"
    assert exported_row["status"] == ProductMatchStatus.APPROVED.value
    assert exported_row["provenance_source"] == ProductMatchProvenanceSource.HUMAN.value
    assert "secret" not in str(exported_row).lower()

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        readback = repo.get_by_source_signature(
            source_id="emart",
            source_name="Emart Flyer",
            signature_key="sku=abc-123; name=tofu 300g",
        )
    assert readback is not None
    assert readback.match_id == exported_row["match_id"]
    assert readback.reviewed_by == "reviewer-1"


def test_product_match_import_rejects_secret_bearing_metadata_and_keeps_readback_safe(
    db: Database,
) -> None:
    safe_payload = {
        "source_id": "emart",
        "source_name": "Emart Flyer",
        "signature_key": "sku=safe-300g; name=safe item 300g",
        "canonical_product_name": "안전 메타데이터 상품 300g",
        "category_id": "processed.safe",
        "keywords": ["안전"],
        "unit_metadata": {"package_quantity": 300, "package_unit": "g"},
        "provenance_source": "human",
        "status": "approved",
        "confidence": 0.99,
        "audit_reason": "human-approved exact source signature import",
        "audit_metadata": {"ticket": "ops-safe"},
        "reviewed_by": "reviewer-1",
    }
    secret_payload = {
        **safe_payload,
        "signature_key": "sku=unsafe-300g; name=unsafe item 300g",
        "audit_metadata": {"api_key": "should-not-be-stored"},
    }

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        assert repo.import_records([safe_payload], rebuild_match_ids=True) == {
            "inserted": 1,
            "updated": 0,
            "skipped": 0,
        }
        with pytest.raises(ValueError, match="secret-bearing metadata"):
            repo.import_records([secret_payload], rebuild_match_ids=True)
        exported = repo.export_records(skip_safe_only=True)
        readback = repo.get_by_source_signature(
            source_id="emart",
            source_name="Emart Flyer",
            signature_key="sku=safe-300g; name=safe item 300g",
        )
        unsafe_readback = repo.get_by_source_signature(
            source_id="emart",
            source_name="Emart Flyer",
            signature_key="sku=unsafe-300g; name=unsafe item 300g",
        )

    assert len(exported) == 1
    assert readback is not None
    assert unsafe_readback is None
    assert "should-not-be-stored" not in str(exported)
    assert "api_key" not in str(exported).lower()


def test_product_match_store_rebuilds_legacy_identity_keys(db: Database) -> None:
    from storage.models import ProductMatch

    with db.session_scope() as session:
        session.add(
            ProductMatch(
                match_id="legacy-row-id",
                source_id="emart",
                source_name="Emart Flyer",
                signature_key="  NAME=Tofu 300G; crawled_at=2025-01-01T00:00:00  ",
                canonical_product_name="풀무원 두부 300g",
                provenance_source=ProductMatchProvenanceSource.HUMAN.value,
                status=ProductMatchStatus.APPROVED.value,
                audit_reason="legacy exact match row before identity rebuild",
            )
        )

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        dry_run = repo.rebuild_identity_keys(dry_run=True)
        applied = repo.rebuild_identity_keys(dry_run=False)
        readback = repo.get_by_source_signature(
            source_id="emart",
            source_name="Emart Flyer",
            signature_key="name=tofu 300g",
        )

    assert dry_run["changed"] == 1
    assert applied["changed"] == 1
    assert readback is not None
    assert readback.match_id != "legacy-row-id"
    assert readback.signature_key == "name-tofu-300g"


def test_product_match_signature_ignores_volatile_payload_fields() -> None:
    first_signature = (
        "name=풀무원 국산콩 두부 300g; "
        "image_url=https://cdn.example.com/a.jpg?cache=1; "
        "detail_url=https://shop.example.com/item/123?utm_source=ad&tracking_id=aaa; "
        "crawled_at=2025-01-02T03:04:05"
    )
    second_signature = (
        "name=풀무원 국산콩 두부 300g; "
        "image_url=https://images.example.net/changed.png?cache=2; "
        "detail_url=https://shop.example.com/new/item/123?utm_source=mail&tracking_id=bbb; "
        "crawled_at=2025-03-04T05:06:07"
    )

    assert normalize_product_signature_key(first_signature) == normalize_product_signature_key(
        second_signature
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("name=불닭볶음면 300g", "name=불닭볶음면 100g"),
        ("name=불닭볶음면 5입 700g", "name=불닭볶음면 1입 140g"),
        ("name=불닭볶음면 140g", "name=핵불닭볶음면 140g"),
        ("name=불닭볶음면 오리지널 140g", "name=불닭볶음면 까르보 140g"),
    ],
)
def test_product_match_signature_preserves_package_and_variant_differences(
    left: str,
    right: str,
) -> None:
    assert normalize_product_signature_key(left) != normalize_product_signature_key(right)


def test_product_match_store_scopes_same_signature_by_source(db: Database) -> None:
    base = ProductMatchContract(
        source_id="emart",
        source_name="Emart Flyer",
        signature_key="name=풀무원 국산콩 두부 300g",
        canonical_product_id="prod-emart-tofu",
        canonical_product_name="이마트 두부 300g",
        provenance_source=ProductMatchProvenanceSource.HUMAN,
        status=ProductMatchStatus.APPROVED,
        audit_reason="human approved emart source match",
    )
    other = base.model_copy(
        update={
            "source_id": "homeplus",
            "source_name": "Homeplus",
            "canonical_product_id": "prod-homeplus-tofu",
            "canonical_product_name": "홈플러스 두부 300g",
            "audit_reason": "human approved homeplus source match",
        }
    )

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        repo.save(base)
        repo.save(other)

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        emart = repo.get_by_source_signature(
            source_id="emart",
            source_name="Emart Flyer",
            signature_key="name=풀무원 국산콩 두부 300g",
        )
        homeplus = repo.get_by_source_signature(
            source_id="homeplus",
            source_name="Homeplus",
            signature_key="name=풀무원 국산콩 두부 300g",
        )

    assert emart is not None
    assert homeplus is not None
    assert emart.match_id != homeplus.match_id
    assert emart.canonical_product_id == "prod-emart-tofu"
    assert homeplus.canonical_product_id == "prod-homeplus-tofu"


def test_product_match_store_exact_lookup_does_not_fuzzy_match_variants(
    db: Database,
) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="Emart Flyer",
                signature_key="name=불닭볶음면 140g",
                canonical_product_name="불닭볶음면 140g",
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="human approved exact variant match",
            )
        )

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        assert (
            repo.get_by_source_signature(
                source_id="emart",
                source_name="Emart Flyer",
                signature_key="name=핵불닭볶음면 140g",
            )
            is None
        )
        assert (
            repo.get_by_source_signature(
                source_id="emart",
                source_name="Emart Flyer",
                signature_key="name=불닭볶음면 100g",
            )
            is None
        )


def test_product_match_store_updates_status_with_human_audit(db: Database) -> None:
    proposed = ProductMatchContract(
        source_id="homeplus",
        source_name="Homeplus",
        signature_key="homeplus milk 1l",
        canonical_product_name="우유 1L",
        category_id="dairy.milk",
        provenance_source=ProductMatchProvenanceSource.PROVIDER,
        raw_record_id="raw-milk",
        batch_id="batch-milk",
        confidence=0.72,
        status=ProductMatchStatus.PROPOSED,
        audit_reason="Provider proposal from normalized source title.",
    )

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        repo.save(proposed)
        repo.save(
            proposed.model_copy(
                update={
                    "status": ProductMatchStatus.APPROVED,
                    "provenance_source": ProductMatchProvenanceSource.HUMAN,
                    "reviewed_by": "reviewer-1",
                    "audit_reason": "Reviewer approved because raw title exactly maps to milk 1L.",
                }
            )
        )

    with db.session_scope() as session:
        loaded = ProductMatchStoreRepository(session).get_by_source_signature(
            source_id="homeplus",
            source_name="Homeplus",
            signature_key="HOMEPLUS MILK 1L",
        )
        assert loaded is not None
        assert loaded.status == ProductMatchStatus.APPROVED
        assert loaded.provenance_source == ProductMatchProvenanceSource.HUMAN
        assert loaded.reviewed_by == "reviewer-1"
    assert "Reviewer approved" in loaded.audit_reason


def test_product_match_strict_title_variant_and_package_matches(db: Database) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="emart",
                signature_key="name=풀무원 두부 300g",
                target_type=ProductMatchTargetType.SOURCE_LISTING,
                target_id="emart-listing-1",
                canonical_product_id="prod-tofu-300g",
                canonical_product_name="풀무원 두부 300g",
                allowed_title_patterns=["풀무원 국산콩 두부"],
                normalized_title_variants=["풀무원 국산콩 두부"],
                package_signature="package=300g",
                source_product_id_history=["sku-1"],
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="human approved title+package source listing match",
                reviewed_by="reviewer-1",
                approved_by="reviewer-1",
            )
        )

    with db.session_scope() as session:
        match = ProductMatchStoreRepository(session).find_strict_approved_match(
            source_id="emart",
            source_name="emart",
            raw_title="풀무원 국산콩 두부",
            package_signature="package=300g",
            source_product_id="sku-1",
        )

    assert match is not None
    assert match.target_type == ProductMatchTargetType.SOURCE_LISTING
    assert match.target_id == "emart-listing-1"


def test_product_match_strict_package_mismatch_does_not_auto_match(db: Database) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="emart",
                signature_key="name=ramen 5pack",
                canonical_product_name="라면 5입",
                allowed_title_patterns=["라면 멀티팩"],
                package_signature="bundle=5;unit=pack",
                source_product_id_history=["ramen-sku"],
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="human approved package-specific source match",
            )
        )

    with db.session_scope() as session:
        match = ProductMatchStoreRepository(session).find_strict_approved_match(
            source_id="emart",
            source_name="emart",
            raw_title="라면 멀티팩",
            package_signature="bundle=4;unit=pack",
            source_product_id="ramen-sku",
        )

    assert match is None


def test_product_match_strict_blocked_pattern_prevents_auto_match(db: Database) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="emart",
                signature_key="name=ramen original 140g",
                canonical_product_name="라면 오리지널 140g",
                allowed_title_patterns=["라면 * 140g"],
                blocked_title_patterns=["라면 매운맛 140g"],
                package_signature="140g",
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="human approved with negative title example",
            )
        )

    with db.session_scope() as session:
        repo = ProductMatchStoreRepository(session)
        blocked = repo.find_strict_approved_match(
            source_id="emart",
            source_name="emart",
            raw_title="라면 매운맛 140g",
            package_signature="140g",
            source_product_id=None,
        )
        allowed = repo.find_strict_approved_match(
            source_id="emart",
            source_name="emart",
            raw_title="라면 오리지널 140g",
            package_signature="140g",
            source_product_id=None,
        )

    assert blocked is None
    assert allowed is not None


def test_product_match_strict_source_product_id_alone_is_not_auto_match(
    db: Database,
) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="emart",
                signature_key="name=milk 1l",
                canonical_product_name="우유 1L",
                allowed_title_patterns=["우유 1l"],
                package_signature="1l",
                source_product_id_history=["stable-source-id"],
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="human approved stable source listing",
            )
        )

    with db.session_scope() as session:
        match = ProductMatchStoreRepository(session).find_strict_approved_match(
            source_id="emart",
            source_name="emart",
            raw_title="우유 900ml",
            package_signature="900ml",
            source_product_id="stable-source-id",
        )

    assert match is None


def test_product_match_store_rejects_secret_bearing_metadata(db: Database) -> None:
    with pytest.raises(ValueError, match="secret-bearing metadata"):
        ProductMatchContract(
            source_id="emart",
            source_name="Emart",
            signature_key="emart tofu",
            canonical_product_name="두부",
            provenance_source=ProductMatchProvenanceSource.AI,
            status=ProductMatchStatus.PROPOSED,
            audit_reason="would leak provider credentials",
            audit_metadata={"api_key": "AIza-secret-value"},
        )

    from storage.models import ProductMatch

    column_names = {column.name for column in ProductMatch.__table__.columns}
    for forbidden in {"secret", "api_key", "secret_value", "password", "token"}:
        assert forbidden not in column_names


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
