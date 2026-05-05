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
from services.review_publish import build_batch_publish_summary, build_publish_rows, db_item_from_review
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

    blocked = rows["emart-cabbage-keyword-blocked"]
    assert blocked["eligible"] is False
    assert any("pending DB keyword proposal" in blocker for blocker in blocked["blockers"])
    assert summary["batch_status"] == "partial_only"
    assert summary["eligible_count"] == 1
    assert summary["unresolved_keyword_proposal_count"] == 1


def test_db_admin_adapter_payload_is_built_from_publish_candidate() -> None:
    payload = build_db_admin_ingestion_payload(
        {
            "source_name": "emart",
            "item": {
                "raw_record_id": "emart-cabbage-ready",
                "source_url": "https://emart.example/products/cabbage",
            },
        }
    )

    assert payload["crawler_name"] == "ai-admin:emart"
    assert payload["schema_type"] == "DiscountItem"
    assert payload["strategy_used"] == "ai_review_publish"
    assert payload["items"][0]["raw_record_id"] == "emart-cabbage-ready"


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
