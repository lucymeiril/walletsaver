"""ai-admin control DB repository.

각 repository는 SQLAlchemy ORM 모델과 Pydantic contract DTO 사이의 변환만 담당한다.
정책(예: lease, retry/backoff)은 shared `JobQueueService`가 가지므로 repository는
단순 CRUD에 가깝게 유지한다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.contracts.ai_pipeline import (
    FieldProposal as FieldProposalContract,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord as RawCrawlRecordContract,
)
from core.contracts.control_plane import (
    ControlJobContract,
    ControlJobStatus,
    LearnedKnowledgeContract,
    PromptPackContract,
    PromptPackStatus,
    ProviderConfigContract,
    RawCrawlBatchContract,
    ReviewDecisionContract,
    ReviewDecision,
    RetryPolicyContract,
    WorkerAttemptContract,
)
from core.contracts.ai_pipeline import AIWorkerRole, ProviderKind

from .models import (
    AIJob,
    FieldProposal,
    KeywordProposal,
    LearnedKnowledge,
    PromptPack,
    ProviderConfig,
    RawCrawlBatch,
    RawCrawlRecord,
    ReviewDecisionRecord,
    WorkerAttempt,
)


# --------------------------------------------------------------------------------------
# RawCrawlBatch
# --------------------------------------------------------------------------------------


class RawCrawlBatchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: RawCrawlBatchContract) -> None:
        existing = self.session.get(RawCrawlBatch, contract.batch_id)
        data = dict(
            source_name=contract.source_name,
            crawler_name=contract.crawler_name,
            item_count=contract.item_count,
            schema_type=contract.schema_type,
            status=contract.status.value,
            source_url=contract.source_url,
            raw_artifact_uri=contract.raw_artifact_uri,
            created_at=contract.created_at,
        )
        if existing is None:
            self.session.add(RawCrawlBatch(batch_id=contract.batch_id, **data))
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def get(self, batch_id: str) -> Optional[RawCrawlBatchContract]:
        row = self.session.get(RawCrawlBatch, batch_id)
        return _batch_to_contract(row) if row else None

    def list(self) -> list[RawCrawlBatchContract]:
        rows = self.session.execute(select(RawCrawlBatch)).scalars().all()
        return [_batch_to_contract(r) for r in rows]

    def save_records(self, batch_id: str, records: list[RawCrawlRecordContract]) -> None:
        for record in records:
            existing = self.session.get(RawCrawlRecord, record.raw_record_id)
            data = dict(
                batch_id=batch_id,
                source_name=record.source_name,
                source_record_key=record.source_record_key,
                source_url=record.source_url,
                raw_title=record.raw_title,
                raw_price=record.raw_price,
                raw_payload=record.raw_payload,
                crawled_at=record.crawled_at,
            )
            if existing is None:
                self.session.add(
                    RawCrawlRecord(raw_record_id=record.raw_record_id, **data)
                )
            else:
                for k, v in data.items():
                    setattr(existing, k, v)
        self.session.flush()

    def list_records(self, batch_id: str) -> list[RawCrawlRecordContract]:
        stmt = select(RawCrawlRecord).where(RawCrawlRecord.batch_id == batch_id)
        rows = self.session.execute(stmt).scalars().all()
        return [_record_to_contract(r) for r in rows]

    def list_all_records(self) -> list[RawCrawlRecordContract]:
        rows = self.session.execute(select(RawCrawlRecord)).scalars().all()
        return [_record_to_contract(r) for r in rows]


def _batch_to_contract(row: RawCrawlBatch) -> RawCrawlBatchContract:
    return RawCrawlBatchContract(
        batch_id=row.batch_id,
        source_name=row.source_name,
        crawler_name=row.crawler_name,
        item_count=row.item_count,
        schema_type=row.schema_type,
        status=PipelineStatus(row.status),
        source_url=row.source_url,
        created_at=row.created_at,
        raw_artifact_uri=row.raw_artifact_uri,
    )


def _record_to_contract(row: RawCrawlRecord) -> RawCrawlRecordContract:
    return RawCrawlRecordContract(
        raw_record_id=row.raw_record_id,
        source_name=row.source_name,
        source_record_key=row.source_record_key,
        source_url=row.source_url,
        raw_title=row.raw_title,
        raw_price=row.raw_price,
        raw_payload=row.raw_payload or {},
        crawled_at=row.crawled_at,
    )


# --------------------------------------------------------------------------------------
# ProviderConfig
# --------------------------------------------------------------------------------------


class ProviderConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: ProviderConfigContract) -> None:
        existing = self.session.get(ProviderConfig, contract.provider_id)
        data = dict(
            provider_kind=contract.provider_kind.value,
            display_name=contract.display_name,
            base_url=contract.base_url,
            default_model=contract.default_model,
            secret_alias=contract.secret_alias,
            is_enabled=contract.is_enabled,
            max_concurrent_jobs=contract.max_concurrent_jobs,
            min_request_interval_seconds=contract.min_request_interval_seconds,
            daily_budget_limit=contract.daily_budget_limit,
        )
        if existing is None:
            self.session.add(ProviderConfig(provider_id=contract.provider_id, **data))
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def get(self, provider_id: str) -> Optional[ProviderConfigContract]:
        row = self.session.get(ProviderConfig, provider_id)
        return _provider_to_contract(row) if row else None

    def list(self) -> list[ProviderConfigContract]:
        rows = self.session.execute(select(ProviderConfig)).scalars().all()
        return [_provider_to_contract(r) for r in rows]


def _provider_to_contract(row: ProviderConfig) -> ProviderConfigContract:
    return ProviderConfigContract(
        provider_id=row.provider_id,
        provider_kind=ProviderKind(row.provider_kind),
        display_name=row.display_name,
        base_url=row.base_url,
        default_model=row.default_model,
        secret_alias=row.secret_alias,
        is_enabled=row.is_enabled,
        max_concurrent_jobs=row.max_concurrent_jobs,
        min_request_interval_seconds=row.min_request_interval_seconds,
        daily_budget_limit=row.daily_budget_limit,
    )


# --------------------------------------------------------------------------------------
# PromptPack
# --------------------------------------------------------------------------------------


class PromptPackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: PromptPackContract) -> None:
        existing = self.session.get(PromptPack, (contract.pack_id, contract.version))
        data = dict(
            role=contract.role.value,
            status=contract.status.value,
            content=contract.content,
            changelog=contract.changelog,
            created_by=contract.created_by,
            approved_by=contract.approved_by,
            activated_at=contract.activated_at,
            backup_of_version=contract.backup_of_version,
        )
        if existing is None:
            self.session.add(
                PromptPack(
                    pack_id=contract.pack_id,
                    version=contract.version,
                    **data,
                )
            )
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def get(
        self, pack_id: str, version: Optional[str] = None
    ) -> Optional[PromptPackContract]:
        if version is not None:
            row = self.session.get(PromptPack, (pack_id, version))
            return _pack_to_contract(row) if row else None
        stmt = select(PromptPack).where(PromptPack.pack_id == pack_id)
        row = self.session.execute(stmt).scalars().first()
        return _pack_to_contract(row) if row else None

    def list_versions(self, pack_id: str) -> list[PromptPackContract]:
        stmt = select(PromptPack).where(PromptPack.pack_id == pack_id)
        rows = self.session.execute(stmt).scalars().all()
        return [_pack_to_contract(r) for r in rows]

    def list(self, *, role: Optional[AIWorkerRole] = None) -> list[PromptPackContract]:
        stmt = select(PromptPack)
        if role is not None:
            stmt = stmt.where(PromptPack.role == role.value)
        rows = self.session.execute(stmt).scalars().all()
        return [_pack_to_contract(r) for r in rows]


def _pack_to_contract(row: PromptPack) -> PromptPackContract:
    return PromptPackContract(
        pack_id=row.pack_id,
        role=AIWorkerRole(row.role),
        version=row.version,
        status=PromptPackStatus(row.status),
        content=row.content,
        changelog=row.changelog,
        created_by=row.created_by,
        approved_by=row.approved_by,
        activated_at=row.activated_at,
        backup_of_version=row.backup_of_version,
    )


# --------------------------------------------------------------------------------------
# FieldProposal
# --------------------------------------------------------------------------------------


class FieldProposalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: FieldProposalContract) -> None:
        existing = self.session.get(FieldProposal, contract.proposal_id)
        data = dict(
            proposal_type=contract.proposal_type.value,
            target_field=contract.target_field,
            proposed_value=contract.proposed_value,
            status=contract.status.value,
            provenance=contract.provenance.model_dump(mode="json"),
            alternatives=list(contract.alternatives),
            created_at=contract.created_at,
        )
        if existing is None:
            self.session.add(FieldProposal(proposal_id=contract.proposal_id, **data))
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def get(self, proposal_id: str) -> Optional[FieldProposalContract]:
        row = self.session.get(FieldProposal, proposal_id)
        return _proposal_to_contract(row) if row else None

    def list(
        self,
        *,
        status: Optional[PipelineStatus] = None,
        proposal_type: Optional[ProposalType] = None,
    ) -> list[FieldProposalContract]:
        stmt = select(FieldProposal)
        if status is not None:
            stmt = stmt.where(FieldProposal.status == status.value)
        if proposal_type is not None:
            stmt = stmt.where(FieldProposal.proposal_type == proposal_type.value)
        rows = self.session.execute(stmt).scalars().all()
        return [_proposal_to_contract(r) for r in rows]

    def delete(self, proposal_id: str) -> bool:
        row = self.session.get(FieldProposal, proposal_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.execute(
            delete(ReviewDecisionRecord).where(
                ReviewDecisionRecord.proposal_id == proposal_id
            )
        )
        self.session.flush()
        return True


def _proposal_to_contract(row: FieldProposal) -> FieldProposalContract:
    return FieldProposalContract(
        proposal_id=row.proposal_id,
        proposal_type=ProposalType(row.proposal_type),
        target_field=row.target_field,
        proposed_value=row.proposed_value,
        status=PipelineStatus(row.status),
        provenance=FieldProvenance.model_validate(row.provenance),
        alternatives=list(row.alternatives or []),
        created_at=row.created_at,
    )


# --------------------------------------------------------------------------------------
# KeywordProposal
# --------------------------------------------------------------------------------------


class KeywordProposalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now()
        existing = self.session.get(KeywordProposal, data["proposal_id"])
        payload = dict(
            proposed_keyword=data["proposed_keyword"],
            match_terms=list(data.get("match_terms") or []),
            category_suggestion=data.get("category_suggestion"),
            confidence=data.get("confidence"),
            reason=data.get("reason") or "",
            triggering_records=list(data.get("triggering_records") or []),
            source_values=list(data.get("source_values") or []),
            status=data.get("status", PipelineStatus.AI_PROPOSED.value),
            reviewer_id=data.get("reviewer_id"),
            rejection_reason=data.get("rejection_reason"),
            persisted_keyword_id=data.get("persisted_keyword_id"),
            updated_at=data.get("updated_at") or now,
        )
        if existing is None:
            self.session.add(
                KeywordProposal(
                    proposal_id=data["proposal_id"],
                    created_at=data.get("created_at") or now,
                    decided_at=data.get("decided_at"),
                    **payload,
                )
            )
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
            if "decided_at" in data:
                existing.decided_at = data.get("decided_at")
        self.session.flush()
        return self.get(data["proposal_id"]) or data

    def get(self, proposal_id: str) -> Optional[dict[str, Any]]:
        row = self.session.get(KeywordProposal, proposal_id)
        return _keyword_proposal_to_dict(row) if row else None

    def list(self, *, status: Optional[PipelineStatus] = None) -> list[dict[str, Any]]:
        stmt = select(KeywordProposal)
        if status is not None:
            stmt = stmt.where(KeywordProposal.status == status.value)
        rows = self.session.execute(stmt).scalars().all()
        return [_keyword_proposal_to_dict(row) for row in rows]

    def list_for_raw_record(self, raw_record_id: str) -> list[dict[str, Any]]:
        return [
            proposal
            for proposal in self.list()
            if any(
                record.get("raw_record_id") == raw_record_id
                for record in proposal.get("triggering_records", [])
                if isinstance(record, dict)
            )
        ]


def _keyword_proposal_to_dict(row: KeywordProposal) -> dict[str, Any]:
    return {
        "proposal_id": row.proposal_id,
        "proposed_keyword": row.proposed_keyword,
        "match_terms": list(row.match_terms or []),
        "category_suggestion": row.category_suggestion,
        "confidence": row.confidence,
        "reason": row.reason,
        "triggering_records": list(row.triggering_records or []),
        "source_values": list(row.source_values or []),
        "status": row.status,
        "reviewer_id": row.reviewer_id,
        "rejection_reason": row.rejection_reason,
        "persisted_keyword_id": row.persisted_keyword_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
    }


# --------------------------------------------------------------------------------------
# ReviewDecision
# --------------------------------------------------------------------------------------


class ReviewDecisionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: ReviewDecisionContract) -> None:
        existing = self.session.get(ReviewDecisionRecord, contract.decision_id)
        data = dict(
            proposal_id=contract.proposal_id,
            proposal_type=contract.proposal_type.value,
            decision=contract.decision.value,
            reviewer_id=contract.reviewer_id,
            corrected_value=contract.corrected_value,
            reason=contract.reason,
            create_learning_rule=contract.create_learning_rule,
            decided_at=contract.decided_at,
        )
        if existing is None:
            self.session.add(
                ReviewDecisionRecord(decision_id=contract.decision_id, **data)
            )
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def get(self, decision_id: str) -> Optional[ReviewDecisionContract]:
        row = self.session.get(ReviewDecisionRecord, decision_id)
        return _decision_to_contract(row) if row else None

    def list_for_proposal(self, proposal_id: str) -> list[ReviewDecisionContract]:
        stmt = select(ReviewDecisionRecord).where(
            ReviewDecisionRecord.proposal_id == proposal_id
        )
        rows = self.session.execute(stmt).scalars().all()
        return [_decision_to_contract(r) for r in rows]


def _decision_to_contract(row: ReviewDecisionRecord) -> ReviewDecisionContract:
    return ReviewDecisionContract(
        decision_id=row.decision_id,
        proposal_id=row.proposal_id,
        proposal_type=ProposalType(row.proposal_type),
        decision=ReviewDecision(row.decision),
        reviewer_id=row.reviewer_id,
        corrected_value=row.corrected_value,
        reason=row.reason,
        create_learning_rule=row.create_learning_rule,
        decided_at=row.decided_at,
    )


class ReviewQueueRepositoryAdapter:
    """shared.core.review_queue.ReviewQueueRepository Protocol을 만족하는 어댑터.

    FieldProposalRepository와 ReviewDecisionRepository를 묶어 ReviewQueueService가
    상태 전이/결정 저장을 한 곳에서 처리하도록 한다.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self._proposals = FieldProposalRepository(session)
        self._decisions = ReviewDecisionRepository(session)

    def get_proposal(self, proposal_id: str) -> Optional[FieldProposalContract]:
        return self._proposals.get(proposal_id)

    def save_proposal(self, proposal: FieldProposalContract) -> None:
        self._proposals.save(proposal)

    def save_decision(self, decision: ReviewDecisionContract) -> None:
        self._decisions.save(decision)

    def list_by_type(
        self, proposal_type: ProposalType, status: PipelineStatus
    ) -> list[FieldProposalContract]:
        return self._proposals.list(status=status, proposal_type=proposal_type)


# --------------------------------------------------------------------------------------
# LearnedKnowledge
# --------------------------------------------------------------------------------------


class LearnedKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: LearnedKnowledgeContract) -> None:
        existing = self.session.get(LearnedKnowledge, contract.knowledge_id)
        data = dict(
            knowledge_type=contract.knowledge_type,
            source_name=contract.source_name,
            pattern=contract.pattern,
            target_value=contract.target_value,
            negative_examples=list(contract.negative_examples),
            positive_examples=list(contract.positive_examples),
            is_active=contract.is_active,
            created_from_decision_id=contract.created_from_decision_id,
            applied_count=contract.applied_count,
            success_count=contract.success_count,
        )
        if existing is None:
            self.session.add(
                LearnedKnowledge(knowledge_id=contract.knowledge_id, **data)
            )
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def get(self, knowledge_id: str) -> Optional[LearnedKnowledgeContract]:
        row = self.session.get(LearnedKnowledge, knowledge_id)
        return _knowledge_to_contract(row) if row else None

    def list(self, *, active_only: bool = False) -> list[LearnedKnowledgeContract]:
        stmt = select(LearnedKnowledge)
        if active_only:
            stmt = stmt.where(LearnedKnowledge.is_active.is_(True))
        rows = self.session.execute(stmt).scalars().all()
        return [_knowledge_to_contract(r) for r in rows]


def _knowledge_to_contract(row: LearnedKnowledge) -> LearnedKnowledgeContract:
    return LearnedKnowledgeContract(
        knowledge_id=row.knowledge_id,
        knowledge_type=row.knowledge_type,
        source_name=row.source_name,
        pattern=row.pattern,
        target_value=row.target_value,
        negative_examples=list(row.negative_examples or []),
        positive_examples=list(row.positive_examples or []),
        is_active=row.is_active,
        created_from_decision_id=row.created_from_decision_id,
        applied_count=row.applied_count,
        success_count=row.success_count,
    )


# --------------------------------------------------------------------------------------
# WorkerAttempt
# --------------------------------------------------------------------------------------


class WorkerAttemptRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, contract: WorkerAttemptContract) -> None:
        existing = self.session.get(WorkerAttempt, contract.attempt_id)
        data = dict(
            job_id=contract.job_id,
            role=contract.role.value,
            provider_kind=contract.provider_kind.value,
            provider_name=contract.provider_name,
            model_name=contract.model_name,
            prompt_pack_id=contract.prompt_pack_id,
            prompt_pack_version=contract.prompt_pack_version,
            request_chars=contract.request_chars,
            item_count=contract.item_count,
            status=contract.status.value,
            started_at=contract.started_at,
            finished_at=contract.finished_at,
            error_message=contract.error_message,
            response_artifact_uri=contract.response_artifact_uri,
        )
        if existing is None:
            self.session.add(WorkerAttempt(attempt_id=contract.attempt_id, **data))
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def list_for_job(self, job_id: str) -> list[WorkerAttemptContract]:
        stmt = select(WorkerAttempt).where(WorkerAttempt.job_id == job_id)
        rows = self.session.execute(stmt).scalars().all()
        return [_attempt_to_contract(r) for r in rows]


def _attempt_to_contract(row: WorkerAttempt) -> WorkerAttemptContract:
    return WorkerAttemptContract(
        attempt_id=row.attempt_id,
        job_id=row.job_id,
        role=AIWorkerRole(row.role),
        provider_kind=ProviderKind(row.provider_kind),
        provider_name=row.provider_name,
        model_name=row.model_name,
        prompt_pack_id=row.prompt_pack_id,
        prompt_pack_version=row.prompt_pack_version,
        request_chars=row.request_chars,
        item_count=row.item_count,
        status=ControlJobStatus(row.status),
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_message=row.error_message,
        response_artifact_uri=row.response_artifact_uri,
    )


# --------------------------------------------------------------------------------------
# JobQueue (shared JobQueueService와 호환되는 repository)
# --------------------------------------------------------------------------------------


class JobQueueSqlRepository:
    """shared.core.job_queue.JobQueueRepository Protocol을 만족하는 SQL 구현."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_ready(self, now: datetime, limit: int) -> list[ControlJobContract]:
        stmt = (
            select(AIJob)
            .where(AIJob.status == ControlJobStatus.QUEUED.value)
            .order_by(AIJob.priority.desc(), AIJob.created_at.asc())
            .limit(limit)
        )
        rows = self.session.execute(stmt).scalars().all()
        ready: list[ControlJobContract] = []
        for row in rows:
            if row.not_before is not None and row.not_before > now:
                continue
            ready.append(_job_to_contract(row))
        return ready

    def get(self, job_id: str) -> Optional[ControlJobContract]:
        row = self.session.get(AIJob, job_id)
        return _job_to_contract(row) if row else None

    def save(self, job: ControlJobContract) -> None:
        existing = self.session.get(AIJob, job.job_id)
        data = _job_to_columns(job)
        if existing is None:
            self.session.add(AIJob(job_id=job.job_id, **data))
        else:
            for k, v in data.items():
                setattr(existing, k, v)
        self.session.flush()

    def list_by_status(
        self, status: ControlJobStatus, *, limit: Optional[int] = None
    ) -> list[ControlJobContract]:
        stmt = select(AIJob).where(AIJob.status == status.value)
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self.session.execute(stmt).scalars().all()
        return [_job_to_contract(r) for r in rows]


def _job_to_columns(job: ControlJobContract) -> dict[str, Any]:
    return dict(
        batch_id=job.batch_id,
        role=job.role.value,
        status=job.status.value,
        priority=job.priority,
        lease_owner=job.lease_owner,
        lease_expires_at=job.lease_expires_at,
        heartbeat_at=job.heartbeat_at,
        not_before=job.not_before,
        retry_policy=job.retry_policy.model_dump(mode="json"),
        attempts=job.attempts,
        error_summary=job.error_summary,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _job_to_contract(row: AIJob) -> ControlJobContract:
    return ControlJobContract(
        job_id=row.job_id,
        batch_id=row.batch_id,
        role=AIWorkerRole(row.role),
        status=ControlJobStatus(row.status),
        priority=row.priority,
        lease_owner=row.lease_owner,
        lease_expires_at=row.lease_expires_at,
        heartbeat_at=row.heartbeat_at,
        not_before=row.not_before,
        retry_policy=RetryPolicyContract.model_validate(row.retry_policy or {}),
        attempts=row.attempts,
        error_summary=row.error_summary,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
