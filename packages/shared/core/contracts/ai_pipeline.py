"""
AI 데이터 파이프라인의 공유 계약.

왜 존재하는가:
    crawler-admin, ai-admin, db-admin, website가 같은 ORM을 공유하면 public/control DB
    분리와 독립 배포가 불가능해진다. 이 파일은 서비스 간에 오가는 DTO와 상태만
    정의하여 각 패키지가 서로의 내부 저장소 구현을 import하지 않도록 한다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..promotion_semantics import PriceState, PromotionPriceFacts, PromotionType


MAX_AI_BATCH_ITEMS = 30
# 2026-05-24: 2000자에서 8000자로 상향. 사용자가 본 422 폭주의 직접 원인.
# Gemma 4 26B (a4b-it) 등 production 타겟 모델은 8K+ 토큰 컨텍스트를 지원하므로
# 2000자 한도는 단일 상품 설명(2022자 사례)도 거부하게 만들어 운영 차단을
#야기했다. 12000자 운영자 상한(MAX_OPERATOR_AI_BATCH_PROMPT_CHARS)은 유지.
MAX_AI_BATCH_PROMPT_CHARS = 8000


class PipelineStatus(str, Enum):
    """Crawler -> AI -> Review -> Publish 데이터 생명주기."""

    RAW_INGESTED = "raw_ingested"
    AI_PROCESSING = "ai_processing"
    AI_PROPOSED = "ai_proposed"
    HUMAN_REVIEWING = "human_reviewing"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    PUBLISHING = "publishing"
    PENDING_DB_REVIEW = "pending_db_review"
    PUBLISHED = "published"
    PUBLISH_FAILED = "publish_failed"
    HELD = "held"
    NEEDS_REWORK = "needs_rework"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    DEAD_LETTER = "dead_letter"


class AIWorkerRole(str, Enum):
    """ai-admin의 역할별 전담 워커."""

    NORMALIZER = "normalizer"
    UNIT_CONVERTER = "unit_converter"
    CLASSIFIER = "classifier"
    CANONICAL_MATCHER = "canonical_matcher"
    KEYWORD_GENERATOR = "keyword_generator"
    PROMPT_CURATOR = "prompt_curator"
    DATA_AUDITOR = "data_auditor"


class ProposalType(str, Enum):
    """검수 큐에서 서로 다른 승인 흐름을 갖는 제안 타입."""

    NORMALIZED_FIELD = "normalized_field"
    CANONICAL_MATCH = "canonical_match"
    CATEGORY = "category"
    ATTRIBUTE_DEFINITION = "attribute_definition"
    ATTRIBUTE_VALUE = "attribute_value"
    KEYWORD = "keyword"
    ALIAS = "alias"


class ProviderKind(str, Enum):
    """초기 지원 AI provider 유형."""

    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class PublicReference(BaseModel):
    """물리적으로 분리된 public DB 사이를 잇는 안정 ID."""

    public_id: str = Field(min_length=3, max_length=120)
    entity_type: Literal["product", "variant", "offer"]
    projection_version: Optional[str] = None


class RawCrawlRecord(BaseModel):
    """
    crawler-admin이 생산하는 불변 원본 레코드.

    원본 제목/가격/URL은 AI 정규화 결과로 덮어쓰면 안 된다. 재처리, 감사, 롤백을
    위해 raw_payload와 source fields를 그대로 보존한다.
    """

    model_config = ConfigDict(frozen=True)

    raw_record_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    source_record_key: Optional[str] = None
    source_url: Optional[str] = None
    raw_title: str = Field(min_length=1)
    raw_price: Optional[int] = Field(default=None, ge=0)
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    crawled_at: datetime = Field(default_factory=datetime.now)

    def prompt_text(self) -> str:
        """AI batch 길이 제한을 계산할 때 쓰는 record-safe 텍스트."""
        price = "" if self.raw_price is None else f" price={self.raw_price}"
        return f"{self.source_name}:{self.raw_record_id}:{self.raw_title}{price}"


class AIProviderRef(BaseModel):
    """provider secret 자체가 아니라 control DB/.env의 alias만 참조한다."""

    provider_kind: ProviderKind
    provider_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    secret_alias: Optional[str] = None


class PromptPackRef(BaseModel):
    """역할별 prompt/rulepack 버전 참조."""

    role: AIWorkerRole
    pack_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class AIJobBatch(BaseModel):
    """
    ai-admin 워커가 처리하는 record-safe 배치.

    한 요청은 최대 30개 record, 최대 8000자 prompt context로 제한한다. 긴 데이터는
    레코드 중간을 자르지 않고 배치 자체를 거절해 호출자가 안전하게 다시 나누게 한다.
    """

    batch_id: str = Field(min_length=1)
    role: AIWorkerRole
    provider: AIProviderRef
    prompt_pack: PromptPackRef
    records: list[RawCrawlRecord] = Field(min_length=1, max_length=MAX_AI_BATCH_ITEMS)
    created_at: datetime = Field(default_factory=datetime.now)

    @model_validator(mode="after")
    def validate_prompt_limit(self) -> "AIJobBatch":
        total_chars = sum(len(record.prompt_text()) for record in self.records)
        if total_chars > MAX_AI_BATCH_PROMPT_CHARS:
            raise ValueError(
                f"AI batch prompt text is {total_chars} chars; "
                f"max is {MAX_AI_BATCH_PROMPT_CHARS}"
            )
        return self


class FieldProvenance(BaseModel):
    """AI/인간이 만든 필드 값의 추적 정보."""

    raw_record_id: str = Field(min_length=1)
    source_field: Optional[str] = None
    evidence_text: str = Field(min_length=1)
    worker_role: AIWorkerRole
    provider: Optional[AIProviderRef] = None
    prompt_pack: Optional[PromptPackRef] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


class FieldProposal(BaseModel):
    """검수 가능한 정규화 필드 제안."""

    proposal_id: str = Field(min_length=1)
    proposal_type: ProposalType
    target_field: str = Field(min_length=1)
    proposed_value: Any
    status: PipelineStatus = PipelineStatus.AI_PROPOSED
    provenance: FieldProvenance
    alternatives: list[Any] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)


class CanonicalProductDraft(BaseModel):
    """승인 전 canonical Product 초안."""

    canonical_name: str = Field(min_length=1)
    brand: Optional[str] = None
    category_id: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProductVariantDraft(BaseModel):
    """승인 전 ProductVariant 초안."""

    canonical_product_public_id: Optional[str] = None
    variant_name: str = Field(min_length=1)
    package_quantity: Optional[float] = Field(default=None, gt=0)
    package_unit: Optional[str] = None
    display_unit: Optional[str] = None
    bundle_count: int = Field(default=1, ge=1)
    standard_unit: Optional[str] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class SaleOfferDraft(BaseModel):
    """승인 전 source-specific 판매/할인 이벤트 초안."""

    source_name: str = Field(min_length=1)
    source_record_key: Optional[str] = None
    source_title: str = Field(min_length=1)
    source_url: Optional[str] = None
    image_url: Optional[str] = None
    price_state: PriceState = PriceState.NORMAL
    promotion_type: PromotionType = PromotionType.UNKNOWN
    price: Optional[int] = Field(default=None, gt=0)
    original_price: Optional[int] = Field(default=None, gt=0)
    discount_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    event_name: Optional[str] = None
    standard_unit_price: Optional[float] = Field(default=None, ge=0)
    price_per_100g: Optional[float] = Field(default=None, ge=0)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    raw_record_id: str = Field(min_length=1)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)
    audit_provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_offer_semantics(self) -> "SaleOfferDraft":
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must be >= valid_from")
        if self.price_state == PriceState.NORMAL and self.price is None:
            raise ValueError("normal sale offers require price")
        facts = PromotionPriceFacts.from_source(
            current_price=self.price,
            original_price=self.original_price,
            discount_rate=self.discount_rate,
            price_state=self.price_state,
            promotion_type=self.promotion_type,
        ).with_safe_calculations()
        self.price = facts.current_price
        self.original_price = facts.original_price
        self.discount_rate = facts.discount_rate
        self.price_state = facts.price_state
        self.promotion_type = facts.promotion_type
        return self


class ProductOfferDraft(BaseModel):
    """
    검수 완료 원본 1건이 public catalog에 투영될 때의 typed aggregate.

    Product(대표 상품), ProductVariant(용량/속성), SaleOffer(판매 이벤트)를 한 번에
    검증해 publish 경계에서 ad-hoc dict가 image/original_price/unit evidence를 누락하지
    않게 한다.
    """

    product: CanonicalProductDraft
    variant: ProductVariantDraft
    offer: SaleOfferDraft
    raw_record: RawCrawlRecord
    audit_provenance: dict[str, Any] = Field(default_factory=dict)

    def to_db_admin_discount_item(self) -> dict[str, Any]:
        """db-admin의 기존 DiscountItem ingestion 경계로 보낼 보존형 payload."""
        attributes = {**self.product.attributes, **self.variant.attributes}
        discount_percent = (
            round(self.offer.discount_rate * 100, 2)
            if self.offer.discount_rate is not None and self.offer.discount_rate <= 1
            else None
        )
        raw_data = {
            "raw_record": self.raw_record.model_dump(mode="json"),
            "raw_payload": self.raw_record.raw_payload,
            "canonical_product": self.product.model_dump(mode="json"),
            "product_variant": self.variant.model_dump(mode="json"),
            "sale_offer": self.offer.model_dump(mode="json"),
            "price_semantics": {
                "price_state": self.offer.price_state.value,
                "promotion_type": self.offer.promotion_type.value,
                "comparable_price_available": PromotionPriceFacts.from_source(
                    current_price=self.offer.price,
                    original_price=self.offer.original_price,
                    discount_rate=self.offer.discount_rate,
                    price_state=self.offer.price_state,
                    promotion_type=self.offer.promotion_type,
                ).comparable_price_available,
            },
            "attributes": attributes,
            "raw_evidence": self.offer.raw_evidence,
            "audit_provenance": {**self.audit_provenance, **self.offer.audit_provenance},
        }
        return {
            "name": self.product.canonical_name,
            "canonical_name": self.product.canonical_name,
            "source_title": self.offer.source_title,
            "sale_price": self.offer.price,
            "current_price": self.offer.price,
            "original_price": self.offer.original_price,
            "discount_percent": discount_percent,
            "discount_rate": discount_percent,
            "price_state": self.offer.price_state.value,
            "promotion_type": self.offer.promotion_type.value,
            "source": self.offer.source_name,
            "store": self.offer.source_name,
            "source_url": self.offer.source_url,
            "detail_url": self.offer.source_url,
            "image_url": self.offer.image_url,
            "event_name": self.offer.event_name,
            "valid_from": self.offer.valid_from,
            "valid_to": self.offer.valid_to,
            "unit": self.variant.display_unit or self.variant.package_unit or self.variant.standard_unit or "개",
            "display_unit": self.variant.display_unit,
            "package_quantity": self.variant.package_quantity,
            "package_unit": self.variant.package_unit,
            "bundle_count": self.variant.bundle_count,
            "standard_unit": self.variant.standard_unit,
            "standard_unit_price": self.offer.standard_unit_price,
            "price_per_100g": self.offer.price_per_100g,
            "category": self.product.category_id,
            "category_id": self.product.category_id,
            "keywords": self.product.keywords,
            "attributes": attributes,
            "raw_data": raw_data,
            "raw_record_id": self.raw_record.raw_record_id,
            "source_record_key": self.offer.source_record_key,
            "ai_review_audit": raw_data["audit_provenance"],
        }


class PublishProjectionRequest(BaseModel):
    """db-admin이 승인 데이터를 public catalog/pricing DB로 publish할 때 쓰는 계약."""

    publish_run_id: str = Field(min_length=1)
    approved_record_ids: list[str] = Field(min_length=1)
    target_projection_version: str = Field(min_length=1)
    requested_by: str = Field(min_length=1)
    allow_republish: bool = False


class CatalogSnapshotManifest(BaseModel):
    """브라우저 캐시/델타 동기화를 위한 public catalog snapshot 계약."""

    snapshot_version: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=datetime.now)
    categories_version: str
    attributes_version: str
    keywords_version: str
    product_dictionary_version: str
    delta_from: Optional[str] = None
