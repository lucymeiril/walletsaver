"""
private control DB의 공유 계약.

control DB는 크롤링 원본, AI job, prompt/rulepack, 검수 이력, provider 설정 alias,
publish 실행 이력을 저장한다. public 웹이 읽는 데이터베이스가 아니므로 사용자에게
공개되면 안 되는 운영 메타데이터를 이 경계 안에 둔다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Optional
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from .ai_pipeline import AIWorkerRole, PipelineStatus, ProposalType, ProviderKind


class ControlJobStatus(str, Enum):
    """DB-backed job queue 상태."""

    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    CANCELLED = "cancelled"


class ReviewDecision(str, Enum):
    """검수자가 제안에 내릴 수 있는 결정."""

    APPROVE = "approve"
    CORRECT = "correct"
    REJECT = "reject"
    MERGE = "merge"
    NEEDS_REWORK = "needs_rework"
    DEFER = "defer"


class PromptPackStatus(str, Enum):
    """prompt/rulepack 릴리즈 상태."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


class ProductMatchProvenanceSource(str, Enum):
    """Who/what taught the source signature -> canonical product match."""

    AI = "ai"
    PROVIDER = "provider"
    HUMAN = "human"


class ProductMatchStatus(str, Enum):
    """Review lifecycle for learned product matches."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProductMatchTargetType(str, Enum):
    """The catalog/entity level a source-specific match points at."""

    SOURCE_LISTING = "source_listing"
    VARIANT = "variant"
    CANONICAL_PRODUCT = "canonical_product"
    CATEGORY_CANDIDATE = "category_candidate"


_SECRET_METADATA_KEY_PARTS = ("secret", "api_key", "apikey", "password", "token")
_VOLATILE_SIGNATURE_FIELD_PATTERN = re.compile(
    r"(?i)(^|[;,\|\s])"
    r"(?:image_url|detail_url|product_display_image|display_image|thumbnail_url|crawled_at)"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s;,\|]+)"
)
_URL_PATTERN = re.compile(r"https?://[^\s;,\|]+", flags=re.IGNORECASE)


def _strip_url_query_and_fragment(match: re.Match[str]) -> str:
    parts = urlsplit(match.group(0))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def normalize_product_signature_key(raw_signature: str) -> str:
    """Return a stable exact-match key for source product signatures."""

    normalized = unicodedata.normalize("NFKC", raw_signature).strip().lower()
    normalized = _VOLATILE_SIGNATURE_FIELD_PATTERN.sub(" ", normalized)
    normalized = _URL_PATTERN.sub(_strip_url_query_and_fragment, normalized)
    normalized = re.sub(r"[^\w.-]+", "-", normalized, flags=re.UNICODE)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-_.")
    if not normalized:
        raise ValueError("signature_key must contain at least one searchable token")
    return normalized


def normalize_match_text(value: str) -> str:
    """Normalize source titles/patterns for strict source-specific matching."""

    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def normalize_package_signature(value: str) -> str:
    """Normalize package signatures while preserving package/variant distinctions."""

    return normalize_product_signature_key(value)


def _assert_no_secret_bearing_metadata(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _SECRET_METADATA_KEY_PARTS):
                raise ValueError(f"secret-bearing metadata is not allowed at {path}.{key}")
            _assert_no_secret_bearing_metadata(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_secret_bearing_metadata(child, path=f"{path}[{index}]")


class RawCrawlBatchContract(BaseModel):
    """crawler-admin이 control DB에 등록하는 원본 batch 메타데이터."""

    batch_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    crawler_name: str = Field(min_length=1)
    item_count: int = Field(ge=0)
    schema_type: str = Field(min_length=1)
    status: PipelineStatus = PipelineStatus.RAW_INGESTED
    source_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    raw_artifact_uri: Optional[str] = None


class RetryPolicyContract(BaseModel):
    """
    provider 밴/무한 재시도를 막기 위한 수동 조절 가능한 재시도 정책.

    min_delay_seconds를 1초 이상으로 강제하여 0.1초 3연속 호출 같은 위험한 기본값을
    막는다. 실제 워커는 provider별 cooldown과 함께 이 값을 적용한다.
    """

    max_attempts: int = Field(default=3, ge=0, le=20)
    min_delay_seconds: float = Field(default=5.0, ge=1.0)
    max_delay_seconds: float = Field(default=300.0, ge=1.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)
    provider_cooldown_seconds: float = Field(default=0.0, ge=0.0)
    dead_letter_after_attempts: int = Field(default=3, ge=1, le=50)

    @model_validator(mode="after")
    def validate_policy(self) -> "RetryPolicyContract":
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("max_delay_seconds must be >= min_delay_seconds")
        if self.dead_letter_after_attempts < max(1, self.max_attempts):
            raise ValueError("dead_letter_after_attempts must be >= max_attempts")
        return self


class ControlJobContract(BaseModel):
    """DB-backed job queue의 job 계약."""

    job_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    role: AIWorkerRole
    status: ControlJobStatus = ControlJobStatus.QUEUED
    priority: int = Field(default=100, ge=0, le=1000)
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    not_before: Optional[datetime] = None
    retry_policy: RetryPolicyContract = Field(default_factory=RetryPolicyContract)
    attempts: int = Field(default=0, ge=0)
    error_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class WorkerAttemptContract(BaseModel):
    """AI worker/provider 호출 1회의 감사 가능한 기록."""

    attempt_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    role: AIWorkerRole
    provider_kind: ProviderKind
    provider_name: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    prompt_pack_id: str = Field(min_length=1)
    prompt_pack_version: str = Field(min_length=1)
    request_chars: int = Field(ge=0)
    item_count: int = Field(ge=0)
    status: ControlJobStatus
    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    response_artifact_uri: Optional[str] = None


class ProviderConfigContract(BaseModel):
    """secret value가 아닌 alias만 저장하는 provider 설정."""

    provider_id: str = Field(min_length=1)
    provider_kind: ProviderKind
    display_name: str = Field(min_length=1)
    base_url: Optional[str] = None
    default_model: str = Field(min_length=1)
    secret_alias: Optional[str] = None
    is_enabled: bool = True
    max_concurrent_jobs: int = Field(default=1, ge=1, le=20)
    min_request_interval_seconds: float = Field(default=12.0, ge=1.0)
    max_provider_calls_per_minute: int = Field(default=5, ge=1, le=120)
    max_provider_calls_per_day: int = Field(default=300, ge=1, le=100000)
    provider_retry_max_attempts: int = Field(default=3, ge=1, le=20)
    provider_retry_min_delay_seconds: float = Field(default=10.0, ge=1.0)
    provider_retry_max_delay_seconds: float = Field(default=60.0, ge=1.0)
    daily_budget_limit: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_live_call_limits(self) -> "ProviderConfigContract":
        if self.provider_retry_max_delay_seconds < self.provider_retry_min_delay_seconds:
            raise ValueError("provider_retry_max_delay_seconds must be >= provider_retry_min_delay_seconds")
        return self


class PromptPackContract(BaseModel):
    """역할별 prompt/rulepack 버전 관리 계약."""

    pack_id: str = Field(min_length=1)
    role: AIWorkerRole
    version: str = Field(min_length=1)
    status: PromptPackStatus = PromptPackStatus.DRAFT
    content: str = Field(min_length=1)
    changelog: str = ""
    created_by: str = Field(min_length=1)
    approved_by: Optional[str] = None
    activated_at: Optional[datetime] = None
    backup_of_version: Optional[str] = None


class ReviewDecisionContract(BaseModel):
    """사람이 AI 제안에 내린 결정을 이후 학습/감사에 재사용한다."""

    decision_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_type: ProposalType
    decision: ReviewDecision
    reviewer_id: str = Field(min_length=1)
    corrected_value: Any = None
    reason: str = ""
    create_learning_rule: bool = False
    decided_at: datetime = Field(default_factory=datetime.now)


class ProductMatchContract(BaseModel):
    """Strict source-specific match used to recognize known source listings/variants.

    The matching table decides whether a newly collected source row is the same known
    source listing/variant/product. Source product IDs are only supporting signals;
    approved title evidence plus package equality is required for strict auto reuse.
    """

    match_id: Optional[str] = None
    source_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    signature_key: str = Field(min_length=1)
    target_type: ProductMatchTargetType = ProductMatchTargetType.CANONICAL_PRODUCT
    target_id: Optional[str] = None
    canonical_product_id: Optional[str] = None
    canonical_product_name: str = Field(min_length=1)
    category_id: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    unit_metadata: dict[str, Any] = Field(default_factory=dict)
    allowed_title_patterns: list[str] = Field(default_factory=list)
    normalized_title_variants: list[str] = Field(default_factory=list)
    blocked_title_patterns: list[str] = Field(default_factory=list)
    package_signature: Optional[str] = None
    package_signature_required: bool = True
    source_product_id_history: list[str] = Field(default_factory=list)
    provenance_source: ProductMatchProvenanceSource
    provider_name: Optional[str] = None
    model_name: Optional[str] = None
    raw_record_id: Optional[str] = None
    batch_id: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    status: ProductMatchStatus = ProductMatchStatus.PROPOSED
    audit_reason: str = Field(min_length=1)
    audit_metadata: dict[str, Any] = Field(default_factory=dict)
    reviewed_by: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    version: int = Field(default=1, ge=1)
    is_active: bool = True
    disabled_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @field_validator("signature_key")
    @classmethod
    def normalize_signature_key(cls, value: str) -> str:
        return normalize_product_signature_key(value)

    @model_validator(mode="after")
    def validate_safe_metadata(self) -> "ProductMatchContract":
        _assert_no_secret_bearing_metadata(self.unit_metadata, path="unit_metadata")
        _assert_no_secret_bearing_metadata(self.audit_metadata, path="audit_metadata")
        self.allowed_title_patterns = [
            normalize_match_text(pattern)
            for pattern in self.allowed_title_patterns
            if normalize_match_text(pattern)
        ]
        self.normalized_title_variants = [
            normalize_match_text(variant)
            for variant in self.normalized_title_variants
            if normalize_match_text(variant)
        ]
        if not self.normalized_title_variants:
            self.normalized_title_variants = list(self.allowed_title_patterns)
        self.blocked_title_patterns = [
            normalize_match_text(pattern)
            for pattern in self.blocked_title_patterns
            if normalize_match_text(pattern)
        ]
        if self.package_signature is not None:
            self.package_signature = normalize_package_signature(self.package_signature)
        self.source_product_id_history = [
            str(value).strip()
            for value in self.source_product_id_history
            if str(value).strip()
        ]
        if self.target_id is None:
            self.target_id = self.canonical_product_id
        return self


class LearnedKnowledgeContract(BaseModel):
    """provider 독립 학습 지식베이스 항목."""

    knowledge_id: str = Field(min_length=1)
    knowledge_type: str = Field(min_length=1)
    source_name: Optional[str] = None
    pattern: str = Field(min_length=1)
    target_value: Any
    negative_examples: list[str] = Field(default_factory=list)
    positive_examples: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_from_decision_id: Optional[str] = None
    applied_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
