"""검수 큐 라우트 테스트.

shared `ReviewQueueService`의 submit -> start -> approve/correct/reject 흐름을
HTTP 경계에서 검증한다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes.prompts import get_db as prompts_get_db
import api.routes.review as review_routes
from api.routes.review import get_db as review_get_db
from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from core.contracts.control_plane import (
    LearnedKnowledgeContract,
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProductMatchTargetType,
    RawCrawlBatchContract,
)
from storage import (
    Database,
    FieldProposalRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    create_database,
)
from storage.models import AIPublishRecord


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


@pytest.fixture(autouse=True)
def no_real_db_admin_final_approve(monkeypatch) -> None:
    async def fake_preflight():
        return {
            "status": "ready",
            "ready_to_mutate": True,
            "snapshot": {"verified": True, "latest_backup": "test-snapshot.sqlite"},
        }

    async def fake_final_approve(ingestion_id, *, notes=None):
        raise RuntimeError("DB-admin safe final approve not stubbed")

    monkeypatch.setattr(review_routes, "_check_db_admin_mutation_preflight", fake_preflight)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)


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


def _automation_proposal(
    raw_id: str,
    target_field: str,
    value,
    *,
    proposal_type: ProposalType = ProposalType.NORMALIZED_FIELD,
    confidence: float = 0.96,
    alternatives: list[dict] | None = None,
) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"{raw_id}:{target_field}",
        proposal_type=proposal_type,
        target_field=target_field,
        proposed_value=value,
        status=PipelineStatus.AI_PROPOSED,
        provenance=FieldProvenance(
            raw_record_id=raw_id,
            source_field="raw_title",
            evidence_text=f"automation evidence for {raw_id}",
            worker_role=AIWorkerRole.KEYWORD_GENERATOR
            if proposal_type == ProposalType.KEYWORD
            else AIWorkerRole.CLASSIFIER,
            confidence=confidence,
        ),
        alternatives=alternatives or [],
    )


def _seed_automation_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="auto-safe",
            source_name="emart",
            source_url="https://emart.example/products/tofu",
            raw_title="풀무원 국산콩 두부 300g",
            raw_price=2480,
            raw_payload={
                "source_url": "https://emart.example/products/tofu",
                "image_url": "https://emart.example/images/tofu.jpg",
                "unit": "300g",
                "category_id": "processed.tofu.firm",
                "expected_ai": {
                    "canonical_name": "풀무원 국산콩 두부 300g",
                    "category_id": "processed.tofu.firm",
                    "package_unit": "g",
                    "keywords": ["두부"],
                    "price": 2480,
                },
            },
        ),
        RawCrawlRecord(
            raw_record_id="auto-missing-image",
            source_name="emart",
            source_url="https://emart.example/products/milk",
            raw_title="서울우유 1L",
            raw_price=2800,
            raw_payload={
                "source_url": "https://emart.example/products/milk",
                "unit": "1L",
                "category_id": "dairy.milk",
                "expected_ai": {
                    "canonical_name": "서울우유 1L",
                    "category_id": "dairy.milk",
                    "package_unit": "L",
                    "keywords": ["우유"],
                    "price": 2800,
                },
            },
        ),
        RawCrawlRecord(
            raw_record_id="auto-unresolved",
            source_name="emart",
            source_url="https://emart.example/products/ssamjang",
            raw_title="고기쌈장 500g",
            raw_price=3980,
            raw_payload={
                "source_url": "https://emart.example/products/ssamjang",
                "image_url": "https://emart.example/images/ssamjang.jpg",
                "unit": "500g",
                "category_id": "processed.sauce.ssamjang",
                "expected_ai": {
                    "canonical_name": "고기쌈장 500g",
                    "category_id": "processed.sauce.ssamjang",
                    "package_unit": "g",
                    "keywords": ["쌈장"],
                    "price": 3980,
                },
            },
        ),
        RawCrawlRecord(
            raw_record_id="auto-learned",
            source_name="emart",
            source_url="https://emart.example/products/gochujang",
            raw_title="태양초 고추장 500g",
            raw_price=4980,
            raw_payload={
                "source_url": "https://emart.example/products/gochujang",
                "image_url": "https://emart.example/images/gochujang.jpg",
                "unit": "500g",
                "category_id": "processed.sauce.ssamjang",
                "expected_ai": {
                    "canonical_name": "태양초 고추장 500g",
                    "category_id": "processed.sauce.ssamjang",
                    "package_unit": "g",
                    "keywords": ["고추장"],
                    "price": 4980,
                },
            },
        ),
    ]
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save(
            RawCrawlBatchContract(
                batch_id="batch-automation",
                source_name="emart",
                crawler_name="automation-test",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        raw_repo.save_records("batch-automation", records)
        proposal_repo = FieldProposalRepository(session)
        for raw_id, category, keyword in [
            ("auto-safe", "processed.tofu.firm", "두부"),
            ("auto-missing-image", "dairy.milk", "우유"),
            ("auto-unresolved", "processed.sauce.ssamjang", "쌈장"),
            ("auto-learned", "processed.sauce.ssamjang", "고추장"),
        ]:
            keyword_alternatives = (
                [{
                    "word": keyword,
                    "keyword_id": 1,
                    "matched_term": keyword,
                    "category_id": category,
                    "evidence_class": "exact_catalog",
                    "trust_label": "reuse_exact_catalog",
                }]
                if raw_id != "auto-learned"
                else [{
                    "word": keyword,
                    "knowledge_id": "knowledge:gochujang",
                    "matched_term": "태양초고추장",
                    "category_id": category,
                    "evidence_class": "learned_alias",
                    "trust_label": "reuse_learned_alias",
                }]
            )
            for proposal in [
                _automation_proposal(raw_id, "canonical_name", records[[r.raw_record_id for r in records].index(raw_id)].raw_title),
                _automation_proposal(raw_id, "package_unit", "g" if raw_id != "auto-missing-image" else "L"),
                _automation_proposal(raw_id, "category_id", category, proposal_type=ProposalType.CATEGORY),
                _automation_proposal(
                    raw_id,
                    "keywords",
                    keyword,
                    proposal_type=ProposalType.KEYWORD,
                    alternatives=keyword_alternatives,
                ),
            ]:
                proposal_repo.save(proposal)
        LearnedKnowledgeRepository(session).save(
            LearnedKnowledgeContract(
                knowledge_id="knowledge:gochujang",
                knowledge_type="keyword_alias_approved",
                source_name="emart",
                pattern="태양초고추장",
                target_value={"word": "고추장", "category_id": "processed.sauce.ssamjang"},
                positive_examples=["태양초 고추장 500g"],
                success_count=3,
            )
        )
        KeywordProposalRepository(session).save(
            {
                "proposal_id": "keyword:auto-unresolved",
                "proposed_keyword": "쌈장",
                "match_terms": ["쌈장"],
                "triggering_records": [{"raw_record_id": "auto-unresolved"}],
                "status": PipelineStatus.AI_PROPOSED.value,
            }
        )


def _seed_match_card_data(db: Database) -> str:
    record = RawCrawlRecord(
        raw_record_id="match-raw-1",
        source_name="emart",
        source_record_key="sku-tofu-new",
        source_url="https://emart.example/tofu",
        raw_title="풀무원 국산콩 두부 300g",
        raw_price=2980,
        raw_payload={
            "source_id": "emart",
            "signature_key": "emart tofu 300g new",
            "package_signature": "300g",
            "source_product_id": "sku-tofu-new",
            "brand": "풀무원",
        },
    )
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save(
            RawCrawlBatchContract(
                batch_id="batch-match-cards",
                source_name="emart",
                crawler_name="match-card-test",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        raw_repo.save_records("batch-match-cards", [record])
        saved = ProductMatchStoreRepository(session).save(
            ProductMatchContract(
                source_id="emart",
                source_name="emart",
                signature_key="emart tofu 300g",
                target_type=ProductMatchTargetType.SOURCE_LISTING,
                target_id="listing-tofu-300g",
                canonical_product_id="prod-tofu",
                canonical_product_name="풀무원 두부 300g",
                category_id="processed.tofu",
                keywords=["두부"],
                allowed_title_patterns=["풀무원 * 두부 300g"],
                blocked_title_patterns=["풀무원 부침두부 300g"],
                package_signature="300g",
                source_product_id_history=["sku-tofu-old"],
                provenance_source=ProductMatchProvenanceSource.HUMAN,
                status=ProductMatchStatus.APPROVED,
                audit_reason="existing approved match",
                reviewed_by="reviewer-old",
            )
        )
    assert saved.match_id is not None
    return saved.match_id


def test_match_cards_show_operator_friendly_candidate_evidence(
    client: TestClient,
    db: Database,
) -> None:
    match_id = _seed_match_card_data(db)

    res = client.get("/api/review/match-cards?batch_id=batch-match-cards")

    assert res.status_code == 200, res.text
    card = res.json()["items"][0]
    assert card["raw_record"]["raw_record_id"] == "match-raw-1"
    assert card["raw_record"]["raw_title"] == "풀무원 국산콩 두부 300g"
    assert card["raw_record"]["collected_fields"]["brand"] == "풀무원"
    candidate = card["candidates"][0]
    assert candidate["match_id"] == match_id
    assert candidate["target_type"] == "source_listing"
    assert candidate["target_id"] == "listing-tofu-300g"
    assert candidate["package_signature_match"] is True
    assert candidate["allowed_title_pattern_evidence"] == ["풀무원 * 두부 300g"]
    assert candidate["blocked_title_pattern_evidence"] == []
    assert "select_existing_candidate" in card["actions"]
    assert "raw_payload" in card["advanced"]["raw_record"]


def test_match_card_blocked_pattern_evidence_is_visible(
    client: TestClient,
    db: Database,
) -> None:
    _seed_match_card_data(db)
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save_records(
            "batch-match-cards",
            [
                RawCrawlRecord(
                    raw_record_id="match-raw-blocked",
                    source_name="emart",
                    raw_title="풀무원 부침두부 300g",
                    raw_price=3180,
                    raw_payload={
                        "source_id": "emart",
                        "signature_key": "emart tofu blocked",
                        "package_signature": "300g",
                    },
                )
            ],
        )

    res = client.get("/api/review/match-cards?raw_record_id=match-raw-blocked")

    assert res.status_code == 200, res.text
    candidate = res.json()["items"][0]["candidates"][0]
    assert candidate["blocked_title_pattern_evidence"] == ["풀무원 부침두부 300g"]
    assert "blocked title pattern matched" in candidate["reasons"]


def test_match_card_actions_require_audit_reason_and_preserve_it(
    client: TestClient,
    db: Database,
) -> None:
    match_id = _seed_match_card_data(db)

    missing_reason = client.post(
        "/api/review/match-cards/match-raw-1/actions",
        json={
            "action": "select_existing_candidate",
            "reviewer_id": "reviewer-2",
            "target_match_id": match_id,
        },
    )
    assert missing_reason.status_code == 422

    res = client.post(
        "/api/review/match-cards/match-raw-1/actions",
        json={
            "action": "select_existing_candidate",
            "reviewer_id": "reviewer-2",
            "audit_reason": "operator selected source listing after title/package review",
            "target_match_id": match_id,
        },
    )

    assert res.status_code == 200, res.text
    match = res.json()["match"]
    assert match["audit_reason"] == "operator selected source listing after title/package review"
    assert match["reviewed_by"] == "reviewer-2"
    assert match["target_type"] == "source_listing"
    assert match["target_id"] == "listing-tofu-300g"
    assert match["audit_metadata"]["previous_audit_reason"] == "existing approved match"
    assert "풀무원 국산콩 두부 300g" in match["allowed_title_patterns"]


def test_match_card_add_allowed_and_blocked_patterns_keep_audit(
    client: TestClient,
    db: Database,
) -> None:
    match_id = _seed_match_card_data(db)

    allowed = client.post(
        "/api/review/match-cards/match-raw-1/actions",
        json={
            "action": "add_allowed_title_pattern",
            "reviewer_id": "reviewer-3",
            "audit_reason": "allow exact collected title for tofu listing",
            "target_match_id": match_id,
            "allowed_title_pattern": "풀무원 국산콩 두부 300g",
        },
    )
    assert allowed.status_code == 200, allowed.text
    allowed_match = allowed.json()["match"]
    assert allowed_match["audit_reason"] == "allow exact collected title for tofu listing"
    assert "풀무원 국산콩 두부 300g" in allowed_match["allowed_title_patterns"]
    assert allowed_match["audit_metadata"]["previous_audit_reason"] == "existing approved match"

    blocked = client.post(
        "/api/review/match-cards/match-raw-1/actions",
        json={
            "action": "add_blocked_title_pattern",
            "reviewer_id": "reviewer-3",
            "audit_reason": "block pan-fry tofu variant from soft tofu listing",
            "target_match_id": match_id,
            "blocked_title_pattern": "풀무원 부침두부 300g",
        },
    )
    assert blocked.status_code == 200, blocked.text
    blocked_match = blocked.json()["match"]
    assert blocked_match["audit_reason"] == "block pan-fry tofu variant from soft tofu listing"
    assert "풀무원 부침두부 300g" in blocked_match["blocked_title_patterns"]
    assert blocked_match["audit_metadata"]["previous_audit_reason"] == "allow exact collected title for tofu listing"


def _seed_raw_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="raw-good",
            source_name="emart",
            raw_title="오리온 오징어 땅콩 98g",
            raw_price=1980,
            source_url="https://emart.example/products/squid-peanut",
            raw_payload={
                "image_url": "https://emart.example/images/squid-peanut.jpg",
                "original_price": 2480,
                "sale_price": 1980,
                "discount_percent": 20,
                "source_url": "https://emart.example/products/squid-peanut",
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


def _seed_quality_audit_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="qa-good-chilled-pork",
            source_name="emart",
            raw_title="국내산 냉장 삼겹살 500g",
            raw_price=9900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "국내산 냉장 삼겹살 500g",
                    "category_id": "meat.pork",
                    "package_unit": "g",
                    "keywords": ["삼겹살"],
                    "price": 9900,
                    "attributes": {"storage_type": "냉장"},
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-price-wrong",
            source_name="emart",
            raw_title="서울우유 1L",
            raw_price=2800,
            source_url="https://emart.example/products/milk",
            raw_payload={
                "image_url": "https://emart.example/images/milk.jpg",
                "original_price": 3500,
                "sale_price": 2800,
                "discount_percent": 20,
                "source_url": "https://emart.example/products/milk",
                "expected_ai": {
                    "canonical_name": "서울우유 1L",
                    "category_id": "dairy.milk",
                    "package_unit": "L",
                    "keywords": ["서울우유", "우유"],
                    "price": 2800,
                    "storage_type": "냉장",
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-snack-seafood-confused",
            source_name="emart",
            raw_title="오리온 오징어땅콩 98g",
            raw_price=1980,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "오리온 오징어땅콩 98g",
                    "category_id": "snack.nut",
                    "package_unit": "g",
                    "keywords": ["오징어땅콩", "과자"],
                    "price": 1980,
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-frozen-seafood-missing-storage",
            source_name="emart",
            raw_title="냉동 손질 오징어 500g",
            raw_price=7900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "냉동 손질 오징어 500g",
                    "category_id": "seafood.squid",
                    "package_unit": "g",
                    "keywords": ["오징어"],
                    "price": 7900,
                    "storage_type": "냉동",
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-keyword-category-wrong",
            source_name="emart",
            raw_title="제주 감귤 1.5kg",
            raw_price=12900,
            raw_payload={
                "expected_ai": {
                    "canonical_name": "제주 감귤 1.5kg",
                    "category_id": "fruit.citrus",
                    "package_unit": "kg",
                    "keywords": ["감귤"],
                    "price": 12900,
                    "attributes": {"storage_type": "fresh"},
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="qa-missing-product",
            source_name="emart",
            raw_title="풀무원 국산콩 두부 300g",
            raw_price=3480,
        ),
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-quality-audit",
                source_name="emart",
                crawler_name="seeded-quality-audit",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-quality-audit", records)


def _seed_publish_batch(db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="pub-1",
            source_name="emart",
            source_url="https://emart.example/products/pub-1",
            raw_title="오리온 오징어땅콩 98g",
            raw_price=1980,
            raw_payload={
                "source_url": "https://emart.example/products/pub-1",
                "image_url": "https://emart.example/images/pub-1.jpg",
                "original_price": 2480,
                "discount_percent": 20,
                "expected_ai": {
                    "canonical_name": "오리온 오징어땅콩 98g",
                    "category_id": "snack.nut",
                    "package_unit": "g",
                    "keywords": ["오징어땅콩"],
                    "price": 1980,
                    "storage_type": "상온",
                }
            },
        ),
        RawCrawlRecord(
            raw_record_id="pub-2",
            source_name="emart",
            source_url="https://emart.example/products/pub-2",
            raw_title="서울우유 1L",
            raw_price=2800,
            raw_payload={
                "source_url": "https://emart.example/products/pub-2",
                "image_url": "https://emart.example/images/pub-2.jpg",
                "original_price": 3200,
                "discount_percent": 12,
                "expected_ai": {
                    "canonical_name": "서울우유 1L",
                    "category_id": "dairy.milk",
                    "package_unit": "L",
                    "keywords": ["서울우유"],
                    "price": 2800,
                    "storage_type": "냉장",
                }
            },
        ),
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-publish",
                source_name="emart",
                crawler_name="seeded-publish",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-publish", records)


def _approve_publish_proposals(client: TestClient, raw_id: str, *, approve_keyword: bool = True) -> None:
    values = [
        ("name", "canonical_name", "오리온 오징어땅콩 98g" if raw_id == "pub-1" else "서울우유 1L", "normalized_field"),
        ("category", "category_id", "snack.nut" if raw_id == "pub-1" else "dairy.milk", "category"),
        ("unit", "package_unit", "g" if raw_id == "pub-1" else "L", "normalized_field"),
        ("price", "sale_price", 1980 if raw_id == "pub-1" else 2800, "normalized_field"),
        ("keyword", "keywords", ["오징어땅콩"] if raw_id == "pub-1" else ["서울우유"], "keyword"),
    ]
    values.append(("storage", "attributes.storage_type", "상온" if raw_id == "pub-1" else "냉장", "attribute_value"))
    for suffix, target, value, proposal_type in values:
        proposal_id = f"{raw_id}-{suffix}"
        res = client.post(
            "/api/review/proposals",
            json=_proposal_for_record(
                proposal_id,
                raw_id,
                target,
                value,
                proposal_type=proposal_type,
            ),
        )
        assert res.status_code == 201, res.text
        if proposal_type != "keyword" or approve_keyword:
            approved = client.post(
                f"/api/review/proposals/{proposal_id}/approve",
                json={"reviewer_id": "lucy"},
            )
            assert approved.status_code == 200, approved.text


def _quality_gate_raw_payload(index: int, name: str, price: int) -> dict:
    return {
        "expected_ai": {
            "canonical_name": name,
            "category_id": "snack.general",
            "package_unit": "개",
            "keywords": [f"테스트 상품 {index}"],
            "price": price,
            "storage_type": "상온",
        },
        "source_url": f"https://emart.example/items/{index}",
        "image_url": f"https://emart.example/images/{index}.jpg",
        "original_price": price + 500,
        "discount_percent": 10,
        "unit": "1개",
        "display_unit": "1개",
        "package_quantity": 1,
        "package_unit": "개",
        "store": "emart",
    }


def _seed_partial_quality_gate_batch(client: TestClient, db: Database) -> None:
    records = [
        RawCrawlRecord(
            raw_record_id=f"gate-{idx}",
            source_name="emart",
            source_url=f"https://emart.example/items/{idx}",
            raw_title=f"테스트 상품 {idx}",
            raw_price=1000 + idx,
            raw_payload=_quality_gate_raw_payload(idx, f"테스트 상품 {idx}", 1000 + idx),
        )
        for idx in range(1, 6)
    ]
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-quality-gate-partial",
                source_name="emart",
                crawler_name="seeded-quality-gate",
                item_count=len(records),
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records("batch-quality-gate-partial", records)

    approved_values = [
        ("name", "canonical_name", "테스트 상품 1", "normalized_field"),
        ("category", "category_id", "snack.general", "category"),
        ("unit", "package_unit", "개", "normalized_field"),
        ("price", "sale_price", 1001, "normalized_field"),
        ("keyword", "keywords", ["테스트 상품 1"], "keyword"),
        ("storage", "attributes.storage_type", "상온", "attribute_value"),
    ]
    for suffix, target, value, proposal_type in approved_values:
        proposal_id = f"gate-1-{suffix}"
        res = client.post(
            "/api/review/proposals",
            json=_proposal_for_record(
                proposal_id,
                "gate-1",
                target,
                value,
                proposal_type=proposal_type,
            ),
        )
        assert res.status_code == 201, res.text
        approved = client.post(
            f"/api/review/proposals/{proposal_id}/approve",
            json={"reviewer_id": "qa"},
        )
        assert approved.status_code == 200, approved.text

    pending_fields = [
        ("canonical_name", "normalized_field"),
        ("category_id", "category"),
        ("package_unit", "normalized_field"),
        ("sale_price", "normalized_field"),
        ("keywords", "keyword"),
        ("attributes.storage_type", "attribute_value"),
        ("image_url", "normalized_field"),
        ("source_url", "normalized_field"),
        ("discount_percent", "normalized_field"),
    ]
    created = 0
    for raw_idx in range(2, 6):
        limit = 8 if raw_idx in {2, 3} else 9
        for field, proposal_type in pending_fields[:limit]:
            created += 1
            value = [f"테스트{raw_idx}"] if field == "keywords" else (
                1000 + raw_idx if field == "sale_price" else records[raw_idx - 1].raw_payload.get(field, field)
            )
            res = client.post(
                "/api/review/proposals",
                json=_proposal_for_record(
                    f"gate-{raw_idx}-pending-{created}",
                    f"gate-{raw_idx}",
                    field,
                    value,
                    proposal_type=proposal_type,
                ),
            )
            assert res.status_code == 201, res.text
    assert created == 34

    with db.session_scope() as session:
        keyword_repo = KeywordProposalRepository(session)
        for idx in range(7):
            raw_idx = 2 + (idx % 4)
            keyword_repo.save({
                "proposal_id": f"gate-keyword-{idx}",
                "proposed_keyword": f"미해결키워드{idx}",
                "match_terms": [f"테스트{raw_idx}"],
                "category_suggestion": "snack.general",
                "confidence": 0.7,
                "reason": "quality gate regression fixture",
                "triggering_records": [
                    {"raw_record_id": f"gate-{raw_idx}", "raw_title": f"테스트 상품 {raw_idx}"}
                ],
                "source_values": [f"테스트 상품 {raw_idx}"],
                "status": PipelineStatus.AI_PROPOSED.value,
            })


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


def test_publish_eligibility_allows_unapproved_keywords_with_audit_flags(client: TestClient, db: Database) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    _approve_publish_proposals(client, "pub-2", approve_keyword=False)

    res = client.get("/api/review/publish-eligibility")
    assert res.status_code == 200, res.text
    rows = {row["raw_record_id"]: row for row in res.json()["items"]}
    assert rows["pub-1"]["eligible"] is True
    assert rows["pub-1"]["status"] == "approved"
    assert rows["pub-2"]["eligible"] is True
    assert not rows["pub-2"]["blockers"]
    assert any(flag["code"] == "ai_suggested_keywords" for flag in rows["pub-2"]["post_publish_audit_flags"])


def test_batch_anomaly_audit_endpoint_is_admin_read_only(client: TestClient, db: Database) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")

    res = client.get("/api/review/batch-anomaly-audit", params={"batch_id": "batch-publish"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "ready_or_published"
    assert body["batch_id"] == "batch-publish"
    assert "review_queue" in body

    invalid = client.get("/api/review/batch-anomaly-audit", params={"stale_days": 0})
    assert invalid.status_code == 400


def test_publish_eligibility_marks_partial_batch_not_safe_with_unresolved_counts(
    client: TestClient, db: Database
) -> None:
    _seed_partial_quality_gate_batch(client, db)

    res = client.get(
        "/api/review/publish-eligibility",
        params={"batch_id": "batch-quality-gate-partial"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    summary = body["summary"]
    rows = {row["raw_record_id"]: row for row in body["items"]}

    assert summary["raw_count"] == 5
    assert summary["ai_record_count"] == 5
    assert summary["eligible_count"] == 1
    assert summary["blocked_count"] == 4
    assert summary["held_count"] == 4
    assert summary["field_proposal_count"] == 40
    assert summary["unresolved_field_proposal_count"] == 26
    assert summary["unresolved_relaxed_field_proposal_count"] == 8
    assert summary["keyword_proposal_count"] == 7
    assert summary["unresolved_keyword_proposal_count"] == 7
    assert summary["batch_status"] == "partial_only"
    assert "배치 전체 발행은 안전하지 않습니다" in summary["quality_verdict"]
    assert rows["gate-1"]["eligible"] is True
    assert [row["raw_record_id"] for row in summary["approved_rows"]] == ["gate-1"]
    assert [row["raw_record_id"] for row in body["approved_rows"]] == ["gate-1"]
    assert len(summary["held_rows"]) == 4
    assert body["safety"]["status"] == "operator_final_approval_required"
    assert body["safety"]["approved_rows_visible"] == 1
    assert body["safety"]["held_rows_visible"] == 4
    assert all(rows[f"gate-{idx}"]["eligible"] is False for idx in range(2, 6))
    blocker_codes = {blocker["code"] for blocker in summary["blockers"]}
    assert {"unresolved_field_proposals", "unresolved_keyword_proposals", "blocked_rows"} <= blocker_codes


def test_operator_dashboard_summary_aggregates_counts_blockers_and_anomaly_buckets_read_only(
    client: TestClient, db: Database
) -> None:
    _seed_partial_quality_gate_batch(client, db)
    with db.session_scope() as session:
        before_publish_records = session.query(AIPublishRecord).count()

    res = client.get(
        "/api/review/operator-dashboard-summary",
        params={"batch_id": "batch-quality-gate-partial"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["read_only"] is True
    stats = body["stats"]
    assert stats["raw_count"] == 5
    assert stats["ai_record_count"] == 5
    assert stats["eligible_count"] == 1
    assert stats["blocked_count"] == 4
    assert stats["batch_status"] == "partial_only"

    blocker_buckets = {bucket["code"]: bucket for bucket in body["blocker_buckets"]}
    assert blocker_buckets["unresolved_field_proposals"]["count"] == 26
    assert blocker_buckets["unresolved_keyword_proposals"]["count"] == 7
    assert blocker_buckets["blocked_rows"]["count"] == 4
    assert set(body["publish_blocker_counts_by_reason"])
    assert [row["raw_record_id"] for row in body["publish_blockers"]] == [
        "gate-2",
        "gate-3",
        "gate-4",
        "gate-5",
    ]
    assert [row["raw_record_id"] for row in body["approved_rows"]] == ["gate-1"]
    assert body["approved_rows"][0]["db_handoff_mode"] == "ai_safe_final_approve"
    assert all(row["blockers"] for row in body["publish_blockers"])

    anomaly_buckets = {bucket["code"]: bucket for bucket in body["anomaly_buckets"]}
    assert anomaly_buckets["new_keyword_proposals"]["count"] == 4
    assert body["anomaly_summary"]["suspicious_row_count"] == 5
    assert body["anomaly_summary"]["mode"] == "report_only_non_destructive"

    with db.session_scope() as session:
        after_publish_records = session.query(AIPublishRecord).count()
    assert after_publish_records == before_publish_records


def test_publish_success_marks_row_pending_db_review_not_published(client: TestClient, db: Database, monkeypatch) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")

    calls = []
    final_calls = []
    events = []

    async def fake_preflight():
        events.append("preflight")
        return {
            "status": "ready",
            "ready_to_mutate": True,
            "snapshot": {"verified": True, "latest_backup": "test-snapshot.sqlite"},
        }

    async def fake_submit(payload):
        events.append("submit")
        calls.append(payload)
        return {"id": 777, "status": "pending", "quality_score": 100}

    async def fake_final_approve(ingestion_id, *, notes=None):
        events.append("final_approve")
        final_calls.append({"ingestion_id": ingestion_id, "notes": notes})
        return {
            "id": int(ingestion_id),
            "status": "approved",
            "saved": 1,
            "public_db_verification": {"verified": True, "verified_count": 1, "expected_count": 1},
            "rollback_supported": True,
            "re_review_supported": True,
            "operator_next_action": "rollback or re-review if audit fails",
        }

    monkeypatch.setattr(review_routes, "_check_db_admin_mutation_preflight", fake_preflight)
    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 1
    assert res.json()["ai_safe_final_approved"] == 1
    assert res.json()["public_db_verified"] == 1
    assert res.json()["rollback_re_review_supported"] == 1
    assert res.json()["submitted_to_db_admin"] == 1
    assert res.json()["pending_db_review"] == 0
    assert res.json()["safety"]["status"] == "operator_final_approval_required"
    assert "ai-safe-final-approve" in res.json()["safety"]["notice"]
    assert events == ["preflight", "submit", "final_approve"]
    assert calls[0]["items"][0]["raw_record_id"] == "pub-1"
    assert final_calls[0]["ingestion_id"] == 777

    rows = {
        row["raw_record_id"]: row
        for row in client.get("/api/review/publish-eligibility").json()["items"]
    }
    assert rows["pub-1"]["status"] == "published"
    assert rows["pub-1"]["eligible"] is False
    assert rows["pub-1"]["db_ingestion_result"]["one_final_action"] is True
    assert rows["pub-1"]["db_ingestion_id"] == "777"
    detail = client.get("/api/review/proposals/pub-1-name").json()
    assert detail["proposal"]["status"] == "approved"

    blocked_retry = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert blocked_retry.status_code == 200, blocked_retry.text
    retry_body = blocked_retry.json()
    assert retry_body["published"] == 0
    assert retry_body["failed"] == 1
    assert retry_body["results"][0]["status"] == "published"
    assert "DB-admin/public DB flow already accepted" in retry_body["results"][0]["error"]


def test_publish_blocks_ai_safe_mutation_when_preflight_lacks_backup(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    submit_calls = []
    final_calls = []

    async def fake_preflight():
        return {
            "status": "blocked",
            "ready_to_mutate": False,
            "readiness": {"status": "ready"},
            "snapshot": {"verified": False, "latest_backup": None},
            "error": {"class": "SnapshotMissing", "message": "No DB-admin backup was listed"},
        }

    async def fake_submit(payload):
        submit_calls.append(payload)
        return {"id": 778, "status": "pending"}

    async def fake_final_approve(ingestion_id, *, notes=None):
        final_calls.append(ingestion_id)
        return {"id": int(ingestion_id), "status": "approved"}

    monkeypatch.setattr(review_routes, "_check_db_admin_mutation_preflight", fake_preflight)
    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)

    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 0
    assert body["submitted_to_db_admin"] == 0
    assert body["final_approve_failed"] == 1
    assert body["safety"]["mutation_preflight"]["snapshot"]["verified"] is False
    assert "rollback backup" in body["results"][0]["error"]
    assert submit_calls == []
    assert final_calls == []
    row = client.get("/api/review/publish-eligibility").json()["items"][0]
    assert row["status"] == "publish_failed"
    assert row["retryable"] is True


def test_publish_final_approve_without_public_verification_stays_pending_db_review(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")

    async def fake_submit(payload):
        return {"id": 778, "status": "pending"}

    async def fake_final_approve(ingestion_id, *, notes=None):
        return {"id": int(ingestion_id), "status": "approved", "saved": 1}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)

    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 0
    assert body["pending_db_review"] == 1
    assert body["public_db_verified"] == 0
    assert "public DB verification" in body["results"][0]["final_approve_error"]


def test_publish_skips_final_approve_if_submit_does_not_retain_pending_status(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    final_calls = []

    async def fake_submit(payload):
        return {"id": 779, "status": "approved", "saved": 1}

    async def fake_final_approve(ingestion_id, *, notes=None):
        final_calls.append(ingestion_id)
        return {"id": ingestion_id, "status": "approved"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)

    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 0
    assert body["pending_db_review"] == 1
    assert body["final_approve_failed"] == 1
    assert final_calls == []
    assert "silent DB mutation" in body["results"][0]["final_approve_error"]
    row = client.get("/api/review/publish-eligibility").json()["items"][0]
    assert row["status"] == "pending_db_review"
    assert row["db_ingestion_result"]["requires_db_admin_review"] is True


def test_publish_safe_final_approve_failure_leaves_visible_db_review_handoff(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")

    async def fake_submit(payload):
        return {"id": 778, "status": "pending"}

    async def fake_final_approve(ingestion_id, *, notes=None):
        raise RuntimeError("DB-admin safe-final validation rejected")

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)

    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 0
    assert body["pending_db_review"] == 1
    assert body["final_approve_failed"] == 1
    result = body["results"][0]
    assert result["status"] == "pending_db_review"
    assert result["requires_db_admin_review"] is True
    assert "safe-final validation rejected" in result["final_approve_error"]
    row = client.get("/api/review/publish-eligibility").json()["items"][0]
    assert row["status"] == "pending_db_review"
    assert "safe-final validation rejected" in row["last_error"]
    assert row["db_ingestion_result"]["requires_db_admin_review"] is True


def test_publish_one_click_submits_eligible_rows_and_reports_selected_holds(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 781, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1", "pub-2"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["submitted_to_db_admin"] == 1
    assert body["failed"] == 1
    assert len(calls) == 1
    results = {result["raw_record_id"]: result for result in body["results"]}
    assert results["pub-1"]["status"] == "pending_db_review"
    assert results["pub-2"]["status"] == "pending_review"


def test_publish_api_submits_price_observation_without_discount_claim(
    client: TestClient, db: Database, monkeypatch
) -> None:
    raw_id = "emart-cabbage-current-price"
    raw_payload = {
        "source": "emart",
        "store": "이마트",
        "name": "한끼 양배추 800g 통",
        "unit": "800g",
        "category_id": "vegetable.cabbage",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "sale_price": 2784,
        "source_url": "https://emart.example/products/cabbage-current",
    }
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-price-observation",
                source_name="emart",
                crawler_name="seeded-price-observation",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records(
            "batch-price-observation",
            [
                RawCrawlRecord(
                    raw_record_id=raw_id,
                    source_name="emart",
                    source_record_key="cabbage-current",
                    source_url=raw_payload["source_url"],
                    raw_title=raw_payload["name"],
                    raw_price=2784,
                    raw_payload=raw_payload,
                )
            ],
        )

    proposals = [
        _proposal_for_record("obs-name", raw_id, "canonical_name", "한끼 양배추 800g 통"),
        _proposal_for_record("obs-cat", raw_id, "category_id", "vegetable.cabbage", proposal_type="category"),
        _proposal_for_record("obs-unit", raw_id, "package_unit", "800g"),
        _proposal_for_record("obs-price", raw_id, "sale_price", 2784),
        _proposal_for_record("obs-kw", raw_id, "keywords", ["양배추"], proposal_type="keyword"),
        _proposal_for_record("obs-storage", raw_id, "attributes.storage_type", "냉장", proposal_type="attribute_value"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text
        approved = client.post(
            f"/api/review/proposals/{proposal['proposal_id']}/approve",
            json={"reviewer_id": "lucy"},
        )
        assert approved.status_code == 200, approved.text

    eligibility = client.get(
        "/api/review/publish-eligibility",
        params={"batch_id": "batch-price-observation"},
    )
    assert eligibility.status_code == 200, eligibility.text
    row = eligibility.json()["items"][0]
    assert row["eligible"] is True
    assert row["publication_kind"] == "price_observation"
    assert row["discount_claim_status"] == "hotdeal_claim_blocked"

    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 780, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": [raw_id], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    item = calls[0]["items"][0]
    assert item["publication_kind"] == "price_observation"
    assert item["price_observation_only"] is True
    assert item["discount_claim_status"] == "hotdeal_claim_blocked"
    assert item["claim_basis"] == "current_price_observation"
    assert item["original_price"] is None
    assert item["discount_percent"] is None
    assert item["sale_price"] == 2784
    assert item["source_url"] == raw_payload["source_url"]
    assert item["observed_at"]
    assert item["raw_data"]["publication"]["discount_claim_status"] == "hotdeal_claim_blocked"


def test_emart_cabbage_publish_payload_preserves_offer_metadata(
    client: TestClient, db: Database, monkeypatch
) -> None:
    raw_id = "emart-cabbage-800g"
    raw_payload = {
        "source": "emart",
        "store": "이마트",
        "name": "한끼 양배추 800g 통",
        "unit": "800g",
        "category_id": "vegetable.cabbage",
        "category": "채소",
        "storage_type": "냉장",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "original_price": 3480,
        "sale_price": 2784,
        "discount_percent": 20,
        "event_name": "e머니 20% 할인",
        "source_url": "https://emart.example/products/cabbage",
        "valid_from": "2026-04-01T00:00:00",
        "valid_to": "2026-04-07T00:00:00",
    }
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-cabbage",
                source_name="emart",
                crawler_name="seeded-cabbage",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records(
            "batch-cabbage",
            [
                RawCrawlRecord(
                    raw_record_id=raw_id,
                    source_name="emart",
                    source_record_key="cabbage",
                    source_url=raw_payload["source_url"],
                    raw_title="한끼 양배추 800g 통",
                    raw_price=2784,
                    raw_payload=raw_payload,
                )
            ],
        )

    proposals = [
        _proposal_for_record("cabbage-name", raw_id, "canonical_name", "한끼 양배추 800g 통"),
        _proposal_for_record("cabbage-cat", raw_id, "category_id", "vegetable.cabbage", proposal_type="category"),
        _proposal_for_record("cabbage-unit", raw_id, "package_unit", "800g"),
        _proposal_for_record("cabbage-price", raw_id, "sale_price", 2784),
        _proposal_for_record("cabbage-kw", raw_id, "keywords", ["양배추"], proposal_type="keyword"),
        _proposal_for_record("cabbage-storage", raw_id, "attributes.storage_type", "냉장", proposal_type="attribute_value"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text
        approved = client.post(
            f"/api/review/proposals/{proposal['proposal_id']}/approve",
            json={"reviewer_id": "lucy"},
        )
        assert approved.status_code == 200, approved.text

    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 778, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": [raw_id], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 0
    assert res.json()["submitted_to_db_admin"] == 1
    item = calls[0]["items"][0]
    assert item["name"] == "한끼 양배추 800g 통"
    assert item["image_url"] == raw_payload["image_url"]
    assert item["original_price"] == 3480
    assert item["sale_price"] == 2784
    assert item["discount_percent"] == 20
    assert item["event_name"] == raw_payload["event_name"]
    assert item["source_url"] == raw_payload["source_url"]
    assert item["display_unit"] == "800g"
    assert item["package_quantity"] == 800
    assert item["package_unit"] == "g"
    assert item["price_per_100g"] == 348
    assert item["category_id"] == "vegetable.cabbage"
    assert item["keywords"] == ["양배추"]
    assert item["attributes"]["storage_type"] == "냉장"
    assert item["ai_review_audit"]["raw_record_id"] == raw_id
    assert set(item["ai_review_audit"]["proposal_ids"]) == {
        proposal["proposal_id"] for proposal in proposals
    }
    assert item["raw_data"]["raw_evidence"]["raw_title"] == raw_payload["name"]
    assert item["raw_data"]["raw_evidence"]["raw_price"] == raw_payload["sale_price"]
    assert item["raw_data"]["raw_payload"]["original_price"] == 3480
    assert item["raw_data"]["raw_payload"]["source_url"] == raw_payload["source_url"]
    assert item["raw_data"]["raw_payload"]["image_url"] == raw_payload["image_url"]
    assert item["raw_data"]["display_unit"] == "800g"


def test_emart_publish_payload_keeps_pack_unit_when_raw_unit_is_100g_reference(
    client: TestClient, db: Database, monkeypatch
) -> None:
    raw_id = "emart-hanwoo-bulgogi-300g"
    raw_payload = {
        "source": "emart",
        "store": "이마트",
        "name": "[냉장] 한우 불고기1+등급300g",
        "unit": "100g",
        "category_id": "meat.beef.bulgogi",
        "image_url": "https://emart.example/images/beef.jpg",
        "original_price": 19800,
        "sale_price": 14850,
        "discount_percent": 25,
        "source_url": "https://emart.example/products/beef",
    }
    with db.session_scope() as session:
        repo = RawCrawlBatchRepository(session)
        repo.save(
            RawCrawlBatchContract(
                batch_id="batch-beef",
                source_name="emart",
                crawler_name="seeded-beef",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        repo.save_records(
            "batch-beef",
            [
                RawCrawlRecord(
                    raw_record_id=raw_id,
                    source_name="emart",
                    source_record_key="beef",
                    source_url=raw_payload["source_url"],
                    raw_title=raw_payload["name"],
                    raw_price=14850,
                    raw_payload=raw_payload,
                )
            ],
        )

    proposals = [
        _proposal_for_record("beef-name", raw_id, "canonical_name", "한우 불고기"),
        _proposal_for_record("beef-cat", raw_id, "category_id", "meat.beef.bulgogi", proposal_type="category"),
        _proposal_for_record("beef-unit", raw_id, "package_unit", "g"),
        _proposal_for_record("beef-qty", raw_id, "package_quantity", 300),
        _proposal_for_record("beef-display", raw_id, "display_unit", "300g"),
        _proposal_for_record("beef-price", raw_id, "sale_price", 14850),
        _proposal_for_record("beef-kw", raw_id, "keywords", ["한우", "불고기"], proposal_type="keyword"),
        _proposal_for_record("beef-storage", raw_id, "attributes.storage_type", "chilled", proposal_type="attribute_value"),
    ]
    for proposal in proposals:
        assert client.post("/api/review/proposals", json=proposal).status_code == 201
        approved = client.post(
            f"/api/review/proposals/{proposal['proposal_id']}/approve",
            json={"reviewer_id": "lucy"},
        )
        assert approved.status_code == 200, approved.text

    calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 779, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": [raw_id], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    item = calls[0]["items"][0]
    assert item["name"] == "한우 불고기"
    assert item["raw_unit"] == "100g"
    assert item["unit"] == "300g"
    assert item["display_unit"] == "300g"
    assert item["package_quantity"] == 300
    assert item["package_unit"] == "g"
    assert item["price_per_100g"] == 4950
    assert item["raw_data"]["raw_payload"]["unit"] == "100g"
    assert item["raw_data"]["display_unit"] == "300g"


def test_publish_partial_failure_keeps_retryable_error(client: TestClient, db: Database, monkeypatch) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    _approve_publish_proposals(client, "pub-2")

    async def fake_submit(payload):
        raw_id = payload["items"][0]["raw_record_id"]
        if raw_id == "pub-2":
            raise RuntimeError("DB-admin validation failed")
        return {"id": 700, "status": "pending"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={
            "raw_record_ids": ["pub-1", "pub-2"],
            "reviewer_id": "lucy",
            "confirm_count": 2,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 0
    assert body["submitted_to_db_admin"] == 1
    assert body["failed"] == 1
    rows = {
        row["raw_record_id"]: row
        for row in client.get("/api/review/publish-eligibility").json()["items"]
    }
    assert rows["pub-1"]["status"] == "pending_db_review"
    assert rows["pub-2"]["status"] == "publish_failed"
    assert rows["pub-2"]["retryable"] is True
    assert "DB-admin validation failed" in rows["pub-2"]["last_error"]


def test_publish_missing_api_key_marks_row_retryable_without_admin_password_defaults(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    monkeypatch.delenv("DB_ADMIN_API_KEY", raising=False)
    monkeypatch.setattr("providers.secret_resolver.DEFAULT_ENV_PATHS", tuple())

    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["published"] == 0
    assert body["failed"] == 1
    assert "DB_ADMIN_API_KEY" in body["results"][0]["error"]
    assert "password" not in body["results"][0]["error"].lower()
    rows = {
        row["raw_record_id"]: row
        for row in client.get("/api/review/publish-eligibility").json()["items"]
    }
    assert rows["pub-1"]["status"] == "publish_failed"
    assert rows["pub-1"]["retryable"] is True


def test_publish_retry_reuses_existing_db_ingestion_without_duplicate_submit(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")
    with db.session_scope() as session:
        session.add(
            AIPublishRecord(
                raw_record_id="pub-1",
                batch_id="batch-publish",
                source_name="emart",
                status=PipelineStatus.PUBLISH_FAILED.value,
                ai_proposal_ids=[
                    "pub-1-name",
                    "pub-1-category",
                    "pub-1-unit",
                    "pub-1-price",
                    "pub-1-keyword",
                    "pub-1-storage",
                ],
                human_decision_ids=[],
                eligibility_errors=[],
                last_error="ambiguous timeout after DB-admin accepted",
                db_ingestion_id="901",
                db_ingestion_result={"id": 901, "status": "pending"},
                publish_attempts=1,
            )
        )
    called = False

    async def fake_submit(payload):
        nonlocal called
        called = True
        return {"id": 902}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )

    assert res.status_code == 200, res.text
    assert called is False
    result = res.json()["results"][0]
    assert result["status"] == "pending_db_review"
    assert result["db_ingestion_id"] == "901"
    assert result["skipped_duplicate"] is True


def test_publish_rollback_marks_ai_record_not_public_safe_and_unpublishes_proposals(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-1")

    async def fake_submit(payload):
        return {"id": 777, "status": "pending", "quality_score": 100}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    published = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-1"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert published.status_code == 200, published.text

    res = client.post(
        "/api/review/publish-records/pub-1/rollback",
        json={"reviewer_id": "lucy", "reason": "wrong image before public exposure"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "rolled_back"
    assert body["db_ingestion_id"] == "777"
    assert "reject/remove" in body["operator_instructions"]
    rows = {
        row["raw_record_id"]: row
        for row in client.get("/api/review/publish-eligibility").json()["items"]
    }
    assert rows["pub-1"]["status"] == "rolled_back"
    assert rows["pub-1"]["eligible"] is False
    assert rows["pub-1"]["db_ingestion_result"]["rollback_requested"] is True
    detail = client.get("/api/review/proposals/pub-1-name").json()
    assert detail["proposal"]["status"] == "approved"


def test_publish_allows_keyword_audit_but_not_missing_raw_quality(
    client: TestClient, db: Database, monkeypatch
) -> None:
    _seed_publish_batch(db)
    _approve_publish_proposals(client, "pub-2", approve_keyword=False)
    calls = []
    final_calls = []

    async def fake_submit(payload):
        calls.append(payload)
        return {"id": 1}

    async def fake_final_approve(ingestion_id, *, notes=None):
        final_calls.append(ingestion_id)
        return {"id": ingestion_id, "status": "approved"}

    monkeypatch.setattr(review_routes, "_submit_to_db_admin", fake_submit)
    monkeypatch.setattr(review_routes, "_ai_safe_final_approve_db_admin", fake_final_approve)
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["pub-2"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 0
    assert res.json()["submitted_to_db_admin"] == 1
    assert res.json()["pending_db_review"] == 1
    assert res.json()["ai_safe_final_approved"] == 0
    assert len(calls) == 1
    assert final_calls == []
    assert any(
        flag["code"] == "ai_suggested_keywords"
        for flag in calls[0]["items"][0]["post_publish_audit_flags"]
    )

    _seed_raw_batch(db)
    calls.clear()
    res = client.post(
        "/api/review/publish-approved",
        json={"raw_record_ids": ["raw-missing"], "reviewer_id": "lucy", "confirm_count": 1},
    )
    assert res.status_code == 200, res.text
    assert res.json()["published"] == 0
    assert calls == []


def test_automation_gates_preview_and_apply_safe_exact_matches_without_publishing(
    client: TestClient,
    db: Database,
) -> None:
    _seed_automation_batch(db)

    preview = client.post(
        "/api/review/automation-gates/preview",
        json={
            "batch_id": "batch-automation",
            "config": {
                "selected_rule_ids": ["exact_catalog_keyword", "exact_category"],
                "default_min_confidence": 0.9,
                "allowed_sources": ["emart"],
                "allowed_categories": ["processed.tofu.firm"],
                "reviewer_id": "automation:test",
            },
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["will_publish_to_db_admin"] is False
    assert body["automation_scope"] == "review_decisions_only"
    eligible_ids = {item["proposal_id"] for item in body["eligible_items"]}
    assert {"auto-safe:keywords", "auto-safe:category_id"}.issubset(eligible_ids)

    missing_image = [
        item for item in body["blocked_items"] if item["raw_record_id"] == "auto-missing-image"
    ]
    assert missing_image
    assert not any("missing image" in blocker for blocker in missing_image[0]["blockers"])

    unresolved = [
        item for item in body["blocked_items"] if item["raw_record_id"] == "auto-unresolved"
    ]
    assert unresolved
    assert any("keyword proposal" in blocker for blocker in unresolved[0]["blockers"])

    apply = client.post(
        "/api/review/automation-gates/apply",
        json={
            "batch_id": "batch-automation",
            "config": {
                "enabled": True,
                "selected_rule_ids": ["exact_catalog_keyword", "exact_category"],
                "default_min_confidence": 0.9,
                "allowed_sources": ["emart"],
                "allowed_categories": ["processed.tofu.firm"],
                "reviewer_id": "automation:test",
            },
        },
    )
    assert apply.status_code == 200, apply.text
    result = apply.json()
    assert result["applied_count"] == 2
    assert result["will_publish_to_db_admin"] is False
    assert result["automation_scope"] == "review_decisions_only"

    with db.session_scope() as session:
        safe_keyword = FieldProposalRepository(session).get("auto-safe:keywords")
        safe_category = FieldProposalRepository(session).get("auto-safe:category_id")
        blocked_missing = FieldProposalRepository(session).get("auto-missing-image:keywords")
        decisions = ReviewDecisionRepository(session).list_for_proposal("auto-safe:keywords")
        publish_record_count = session.query(AIPublishRecord).count()

    assert safe_keyword.status == PipelineStatus.APPROVED
    assert safe_category.status == PipelineStatus.APPROVED
    assert blocked_missing.status == PipelineStatus.AI_PROPOSED
    assert publish_record_count == 0
    assert decisions
    assert decisions[0].reviewer_id == "automation:test"
    assert "automation_rule_id" in decisions[0].reason
    assert decisions[0].corrected_value["proposal_id"] == "auto-safe:keywords"


def test_automation_apply_requires_explicit_opt_in(client: TestClient, db: Database) -> None:
    _seed_automation_batch(db)

    res = client.post(
        "/api/review/automation-gates/apply",
        json={
            "batch_id": "batch-automation",
            "config": {
                "enabled": False,
                "selected_rule_ids": ["exact_catalog_keyword"],
                "reviewer_id": "automation:test",
            },
        },
    )

    assert res.status_code == 400
    assert "enabled=true" in res.text


def test_automation_learned_alias_requires_prior_success_count(
    client: TestClient,
    db: Database,
) -> None:
    _seed_automation_batch(db)

    preview = client.post(
        "/api/review/automation-gates/preview",
        json={
            "batch_id": "batch-automation",
            "config": {
                "selected_rule_ids": ["learned_alias"],
                "learned_alias_min_confidence": 0.9,
                "learned_alias_min_success_count": 2,
                "allowed_sources": ["emart"],
                "allowed_categories": ["processed.sauce.ssamjang"],
                "reviewer_id": "automation:test",
            },
        },
    )
    assert preview.status_code == 200, preview.text
    eligible_ids = {item["proposal_id"] for item in preview.json()["eligible_items"]}
    assert "auto-learned:keywords" in eligible_ids

    blocked = client.post(
        "/api/review/automation-gates/preview",
        json={
            "batch_id": "batch-automation",
            "config": {
                "selected_rule_ids": ["learned_alias"],
                "learned_alias_min_confidence": 0.9,
                "learned_alias_min_success_count": 4,
                "allowed_sources": ["emart"],
                "allowed_categories": ["processed.sauce.ssamjang"],
                "reviewer_id": "automation:test",
            },
        },
    )
    assert blocked.status_code == 200, blocked.text
    learned_row = next(
        item for item in blocked.json()["blocked_items"] if item["proposal_id"] == "auto-learned:keywords"
    )
    assert any("success_count below 4" in blocker for blocker in learned_row["blockers"])


def test_automation_blocks_generalization_or_review_required_evidence(
    client: TestClient,
    db: Database,
) -> None:
    _seed_automation_batch(db)
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        inferred = repo.get("auto-safe:keywords")
        repo.save(
            inferred.model_copy(
                update={
                    "proposal_id": "auto-safe:model-inferred-keyword",
                    "alternatives": [
                        {
                            "word": "두부",
                            "keyword_id": 1,
                            "evidence_class": "model_inferred",
                            "trust_label": "provider_inferred_holdout",
                        }
                    ],
                }
            )
        )
        taxonomy_hint = repo.get("auto-safe:category_id")
        repo.save(
            taxonomy_hint.model_copy(
                update={
                    "proposal_id": "auto-safe:taxonomy-hint-category",
                    "alternatives": [
                        {
                            "evidence_class": "deterministic_keyword",
                            "trust_label": "taxonomy_hint_needs_review",
                            "match_kind": "substring",
                        }
                    ],
                }
            )
        )

    preview = client.post(
        "/api/review/automation-gates/preview",
        json={
            "batch_id": "batch-automation",
            "config": {
                "selected_rule_ids": ["exact_catalog_keyword", "exact_category"],
                "default_min_confidence": 0.9,
                "allowed_sources": ["emart"],
                "allowed_categories": ["processed.tofu.firm"],
                "reviewer_id": "automation:test",
            },
        },
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    blocked = {item["proposal_id"]: item for item in body["blocked_items"]}
    assert "auto-safe:model-inferred-keyword" in blocked
    assert any("generalization evidence" in blocker for blocker in blocked["auto-safe:model-inferred-keyword"]["blockers"])
    assert "auto-safe:taxonomy-hint-category" in blocked
    assert any(
        "review-required evidence" in blocker
        for blocker in blocked["auto-safe:taxonomy-hint-category"]["blockers"]
    )
    assert body["blocked_generalization_count"] >= 2


def test_automation_blocks_high_confidence_slash_category_id_validation_failure(
    client: TestClient,
    db: Database,
) -> None:
    _seed_automation_batch(db)
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save_records(
            "batch-automation",
            [
                RawCrawlRecord(
                    raw_record_id="auto-slash-category",
                    source_name="emart",
                    source_url="https://emart.example/products/shrimp",
                    raw_title="냉동 새우살 300g",
                    raw_price=6980,
                    raw_payload={
                        "source_url": "https://emart.example/products/shrimp",
                        "image_url": "https://emart.example/images/shrimp.jpg",
                        "unit": "300g",
                        "category_id": "수산/냉동",
                        "expected_ai": {
                            "canonical_name": "냉동 새우살 300g",
                            "category_id": "수산/냉동",
                            "package_unit": "g",
                            "keywords": ["새우"],
                            "price": 6980,
                        },
                    },
                )
            ],
        )
        proposal_repo = FieldProposalRepository(session)
        for proposal in [
            _automation_proposal("auto-slash-category", "category_id", "수산/냉동", proposal_type=ProposalType.CATEGORY),
            _automation_proposal(
                "auto-slash-category",
                "keywords",
                "새우",
                proposal_type=ProposalType.KEYWORD,
                alternatives=[
                    {
                        "word": "새우",
                        "keyword_id": 42,
                        "matched_term": "새우",
                        "category_id": "seafood.frozen",
                        "evidence_class": "exact_catalog",
                        "trust_label": "reuse_exact_catalog",
                    }
                ],
            ),
            _automation_proposal("auto-slash-category", "package_unit", "g"),
        ]:
            proposal_repo.save(proposal)

    preview = client.post(
        "/api/review/automation-gates/preview",
        json={
            "batch_id": "batch-automation",
            "config": {
                "selected_rule_ids": ["exact_catalog_keyword", "exact_category"],
                "default_min_confidence": 0.9,
                "allowed_sources": ["emart"],
                "allowed_categories": ["seafood.frozen"],
                "reviewer_id": "automation:test",
            },
        },
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert "auto-slash-category:category_id" not in {
        item["proposal_id"] for item in body["eligible_items"]
    }
    blocked = {
        item["proposal_id"]: item
        for item in body["blocked_items"]
        if item["raw_record_id"] == "auto-slash-category"
    }
    assert blocked
    assert any(
        "raw/AI audit has mismatch or quality issue" in blocker
        for item in blocked.values()
        for blocker in item["blockers"]
    )


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


def test_batch_audit_excludes_generated_proposals_from_previous_batch_with_same_raw_id(
    client: TestClient,
    db: Database,
) -> None:
    _seed_raw_batch(db)
    old_batch_proposal = _proposal_for_record(
        "old-batch:ai:1:classifier:raw-good:category_id:category_id",
        "raw-good",
        "category_id",
        "seafood.squid",
        proposal_type="category",
    )
    current_batch_proposal = _proposal_for_record(
        "batch-review:ai:1:normalizer:raw-good:canonical_name:canonical_name",
        "raw-good",
        "canonical_name",
        "오리온 오징어 땅콩 98g",
    )
    for proposal in (old_batch_proposal, current_batch_proposal):
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text

    audit = client.get("/api/review/audit", params={"batch_id": "batch-review"})
    assert audit.status_code == 200, audit.text
    issues = audit.json()["issues"]
    category_issues = [
        issue for issue in issues
        if issue["raw_record_id"] == "raw-good" and issue["code"] == "mismatched_category_id"
    ]
    assert category_issues
    assert category_issues[0]["actual"] == []


def test_raw_vs_ai_audit_flags_seeded_korean_data_that_exists_but_is_not_serviceable(
    client: TestClient,
    db: Database,
) -> None:
    _seed_quality_audit_batch(db)
    proposals = [
        _proposal_for_record("qa-good-name", "qa-good-chilled-pork", "canonical_name", "국내산 냉장 삼겹살 500g"),
        _proposal_for_record("qa-good-cat", "qa-good-chilled-pork", "category_id", "meat.pork", proposal_type="category"),
        _proposal_for_record("qa-good-unit", "qa-good-chilled-pork", "package_unit", "g"),
        _proposal_for_record("qa-good-kw", "qa-good-chilled-pork", "keywords", "삼겹살", proposal_type="keyword"),
        _proposal_for_record("qa-good-price", "qa-good-chilled-pork", "price", 9900),
        _proposal_for_record("qa-good-storage", "qa-good-chilled-pork", "attributes.storage_type", "냉장", proposal_type="attribute_value"),
        _proposal_for_record("qa-price-name", "qa-price-wrong", "canonical_name", "서울우유 1L"),
        _proposal_for_record("qa-price-cat", "qa-price-wrong", "category_id", "dairy.milk", proposal_type="category"),
        _proposal_for_record("qa-price-unit", "qa-price-wrong", "package_unit", "L"),
        _proposal_for_record("qa-price-kw", "qa-price-wrong", "keywords", ["서울우유", "우유"], proposal_type="keyword"),
        _proposal_for_record("qa-price-price", "qa-price-wrong", "price", "3,800원"),
        _proposal_for_record("qa-snack-name", "qa-snack-seafood-confused", "canonical_name", "오리온 오징어땅콩 98g"),
        _proposal_for_record("qa-snack-cat", "qa-snack-seafood-confused", "category_id", "seafood.squid", proposal_type="category"),
        _proposal_for_record("qa-snack-unit", "qa-snack-seafood-confused", "package_unit", "g"),
        _proposal_for_record("qa-snack-kw", "qa-snack-seafood-confused", "keywords", "오징어", proposal_type="keyword"),
        _proposal_for_record("qa-snack-price", "qa-snack-seafood-confused", "price", 1980),
        _proposal_for_record("qa-seafood-name", "qa-frozen-seafood-missing-storage", "canonical_name", "냉동 손질 오징어 500g"),
        _proposal_for_record("qa-seafood-cat", "qa-frozen-seafood-missing-storage", "category_id", "seafood.squid", proposal_type="category"),
        _proposal_for_record("qa-seafood-unit", "qa-frozen-seafood-missing-storage", "package_unit", "g"),
        _proposal_for_record("qa-seafood-kw", "qa-frozen-seafood-missing-storage", "keywords", "오징어", proposal_type="keyword"),
        _proposal_for_record("qa-seafood-price", "qa-frozen-seafood-missing-storage", "price", 7900),
        _proposal_for_record("qa-citrus-name", "qa-keyword-category-wrong", "canonical_name", "제주 감귤 1.5kg"),
        _proposal_for_record("qa-citrus-cat", "qa-keyword-category-wrong", "category_id", "fruit.apple", proposal_type="category"),
        _proposal_for_record("qa-citrus-unit", "qa-keyword-category-wrong", "package_unit", "kg"),
        _proposal_for_record("qa-citrus-kw", "qa-keyword-category-wrong", "keywords", "사과", proposal_type="keyword"),
        _proposal_for_record("qa-citrus-price", "qa-keyword-category-wrong", "price", 12900),
        _proposal_for_record("qa-citrus-storage", "qa-keyword-category-wrong", "attributes.storage_type", "ambient", proposal_type="attribute_value"),
        _proposal_for_record("qa-orphan-name", "qa-not-in-raw", "canonical_name", "없는 상품"),
    ]
    for proposal in proposals:
        res = client.post("/api/review/proposals", json=proposal)
        assert res.status_code == 201, res.text

    audit = client.get("/api/review/audit", params={"batch_id": "batch-quality-audit"})
    assert audit.status_code == 200, audit.text
    body = audit.json()

    assert body["raw_record_count"] == 6
    assert body["covered_record_count"] == 5
    assert body["missing_record_count"] == 1
    assert body["status"] == "warning"

    issue_codes = {(issue["raw_record_id"], issue["code"]) for issue in body["issues"]}
    assert ("qa-missing-product", "missing_all_proposals") in issue_codes
    assert ("qa-not-in-raw", "orphan_ai_proposals") not in issue_codes
    assert ("qa-price-wrong", "price_mismatch_raw") in issue_codes
    assert ("qa-price-wrong", "mismatched_price") in issue_codes
    assert ("qa-price-wrong", "missing_storage_attribute") in issue_codes
    assert ("qa-snack-seafood-confused", "mismatched_category_id") in issue_codes
    assert ("qa-snack-seafood-confused", "mismatched_keywords") in issue_codes
    assert ("qa-snack-seafood-confused", "snack_seafood_confusion") in issue_codes
    assert ("qa-frozen-seafood-missing-storage", "missing_storage_attribute") in issue_codes
    assert ("qa-frozen-seafood-missing-storage", "mismatched_storage_attribute") in issue_codes
    assert ("qa-keyword-category-wrong", "mismatched_category_id") in issue_codes
    assert ("qa-keyword-category-wrong", "mismatched_keywords") in issue_codes
    assert ("qa-keyword-category-wrong", "mismatched_storage_attribute") in issue_codes
    assert not any(issue[0] == "qa-good-chilled-pork" for issue in issue_codes)
