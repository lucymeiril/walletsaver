"""ai-admin control DB SQLAlchemy 모델.

설계 원칙:
    * SQLite/Postgres 양쪽에서 같은 DDL이 동작하도록 JSON/Text/DateTime/Integer/String
      만 쓴다.
    * 비밀값은 절대 저장하지 않는다. ProviderConfig는 `secret_alias`만 가진다.
    * 공유 contracts(Pydantic DTO)와 1:1로 매핑되며, ORM 모델이 contracts를
      대체하지 않는다 (직렬화/검증은 여전히 Pydantic 쪽이 담당한다).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """ai-admin control DB의 SQLAlchemy declarative base."""


class RawCrawlBatch(Base):
    __tablename__ = "raw_crawl_batches"

    batch_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    crawler_name: Mapped[str] = mapped_column(String(120), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_artifact_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    records: Mapped[list["RawCrawlRecord"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class RawCrawlRecord(Base):
    __tablename__ = "raw_crawl_records"

    raw_record_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    batch_id: Mapped[str] = mapped_column(
        String(120),
        ForeignKey("raw_crawl_batches.batch_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    batch: Mapped[RawCrawlBatch] = relationship(back_populates="records")


class AIJob(Base):
    __tablename__ = "ai_jobs"

    job_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    not_before: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class WorkerAttempt(Base):
    __tablename__ = "worker_attempts"

    attempt_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_pack_id: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_pack_version: Mapped[str] = mapped_column(String(64), nullable=False)
    request_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_artifact_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ProviderConfig(Base):
    """provider 설정. 비밀값(secret value)은 저장하지 않고 alias만 보관한다."""

    __tablename__ = "provider_configs"

    provider_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_model: Mapped[str] = mapped_column(String(120), nullable=False)
    secret_alias: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    min_request_interval_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=12.0
    )
    max_provider_calls_per_minute: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5
    )
    max_provider_calls_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300
    )
    provider_retry_max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    provider_retry_min_delay_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=10.0
    )
    provider_retry_max_delay_seconds: Mapped[float] = mapped_column(
        Float, nullable=False, default=60.0
    )
    daily_budget_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class PromptPack(Base):
    __tablename__ = "prompt_packs"

    pack_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    approved_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    backup_of_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class FieldProposal(Base):
    __tablename__ = "field_proposals"

    proposal_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_field: Mapped[str] = mapped_column(String(120), nullable=False)
    proposed_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    alternatives: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class KeywordProposal(Base):
    __tablename__ = "keyword_proposals"

    proposal_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    proposed_keyword: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    match_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    category_suggestion: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    triggering_records: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    source_values: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    persisted_keyword_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ReviewDecisionRecord(Base):
    __tablename__ = "review_decisions"

    decision_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    proposal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(120), nullable=False)
    corrected_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    create_learning_rule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class AIPublishRecord(Base):
    __tablename__ = "ai_publish_records"

    raw_record_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True, default="pending_review")
    ai_proposal_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    human_decision_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    eligibility_errors: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    db_ingestion_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    db_ingestion_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    publish_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requested_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class ProductMatch(Base):
    __tablename__ = "product_matches"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "source_name",
            "signature_key",
            name="uq_product_matches_source_signature",
        ),
    )

    match_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    signature_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False, default="canonical_product")
    target_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    canonical_product_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    canonical_product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    category_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    unit_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    allowed_title_patterns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    normalized_title_variants: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    blocked_title_patterns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    package_signature: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    package_signature_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source_product_id_history: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    provenance_source: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    raw_record_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    batch_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    audit_reason: Mapped[str] = mapped_column(Text, nullable=False)
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    disabled_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )


class LearnedKnowledge(Base):
    __tablename__ = "learned_knowledge"

    knowledge_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    knowledge_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    target_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    negative_examples: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    positive_examples: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_from_decision_id: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True
    )
    applied_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class LabelingRunLog(Base):
    """Per-labeling-run statistics for the match monitor dashboard."""

    __tablename__ = "labeling_run_logs"

    run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    mode: Mapped[str] = mapped_column(String(40), nullable=False, default="dry_run")
    ai_provider_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="mock")
    total_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_initial: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_called: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_resolved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_escalated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gate_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gate_escalated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canonical_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    product_match_total_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    learned_knowledge_total_snapshot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    by_mart: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
