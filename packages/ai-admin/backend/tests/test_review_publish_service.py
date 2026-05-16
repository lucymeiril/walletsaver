"""Service-level tests for AI review publish eligibility and DB-admin payloads."""
from __future__ import annotations

from datetime import datetime

import pytest

from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from core.contracts.control_plane import RawCrawlBatchContract
from services.db_admin_adapter import build_db_admin_ingestion_payload
from services.review_publish import (
    build_batch_publish_summary,
    build_publish_rows,
    build_raw_ai_audit,
    db_item_from_review,
    is_ai_safe_final_approve_eligible,
    publish_blockers,
)
from storage import (
    Database,
    FieldProposalRepository,
    KeywordProposalRepository,
    RawCrawlBatchRepository,
    create_database,
)


@pytest.fixture()
def db() -> Database:
    database = create_database("sqlite:///:memory:")
    yield database
    database.dispose()


def _proposal(raw_id: str, target: str, value, *, proposal_type: ProposalType) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"{raw_id}:{target}",
        proposal_type=proposal_type,
        target_field=target,
        proposed_value=value,
        status=PipelineStatus.APPROVED,
        provenance=FieldProvenance(
            raw_record_id=raw_id,
            source_field="ai",
            evidence_text=f"evidence for {raw_id}",
            worker_role=AIWorkerRole.NORMALIZER,
            reviewed_by="qa",
            reviewed_at=datetime.now(),
        ),
    )


def _seed_emart_record(session, raw_id: str) -> None:
    raw_payload = {
        "source": "emart",
        "store": "이마트",
        "name": "한끼 양배추 800g 통",
        "unit": "800g",
        "category_id": "vegetable.cabbage",
        "storage_type": "냉장",
        "image_url": "https://emart.example/images/cabbage.jpg",
        "original_price": 3480,
        "sale_price": 2784,
        "discount_percent": 20,
        "source_url": "https://emart.example/products/cabbage",
    }
    raw_repo = RawCrawlBatchRepository(session)
    raw_repo.save_records(
        "batch-emart-service",
        [
            RawCrawlRecord(
                raw_record_id=raw_id,
                source_name="emart",
                source_record_key=raw_id,
                source_url=raw_payload["source_url"],
                raw_title=raw_payload["name"],
                raw_price=2784,
                raw_payload=raw_payload,
            )
        ],
    )
    proposal_repo = FieldProposalRepository(session)
    for proposal in [
        _proposal(raw_id, "canonical_name", "한끼 양배추 800g 통", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal(raw_id, "category_id", "vegetable.cabbage", proposal_type=ProposalType.CATEGORY),
        _proposal(raw_id, "package_unit", "800g", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal(raw_id, "sale_price", 2784, proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal(raw_id, "keywords", ["양배추"], proposal_type=ProposalType.KEYWORD),
        _proposal(raw_id, "attributes.storage_type", "냉장", proposal_type=ProposalType.ATTRIBUTE_VALUE),
    ]:
        proposal_repo.save(proposal)


def _raw_record(raw_id: str, title: str, **payload_overrides) -> RawCrawlRecord:
    payload = {
        "source": "emart",
        "store": "이마트",
        "name": title,
        "sale_price": 10000,
        "source_url": f"https://emart.example/products/{raw_id}",
        "image_url": f"https://emart.example/images/{raw_id}.jpg",
    }
    payload.update(payload_overrides)
    return RawCrawlRecord(
        raw_record_id=raw_id,
        source_name="emart",
        source_record_key=raw_id,
        source_url=payload["source_url"],
        raw_title=title,
        raw_price=payload["sale_price"],
        raw_payload=payload,
    )


def test_db_item_from_review_defaults_physical_rows_to_single_count_unit() -> None:
    item = db_item_from_review(_raw_record("hanger", "심플 높이조절 행거"), [], {})

    assert item["package_quantity"] == 1
    assert item["package_unit"] == "개"
    assert item["display_unit"] == "1개"
    assert item["standard_unit"] == "개"
    assert item["standard_unit_price"] == 10000


def test_service_or_option_rows_remain_held_without_synthetic_package_unit() -> None:
    voucher = _raw_record("voucher", "모바일금액권 1만원권 (2%할인)")
    voucher_item = db_item_from_review(voucher, [], {})

    assert voucher_item["package_quantity"] is None
    assert voucher_item["package_unit"] is None
    blockers = publish_blockers(voucher, [], [], {}, [])
    assert "held: non_comparable_package_metadata: service_voucher_or_option_selection" in blockers

    option_row = _raw_record("choice", "기능성 양말 10종택1")
    option_item = db_item_from_review(option_row, [], {})
    assert option_item["package_quantity"] is None
    assert option_item["package_unit"] is None
    assert any("non_comparable_package_metadata" in blocker for blocker in publish_blockers(option_row, [], [], {}, []))


def test_publish_service_marks_emart_row_eligible_and_preserves_offer_metadata(db: Database) -> None:
    with db.session_scope() as session:
        RawCrawlBatchRepository(session).save(
            RawCrawlBatchContract(
                batch_id="batch-emart-service",
                source_name="emart",
                crawler_name="service-test",
                item_count=2,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        _seed_emart_record(session, "emart-cabbage-ready")
        _seed_emart_record(session, "emart-cabbage-keyword-blocked")
        KeywordProposalRepository(session).save(
            {
                "proposal_id": "keyword:cabbage-special",
                "proposed_keyword": "특가양배추",
                "match_terms": ["특가양배추"],
                "triggering_records": [{"raw_record_id": "emart-cabbage-keyword-blocked"}],
                "status": PipelineStatus.AI_PROPOSED.value,
            }
        )

        rows = {
            row["raw_record_id"]: row
            for row in build_publish_rows(session, batch_id="batch-emart-service")
        }
        summary = build_batch_publish_summary(
            session,
            list(rows.values()),
            batch_id="batch-emart-service",
        )

    ready = rows["emart-cabbage-ready"]
    assert ready["eligible"] is True
    assert ready["status"] == PipelineStatus.APPROVED.value
    assert ready["item"]["original_price"] == 3480
    assert ready["item"]["discount_percent"] == 20
    assert ready["item"]["image_url"].endswith("cabbage.jpg")
    assert ready["item"]["package_quantity"] == 800
    assert ready["item"]["package_unit"] == "g"
    assert ready["item"]["source_title"] == "한끼 양배추 800g 통"
    assert ready["item"]["raw_data"]["sale_offer"]["source_title"] == "한끼 양배추 800g 통"
    assert ready["item"]["raw_data"]["raw_evidence"]["raw_unit"] == "800g"

    keyword_audit = rows["emart-cabbage-keyword-blocked"]
    assert keyword_audit["eligible"] is True
    assert keyword_audit["ai_safe_final_approve_eligible"] is False
    assert keyword_audit["db_handoff_mode"] == "db_admin_review"
    assert any(flag["code"] == "db_keyword_proposal_unresolved" for flag in keyword_audit["post_publish_audit_flags"])
    assert summary["batch_status"] == "ready"
    assert summary["eligible_count"] == 2
    assert summary["ai_safe_final_approve_count"] == 1
    assert summary["db_review_handoff_count"] == 1
    assert summary["unresolved_keyword_proposal_count"] == 1


def test_db_admin_adapter_payload_is_built_from_publish_candidate() -> None:
    item = {
        "raw_record_id": "emart-cabbage-ready",
        "source_url": "https://emart.example/products/cabbage",
        "publication_kind": "price_observation",
        "raw_data": {
            "raw_record": {
                "raw_record_id": "emart-cabbage-ready",
                "raw_title": "한끼 양배추 800g 통",
            },
        },
    }
    payload = build_db_admin_ingestion_payload(
        {
            "raw_record_id": "emart-cabbage-ready",
            "batch_id": "batch-emart-service",
            "source_name": "emart",
            "proposal_ids": ["emart-cabbage-ready:canonical_name"],
            "human_decision_ids": ["decision-1"],
            "db_handoff_mode": "db_admin_review",
            "publication_kind": "price_observation",
            "item": item,
        }
    )

    assert payload["crawler_name"] == "ai-admin:emart"
    assert payload["schema_type"] == "DiscountItem"
    assert payload["strategy_used"] == "ai_review_publish"
    assert payload["items"][0]["raw_record_id"] == "emart-cabbage-ready"
    assert "ai_review_publish_provenance" not in item["raw_data"]
    provenance = payload["items"][0]["raw_data"]["ai_review_publish_provenance"]
    assert provenance == {
        "raw_record_id": "emart-cabbage-ready",
        "batch_id": "batch-emart-service",
        "source_name": "emart",
        "proposal_ids": ["emart-cabbage-ready:canonical_name"],
        "human_decision_ids": ["decision-1"],
        "db_handoff_mode": "db_admin_review",
        "publication_kind": "price_observation",
    }
    assert payload["items"][0]["ai_review_audit"]["human_decision_ids"] == ["decision-1"]


def test_pending_db_review_final_approve_eligibility_preserves_critical_blockers() -> None:
    base_row = {
        "status": PipelineStatus.PENDING_DB_REVIEW.value,
        "eligible": False,
        "db_ingestion_id": "782",
        "blocking_audit_issues": [],
        "post_publish_audit_flags": [],
        "claim_blockers": [],
    }

    assert is_ai_safe_final_approve_eligible(
        {
            **base_row,
            "blockers": [
                "pending_db_review: already submitted to DB-admin; wait for final DB-admin approval"
            ],
        }
    ) is True
    assert is_ai_safe_final_approve_eligible(
        {
            **base_row,
            "blockers": [
                "pending_review: critical AI proposals must be human approved",
                "pending_db_review: already submitted to DB-admin; wait for final DB-admin approval",
            ],
        }
    ) is False


def test_price_observation_claim_blocker_does_not_block_final_approve() -> None:
    assert is_ai_safe_final_approve_eligible(
        {
            "status": PipelineStatus.PENDING_DB_REVIEW.value,
            "eligible": False,
            "db_ingestion_id": "price-observation-1",
            "publication_kind": "price_observation",
            "price_observation_only": True,
            "blockers": [
                "pending_db_review: already submitted to DB-admin; wait for final DB-admin approval"
            ],
            "blocking_audit_issues": [],
            "post_publish_audit_flags": [],
            "claim_blockers": [
                "hotdeal_claim_blocked: missing verified original_price/discount_percent/source_event/historical_baseline"
            ],
        }
    ) is True


def test_source_owned_fields_win_over_conflicting_ai_proposals() -> None:
    record = RawCrawlRecord(
        raw_record_id="source-boundary",
        source_name="emart",
        source_record_key="source-boundary",
        source_url="https://emart.example/source",
        raw_title="원본 상품 500g",
        raw_price=1000,
        raw_payload={
            "store": "이마트",
            "sale_price": 1000,
            "original_price": 2000,
            "discount_percent": 50,
            "source_url": "https://emart.example/source",
            "image_url": "https://emart.example/source.jpg",
            "event_name": "source event",
            "valid_from": "2026-01-01T00:00:00",
            "valid_to": "2026-01-07T23:59:59",
        },
    )
    proposals = [
        _proposal("source-boundary", "canonical_name", "AI 상품명", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "category_id", "vegetable.cabbage", proposal_type=ProposalType.CATEGORY),
        _proposal("source-boundary", "keywords", ["양배추"], proposal_type=ProposalType.KEYWORD),
        _proposal("source-boundary", "sale_price", 777, proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "current_price", 777, proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "original_price", 9999, proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "discount_percent", 90, proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "source_url", "https://ai.example/wrong", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "image_url", "https://ai.example/wrong.jpg", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "event_name", "ai event", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "valid_from", "2030-01-01T00:00:00", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("source-boundary", "valid_to", "2030-01-31T23:59:59", proposal_type=ProposalType.NORMALIZED_FIELD),
    ]

    item = db_item_from_review(record, proposals, {})

    assert item["sale_price"] == 1000
    assert item["current_price"] == 1000
    assert item["original_price"] == 2000
    assert item["discount_percent"] == 50
    assert item["source_url"] == "https://emart.example/source"
    assert item["detail_url"] == "https://emart.example/source"
    assert item["image_url"] == "https://emart.example/source.jpg"
    assert item["event_name"] == "source event"
    assert item["raw_data"]["sale_offer"]["valid_from"].startswith("2026-01-01")
    assert item["raw_data"]["sale_offer"]["valid_to"].startswith("2026-01-07")
    ignored = item["raw_data"]["audit_provenance"]["ignored_source_owned_ai_fields"]
    assert ignored["sale_price"] == 777
    assert ignored["source_url"] == "https://ai.example/wrong"
    normalized = item["raw_data"]["normalized"]
    assert normalized["source_owned_fields"]["price"] == 1000
    assert normalized["source_listing"]["source_url"] == "https://emart.example/source"
    assert normalized["source_listing"]["image_url"] == "https://emart.example/source.jpg"
    assert normalized["offer_event"]["valid_from"].startswith("2026-01-01")
    assert normalized["offer_event"]["valid_to"].startswith("2026-01-07")


def test_conflicting_ai_price_proposal_is_held_not_published(db: Database) -> None:
    with db.session_scope() as session:
        RawCrawlBatchRepository(session).save(
            RawCrawlBatchContract(
                batch_id="batch-source-boundary",
                source_name="emart",
                crawler_name="service-test",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        raw_repo = RawCrawlBatchRepository(session)
        raw_repo.save_records(
            "batch-source-boundary",
            [
                RawCrawlRecord(
                    raw_record_id="source-price-conflict",
                    source_name="emart",
                    source_record_key="source-price-conflict",
                    source_url="https://emart.example/price-conflict",
                    raw_title="가격 충돌 상품 500g",
                    raw_price=1000,
                    raw_payload={
                        "store": "이마트",
                        "sale_price": 1000,
                        "image_url": "https://emart.example/price-conflict.jpg",
                    },
                )
            ],
        )
        proposal_repo = FieldProposalRepository(session)
        for proposal in [
            _proposal("source-price-conflict", "canonical_name", "가격 충돌 상품", proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal("source-price-conflict", "category_id", "vegetable.cabbage", proposal_type=ProposalType.CATEGORY),
            _proposal("source-price-conflict", "keywords", ["양배추"], proposal_type=ProposalType.KEYWORD),
            _proposal("source-price-conflict", "sale_price", 777, proposal_type=ProposalType.NORMALIZED_FIELD),
        ]:
            proposal_repo.save(proposal)

        row = build_publish_rows(session, batch_id="batch-source-boundary")[0]

    assert row["item"]["sale_price"] == 1000
    assert row["eligible"] is False
    assert "data_quality: price_mismatch_raw" in row["blockers"]


def test_ai_price_does_not_fill_missing_source_price() -> None:
    record = RawCrawlRecord(
        raw_record_id="missing-source-price",
        source_name="emart",
        source_record_key="missing-source-price",
        source_url="https://emart.example/missing-price",
        raw_title="가격 누락 상품",
        raw_price=None,
        raw_payload={
            "store": "이마트",
            "discount_percent": 30,
            "source_url": "https://emart.example/missing-price",
            "image_url": "https://emart.example/missing-price.jpg",
        },
    )
    proposals = [
        _proposal("missing-source-price", "canonical_name", "가격 누락 상품", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("missing-source-price", "category_id", "vegetable.cabbage", proposal_type=ProposalType.CATEGORY),
        _proposal("missing-source-price", "keywords", ["양배추"], proposal_type=ProposalType.KEYWORD),
        _proposal("missing-source-price", "sale_price", 777, proposal_type=ProposalType.NORMALIZED_FIELD),
    ]

    item = db_item_from_review(record, proposals, {})
    blockers = publish_blockers(record, proposals, [], {}, [])

    assert item["sale_price"] is None
    assert item["discount_percent"] == 30
    assert "data_quality: missing positive DB ingestion field sale_price" in blockers


def test_normalized_publish_payload_contains_identity_variant_listing_and_offer_sections() -> None:
    record = RawCrawlRecord(
        raw_record_id="normalized-payload",
        source_name="emart",
        source_record_key="sku-normalized",
        source_url="https://emart.example/normalized",
        raw_title="풀무원 국산콩 두부 300g",
        raw_price=1980,
        raw_payload={
            "store": "이마트",
            "sale_price": 1980,
            "unit": "300g",
            "image_url": "https://emart.example/tofu.jpg",
            "source_url": "https://emart.example/normalized",
        },
    )
    proposals = [
        _proposal("normalized-payload", "canonical_name", "풀무원 국산콩 두부", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("normalized-payload", "category_id", "processed.tofu", proposal_type=ProposalType.CATEGORY),
        _proposal("normalized-payload", "keywords", ["두부"], proposal_type=ProposalType.KEYWORD),
    ]

    item = db_item_from_review(record, proposals, {})
    payload = build_db_admin_ingestion_payload(
        {
            "raw_record_id": "normalized-payload",
            "batch_id": "batch-normalized",
            "source_name": "emart",
            "proposal_ids": [proposal.proposal_id for proposal in proposals],
            "human_decision_ids": [],
            "db_handoff_mode": "ai_safe_final_approve",
            "publication_kind": item["publication_kind"],
            "item": item,
        }
    )

    published_item = payload["items"][0]
    normalized = published_item["raw_data"]["normalized"]
    assert published_item["price"] == 1980
    assert published_item["source_name"] == "이마트"
    assert published_item["variant_name"] == "풀무원 국산콩 두부 300g"
    assert normalized["canonical_product"]["canonical_name"] == "풀무원 국산콩 두부"
    assert normalized["product_variant"]["package_quantity"] == 300
    assert normalized["product_variant"]["package_unit"] == "g"
    assert normalized["product_variant"]["package_match_status"] == "source_confirmed"
    assert normalized["source_listing"]["source_record_key"] == "sku-normalized"
    assert normalized["offer_event"]["price"] == 1980
    assert normalized["offer_event"]["price_state"] == "normal"


def test_hidden_and_discount_only_price_states_are_represented_without_fake_prices() -> None:
    hidden = RawCrawlRecord(
        raw_record_id="hidden-price",
        source_name="homeplus",
        source_record_key="hidden-price",
        source_url="https://homeplus.example/hidden",
        raw_title="앱에서 가격 확인 라면 5입",
        raw_price=0,
        raw_payload={
            "store": "홈플러스",
            "price": 0,
            "source_url": "https://homeplus.example/hidden",
            "image_url": "https://homeplus.example/hidden.jpg",
        },
    )
    discount_only = RawCrawlRecord(
        raw_record_id="discount-only",
        source_name="lottemart",
        source_record_key="discount-only",
        source_url="https://lotte.example/discount",
        raw_title="카드 20% 할인 양배추",
        raw_price=None,
        raw_payload={
            "store": "롯데마트",
            "discount_percent": 20,
            "promotion_type": "checkout_discount",
            "source_url": "https://lotte.example/discount",
            "image_url": "https://lotte.example/discount.jpg",
        },
    )

    hidden_item = db_item_from_review(hidden, [], {})
    discount_item = db_item_from_review(discount_only, [], {})

    assert hidden_item["sale_price"] is None
    assert hidden_item["price"] is None
    assert hidden_item["price_state"] == "price_hidden"
    assert hidden_item["raw_data"]["normalized"]["offer_event"]["price"] is None
    assert discount_item["sale_price"] is None
    assert discount_item["price_state"] == "discount_rate_only"
    assert discount_item["promotion_type"] == "checkout_discount"
    assert discount_item["raw_data"]["normalized"]["offer_event"]["discount_rate"] == 0.2
    assert discount_item["raw_data"]["normalized"]["offer_event"]["price"] is None


def test_source_package_mismatch_is_held_as_candidate_until_evidence_is_strong(db: Database) -> None:
    with db.session_scope() as session:
        RawCrawlBatchRepository(session).save(
            RawCrawlBatchContract(
                batch_id="batch-package-mismatch",
                source_name="emart",
                crawler_name="service-test",
                item_count=1,
                schema_type="product_offer",
                status=PipelineStatus.RAW_INGESTED,
            )
        )
        RawCrawlBatchRepository(session).save_records(
            "batch-package-mismatch",
            [
                RawCrawlRecord(
                    raw_record_id="package-mismatch",
                    source_name="emart",
                    source_record_key="package-mismatch",
                    source_url="https://emart.example/package-mismatch",
                    raw_title="풀무원 국산콩 두부",
                    raw_price=1980,
                    raw_payload={
                        "store": "이마트",
                        "sale_price": 1980,
                        "package_quantity": 300,
                        "package_unit": "g",
                        "display_unit": "300g",
                        "source_url": "https://emart.example/package-mismatch",
                        "image_url": "https://emart.example/package-mismatch.jpg",
                    },
                )
            ],
        )
        proposal_repo = FieldProposalRepository(session)
        for proposal in [
            _proposal("package-mismatch", "canonical_name", "풀무원 국산콩 두부", proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal("package-mismatch", "category_id", "processed.tofu", proposal_type=ProposalType.CATEGORY),
            _proposal("package-mismatch", "keywords", ["두부"], proposal_type=ProposalType.KEYWORD),
            _proposal("package-mismatch", "package_quantity", 500, proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal("package-mismatch", "package_unit", "g", proposal_type=ProposalType.NORMALIZED_FIELD),
        ]:
            proposal_repo.save(proposal)

        row = build_publish_rows(session, batch_id="batch-package-mismatch")[0]

    assert row["eligible"] is False
    assert row["status"] in {PipelineStatus.PENDING_REVIEW.value, PipelineStatus.HELD.value}
    assert "data_quality: package_mismatch_source" in row["blockers"]
    assert "held: package mismatch must remain a candidate until source listing evidence is strong" in row["blockers"]
    assert row["item"]["package_quantity"] == 300
    assert row["item"]["raw_data"]["normalized"]["product_variant"]["package_evidence_source"] == "source_payload"


def test_review_publish_builds_typed_offer_items_for_food_and_daily_goods() -> None:
    records = [
        RawCrawlRecord(
            raw_record_id="beef-300g",
            source_name="emart",
            source_record_key="beef-sku",
            source_url="https://emart.example/beef",
            raw_title="[냉장] 한우 불고기1+등급300g",
            raw_price=14850,
            raw_payload={
                "store": "이마트",
                "unit": "100g",
                "image_url": "https://emart.example/beef.jpg",
                "original_price": 19800,
                "discount_percent": 25,
                "category_id": "meat.beef",
            },
        ),
        RawCrawlRecord(
            raw_record_id="tofu-300g",
            source_name="emart",
            source_record_key="tofu-sku",
            source_url="https://emart.example/tofu",
            raw_title="국산콩 두부 300g 1+1",
            raw_price=2480,
            raw_payload={
                "store": "이마트",
                "image_url": "https://emart.example/tofu.jpg",
                "original_price": 3100,
                "discount_percent": 20,
                "category_id": "food.tofu",
                "event_name": "1+1",
            },
        ),
        RawCrawlRecord(
            raw_record_id="detergent-2l",
            source_name="emart",
            raw_title="세탁세제 리필 2L",
            raw_price=6900,
            raw_payload={
                "store": "이마트",
                "image_url": "https://emart.example/detergent.jpg",
                "original_price": 9900,
                "discount_percent": 30,
                "category_id": "daily.detergent",
            },
        ),
    ]

    proposal_sets = [
        [
            _proposal("beef-300g", "canonical_name", "한우 불고기", proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal("beef-300g", "category_id", "meat.beef", proposal_type=ProposalType.CATEGORY),
            _proposal("beef-300g", "keywords", ["한우", "불고기"], proposal_type=ProposalType.KEYWORD),
        ],
        [
            _proposal("tofu-300g", "canonical_name", "국산콩 두부", proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal("tofu-300g", "category_id", "food.tofu", proposal_type=ProposalType.CATEGORY),
            _proposal("tofu-300g", "keywords", ["두부"], proposal_type=ProposalType.KEYWORD),
        ],
        [
            _proposal("detergent-2l", "canonical_name", "세탁세제 리필", proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal("detergent-2l", "category_id", "daily.detergent", proposal_type=ProposalType.CATEGORY),
            _proposal("detergent-2l", "keywords", ["세탁세제"], proposal_type=ProposalType.KEYWORD),
        ],
    ]

    items = [
        db_item_from_review(record, proposals, {})
        for record, proposals in zip(records, proposal_sets)
    ]

    beef, tofu, detergent = items
    assert beef["source_title"] == records[0].raw_title
    assert beef["sale_price"] == 14850
    assert beef["package_quantity"] == 300
    assert beef["price_per_100g"] == 4950
    assert beef["standard_unit"] == "kg"
    assert beef["standard_unit_price"] == 49500
    assert beef["attributes"]["storage_type"] == "chilled"
    assert beef["attributes"]["quality_grade"] == "1+"
    assert tofu["event_name"] == "1+1"
    assert tofu["display_unit"] == "300g"
    assert detergent["display_unit"] == "2L"
    assert detergent["package_unit"] == "L"
    assert detergent["standard_unit_price"] == 3450
    for item in items:
        assert item["image_url"]
        assert item["original_price"]
        assert item["raw_data"]["raw_record"]["raw_title"] == item["source_title"]


def test_lottemart_general_taxonomy_ids_are_normalized_without_manual_product_aliases() -> None:
    records = [
        RawCrawlRecord(
            raw_record_id=raw_id,
            source_name="lottemart",
            source_record_key=raw_id,
            source_url=f"https://lottemart.example/{raw_id}",
            raw_title=title,
            raw_price=price,
            raw_payload={
                "store": "롯데마트",
                "image_url": f"https://lottemart.example/{raw_id}.jpg",
                "sale_price": price,
                "unit": unit,
            },
        )
        for raw_id, title, price, unit in [
            ("lotte-egg", "행복생생란 (특란, 30입) (1.8KG)", 6990, "1.8kg"),
            ("lotte-ice", "롯데 빠삐코 (130ML)", 880, "130ml"),
            ("lotte-bread", "오늘좋은 숨결통식빵 (400G)", 2990, "400g"),
            ("lotte-shrimp-snack", "농심 새우깡 (90G)", 990, "90g"),
            ("lotte-abalone", "완도 전복(대) (마리)", 3990, "마리"),
            ("lotte-tissue", "오늘좋은 물티슈 (120매)", 1000, "120매"),
            ("lotte-sauce", "오뚜기 미트 파스타소스 (600G)", 4980, "600g"),
            ("lotte-soda", "펩시콜라 제로슈거 라임 (1.25L)", 1980, "1.25L"),
        ]
    ]
    category_by_raw_id = {
        "lotte-egg": "agriculture.egg",
        "lotte-ice": "snack.ice_cream",
        "lotte-bread": "bakery.bread",
        "lotte-shrimp-snack": "snack.chips",
        "lotte-abalone": "seafood.shellfish",
        "lotte-tissue": "household.tissue",
        "lotte-sauce": "processed.sauce",
        "lotte-soda": "beverage.carbonated",
    }
    proposals = [
        proposal
        for record in records
        for proposal in [
            _proposal(record.raw_record_id, "canonical_name", record.raw_title, proposal_type=ProposalType.NORMALIZED_FIELD),
            _proposal(record.raw_record_id, "category_id", category_by_raw_id[record.raw_record_id], proposal_type=ProposalType.CATEGORY),
            _proposal(record.raw_record_id, "keywords", [record.raw_title.split()[0]], proposal_type=ProposalType.KEYWORD),
            _proposal(record.raw_record_id, "package_unit", "raw", proposal_type=ProposalType.NORMALIZED_FIELD),
        ]
    ]

    audit = build_raw_ai_audit(records, proposals, batch_id="lottemart-taxonomy")
    issue_codes = {issue["code"] for issue in audit["issues"]}
    items = [
        db_item_from_review(
            record,
            [proposal for proposal in proposals if proposal.provenance.raw_record_id == record.raw_record_id],
            {},
        )
        for record in records
    ]

    assert "unknown_taxonomy_category" not in issue_codes
    assert "invalid_category_id_format" not in issue_codes
    assert [item["category_id"] for item in items] == [
        "livestock.egg",
        "snack.ice_cream",
        "bakery.bread",
        "snack.chip",
        "seafood.shellfish",
        "household.tissue",
        "processed.sauce",
        "beverage.soda",
    ]


def test_korean_slash_category_id_normalizes_without_invalid_category_audit() -> None:
    record = RawCrawlRecord(
        raw_record_id="slash-category",
        source_name="emart",
        source_record_key="slash-category",
        source_url="https://emart.example/slash-category",
        raw_title="처음보는 토마토 파스타소스 300g",
        raw_price=3980,
        raw_payload={
            "store": "이마트",
            "sale_price": 3980,
            "unit": "300g",
            "image_url": "https://emart.example/slash-category.jpg",
        },
    )
    proposals = [
        _proposal("slash-category", "canonical_name", "처음보는 토마토 파스타소스", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("slash-category", "category_id", "가공식품/소스", proposal_type=ProposalType.CATEGORY),
        _proposal("slash-category", "keywords", ["파스타소스"], proposal_type=ProposalType.KEYWORD),
        _proposal("slash-category", "package_unit", "g", proposal_type=ProposalType.NORMALIZED_FIELD),
    ]

    audit = build_raw_ai_audit([record], proposals, batch_id="slash-category")
    item = db_item_from_review(record, proposals, {})

    assert item["category_id"] == "processed.sauce"
    assert "invalid_category_id_format" not in {issue["code"] for issue in audit["issues"]}
    assert "unknown_taxonomy_category" not in {issue["code"] for issue in audit["issues"]}


def test_model_inferred_keywords_without_crawler_keywords_do_not_fail_raw_evidence_audit() -> None:
    record = RawCrawlRecord(
        raw_record_id="lotte-water",
        source_name="lottemart",
        source_record_key="lotte-water",
        source_url="https://lottemart.example/water",
        raw_title="오늘좋은 미네랄워터 (2L*6입)",
        raw_price=2990,
        raw_payload={
            "store": "롯데마트",
            "sale_price": 2990,
            "unit": "2L*6입",
            "image_url": "https://lottemart.example/water.jpg",
        },
    )
    proposals = [
        _proposal("lotte-water", "canonical_name", "생수", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("lotte-water", "category_id", "beverage.water", proposal_type=ProposalType.CATEGORY),
        _proposal("lotte-water", "keywords", ["생수"], proposal_type=ProposalType.KEYWORD),
        _proposal("lotte-water", "package_unit", "L", proposal_type=ProposalType.NORMALIZED_FIELD),
    ]

    audit = build_raw_ai_audit([record], proposals, batch_id="lottemart-keyword")

    assert "keyword_signal_mismatch" not in {issue["code"] for issue in audit["issues"]}


def test_lottemart_parenthesized_count_units_build_db_package_fields() -> None:
    for title, expected_unit in [
        ("완도 전복(대) (마리)", "마리"),
        ("탱글탱글 소세지가 쏙!  15핫도그 (팩)", "팩"),
        ("국내산 큰 양배추 (통)", "통"),
    ]:
        record = RawCrawlRecord(
            raw_record_id=f"lotte-unit-{expected_unit}",
            source_name="lottemart",
            raw_title=title,
            raw_price=3990,
            raw_payload={"store": "롯데마트", "sale_price": 3990, "unit": expected_unit},
        )

        item = db_item_from_review(record, [], {})

        assert item["package_quantity"] == 1
        assert item["package_unit"] == expected_unit
        assert item["display_unit"] == f"1{expected_unit}"


def test_provider_unit_discrepancy_is_audit_only_when_deterministic_package_is_usable() -> None:
    record = RawCrawlRecord(
        raw_record_id="lotte-water-bundle",
        source_name="lottemart",
        source_record_key="lotte-water-bundle",
        source_url="https://lottemart.example/water-bundle",
        raw_title="오늘좋은 미네랄워터 (2L*6입)",
        raw_price=2000,
        raw_payload={
            "store": "롯데마트",
            "sale_price": 2000,
            "unit": "6입",
            "image_url": "https://lottemart.example/water-bundle.jpg",
        },
    )
    proposals = [
        _proposal("lotte-water-bundle", "canonical_name", "오늘좋은 미네랄워터", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("lotte-water-bundle", "category_id", "beverage.water", proposal_type=ProposalType.CATEGORY),
        _proposal("lotte-water-bundle", "keywords", ["미네랄워터"], proposal_type=ProposalType.KEYWORD),
        _proposal("lotte-water-bundle", "package_quantity", 6, proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("lotte-water-bundle", "display_unit", "6입", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("lotte-water-bundle", "standard_unit", "100ml", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("lotte-water-bundle", "standard_unit_price", 16.7, proposal_type=ProposalType.NORMALIZED_FIELD),
    ]

    audit = build_raw_ai_audit([record], proposals, batch_id="lottemart-unit-audit")
    item = db_item_from_review(record, proposals, {})
    blockers = publish_blockers(record, proposals, audit["issues"], {}, [])

    assert any(issue["code"] == "provider_unit_discrepancy" for issue in audit["issues"])
    assert not any(issue["code"] == "inflated_confidence_after_validation_failure" for issue in audit["issues"])
    assert item["display_unit"] == "2L×6"
    assert item["standard_unit"] == "L"
    assert item["standard_unit_price"] == pytest.approx(166.67)
    assert blockers == []


def test_publish_blockers_do_not_require_package_fields_without_package_signal() -> None:
    record = RawCrawlRecord(
        raw_record_id="service-ticket",
        source_name="emart",
        source_record_key="service-ticket",
        source_url="https://emart.example/service-ticket",
        raw_title="[쓱전용 할인] 호텔 뷔페 1인 식사권",
        raw_price=99000,
        raw_payload={
            "source_url": "https://emart.example/service-ticket",
            "image_url": "https://emart.example/service-ticket.jpg",
        },
    )
    proposals = [
        _proposal("service-ticket", "canonical_name", "호텔 뷔페 1인 식사권", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("service-ticket", "category_id", "daily.detergent", proposal_type=ProposalType.CATEGORY),
        _proposal("service-ticket", "keywords", ["식사권"], proposal_type=ProposalType.KEYWORD),
    ]

    blockers = publish_blockers(record, proposals, [], {}, [])

    assert not any("missing DB-admin package field" in blocker for blocker in blockers)


def test_publish_blockers_accept_reference_unit_without_false_package_requirement() -> None:
    record = RawCrawlRecord(
        raw_record_id="variable-weight-meat",
        source_name="emart",
        source_record_key="variable-weight-meat",
        source_url="https://emart.example/meat",
        raw_title="미국냉장프라임윗등심살",
        raw_price=4980,
        raw_payload={
            "unit": "100g",
            "source_url": "https://emart.example/meat",
            "image_url": "https://emart.example/meat.jpg",
        },
    )
    proposals = [
        _proposal("variable-weight-meat", "canonical_name", "미국냉장프라임윗등심살", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("variable-weight-meat", "category_id", "meat.beef", proposal_type=ProposalType.CATEGORY),
        _proposal("variable-weight-meat", "keywords", ["소고기"], proposal_type=ProposalType.KEYWORD),
    ]

    item = db_item_from_review(record, proposals, {})
    blockers = publish_blockers(record, proposals, [], {}, [])

    assert item["display_unit"] is None
    assert item["package_quantity"] is None
    assert not any("missing DB-admin package field" in blocker for blocker in blockers)


def test_db_item_ignores_zero_package_quantity_from_source() -> None:
    record = RawCrawlRecord(
        raw_record_id="zero-package",
        source_name="emart",
        source_record_key="zero-package",
        source_url="https://emart.example/zero-package",
        raw_title="전단 예약상품 0g",
        raw_price=1980,
        raw_payload={
            "package_quantity": 0,
            "package_unit": "g",
            "source_url": "https://emart.example/zero-package",
            "image_url": "https://emart.example/zero-package.jpg",
        },
    )

    item = db_item_from_review(record, [], {})

    assert item["package_quantity"] is None


def test_publish_blockers_still_reject_partial_package_metadata() -> None:
    record = RawCrawlRecord(
        raw_record_id="partial-package",
        source_name="emart",
        source_record_key="partial-package",
        source_url="https://emart.example/partial",
        raw_title="소용량 생활용품",
        raw_price=1980,
        raw_payload={
            "source_url": "https://emart.example/partial",
            "image_url": "https://emart.example/partial.jpg",
        },
    )
    proposals = [
        _proposal("partial-package", "canonical_name", "소용량 생활용품", proposal_type=ProposalType.NORMALIZED_FIELD),
        _proposal("partial-package", "category_id", "daily.detergent", proposal_type=ProposalType.CATEGORY),
        _proposal("partial-package", "keywords", ["생활용품"], proposal_type=ProposalType.KEYWORD),
        _proposal("partial-package", "package_quantity", 2, proposal_type=ProposalType.NORMALIZED_FIELD),
    ]

    blockers = publish_blockers(record, proposals, [], {}, [])

    assert "data_quality: missing DB-admin package field display_unit" in blockers
    assert "data_quality: missing DB-admin package field package_unit" in blockers
