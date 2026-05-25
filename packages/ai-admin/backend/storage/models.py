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
    # §4-E v5 undo window — operator can rollback within `undoable_until`.
    # `downstream_application_count` rises every time this decision was reused as a
    # learned alias / canonical match in a subsequent labeling run; once > 0 the undo
    # turns into "cascade revert" mode (must explicitly cascade).
    # `reused_in_run_ids` lists `LabelingRunLog.run_id` for the same purpose.
    undoable_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    downstream_application_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reused_in_run_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_undone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    undone_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    undone_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


class AliasAuditLog(Base):
    """§4-B alias audit — every alias add / disable / re-enable / decay is logged.

    The product-match store and `LearnedKnowledge` are auto-learning assets. Spec §14
    forbids sealing them, so we log every change with provenance + recall path
    (`recoverable_via_decision_id`) instead.
    """

    __tablename__ = "alias_audit_log"

    audit_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    alias_kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # one of: keyword_alias, category_alias, product_match, learned_knowledge
    alias_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # create, disable, re-enable, decay, recall, recover
    before_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    after_value: Mapped[Any] = mapped_column(JSON, nullable=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False, default="system")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    related_decision_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    related_match_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    related_knowledge_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    recoverable_via_decision_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )


class BulkArchiveAuditRow(Base):
    """AI 제안 일괄 비우기(bulk-archive) 감사 + undo 토큰의 영속 저장소.

    설계 목적:
      * 운영자가 비운 제안의 스냅샷을 DB에 저장 (서버 재기동에도 30초 undo 유효).
      * `status` 컬럼 + atomic `UPDATE ... WHERE status='active'` 로 multi-worker
        race-free 단일 undo 보장 (CAS 패턴, rowcount==1 인 worker만 성공).
      * 만료된 토큰은 일정 주기로 status='expired' 로 전이.
    """

    __tablename__ = "bulk_archive_audit"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    reviewer_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    snapshots: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    archived_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", index=True
    )  # active | undone | expired
    archived_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    undone_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    undone_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


class UserFeedback(Base):
    """§9 — sourced from website / web-api 신고 (reports) endpoint.

    Captured here as a bounded queue so the AI learning loop can consume it
    (downvote-on-match, prompt-injection of past reports, etc.). Pure data ingest;
    consumers decide what to do with it.
    """

    __tablename__ = "user_feedback"

    feedback_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # one of: bad_match, wrong_category, wrong_canonical, missing_keyword, other
    raw_record_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    match_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    knowledge_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    category_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    reporter_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    # open → reviewed → applied / dismissed
    handled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    handled_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
    )


class ThresholdCalibration(Base):
    """§4-A 표본 본조건 — data-driven thresholds.

    Every periodic calibration writes one row per `metric_name`. The newest row is
    the active threshold; older rows stay for audit/regression.
    """

    __tablename__ = "threshold_calibration"

    calibration_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    # e.g. confidence_min, learned_alias_min_sources, learned_alias_min_titles,
    #      learned_alias_min_settled, vague_penalty_threshold
    value: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="percentile")
    method_params: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, index=True
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


# ══════════════════════════════════════════════════════
# p1-ai-admin-evidence-schema — BrandAliasEvidence
# ══════════════════════════════════════════════════════

class BrandAliasEvidence(Base):
    """AI가 제안한 brand_alias 근거(evidence) 적재 테이블.

    AI가 RawCrawlRecord 배치를 처리하면서 동일 brand의 이표기(예: '풀무원' vs '풀무원식품')를
    발견하면 이 테이블에 suggested 상태로 적재한다. 운영자가 approved/rejected로 전환한다.

    source_batch_ids:
        JSON array — 이 evidence를 생성한 RawCrawlBatch id 목록.
        복수 배치에서 같은 alias가 반복 등장하면 count가 올라가 evidence_score가 높아진다.

    evidence_score:
        0.0~1.0 — 배치 내 등장 빈도 + AI 확신도를 혼합한 점수.
        임계값(기본 0.6) 이상이면 operator 알림 대상.
    """

    __tablename__ = "brand_alias_evidence"

    evidence_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    brand_alias: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    canonical_brand: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="suggested", index=True
    )
    source_batch_ids: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    evidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    __table_args__ = (
        UniqueConstraint("brand_alias", "canonical_brand", name="uq_brand_alias_evidence"),
    )
