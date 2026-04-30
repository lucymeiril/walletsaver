"""
private control DB의 공유 계약.

control DB는 크롤링 원본, AI job, prompt/rulepack, 검수 이력, provider 설정 alias,
publish 실행 이력을 저장한다. public 웹이 읽는 데이터베이스가 아니므로 사용자에게
공개되면 안 되는 운영 메타데이터를 이 경계 안에 둔다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator

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
    min_request_interval_seconds: float = Field(default=1.0, ge=1.0)
    daily_budget_limit: Optional[float] = Field(default=None, ge=0)


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
