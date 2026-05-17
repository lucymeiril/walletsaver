"""ai-admin control DB repository.

각 repository는 SQLAlchemy ORM 모델과 Pydantic contract DTO 사이의 변환만 담당한다.
정책(예: lease, retry/backoff)은 shared `JobQueueService`가 가지므로 repository는
단순 CRUD에 가깝게 유지한다.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any, Optional

from sqlalchemy import delete, func, select
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
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProductMatchTargetType,
    PromptPackContract,
    PromptPackStatus,
    ProviderConfigContract,
    RawCrawlBatchContract,
    ReviewDecisionContract,
    ReviewDecision,
    RetryPolicyContract,
    WorkerAttemptContract,
    normalize_match_text,
    normalize_package_signature,
    normalize_product_signature_key,
)
from core.contracts.ai_pipeline import AIWorkerRole, ProviderKind

from .models import (
    AIJob,
    FieldProposal,
    KeywordProposal,
    LabelingRunLog,
    LearnedKnowledge,
    ProductMatch,
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
            max_provider_calls_per_minute=contract.max_provider_calls_per_minute,
            max_provider_calls_per_day=contract.max_provider_calls_per_day,
            provider_retry_max_attempts=contract.provider_retry_max_attempts,
            provider_retry_min_delay_seconds=contract.provider_retry_min_delay_seconds,
            provider_retry_max_delay_seconds=contract.provider_retry_max_delay_seconds,
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
        max_provider_calls_per_minute=row.max_provider_calls_per_minute,
        max_provider_calls_per_day=row.max_provider_calls_per_day,
        provider_retry_max_attempts=row.provider_retry_max_attempts,
        provider_retry_min_delay_seconds=row.provider_retry_min_delay_seconds,
        provider_retry_max_delay_seconds=row.provider_retry_max_delay_seconds,
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
# ProductMatch
# --------------------------------------------------------------------------------------


class ProductMatchStoreRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_all(self) -> int:
        from sqlalchemy import func
        return self.session.execute(select(func.count()).select_from(ProductMatch)).scalar() or 0

    def count_by_status(self) -> dict[str, int]:
        from sqlalchemy import func
        rows = self.session.execute(
            select(ProductMatch.status, func.count()).group_by(ProductMatch.status)
        ).all()
        return {status: count for status, count in rows}

    def count_by_source(self) -> dict[str, int]:
        from sqlalchemy import func
        rows = self.session.execute(
            select(ProductMatch.source_name, func.count()).group_by(ProductMatch.source_name)
        ).all()
        return {src: count for src, count in rows}

    def save(self, contract: ProductMatchContract) -> ProductMatchContract:
        match_id = contract.match_id or _product_match_id(
            contract.source_id,
            contract.source_name,
            contract.signature_key,
        )
        existing = self.session.get(ProductMatch, match_id)
        if existing is None:
            existing = self._get_row_by_source_signature(
                source_id=contract.source_id,
                source_name=contract.source_name,
                signature_key=contract.signature_key,
            )
            if existing is not None:
                match_id = existing.match_id
        now = datetime.now()
        data = dict(
            source_id=contract.source_id,
            source_name=contract.source_name,
            signature_key=contract.signature_key,
            target_type=contract.target_type.value,
            target_id=contract.target_id,
            canonical_product_id=contract.canonical_product_id,
            canonical_product_name=contract.canonical_product_name,
            category_id=contract.category_id,
            keywords=list(contract.keywords),
            unit_metadata=dict(contract.unit_metadata),
            allowed_title_patterns=list(contract.allowed_title_patterns),
            normalized_title_variants=list(contract.normalized_title_variants),
            blocked_title_patterns=list(contract.blocked_title_patterns),
            package_signature=contract.package_signature,
            package_signature_required=contract.package_signature_required,
            source_product_id_history=list(contract.source_product_id_history),
            provenance_source=contract.provenance_source.value,
            provider_name=contract.provider_name,
            model_name=contract.model_name,
            raw_record_id=contract.raw_record_id,
            batch_id=contract.batch_id,
            confidence=contract.confidence,
            status=contract.status.value,
            audit_reason=contract.audit_reason,
            audit_metadata=dict(contract.audit_metadata),
            reviewed_by=contract.reviewed_by,
            approved_by=contract.approved_by,
            approved_at=contract.approved_at,
            version=contract.version,
            is_active=contract.is_active,
            disabled_reason=contract.disabled_reason,
            updated_at=now,
        )
        if existing is None:
            self.session.add(
                ProductMatch(
                    match_id=match_id,
                    created_at=contract.created_at,
                    **data,
                )
            )
        else:
            for key, value in data.items():
                setattr(existing, key, value)
        self.session.flush()
        return self.get(match_id) or contract.model_copy(update={"match_id": match_id})

    def get(self, match_id: str) -> Optional[ProductMatchContract]:
        row = self.session.get(ProductMatch, match_id)
        return _product_match_to_contract(row) if row else None

    def get_by_source_signature(
        self,
        *,
        source_id: str,
        source_name: str,
        signature_key: str,
    ) -> Optional[ProductMatchContract]:
        row = self._get_row_by_source_signature(
            source_id=source_id,
            source_name=source_name,
            signature_key=signature_key,
        )
        return _product_match_to_contract(row) if row else None

    def list(
        self,
        *,
        source_id: str | None = None,
        source_name: str | None = None,
        status: ProductMatchStatus | None = None,
        provenance_source: ProductMatchProvenanceSource | None = None,
    ) -> list[ProductMatchContract]:
        stmt = select(ProductMatch)
        if source_id is not None:
            stmt = stmt.where(ProductMatch.source_id == source_id)
        if source_name is not None:
            stmt = stmt.where(ProductMatch.source_name == source_name)
        if status is not None:
            stmt = stmt.where(ProductMatch.status == status.value)
        if provenance_source is not None:
            stmt = stmt.where(ProductMatch.provenance_source == provenance_source.value)
        stmt = stmt.order_by(
            ProductMatch.source_id,
            ProductMatch.source_name,
            ProductMatch.signature_key,
        )
        rows = self.session.execute(stmt).scalars().all()
        return [_product_match_to_contract(row) for row in rows]

    def find_strict_approved_match(
        self,
        *,
        source_id: str,
        source_name: str,
        raw_title: str,
        package_signature: str | None = None,
        source_product_id: str | None = None,
    ) -> Optional[ProductMatchContract]:
        """Find a safe strict match without treating source product ID as identity.

        Highest-confidence auto matching requires the same source, an approved active
        row, an allowed/normalized title hit, and strict package equality when the row
        has a package requirement. A historical source product ID only breaks ties; it
        never matches by itself.
        """

        normalized_title = normalize_match_text(raw_title)
        normalized_package = (
            normalize_package_signature(package_signature)
            if package_signature
            else None
        )
        source_product_id = source_product_id.strip() if source_product_id else None
        stmt = select(ProductMatch).where(
            ProductMatch.source_id == source_id,
            ProductMatch.source_name == source_name,
            ProductMatch.status == ProductMatchStatus.APPROVED.value,
            ProductMatch.provenance_source == ProductMatchProvenanceSource.HUMAN.value,
            ProductMatch.is_active.is_(True),
        )
        rows = self.session.execute(stmt).scalars().all()
        candidates: list[tuple[int, ProductMatch]] = []
        for row in rows:
            if _matches_any_title_pattern(normalized_title, row.blocked_title_patterns or []):
                continue
            title_patterns = list(row.allowed_title_patterns or []) + list(
                row.normalized_title_variants or []
            )
            if not title_patterns:
                continue
            if not _matches_any_title_pattern(normalized_title, title_patterns):
                continue
            row_package = row.package_signature
            if row.package_signature_required or row_package is not None:
                if not normalized_package or normalized_package != row_package:
                    continue
            score = 100
            if source_product_id and source_product_id in (row.source_product_id_history or []):
                score += 5
            candidates.append((score, row))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], item[1].match_id))
        return _product_match_to_contract(candidates[0][1])

    def export_records(
        self,
        *,
        approved_only: bool = False,
        skip_safe_only: bool = False,
    ) -> list[dict[str, Any]]:
        status = ProductMatchStatus.APPROVED if approved_only or skip_safe_only else None
        provenance_source = (
            ProductMatchProvenanceSource.HUMAN if skip_safe_only else None
        )
        return [
            contract.model_dump(mode="json")
            for contract in self.list(
                status=status,
                provenance_source=provenance_source,
            )
        ]

    def import_records(
        self,
        records: list[dict[str, Any]],
        *,
        replace: bool = False,
        rebuild_match_ids: bool = True,
    ) -> dict[str, int]:
        summary = {"inserted": 0, "updated": 0, "skipped": 0}
        for record in records:
            contract = ProductMatchContract(**record)
            if rebuild_match_ids:
                contract = contract.model_copy(update={"match_id": None})
            existing = self.get_by_source_signature(
                source_id=contract.source_id,
                source_name=contract.source_name,
                signature_key=contract.signature_key,
            )
            if existing is not None and not replace:
                summary["skipped"] += 1
                continue
            saved = self.save(contract)
            if existing is None:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
        return summary

    def rebuild_identity_keys(self, *, dry_run: bool = True) -> dict[str, Any]:
        rows = self.session.execute(select(ProductMatch)).scalars().all()
        row_by_id = {row.match_id: row for row in rows}
        changes: list[dict[str, str]] = []
        conflicts: list[dict[str, str]] = []
        for row in rows:
            normalized_signature = normalize_product_signature_key(row.signature_key)
            rebuilt_match_id = _product_match_id(
                row.source_id,
                row.source_name,
                normalized_signature,
            )
            conflicting_row = row_by_id.get(rebuilt_match_id)
            if conflicting_row is not None and conflicting_row.match_id != row.match_id:
                conflicts.append(
                    {
                        "match_id": row.match_id,
                        "rebuilt_match_id": rebuilt_match_id,
                        "conflicting_match_id": conflicting_row.match_id,
                    }
                )
                continue
            if (
                row.signature_key == normalized_signature
                and row.match_id == rebuilt_match_id
            ):
                continue
            changes.append(
                {
                    "match_id": row.match_id,
                    "rebuilt_match_id": rebuilt_match_id,
                    "signature_key": row.signature_key,
                    "normalized_signature_key": normalized_signature,
                }
            )
            if not dry_run:
                row.signature_key = normalized_signature
                row.match_id = rebuilt_match_id
        if not dry_run and changes:
            self.session.flush()
        return {
            "checked": len(rows),
            "changed": len(changes),
            "conflicts": len(conflicts),
            "changes": changes,
            "conflict_rows": conflicts,
            "dry_run": dry_run,
        }

    def _get_row_by_source_signature(
        self,
        *,
        source_id: str,
        source_name: str,
        signature_key: str,
    ) -> Optional[ProductMatch]:
        normalized = normalize_product_signature_key(signature_key)
        stmt = select(ProductMatch).where(
            ProductMatch.source_id == source_id,
            ProductMatch.source_name == source_name,
            ProductMatch.signature_key == normalized,
        )
        return self.session.execute(stmt).scalars().first()

    def count_all(self) -> int:
        return self.session.execute(select(func.count()).select_from(ProductMatch)).scalar() or 0

    def count_by_status(self) -> dict[str, int]:
        rows = self.session.execute(
            select(ProductMatch.status, func.count()).group_by(ProductMatch.status)
        ).all()
        return {status: count for status, count in rows}

    def count_by_source(self) -> dict[str, int]:
        rows = self.session.execute(
            select(ProductMatch.source_name, func.count()).group_by(ProductMatch.source_name)
        ).all()
        return {src: count for src, count in rows}


def _product_match_id(source_id: str, source_name: str, signature_key: str) -> str:
    identity = f"{source_id}\x1f{source_name}\x1f{signature_key}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"pm-{digest}"


def _matches_any_title_pattern(normalized_title: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        normalized_pattern = normalize_match_text(pattern)
        if not normalized_pattern:
            continue
        if "*" in normalized_pattern:
            parts = [re.escape(part) for part in normalized_pattern.split("*")]
            if re.fullmatch(".*".join(parts), normalized_title):
                return True
        elif normalized_title == normalized_pattern:
            return True
    return False


def _product_match_to_contract(row: ProductMatch) -> ProductMatchContract:
    return ProductMatchContract(
        match_id=row.match_id,
        source_id=row.source_id,
        source_name=row.source_name,
        signature_key=row.signature_key,
        target_type=ProductMatchTargetType(row.target_type),
        target_id=row.target_id,
        canonical_product_id=row.canonical_product_id,
        canonical_product_name=row.canonical_product_name,
        category_id=row.category_id,
        keywords=list(row.keywords or []),
        unit_metadata=dict(row.unit_metadata or {}),
        allowed_title_patterns=list(row.allowed_title_patterns or []),
        normalized_title_variants=list(row.normalized_title_variants or []),
        blocked_title_patterns=list(row.blocked_title_patterns or []),
        package_signature=row.package_signature,
        package_signature_required=row.package_signature_required,
        source_product_id_history=list(row.source_product_id_history or []),
        provenance_source=ProductMatchProvenanceSource(row.provenance_source),
        provider_name=row.provider_name,
        model_name=row.model_name,
        raw_record_id=row.raw_record_id,
        batch_id=row.batch_id,
        confidence=row.confidence,
        status=ProductMatchStatus(row.status),
        audit_reason=row.audit_reason,
        audit_metadata=dict(row.audit_metadata or {}),
        reviewed_by=row.reviewed_by,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        version=row.version,
        is_active=row.is_active,
        disabled_reason=row.disabled_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# --------------------------------------------------------------------------------------
# LearnedKnowledge
# --------------------------------------------------------------------------------------


class LearnedKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def count_all(self) -> int:
        from sqlalchemy import func
        return self.session.execute(select(func.count()).select_from(LearnedKnowledge)).scalar() or 0

    def count_by_type(self) -> dict[str, int]:
        from sqlalchemy import func
        rows = self.session.execute(
            select(LearnedKnowledge.knowledge_type, func.count()).group_by(LearnedKnowledge.knowledge_type)
        ).all()
        return {ktype: count for ktype, count in rows}

    def success_count_distribution(self) -> dict[str, int]:
        """Returns distribution of success_count (0, 1-5, 6-20, 21+)"""
        from sqlalchemy import func, case
        bucket = case(
            (LearnedKnowledge.success_count == 0, "0"),
            (LearnedKnowledge.success_count <= 5, "1-5"),
            (LearnedKnowledge.success_count <= 20, "6-20"),
            else_="21+",
        )
        rows = self.session.execute(
            select(bucket, func.count()).group_by(bucket)
        ).all()
        return {label: count for label, count in rows}

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


# --------------------------------------------------------------------------------------
# LabelingRunLog
# --------------------------------------------------------------------------------------


class LabelingRunLogRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, run_id: str, **fields) -> None:
        existing = self.session.get(LabelingRunLog, run_id)
        if existing is None:
            self.session.add(LabelingRunLog(run_id=run_id, **fields))
        else:
            for k, v in fields.items():
                setattr(existing, k, v)
        self.session.flush()

    def list_recent(self, limit: int = 20) -> list[dict]:
        from sqlalchemy import desc
        rows = self.session.execute(
            select(LabelingRunLog).order_by(desc(LabelingRunLog.run_at)).limit(limit)
        ).scalars().all()
        return [_run_log_to_dict(r) for r in rows]

    def count(self) -> int:
        from sqlalchemy import func
        return self.session.execute(select(func.count()).select_from(LabelingRunLog)).scalar() or 0


def _run_log_to_dict(row: LabelingRunLog) -> dict:
    ai_call_rate = (row.ai_called / row.total_input * 100) if row.total_input > 0 else 0.0
    return {
        "run_id": row.run_id,
        "run_at": row.run_at.isoformat() if row.run_at else None,
        "mode": row.mode,
        "ai_provider_kind": row.ai_provider_kind,
        "total_input": row.total_input,
        "queue_initial": row.queue_initial,
        "ai_called": row.ai_called,
        "ai_resolved": row.ai_resolved,
        "ai_escalated": row.ai_escalated,
        "gate_passed": row.gate_passed,
        "gate_escalated": row.gate_escalated,
        "canonical_created": row.canonical_created,
        "product_match_total_snapshot": row.product_match_total_snapshot,
        "learned_knowledge_total_snapshot": row.learned_knowledge_total_snapshot,
        "ai_call_rate": round(ai_call_rate, 1),
        "by_mart": row.by_mart or {},
    }
