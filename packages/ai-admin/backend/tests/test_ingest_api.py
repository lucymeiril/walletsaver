"""Raw ingest -> AI proposal persistence tests."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.app import create_app
from api.deps import get_db_session
from api.routes.review import get_db as get_review_db
from core.contracts.ai_pipeline import PipelineStatus
from core.contracts.control_plane import (
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProviderConfigContract,
)
from providers.google_genai import ProviderResponseError
from services import ai_ingestion
from services.review_publish import build_publish_rows
from storage import (
    Database,
    FieldProposalRepository,
    ProductMatchStoreRepository,
    ProviderConfigRepository,
    RawCrawlBatchRepository,
    create_database,
)
from storage.models import AIPublishRecord


FAKE_GOOGLE_KEY = "AIza" + "1" * 25


@pytest.fixture()
def db(tmp_path) -> Iterator[Database]:
    database = create_database(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield database
    database.dispose()


@pytest.fixture()
def client(db: Database, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
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

    class FakeProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            records = re.findall(r"- id=([^;]+); source=[^;]+; title=([^;]+); price=([^\n]+)", prompt)
            if not records:
                records = [(record_id, "", "") for record_id in re.findall(r"- id=([^;]+);", prompt)]

            def _label(record_id: str, title: str) -> dict:
                if "두부" in title or "tofu" in record_id:
                    canonical_name = "풀무원 국산콩 두부 300g"
                    brand = "풀무원"
                    category_id = "fresh.tofu"
                    keywords = ["두부", "국산콩", "마트특가"]
                    aliases = ["국산콩두부"]
                    attributes = {"food_type": "tofu"}
                    package_quantity = 300
                    package_unit = "g"
                    standard_unit = "kg"
                    standard_unit_price = 9966.67
                elif "삼겹살" in title or "meat" in record_id:
                    canonical_name = "국내산 삼겹살 600g"
                    brand = "정육"
                    category_id = "fresh.meat"
                    keywords = ["삼겹살", "돼지고기", "핫딜"]
                    aliases = ["국내산삼겹살"]
                    attributes = {"meat_cut": "pork_belly"}
                    package_quantity = 600
                    package_unit = "g"
                    standard_unit = "kg"
                    standard_unit_price = 19800
                elif "orion" in record_id or record_id == "r1":
                    canonical_name = "오리온 오징어 땅콩 98g"
                    brand = "오리온"
                    category_id = "snack.nut"
                    keywords = ["오징어땅콩", "과자"]
                    aliases = ["오징어땅콩"]
                    attributes = {"snack_type": "nut"}
                    package_quantity = 98
                    package_unit = "g"
                    standard_unit = "kg"
                    standard_unit_price = 20204.08
                else:
                    canonical_name = "이마트 테스트 상품"
                    brand = "이마트"
                    category_id = "mart.test"
                    keywords = ["테스트"]
                    aliases = ["테스트상품"]
                    attributes = {"source": "mart"}
                    package_quantity = 1
                    package_unit = "ea"
                    standard_unit = "ea"
                    standard_unit_price = 1000
                return {
                    "raw_record_id": record_id,
                    "canonical_name": canonical_name,
                    "brand": brand,
                    "category_id": category_id,
                    "keywords": keywords,
                    "aliases": aliases,
                    "attributes": attributes,
                    "package_quantity": package_quantity,
                    "package_unit": package_unit,
                    "bundle_count": 1,
                    "standard_unit": standard_unit,
                    "standard_unit_price": standard_unit_price,
                    "confidence": 0.91,
                    "notes": "real-shaped hotdeal/mart product",
                }

            return {
                "items": [_label(record_id, title) for record_id, title, _price in records]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: FakeProvider(config),
    )

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[get_review_db] = lambda: db
    try:
        with db.session_scope() as session:
            ProviderConfigRepository(session).save(
                ProviderConfigContract(
                    provider_id="google-dev",
                    provider_kind="gemini",
                    display_name="Google Dev",
                    default_model="gemma-4-26b-a4b-it",
                    secret_alias="GOOGLE_API_KEY",
                )
            )
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _store_product_match(
    db: Database,
    *,
    source_id: str = "emart",
    source_name: str = "emart",
    signature_key: str = "풀무원 국산콩 두부 300g",
    status: ProductMatchStatus = ProductMatchStatus.APPROVED,
    provenance_source: ProductMatchProvenanceSource = ProductMatchProvenanceSource.HUMAN,
    is_active: bool = True,
) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id=source_id,
                source_name=source_name,
                signature_key=signature_key,
                canonical_product_id="prod-tofu-300g",
                canonical_product_name="풀무원 국산콩 두부 300g",
                category_id="processed.tofu.firm",
                keywords=["두부", "풀무원"],
                unit_metadata={
                    "package_quantity": 300,
                    "package_unit": "g",
                    "display_unit": "300g",
                    "standard_unit": "kg",
                    "bundle_count": 1,
                },
                provenance_source=provenance_source,
                raw_record_id="learned:tofu",
                batch_id="learned-batch",
                confidence=0.97,
                status=status,
                audit_reason="human approved exact product match for ingestion reuse",
                reviewed_by="reviewer-1" if provenance_source == ProductMatchProvenanceSource.HUMAN else None,
                is_active=is_active,
            )
        )


def test_ingest_uses_approved_product_match_before_provider_call(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(db)
    provider_calls: list[str] = []

    class ProviderMustNotBeCalled:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            provider_calls.append(prompt)
            raise AssertionError("matched row should not call provider")

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderMustNotBeCalled(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:tofu",
                    "source_name": "emart",
                    "source_url": "https://emart.example/tofu",
                    "raw_title": "풀무원 국산콩 두부 300g",
                    "raw_price": 2990,
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["provider_calls"] == 0
    assert body["ai_batches"] == 0
    assert body["product_match_hits"] == 1
    assert provider_calls == []


def test_ingest_does_not_auto_approve_inactive_product_match(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(db, is_active=False)
    prompts: list[str] = []

    class ProviderForInactiveMatch:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            prompts.append(prompt)
            return {
                "items": [
                    {
                        "raw_record_id": "emart:tofu",
                        "canonical_name": "provider reviewed tofu",
                        "category_id": "processed.tofu.firm",
                        "keywords": ["두부"],
                        "aliases": [],
                        "attributes": {},
                        "confidence": 0.8,
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderForInactiveMatch(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:tofu",
                    "source_name": "emart",
                    "source_url": "https://emart.example/tofu",
                    "raw_title": "풀무원 국산콩 두부 300g",
                    "raw_price": 2990,
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider_calls"] == 1
    assert body["product_match_hits"] == 0
    assert len(prompts) == 1


def test_ingest_recovers_provider_omitted_rows_with_reviewer_safe_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SkipsSecondRowProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            records = re.findall(r"- id=([^;]+); source=[^;]+; title=([^;]+); price=([^\n]+)", prompt)
            if len(records) == 1 and records[0][0] == "row-mobile":
                return {"items": []}
            first_id, first_title, _price = records[0]
            return {
                "items": [
                    {
                        "raw_record_id": first_id,
                        "canonical_name": first_title.strip(),
                        "category_id": "processed.tofu.firm",
                        "keywords": ["두부"],
                        "package_quantity": 300,
                        "package_unit": "g",
                        "bundle_count": 1,
                        "confidence": 0.91,
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: SkipsSecondRowProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "max_provider_calls": 2,
            "records": [
                {
                    "raw_record_id": "row-tofu",
                    "source_name": "emart",
                    "raw_title": "국산콩 두부 300g",
                    "raw_price": 2980,
                },
                {
                    "raw_record_id": "row-mobile",
                    "source_name": "emart",
                    "raw_title": "[즉시할인] 갤럭시 자급제폰 256GB",
                    "raw_price": 990000,
                },
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["missing_label_count"] == 0
    assert body["deterministic_recovery_count"] == 1

    proposals = client.get("/api/review/proposals").json()["items"]
    mobile = [
        proposal
        for proposal in proposals
        if proposal["provenance"]["raw_record_id"] == "row-mobile"
    ]
    values_by_field: dict[str, list] = {}
    for proposal in mobile:
        values_by_field.setdefault(proposal["target_field"], []).append(proposal["proposed_value"])
    by_field = {field: values[-1] for field, values in values_by_field.items()}
    assert by_field["category_id"] == "electronics.mobile"
    assert "갤럭시" in values_by_field["keywords"]
    assert by_field["package_quantity"] == 1
    assert by_field["package_unit"] == "개"


def test_ingest_reports_missing_rows_when_reviewer_safe_fallback_cannot_recover(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            return {"items": []}

    def fallback_still_missing(**kwargs):
        records = kwargs["records"]
        return (
            [],
            [],
            records,
            {
                "fallback_recovered_count": 0,
                "fallback_missing_count": len(records),
                "invalid_response_rows": [],
                "index_mappings": [],
            },
        )

    monkeypatch.setattr(ai_ingestion, "provider_from_config", lambda config: EmptyProvider(config))
    monkeypatch.setattr(ai_ingestion, "_fallback_proposals_for_missing_records", fallback_still_missing)

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "max_provider_calls": 1,
            "records": [
                {
                    "raw_record_id": "row-unrecovered",
                    "source_name": "emart",
                    "raw_title": "미복구 상품 1개",
                    "raw_price": 1000,
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "partial_review_required"
    assert body["missing_label_count"] == 1
    assert body["missing_label_raw_record_ids"] == ["row-unrecovered"]
    assert body["deterministic_recovery_count"] == 0


def test_repeated_exact_product_match_batches_accumulate_review_rows_without_ai(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(
        db,
        source_id="emart",
        source_name="emart",
        signature_key="source-sku=stable-300g; package=300g",
    )
    provider_calls: list[str] = []

    class ProviderMustNotBeCalled:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            provider_calls.append(prompt)
            raise AssertionError("exact learned product match should skip provider")

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderMustNotBeCalled(config),
    )

    for raw_record_id, price in (("emart:stable:first", 2990), ("emart:stable:second", 2790)):
        res = client.post(
            "/api/ingest/raw-records/label",
            json={
                "provider_id": "google-dev",
                "source_name": "emart",
                "records": [
                    {
                        "raw_record_id": raw_record_id,
                        "source_name": "emart",
                        "raw_title": "renamed source title is ignored when source signature is exact",
                        "raw_price": price,
                        "raw_payload": {
                            "source_id": "emart",
                            "source_signature": "source-sku=stable-300g; package=300g",
                        },
                    }
                ],
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["provider_calls"] == 0
        assert body["ai_batches"] == 0
        assert body["product_match_hits"] == 1

    with db.session_scope() as session:
        batches = RawCrawlBatchRepository(session).list()
        proposals = FieldProposalRepository(session).list()
        matches = ProductMatchStoreRepository(session).list()

    assert provider_calls == []
    assert len(batches) == 2
    assert len(matches) == 1
    assert {proposal.provenance.raw_record_id for proposal in proposals} == {
        "emart:stable:first",
        "emart:stable:second",
    }
    assert {
        proposal.provenance.provider.provider_name
        for proposal in proposals
        if proposal.provenance.provider is not None
    } == {"learned_match/product_match"}


def test_product_match_builds_review_data_with_learned_provenance(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(db)

    class ProviderMustNotBeCalled:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            raise AssertionError("approved product match should skip provider")

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderMustNotBeCalled(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:tofu",
                    "source_name": "emart",
                    "source_url": "https://emart.example/tofu",
                    "raw_title": "풀무원 국산콩 두부 300g",
                    "raw_price": 2990,
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
        rows = build_publish_rows(session, batch_id=body["raw_batch_id"])
        publish_state = session.get(AIPublishRecord, "emart:tofu")

    assert publish_state is None
    assert {proposal.status for proposal in proposals} == {PipelineStatus.APPROVED}
    assert all(
        proposal.provenance.provider is not None
        and proposal.provenance.provider.provider_name == "learned_match/product_match"
        and "learned_match/product_match" in proposal.provenance.evidence_text
        for proposal in proposals
    )
    values = {(proposal.target_field, proposal.proposed_value) for proposal in proposals}
    assert ("canonical_name", "풀무원 국산콩 두부 300g") in values
    assert ("category_id", "processed.tofu.firm") in values
    assert ("keywords", "두부") in values
    assert len(rows) == 1
    assert rows[0]["raw_record_id"] == "emart:tofu"
    assert rows[0]["item"]["name"] == "풀무원 국산콩 두부 300g"
    assert rows[0]["item"]["category_id"] == "processed.tofu.firm"


def test_mixed_ingest_uses_match_for_known_rows_and_provider_for_unknown(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(db)
    prompts: list[str] = []

    class UnknownOnlyProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            prompts.append(prompt)
            record_ids = re.findall(r"- id=([^;]+);", prompt)
            assert record_ids == ["emart:milk"]
            return {
                "items": [
                    {
                        "raw_record_id": "emart:milk",
                        "canonical_name": "서울우유 1L",
                        "category_id": "dairy.milk",
                        "keywords": ["우유"],
                        "aliases": [],
                        "attributes": {},
                        "confidence": 0.88,
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: UnknownOnlyProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:tofu",
                    "source_name": "emart",
                    "source_url": "https://emart.example/tofu",
                    "raw_title": "풀무원 국산콩 두부 300g",
                    "raw_price": 2990,
                },
                {
                    "raw_record_id": "emart:milk",
                    "source_name": "emart",
                    "source_url": "https://emart.example/milk",
                    "raw_title": "서울우유 1L",
                    "raw_price": 2980,
                },
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider_calls"] == 1
    assert body["product_match_hits"] == 1
    assert len(prompts) == 1
    assert "emart:tofu" not in prompts[0]
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
    by_record = {}
    for proposal in proposals:
        by_record.setdefault(proposal.provenance.raw_record_id, set()).add(
            proposal.provenance.provider.provider_name if proposal.provenance.provider else None
        )
    assert by_record["emart:tofu"] == {"learned_match/product_match"}
    assert by_record["emart:milk"] == {"google-dev"}


def test_product_match_precheck_requires_exact_source_name_and_signature(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(
        db,
        source_id="emart",
        source_name="emart",
        signature_key="source-sku=known-300g; name=known item 300g",
    )
    prompts: list[str] = []

    class ProviderForUnmatchedRows:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            prompts.append(prompt)
            record_ids = re.findall(r"- id=([^;]+);", prompt)
            assert record_ids == ["homeplus:known", "emart:changed"]
            return {
                "items": [
                    {
                        "raw_record_id": record_id,
                        "canonical_name": "provider reviewed item",
                        "category_id": "mart.review",
                        "keywords": ["검수"],
                        "aliases": [],
                        "attributes": {},
                        "confidence": 0.8,
                    }
                    for record_id in record_ids
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderForUnmatchedRows(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:known",
                    "source_name": "emart",
                    "raw_title": "renamed listing still carries exact source signature",
                    "raw_price": 2990,
                    "raw_payload": {
                        "source_id": "emart",
                        "signature_key": "source-sku=known-300g; name=known item 300g",
                    },
                },
                {
                    "raw_record_id": "homeplus:known",
                    "source_name": "homeplus",
                    "raw_title": "same signature from a different source must be reviewed",
                    "raw_price": 2990,
                    "raw_payload": {
                        "source_id": "emart",
                        "signature_key": "source-sku=known-300g; name=known item 300g",
                    },
                },
                {
                    "raw_record_id": "emart:changed",
                    "source_name": "emart",
                    "raw_title": "same source but changed source signature must be reviewed",
                    "raw_price": 2990,
                    "raw_payload": {
                        "source_id": "emart",
                        "signature_key": "source-sku=known-500g; name=known item 500g",
                    },
                },
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product_match_hits"] == 1
    assert body["provider_calls"] == 1
    assert len(prompts) == 1
    assert "emart:known" not in prompts[0]
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
    by_record = {}
    for proposal in proposals:
        by_record.setdefault(proposal.provenance.raw_record_id, set()).add(
            proposal.provenance.provider.provider_name if proposal.provenance.provider else None
        )
    assert by_record["emart:known"] == {"learned_match/product_match"}
    assert by_record["homeplus:known"] == {"google-dev"}
    assert by_record["emart:changed"] == {"google-dev"}


def test_product_match_requires_human_approved_safe_provenance_to_skip_provider(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _store_product_match(
        db,
        provenance_source=ProductMatchProvenanceSource.PROVIDER,
        status=ProductMatchStatus.APPROVED,
    )
    provider_calls = 0

    class ProviderFallback:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            nonlocal provider_calls
            provider_calls += 1
            return {
                "items": [
                    {
                        "raw_record_id": "emart:tofu",
                        "canonical_name": "AI fallback tofu",
                        "category_id": "fresh.tofu",
                        "keywords": ["두부"],
                        "aliases": [],
                        "attributes": {},
                        "confidence": 0.8,
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderFallback(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:tofu",
                    "source_name": "emart",
                    "source_url": "https://emart.example/tofu",
                    "raw_title": "풀무원 국산콩 두부 300g",
                    "raw_price": 2990,
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product_match_hits"] == 0
    assert body["provider_calls"] == 1
    assert provider_calls == 1
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
    assert {proposal.status for proposal in proposals} == {PipelineStatus.AI_PROPOSED}
    assert all(
        proposal.provenance.provider is not None
        and proposal.provenance.provider.provider_name == "google-dev"
        for proposal in proposals
    )


def test_product_match_source_product_id_alone_does_not_skip_provider(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with db.session_scope() as session:
        ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="emart",
                signature_key="name=우유 1l",
                canonical_product_id="prod-milk-1l",
                canonical_product_name="우유 1L",
                category_id="dairy.milk",
                keywords=["우유"],
                allowed_title_patterns=["우유 1l"],
                package_signature="1l",
                source_product_id_history=["stable-source-id"],
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="human approved strict source listing",
                reviewed_by="reviewer-1",
            )
        )
    provider_calls = 0

    class ProviderFallback:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            nonlocal provider_calls
            provider_calls += 1
            return {
                "items": [
                    {
                        "raw_record_id": "emart:milk",
                        "canonical_name": "AI fallback milk 900ml",
                        "category_id": "dairy.milk",
                        "keywords": ["우유"],
                        "aliases": [],
                        "attributes": {},
                        "package_quantity": 900,
                        "package_unit": "ml",
                        "confidence": 0.8,
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: ProviderFallback(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:milk",
                    "source_name": "emart",
                    "source_record_key": "stable-source-id",
                    "raw_title": "우유 900ml",
                    "raw_price": 1990,
                    "raw_payload": {
                        "source_id": "emart",
                        "source_product_id": "stable-source-id",
                        "package_signature": "900ml",
                    },
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product_match_hits"] == 0
    assert body["provider_calls"] == 1
    assert provider_calls == 1


def test_ingest_label_stores_raw_batch_and_proposals(client: TestClient) -> None:
    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "r1",
                    "source_name": "emart",
                    "raw_title": "오리온 오징어 땅콩 98g",
                    "raw_price": 1980,
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["records_stored"] == 1
    assert body["ai_batches"] == 1
    assert body["provider_calls"] == 1
    assert body["proposals_stored"] >= 8

    proposals = client.get("/api/review/proposals").json()["items"]
    values = {(p["target_field"], p["proposed_value"]) for p in proposals}
    assert ("category_id", "snack.nut") in values
    assert ("brand", "오리온") in values


def test_ingest_label_accepts_bounded_operator_ai_batch_size(client: TestClient) -> None:
    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "max_ai_batch_items": 2,
            "max_ai_batch_prompt_chars": 8000,
            "records": [
                {
                    "raw_record_id": f"emart:item-{index}",
                    "source_name": "emart",
                    "raw_title": f"이마트 테스트 상품 {index}",
                    "raw_price": 1000 + index,
                }
                for index in range(5)
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["records_stored"] == 5
    assert body["ai_batches"] == 3
    assert body["provider_calls"] == 3
    assert body["max_ai_batch_items"] == 2
    assert body["max_ai_batch_prompt_chars"] == 8000


def test_ingest_rejects_more_than_30_records(client: TestClient) -> None:
    records = [
        {
            "raw_record_id": f"r{i}",
            "source_name": "emart",
            "raw_title": f"상품 {i}",
            "raw_price": 1000,
        }
        for i in range(31)
    ]
    res = client.post(
        "/api/ingest/raw-records/label",
        json={"provider_id": "google-dev", "source_name": "emart", "records": records},
    )
    assert res.status_code == 422


def test_ingest_label_handles_realistic_hotdeal_food_records(client: TestClient) -> None:
    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "ppomppu",
            "crawler_name": "ppomppu_hotdeal",
            "schema_type": "hotdeal",
            "records": [
                {
                    "raw_record_id": "hotdeal:tofu-300g",
                    "source_name": "ppomppu",
                    "source_url": "https://ppomppu.example/post/tofu",
                    "raw_title": "[이마트] 풀무원 국산콩 두부 300g 2,990원",
                    "raw_price": 2990,
                    "raw_payload": {"mall": "이마트", "discount": "행사"},
                },
                {
                    "raw_record_id": "hotdeal:meat-600g",
                    "source_name": "ppomppu",
                    "source_url": "https://ppomppu.example/post/meat",
                    "raw_title": "[마트] 국내산 삼겹살 600g 11,880원",
                    "raw_price": 11880,
                    "raw_payload": {"mall": "동네마트", "shipping": "매장픽업"},
                },
            ],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["records_stored"] == 2
    assert body["provider_calls"] == 1
    assert body["proposals_stored"] >= 16

    proposals = client.get("/api/review/proposals").json()["items"]
    values = {(p["target_field"], p["proposed_value"]) for p in proposals}
    assert ("category_id", "fresh.tofu") in values
    assert ("category_id", "fresh.meat") in values
    assert ("keywords", "두부") in values


def test_labeling_response_overrides_emart_100g_hint_with_package_metadata() -> None:
    provider = ai_ingestion._provider_ref(
        ProviderConfigContract(
            provider_id="local",
            provider_kind="gemini",
            display_name="Local",
            default_model="fake",
            secret_alias="NONE",
        )
    )
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id="emart-beef",
            source_name="emart",
            raw_title="[냉장] 한우 불고기1+등급300g",
            raw_price=14850,
            raw_payload={"unit": "100g"},
        )
    ]

    proposals = ai_ingestion.proposals_from_labeling_response(
        batch_id="b-emart",
        provider=provider,
        records=records,
        response={
            "items": [
                {
                    "raw_record_id": "emart-beef",
                    "canonical_name": "한우 불고기",
                    "source_title": "[냉장] 한우 불고기1+등급300g",
                    "sale_price": 14850,
                    "original_price": 19800,
                    "discount_percent": 25,
                    "source_url": "https://emart.example/beef",
                    "image_url": "https://emart.example/beef.jpg",
                    "keywords": ["냉장", "한우", "불고기"],
                    "attributes": {},
                    "package_quantity": 100,
                    "package_unit": "g",
                    "display_unit": "100g",
                    "standard_unit_price": 14850,
                }
            ]
        },
    )
    values = {(p.target_field, p.proposed_value) for p in proposals}

    assert ("package_quantity", 300.0) in values
    assert ("package_unit", "g") in values
    assert ("display_unit", "300g") in values
    assert ("price_per_100g", 4950.0) in values
    assert ("sale_price", 14850) in values
    assert ("original_price", 19800) in values
    assert ("discount_percent", 25) in values
    assert ("source_url", "https://emart.example/beef") in values
    assert ("image_url", "https://emart.example/beef.jpg") in values
    assert ("attributes.storage_type", "chilled") in values
    assert ("attributes.quality_grade", "1+") in values
    assert ("keywords", "냉장") not in values


def test_labeling_response_recomputes_bundle_standard_unit_price() -> None:
    provider = ai_ingestion._provider_ref(
        ProviderConfigContract(
            provider_id="local",
            provider_kind="gemini",
            display_name="Local",
            default_model="fake",
            secret_alias="NONE",
        )
    )
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id="emart-tofu-bundle",
            source_name="emart",
            raw_title="국산콩 촌두부 300g*2",
            raw_price=3136,
            raw_payload={"unit": "100g"},
        )
    ]

    proposals = ai_ingestion.proposals_from_labeling_response(
        batch_id="b-emart-bundle",
        provider=provider,
        records=records,
        response={
            "items": [
                {
                    "raw_record_id": "emart-tofu-bundle",
                    "canonical_name": "국산콩 촌두부",
                    "source_title": "국산콩 촌두부 300g*2",
                    "sale_price": 3136,
                    "package_quantity": 300,
                    "package_unit": "g",
                    "display_unit": "300g×2",
                    "bundle_count": 2,
                    "standard_unit": "kg",
                    "standard_unit_price": 10453.33,
                    "price_per_100g": 522.67,
                }
            ]
        },
    )
    values = {(p.target_field, p.proposed_value) for p in proposals}

    assert ("package_quantity", 300.0) in values
    assert ("package_unit", "g") in values
    assert ("display_unit", "300g×2") in values
    assert ("bundle_count", 2) in values
    assert ("standard_unit", "kg") in values
    assert ("standard_unit_price", 5226.67) in values
    assert ("price_per_100g", 522.67) in values


def test_labeling_response_rejects_zero_count_bundle_title() -> None:
    provider = ai_ingestion._provider_ref(
        ProviderConfigContract(
            provider_id="local",
            provider_kind="gemini",
            display_name="Local",
            default_model="fake",
            secret_alias="NONE",
        )
    )
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id="bad-zero-bundle",
            source_name="emart",
            raw_title="비정상 묶음 300g*0",
            raw_price=3000,
            raw_payload={"unit": "100g"},
        )
    ]

    with pytest.raises(ProviderResponseError) as exc_info:
        ai_ingestion.proposals_from_labeling_response(
            batch_id="b-bad-zero-bundle",
            provider=provider,
            records=records,
            response={
                "items": [
                    {
                        "raw_record_id": "bad-zero-bundle",
                        "canonical_name": "비정상 묶음",
                        "source_title": "비정상 묶음 300g*0",
                        "sale_price": 3000,
                        "package_quantity": 300,
                        "package_unit": "g",
                        "display_unit": "300g",
                        "bundle_count": 0,
                        "standard_unit": "kg",
                        "standard_unit_price": 10000,
                    }
                ]
            },
        )

    assert "bundle_count" in str(exc_info.value)


def test_labeling_response_normalizes_korean_category_id_to_safe_dot_id() -> None:
    provider = ai_ingestion._provider_ref(
        ProviderConfigContract(
            provider_id="local",
            provider_kind="gemini",
            display_name="Local",
            default_model="fake",
            secret_alias="NONE",
        )
    )
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id="emart-frozen-seafood",
            source_name="emart",
            raw_title="냉동 새우살 300g",
            raw_price=6980,
        )
    ]

    proposals = ai_ingestion.proposals_from_labeling_response(
        batch_id="b-category",
        provider=provider,
        records=records,
        response={
            "items": [
                {
                    "raw_record_id": "emart-frozen-seafood",
                    "canonical_name": "냉동 새우살",
                    "category_id": "수산/냉동",
                    "keywords": ["새우"],
                    "aliases": [],
                    "attributes": {},
                }
            ]
        },
    )
    values = {(p.target_field, p.proposed_value) for p in proposals}

    assert ("category_id", "seafood.frozen") in values
    assert ("category_id", "수산/냉동") not in values


def test_ingest_missing_provider_labels_retains_raw_records_for_review(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            return {"items": []}

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: BrokenProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "ppomppu",
            "crawler_name": "ppomppu_hotdeal",
            "schema_type": "hotdeal",
            "records": [
                {
                    "raw_record_id": "hotdeal:tofu-300g",
                    "source_name": "ppomppu",
                    "raw_title": "[이마트] 풀무원 국산콩 두부 300g 2,990원",
                    "raw_price": 2990,
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["records_stored"] == 1
    assert body["proposals_stored"] > 0
    assert body["missing_label_count"] == 0
    assert body["missing_label_raw_record_ids"] == []
    assert body["deterministic_recovery_count"] == 1
    with db.session_scope() as session:
        rows = build_publish_rows(session, batch_id=body["raw_batch_id"])
    assert len(rows) == 1
    assert rows[0]["raw_record_id"] == "hotdeal:tofu-300g"
    assert rows[0]["eligible"] is False
    assert "pending_review: no AI proposals linked to raw record" not in rows[0]["blockers"]


def test_ingest_retries_missing_labels_before_reporting_raw_only(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    sleeps: list[float] = []
    now = [0.0]
    monkeypatch.setattr(ai_ingestion, "_provider_call_history", {})
    monkeypatch.setattr(ai_ingestion, "_monotonic", lambda: now[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(ai_ingestion, "_sleep", fake_sleep)

    class MissingThenRecoveredProvider:
        provider_mode = "live"

        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            record_ids = re.findall(r"- id=([^;]+);", prompt)
            calls.append(record_ids)
            selected = record_ids[:1] if len(calls) == 1 else record_ids
            return {
                "items": [
                    {
                        "raw_record_id": record_id,
                        "canonical_name": "재시도 상품",
                        "category_id": "dairy.milk",
                        "keywords": ["우유"],
                        "aliases": [],
                        "attributes": {},
                        "confidence": 0.8,
                    }
                    for record_id in selected
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: MissingThenRecoveredProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {"raw_record_id": "emart:milk-1", "source_name": "emart", "raw_title": "서울우유 1L", "raw_price": 2980},
                {"raw_record_id": "emart:milk-2", "source_name": "emart", "raw_title": "매일우유 1L", "raw_price": 2880},
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["provider_calls"] == 2
    assert body["missing_label_count"] == 0
    assert calls == [["emart:milk-1", "emart:milk-2"], ["emart:milk-2"]]
    assert any(seconds >= 10 for seconds in sleeps)


def test_ingest_respects_per_request_provider_call_cap_for_missing_label_retries(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(ai_ingestion, "_provider_call_history", {})

    class MissingOneProvider:
        provider_mode = "live"

        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            record_ids = re.findall(r"- id=([^;]+);", prompt)
            calls.append(record_ids)
            return {
                "items": [
                    {
                        "raw_record_id": record_ids[0],
                        "canonical_name": "호출 제한 상품",
                        "category_id": "dairy.milk",
                        "keywords": ["우유"],
                        "aliases": [],
                        "attributes": {},
                    }
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: MissingOneProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "max_provider_calls": 1,
            "records": [
                {"raw_record_id": "emart:milk-1", "source_name": "emart", "raw_title": "서울우유 1L", "raw_price": 2980},
                {"raw_record_id": "emart:milk-2", "source_name": "emart", "raw_title": "매일우유 1L", "raw_price": 2880},
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["provider_calls"] == 1
    assert body["missing_label_count"] == 0
    assert body["missing_label_raw_record_ids"] == []
    assert body["deterministic_recovery_count"] == 1
    assert calls == [["emart:milk-1", "emart:milk-2"]]


def test_live_provider_rate_limits_use_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    now = [0.0]
    config = ProviderConfigContract(
        provider_id="google-dev",
        provider_kind="gemini",
        display_name="Google Dev",
        default_model="gemini-test",
        min_request_interval_seconds=1.0,
        max_provider_calls_per_minute=2,
        max_provider_calls_per_day=10,
    )

    monkeypatch.setattr(ai_ingestion, "_provider_call_history", {})
    monkeypatch.setattr(ai_ingestion, "_monotonic", lambda: now[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    monkeypatch.setattr(ai_ingestion, "_sleep", fake_sleep)

    ai_ingestion._reserve_live_provider_call("google-dev", config)
    ai_ingestion._reserve_live_provider_call("google-dev", config)
    ai_ingestion._reserve_live_provider_call("google-dev", config)

    assert sleeps == [1.0, 59.0]


def test_live_provider_daily_cap_uses_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = ProviderConfigContract(
        provider_id="google-dev",
        provider_kind="gemini",
        display_name="Google Dev",
        default_model="gemini-test",
        max_provider_calls_per_day=1,
    )

    monkeypatch.setattr(ai_ingestion, "_provider_call_history", {})
    monkeypatch.setattr(ai_ingestion, "_monotonic", lambda: 0.0)
    monkeypatch.setattr(ai_ingestion, "_sleep", lambda _seconds: None)

    ai_ingestion._reserve_live_provider_call("google-dev", config)
    with pytest.raises(ai_ingestion.AIIngestionError) as exc_info:
        ai_ingestion._reserve_live_provider_call("google-dev", config)

    assert exc_info.value.stage == "provider_rate_limit"
    assert exc_info.value.status_code == 429


def test_provider_retry_policy_uses_provider_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    config = ProviderConfigContract(
        provider_id="google-dev",
        provider_kind="gemini",
        display_name="Google Dev",
        default_model="gemini-test",
        provider_retry_max_attempts=2,
        provider_retry_min_delay_seconds=2.0,
        provider_retry_max_delay_seconds=2.0,
    )

    class AlwaysTransientProvider:
        provider_mode = "offline"

        def __init__(self) -> None:
            self.config = config
            self.calls = 0

        def call(self, *, prompt: str, schema=None) -> dict:
            self.calls += 1
            raise ProviderResponseError(
                "Google GenAI provider call failed: 503 temporarily unavailable",
                provider_id="google-dev",
                model="gemini-test",
            )

    provider = AlwaysTransientProvider()
    monkeypatch.setattr(ai_ingestion, "_sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(ai_ingestion.AIIngestionError) as exc_info:
        ai_ingestion._call_provider_with_retries(
            provider=provider,
            prompt="prompt",
            schema={},
            provider_id="google-dev",
            model="gemini-test",
            raw_batch_id="raw-1",
            ai_batch_id="ai-1",
            row_count=1,
        )

    assert provider.calls == 2
    assert sleeps == [2.0]
    assert "attempt 2/2" in str(exc_info.value)


def test_provider_call_error_preserves_sanitized_cause_location() -> None:
    config = ProviderConfigContract(
        provider_id="google-dev",
        provider_kind="gemini",
        display_name="Google Dev",
        default_model="gemini-test",
        provider_retry_max_attempts=1,
    )

    class AsciiEncodingFailProvider:
        provider_mode = "offline"

        def __init__(self) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            try:
                "이마트".encode("ascii")
            except UnicodeEncodeError as cause:
                raise ProviderResponseError(
                    "Google GenAI provider call failed: ascii encoding failed",
                    provider_id="google-dev",
                    model="gemini-test",
                    cause=cause,
                ) from cause
            raise AssertionError("expected ascii encoding to fail")

    with pytest.raises(ai_ingestion.AIIngestionError) as exc_info:
        ai_ingestion._call_provider_with_retries(
            provider=AsciiEncodingFailProvider(),
            prompt="prompt",
            schema={},
            provider_id="google-dev",
            model="gemini-test",
            raw_batch_id="raw-1",
            ai_batch_id="ai-1",
            row_count=1,
        )

    detail = exc_info.value.to_detail()
    assert detail["provider_error"]["cause"]["class"] == "UnicodeEncodeError"
    assert detail["provider_error"]["cause"]["location"]["function"] == "call"
    assert "이마트" not in detail["provider_error"]["cause"]["message"]


def test_ingest_provider_call_failure_returns_safe_actionable_502(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            raise ProviderResponseError(
                "Google GenAI provider call failed: quota exhausted for request; key=[REDACTED]",
                provider_id="google-dev",
                model="gemma-4-26b-a4b-it",
            )

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: FailingProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "crawler_name": "emart_sale_crawler",
            "schema_type": "mart_discount",
            "records": [
                {
                    "raw_record_id": "emart:8801111111111",
                    "source_name": "emart",
                    "source_record_key": "8801111111111",
                    "source_url": "https://emart.example/products/8801111111111",
                    "raw_title": "서울우유 나100% 1L 2입",
                    "raw_price": 5980,
                    "raw_payload": {
                        "source": "emart",
                        "name": "서울우유 나100% 1L 2입",
                        "unit": "1L",
                        "quantity": "2개",
                        "category_hint": "우유/유제품",
                        "image_url": "https://emart.example/images/milk.jpg",
                    },
                }
            ],
        },
    )

    assert res.status_code == 502
    detail = res.json()["detail"]
    assert detail["error"] == "ai_ingestion_error"
    assert detail["stage"] == "provider_call"
    assert detail["provider_id"] == "google-dev"
    assert detail["model"] == "gemma-4-26b-a4b-it"
    assert detail["row_count"] == 1
    assert detail["raw_batch_id"].startswith("raw-")
    assert ":ai:" in detail["ai_batch_id"]
    assert "quota exhausted" in detail["message"]
    assert "AIza" not in detail["message"]
    with db.session_scope() as session:
        retained = RawCrawlBatchRepository(session).list_records(detail["raw_batch_id"])
        rows = build_publish_rows(session, batch_id=detail["raw_batch_id"])
    assert len(retained) == 1
    assert retained[0].raw_record_id == "emart:8801111111111"
    assert len(rows) == 1
    assert rows[0]["item"]["sale_price"] == 5980
    assert rows[0]["item"]["source_url"] == "https://emart.example/products/8801111111111"


def test_ingest_retries_transient_provider_failure_without_duplicate_proposals(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_ingestion, "_sleep", lambda _seconds: None)

    class FlakyProvider:
        calls = 0

        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            type(self).calls += 1
            if type(self).calls == 1:
                raise ProviderResponseError(
                    "Google GenAI provider call failed: 503 quota temporarily unavailable",
                    provider_id="google-dev",
                    model="gemma-4-26b-a4b-it",
                )
            record_ids = re.findall(r"- id=([^;]+);", prompt)
            return {
                "items": [
                    {
                        "raw_record_id": record_id,
                        "canonical_name": "이마트 서울우유 나100% 1L 2입",
                        "brand": "서울우유",
                        "category_id": "dairy.milk",
                        "keywords": ["우유"],
                        "aliases": ["서울우유1L"],
                        "attributes": {"source": "emart"},
                        "confidence": 0.9,
                    }
                    for record_id in record_ids
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: FlakyProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "crawler_name": "emart_sale_crawler",
            "schema_type": "mart_discount",
            "records": [
                {
                    "raw_record_id": "emart:milk-1l-2",
                    "source_name": "emart",
                    "source_url": "https://emart.example/products/milk",
                    "raw_title": "서울우유 나100% 1L 2입",
                    "raw_price": 5980,
                    "raw_payload": {"source": "emart", "unit": "1L", "quantity": "2개"},
                }
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["provider_calls"] == 2
    assert FlakyProvider.calls == 2
    assert len(body["proposal_ids"]) == len(set(body["proposal_ids"]))
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
    assert len(proposals) == len(body["proposal_ids"])


def test_ingest_partial_invalid_provider_records_are_actionable(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PartiallyInvalidProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config
            self.calls = 0

        def call(self, *, prompt: str, schema=None) -> dict:
            self.calls += 1
            if self.calls > 1:
                return {"items": []}
            return {
                "items": [
                    {
                        "raw_record_id": "emart:tofu",
                        "canonical_name": "풀무원 두부 300g",
                        "category_id": "fresh.tofu",
                        "keywords": ["두부"],
                        "aliases": [],
                        "attributes": {},
                    },
                    {
                        "raw_record_id": "emart:unknown",
                        "canonical_name": "알 수 없는 상품",
                        "keywords": [],
                    },
                    {
                        "raw_record_id": "emart:extra-hallucinated",
                        "canonical_name": "존재하지 않는 추가 상품",
                        "keywords": ["환각"],
                    },
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: PartiallyInvalidProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "crawler_name": "emart_sale_crawler",
            "schema_type": "mart_discount",
            "records": [
                {
                    "raw_record_id": "emart:tofu",
                    "source_name": "emart",
                    "raw_title": "풀무원 국산콩 두부 300g",
                    "raw_price": 2990,
                },
                {
                    "raw_record_id": "emart:milk",
                    "source_name": "emart",
                    "raw_title": "서울우유 나100% 1L",
                    "raw_price": 2980,
                },
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["records_stored"] == 2
    assert body["missing_label_count"] == 0
    assert body["missing_label_raw_record_ids"] == []
    assert body["deterministic_recovery_count"] == 1
    validation = body["provider_response_validation"]
    assert validation["invalid_response_row_count"] == 2
    assert validation["index_mapping_count"] == 0
    assert {row["raw_record_id"] for row in validation["invalid_response_rows"]} == {
        "emart:unknown",
        "emart:extra-hallucinated",
    }
    assert body["reviewer_retry_candidates"]["missing_label"] == []
    with db.session_scope() as session:
        rows = build_publish_rows(session, batch_id=body["raw_batch_id"])
        proposals = FieldProposalRepository(session).list()
    assert {row["raw_record_id"] for row in rows} == {"emart:tofu", "emart:milk"}
    assert all("unknown" not in proposal.provenance.raw_record_id for proposal in proposals)
    assert all("extra-hallucinated" not in proposal.provenance.raw_record_id for proposal in proposals)


def test_ingest_uses_ascii_raw_record_ids_with_korean_source_evidence(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_prompt = ""

    class AsciiIdProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            nonlocal captured_prompt
            captured_prompt = prompt
            assert "id=이마트:url" not in prompt
            assert "id=emart:url:99663ac53a26b79b" in prompt
            assert "source=이마트" in prompt
            assert "store=이마트" in prompt
            return {
                "items": [
                    {
                        "raw_record_id": "emart:url:99663ac53a26b79b",
                        "canonical_name": "친환경 대추방울토마토 600g",
                        "category_id": "fresh.produce",
                        "keywords": ["방울토마토"],
                        "aliases": [],
                        "attributes": {},
                    },
                    {
                        "raw_record_id": "emart:url:59c6424034aa0e42",
                        "canonical_name": "고산지 사과 1.3kg",
                        "category_id": "fresh.produce",
                        "keywords": ["사과"],
                        "aliases": [],
                        "attributes": {},
                    },
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: AsciiIdProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "이마트",
            "crawler_name": "emart_sale_crawler",
            "schema_type": "mart_discount",
            "records": [
                {
                    "raw_record_id": "emart:url:99663ac53a26b79b",
                    "source_name": "이마트",
                    "raw_title": "친환경 대추방울토마토 600g/팩",
                    "raw_price": 4110,
                    "raw_payload": {"store": "이마트", "detail_url": "https://emart.example/product/100"},
                },
                {
                    "raw_record_id": "emart:url:59c6424034aa0e42",
                    "source_name": "이마트",
                    "raw_title": "고산지 사과 (청송) 1.3kg내외 봉",
                    "raw_price": 12980,
                    "raw_payload": {"store": "이마트", "detail_url": "https://emart.example/product/101"},
                },
            ],
        },
    )

    assert captured_prompt
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    assert body["missing_label_count"] == 0
    validation = body["provider_response_validation"]
    assert validation["invalid_response_row_count"] == 0
    assert validation["index_mapping_count"] == 0
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
    assert proposals
    proposal_raw_ids = {proposal.provenance.raw_record_id for proposal in proposals}
    assert proposal_raw_ids == {
        "emart:url:99663ac53a26b79b",
        "emart:url:59c6424034aa0e42",
    }


def test_ingest_maps_legacy_korean_raw_ids_to_provider_ascii_ids(
    client: TestClient,
    db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LegacyIdProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            assert "id=이마트:url" not in prompt
            assert "id=emart:url:99663ac53a26b79b" in prompt
            assert "source=이마트" in prompt
            return {
                "items": [
                    {
                        "raw_record_id": "emart:url:99663ac53a26b79b",
                        "canonical_name": "친환경 대추방울토마토 600g",
                        "category_id": "fresh.produce",
                        "keywords": ["방울토마토"],
                        "aliases": [],
                        "attributes": {},
                    },
                    {
                        "raw_record_id": "emart:url:59c6424034aa0e42",
                        "canonical_name": "고산지 사과 1.3kg",
                        "category_id": "fresh.produce",
                        "keywords": ["사과"],
                        "aliases": [],
                        "attributes": {},
                    },
                ]
            }

    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: LegacyIdProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "이마트",
            "crawler_name": "emart_sale_crawler",
            "schema_type": "mart_discount",
            "records": [
                {
                    "raw_record_id": "이마트:url:99663ac53a26b79b",
                    "source_name": "이마트",
                    "raw_title": "친환경 대추방울토마토 600g/팩",
                    "raw_price": 4110,
                },
                {
                    "raw_record_id": "이마트:url:59c6424034aa0e42",
                    "source_name": "이마트",
                    "raw_title": "고산지 사과 (청송) 1.3kg내외 봉",
                    "raw_price": 12980,
                },
            ],
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "labeled"
    validation = body["provider_response_validation"]
    assert validation["invalid_response_row_count"] == 0
    assert validation["index_mapping_count"] == 2
    assert validation["index_mappings"][0] == {
        "item_index": 0,
        "original_raw_record_id": "emart:url:99663ac53a26b79b",
        "mapped_raw_record_id": "이마트:url:99663ac53a26b79b",
        "reason": "provider_ascii_id",
    }
    with db.session_scope() as session:
        proposals = FieldProposalRepository(session).list()
    assert proposals
    proposal_raw_ids = {proposal.provenance.raw_record_id for proposal in proposals}
    assert proposal_raw_ids == {
        "이마트:url:99663ac53a26b79b",
        "이마트:url:59c6424034aa0e42",
    }

def test_ingest_error_detail_redacts_secrets_from_provider_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SecretLeakingProvider:
        def __init__(self, config: ProviderConfigContract) -> None:
            self.config = config

        def call(self, *, prompt: str, schema=None) -> dict:
            raise ProviderResponseError(
                f"500 INTERNAL_ERROR authorization=Bearer-secret api_key={FAKE_GOOGLE_KEY}",
                provider_id="google-dev",
                model="gemma-4-26b-a4b-it",
            )

    monkeypatch.setattr(ai_ingestion, "_sleep", lambda _seconds: None)
    monkeypatch.setattr(
        ai_ingestion,
        "provider_from_config",
        lambda config: SecretLeakingProvider(config),
    )

    res = client.post(
        "/api/ingest/raw-records/label",
        json={
            "provider_id": "google-dev",
            "source_name": "emart",
            "records": [
                {
                    "raw_record_id": "emart:snack",
                    "source_name": "emart",
                    "raw_title": "오리온 오징어 땅콩 98g",
                    "raw_price": 1980,
                }
            ],
        },
    )

    assert res.status_code == 502
    serialized = str(res.json())
    assert "INTERNAL_ERROR" in serialized
    assert "AIza" not in serialized
    assert "Bearer-secret" not in serialized


def test_split_records_builds_bounded_prompts_for_realistic_emart_records() -> None:
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id=f"emart:item-{i}",
            source_name="emart",
            source_url=f"https://emart.example/products/{i}",
            raw_title=f"이마트 행사 상품 {i} 300g",
            raw_price=1000 + i,
            raw_payload={"source": "emart", "unit": "100g", "category_hint": "가공식품"},
        )
        for i in range(30)
    ]

    batches = ai_ingestion.split_records_for_ai(records)

    assert sum(len(batch) for batch in batches) == 30
    assert all(len(batch) <= 30 for batch in batches)
    assert all(
        len(ai_ingestion.build_labeling_prompt(batch))
        <= ai_ingestion.MAX_AI_BATCH_PROMPT_CHARS
        for batch in batches
    )


def test_labeling_prompt_excludes_test_sentinel_keywords_from_catalog() -> None:
    records = [
        ai_ingestion.RawCrawlRecord(
            raw_record_id="emart:shrimp",
            source_name="emart",
            source_url="https://emart.example/shrimp",
            raw_title="베트남산 냉동 새우살 300g",
            raw_price=7980,
        )
    ]
    catalog = [
        type("Keyword", (), {"word": "test_auth_keyword_unique_xyz", "synonyms": (), "category_id": None})(),
        type("Keyword", (), {"word": "debug_placeholder_product", "synonyms": ("temp_auth_item",), "category_id": None})(),
        type("Keyword", (), {"word": "새우", "synonyms": ("냉동새우",), "category_id": "seafood.crustacean.shrimp"})(),
    ]

    prompt = ai_ingestion.build_labeling_prompt(records, catalog=catalog)

    assert "test_auth_keyword_unique_xyz" not in prompt
    assert "debug_placeholder_product" not in prompt
    assert "temp_auth_item" not in prompt
    assert "keyword=새우" in prompt


def _load_crawler_ai_export():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = repo_root / "packages" / "crawler-admin" / "backend" / "pipeline" / "ai_export.py"
    spec = importlib.util.spec_from_file_location("crawler_ai_export_for_e2e", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_emart_crawler_batches_ingest_and_persist_ai_proposals(
    client: TestClient,
    db: Database,
) -> None:
    crawler_ai_export = _load_crawler_ai_export()
    items = [
        {
            "product_id": "orion-squid-peanut",
            "name": "오리온 오징어 땅콩 98g",
            "sale_price": "1,980원",
            "detail_url": "https://emart.example/products/orion-squid-peanut",
            "category": "과자",
        },
        *[
            {
                "product_id": f"emart-test-{i}",
                "name": f"이마트 테스트 상품 {i}",
                "sale_price": f"{1000 + i}원",
                "detail_url": f"https://emart.example/products/{i}",
                "category": "테스트",
            }
            for i in range(31)
        ],
    ]
    _, record_batches, skipped = crawler_ai_export.build_raw_batches(
        items,
        source_name="emart",
        crawler_name="emart_crawler",
        schema_type="mart_discount",
        batch_id="raw-emart-e2e",
    )
    assert skipped == 0
    assert [len(records) for records in record_batches] == [30, 2]

    raw_batch_ids = []
    for records in record_batches:
        assert len(records) <= 30
        assert sum(len(record.prompt_text()) for record in records) <= 2000
        response = client.post(
            "/api/ingest/raw-records/label",
            json={
                "provider_id": "google-dev",
                "source_name": "emart",
                "crawler_name": "emart_crawler",
                "schema_type": "mart_discount",
                "records": [record.model_dump(mode="json") for record in records],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["records_stored"] == len(records)
        assert body["proposals_stored"] >= len(records) * 8
        raw_batch_ids.append(body["raw_batch_id"])

    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        persisted_records = [
            record
            for batch_id in raw_batch_ids
            for record in raw_repo.list_records(batch_id)
        ]
    assert len(persisted_records) == 32
    assert any(record.raw_title == "오리온 오징어 땅콩 98g" for record in persisted_records)

    proposals = client.get("/api/review/proposals").json()["items"]
    values = {(p["target_field"], p["proposed_value"]) for p in proposals}
    assert ("category_id", "snack.nut") in values
    assert ("package_unit", "g") in values
    assert ("keywords", "오징어땅콩") in values
