"""AI 데이터 파이프라인 공유 계약 테스트."""

import pytest
from pydantic import ValidationError

from shared.core.contracts.ai_pipeline import (
    AIJobBatch,
    AIProviderRef,
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProductOfferDraft,
    ProductVariantDraft,
    PromptPackRef,
    ProposalType,
    ProviderKind,
    RawCrawlRecord,
    CanonicalProductDraft,
    SaleOfferDraft,
)


def make_record(index: int, title: str = "알프스 탄탄포크 정육 행사") -> RawCrawlRecord:
    return RawCrawlRecord(
        raw_record_id=f"raw-{index}",
        source_name="emart",
        source_record_key=f"sku-{index}",
        raw_title=title,
        raw_price=12900,
    )


def make_provider() -> AIProviderRef:
    return AIProviderRef(
        provider_kind=ProviderKind.GEMINI,
        provider_name="gemini-main",
        model_name="gemini-2.5-pro",
        secret_alias="GEMINI_API_KEY",
    )


def make_prompt_pack(role: AIWorkerRole) -> PromptPackRef:
    return PromptPackRef(role=role, pack_id=f"{role.value}-default", version="1")


def test_raw_crawl_record_is_immutable():
    record = make_record(1)

    with pytest.raises(ValidationError):
        record.raw_title = "AI가 원본명을 덮어쓰면 안 됨"


def test_ai_job_batch_allows_at_most_30_records():
    records = [make_record(i) for i in range(31)]

    with pytest.raises(ValidationError):
        AIJobBatch(
            batch_id="batch-too-many",
            role=AIWorkerRole.CLASSIFIER,
            provider=make_provider(),
            prompt_pack=make_prompt_pack(AIWorkerRole.CLASSIFIER),
            records=records,
        )


def test_ai_job_batch_rejects_prompt_text_over_2000_chars_without_splitting_records():
    records = [make_record(i, title="긴상품명" * 60) for i in range(10)]

    with pytest.raises(ValidationError, match="max is 2000"):
        AIJobBatch(
            batch_id="batch-too-long",
            role=AIWorkerRole.NORMALIZER,
            provider=make_provider(),
            prompt_pack=make_prompt_pack(AIWorkerRole.NORMALIZER),
            records=records,
        )


def test_ai_job_batch_accepts_record_safe_batch():
    batch = AIJobBatch(
        batch_id="batch-ok",
        role=AIWorkerRole.UNIT_CONVERTER,
        provider=make_provider(),
        prompt_pack=make_prompt_pack(AIWorkerRole.UNIT_CONVERTER),
        records=[make_record(1), make_record(2)],
    )

    assert batch.role == AIWorkerRole.UNIT_CONVERTER
    assert len(batch.records) == 2


def test_field_proposal_requires_field_level_provenance():
    proposal = FieldProposal(
        proposal_id="proposal-1",
        proposal_type=ProposalType.NORMALIZED_FIELD,
        target_field="variant.attributes.storage_state",
        proposed_value="chilled",
        provenance=FieldProvenance(
            raw_record_id="raw-1",
            source_field="raw_title",
            evidence_text="냉장 삼겹살",
            worker_role=AIWorkerRole.CLASSIFIER,
            provider=make_provider(),
            prompt_pack=make_prompt_pack(AIWorkerRole.CLASSIFIER),
            confidence=0.91,
            reviewed_by="admin",
        ),
    )

    assert proposal.status == PipelineStatus.AI_PROPOSED
    assert proposal.provenance.confidence == 0.91
    assert proposal.provenance.worker_role == AIWorkerRole.CLASSIFIER


def test_product_offer_draft_preserves_customer_safe_offer_variant_and_audit_fields():
    raw = RawCrawlRecord(
        raw_record_id="emart-beef-300g",
        source_name="emart",
        source_record_key="sku-beef",
        source_url="https://emart.example/beef",
        raw_title="[냉장] 한우 불고기1+등급300g",
        raw_price=14850,
        raw_payload={"unit": "100g", "image_url": "https://emart.example/beef.jpg"},
    )

    draft = ProductOfferDraft(
        product=CanonicalProductDraft(
            canonical_name="한우 불고기",
            category_id="meat.beef",
            keywords=["한우", "불고기"],
            attributes={"storage_type": "chilled", "origin": "domestic", "quality_grade": "1+"},
        ),
        variant=ProductVariantDraft(
            variant_name=raw.raw_title,
            package_quantity=300,
            package_unit="g",
            display_unit="300g",
            standard_unit="kg",
            attributes={"cut": "bulgogi"},
        ),
        offer=SaleOfferDraft(
            source_name="emart",
            source_record_key="sku-beef",
            source_title=raw.raw_title,
            source_url=raw.source_url,
            image_url="https://emart.example/beef.jpg",
            price=14850,
            original_price=19800,
            standard_unit_price=49500,
            price_per_100g=4950,
            raw_record_id=raw.raw_record_id,
            raw_evidence={"raw_unit": "100g"},
        ),
        raw_record=raw,
        audit_provenance={"proposal_ids": ["name", "unit", "offer"]},
    )

    item = draft.to_db_admin_discount_item()

    assert item["source_title"] == raw.raw_title
    assert item["image_url"].endswith("beef.jpg")
    assert item["original_price"] == 19800
    assert item["discount_percent"] == 25
    assert item["package_quantity"] == 300
    assert item["price_per_100g"] == 4950
    assert item["raw_data"]["raw_evidence"]["raw_unit"] == "100g"
