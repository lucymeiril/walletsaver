"""검수 큐 라우트.

shared `ReviewQueueService`에 상태 전이를 위임한다. AI 제안의 approve/correct/reject
결정은 이후 학습/감사의 근거가 되므로 모든 결정은 ReviewDecision으로 저장된다.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal as FieldProposalContract,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from core.contracts.control_plane import LearnedKnowledgeContract, ReviewDecision, ReviewDecisionContract
from core.contracts.control_plane import (
    ProductMatchContract,
    ProductMatchProvenanceSource,
    ProductMatchStatus,
    ProductMatchTargetType,
    normalize_match_text,
    normalize_package_signature,
    normalize_product_signature_key,
)
from core.review_queue import ReviewQueueService

from storage import (
    Database,
    FieldProposalRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
    ProductMatchStoreRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    ReviewQueueRepositoryAdapter,
    get_default_database,
)
from services.keyword_catalog import (
    KeywordCatalogAdapter,
    can_approve_keyword_proposal,
    can_reject_keyword_proposal,
    normalize_keyword,
)
from services.db_admin_adapter import (
    ai_safe_final_approve_db_admin,
    build_db_admin_ingestion_payload,
    check_db_admin_mutation_preflight,
    submit_to_db_admin,
)
from services.review_publish import (
    build_ai_batch_anomaly_audit,
    build_batch_publish_summary,
    build_operator_dashboard_summary,
    build_publish_rows,
    build_raw_ai_audit,
    _field_proposals_for_scope,
    mark_publish_record_rolled_back,
    proposals_by_raw_record,
    upsert_publish_record,
)
from services.review_automation import (
    AutomationApplyRequest,
    AutomationGateConfig,
    AutomationPreviewRequest,
    apply_automation_gates,
    build_automation_preview,
)
from services.seed_taxonomy import is_safe_seed_category, normalize_category_id

router = APIRouter(prefix="/api/review", tags=["review"])


def get_db() -> Database:
    return get_default_database()


class ApproveRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    create_learning_rule: bool = True


class CorrectRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    corrected_value: Any
    reason: str = Field(min_length=1)
    create_learning_rule: bool = True


class RejectRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class KeywordProposalApproveRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    proposed_keyword: Optional[str] = Field(default=None, min_length=1)
    match_terms: Optional[list[str]] = None
    category_suggestion: Optional[str] = None


class UpdateProposalRequest(BaseModel):
    proposal_type: Optional[ProposalType] = None
    target_field: Optional[str] = Field(default=None, min_length=1)
    proposed_value: Any = None
    alternatives: Optional[list[Any]] = None


class PublishApprovedRequest(BaseModel):
    raw_record_ids: list[str] = Field(default_factory=list, max_length=500)
    reviewer_id: str = Field(min_length=1)
    confirm_count: int = Field(ge=1, le=500)
    batch_id: Optional[str] = None


class RollbackPublishRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class MatchCardActionRequest(BaseModel):
    action: str = Field(min_length=1)
    reviewer_id: str = Field(min_length=1)
    audit_reason: str = Field(min_length=1)
    target_match_id: Optional[str] = None
    target_type: Optional[ProductMatchTargetType] = None
    target_id: Optional[str] = None
    canonical_product_id: Optional[str] = None
    canonical_product_name: Optional[str] = None
    category_id: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)
    package_signature: Optional[str] = None
    allowed_title_pattern: Optional[str] = None
    blocked_title_pattern: Optional[str] = None
    fields: dict[str, Any] = Field(default_factory=dict)


def _service(session) -> ReviewQueueService:
    return ReviewQueueService(ReviewQueueRepositoryAdapter(session))


async def _submit_to_db_admin(payload: dict[str, Any]) -> dict[str, Any]:
    return await submit_to_db_admin(payload)


async def _ai_safe_final_approve_db_admin(
    ingestion_id: int | str,
    *,
    notes: str | None = None,
) -> dict[str, Any]:
    return await ai_safe_final_approve_db_admin(ingestion_id, notes=notes)


async def _check_db_admin_mutation_preflight() -> dict[str, Any]:
    return await check_db_admin_mutation_preflight()


AI_DB_HANDOFF_SAFETY_NOTICE = (
    "AI-admin submit only creates/updates a DB-admin pending ingestion; public DB rows "
    "are saved only after explicit DB-admin ai-safe-final-approve succeeds."
)


def _publish_safety_metadata(summary: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = summary or {}
    return {
        "status": "operator_final_approval_required",
        "notice": AI_DB_HANDOFF_SAFETY_NOTICE,
        "held_rows_visible": len(summary.get("held_rows") or []),
        "approved_rows_visible": len(summary.get("approved_rows") or []),
        "final_approve_route": "/api/ingestions/{id}/ai-safe-final-approve",
    }


def _db_admin_submit_retained_pending(response: dict[str, Any]) -> bool:
    return response.get("id") is not None and response.get("status") == "pending"


def _db_admin_mutation_preflight_ready(result: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(result, dict)
        and result.get("status") == "ready"
        and result.get("ready_to_mutate") is True
        and isinstance(result.get("snapshot"), dict)
        and result["snapshot"].get("verified") is True
    )


def _db_admin_mutation_preflight_error(result: dict[str, Any] | None) -> str:
    return (
        "DB-admin mutation preflight failed; readiness and a listed rollback backup "
        "are required before AI-safe live DB mutation: "
        f"{result}"
    )


def _final_approve_public_verified(response: dict[str, Any] | None) -> bool:
    if not isinstance(response, dict):
        return False
    verification = response.get("public_db_verification")
    return (
        response.get("status") == "approved"
        and bool(response.get("saved"))
        and isinstance(verification, dict)
        and verification.get("verified") is True
        and int(verification.get("verified_count") or 0) >= int(response.get("saved") or 0)
    )


def _final_approve_rollback_re_review_supported(response: dict[str, Any] | None) -> bool:
    if not isinstance(response, dict):
        return False
    return bool(
        response.get("rollback_supported")
        and response.get("re_review_supported")
        and (
            response.get("operator_next_action")
            or response.get("raw_evidence_retained")
        )
    )


def _proposal_payload(proposal: FieldProposalContract) -> dict[str, Any]:
    return proposal.model_dump(mode="json")


def _raw_payload(record: RawCrawlRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _normalize_category_proposal_payload(
    proposal_type: ProposalType | None,
    target_field: str | None,
    proposed_value: Any,
) -> tuple[ProposalType | None, str | None, Any]:
    if target_field not in {"category_id", "category", "category_hint", "category_name"}:
        return proposal_type, target_field, proposed_value
    normalized = normalize_category_id(proposed_value)
    if is_safe_seed_category(normalized):
        return ProposalType.CATEGORY, "category_id", normalized
    return proposal_type, target_field, proposed_value


@router.get("/automation-gates")
def automation_gate_defaults(
    batch_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    config = AutomationGateConfig()
    with db.session_scope() as session:
        preview = build_automation_preview(session, config, batch_id=batch_id)
    return {"config": config.model_dump(mode="json"), "preview": preview}


@router.post("/automation-gates/preview")
def preview_automation_gates(
    payload: AutomationPreviewRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        return build_automation_preview(session, payload.config, batch_id=payload.batch_id)


@router.post("/automation-gates/apply")
def apply_automation_gate_decisions(
    payload: AutomationApplyRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            return apply_automation_gates(session, payload.config, batch_id=payload.batch_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/proposals")
def list_proposals(
    proposal_type: Optional[ProposalType] = None,
    status: Optional[PipelineStatus] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        items = repo.list(status=status, proposal_type=proposal_type)
        return {"items": [_proposal_payload(p) for p in items]}


@router.get("/proposals/{proposal_id}")
def get_proposal(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        decisions = ReviewDecisionRepository(session).list_for_proposal(proposal_id)
        return {
            "proposal": proposal.model_dump(mode="json"),
            "decisions": [d.model_dump(mode="json") for d in decisions],
        }


@router.post("/proposals", status_code=201)
def submit_proposal(
    proposal: FieldProposalContract,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            proposal_type, target_field, proposed_value = _normalize_category_proposal_payload(
                proposal.proposal_type,
                proposal.target_field,
                proposal.proposed_value,
            )
            normalized = proposal.model_copy(
                update={
                    "proposal_type": proposal_type or proposal.proposal_type,
                    "target_field": target_field or proposal.target_field,
                    "proposed_value": proposed_value,
                }
            )
            _service(session).submit(normalized)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return normalized.model_dump(mode="json")


@router.put("/proposals/{proposal_id}")
def update_proposal(
    proposal_id: str,
    payload: UpdateProposalRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status not in {
            PipelineStatus.AI_PROPOSED,
            PipelineStatus.HUMAN_REVIEWING,
        }:
            raise HTTPException(
                status_code=400,
                detail="only proposed or reviewing proposals can be modified",
            )

        update: dict[str, Any] = {}
        if payload.proposal_type is not None:
            update["proposal_type"] = payload.proposal_type
        if payload.target_field is not None:
            update["target_field"] = payload.target_field
        if "proposed_value" in payload.model_fields_set:
            update["proposed_value"] = payload.proposed_value
        if payload.alternatives is not None:
            update["alternatives"] = payload.alternatives
        proposal_type, target_field, proposed_value = _normalize_category_proposal_payload(
            update.get("proposal_type", proposal.proposal_type),
            update.get("target_field", proposal.target_field),
            update.get("proposed_value", proposal.proposed_value),
        )
        if target_field is not None:
            update["target_field"] = target_field
        if proposal_type is not None:
            update["proposal_type"] = proposal_type
        update["proposed_value"] = proposed_value
        updated = proposal.model_copy(update=update)
        repo.save(updated)
        return _proposal_payload(updated)


@router.delete("/proposals/{proposal_id}")
def delete_proposal(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status not in {
            PipelineStatus.AI_PROPOSED,
            PipelineStatus.HUMAN_REVIEWING,
            PipelineStatus.REJECTED,
        }:
            raise HTTPException(
                status_code=400,
                detail="approved or published proposals cannot be deleted",
            )
        repo.delete(proposal_id)
        return {"deleted": True, "proposal_id": proposal_id}


@router.get("/raw-records")
def list_raw_records(
    batch_id: Optional[str] = None,
    include_proposals: bool = True,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        records = (
            raw_repo.list_records(batch_id)
            if batch_id
            else raw_repo.list_all_records()
        )
        items = [_raw_payload(record) for record in records]
        if include_proposals:
            proposals_by_record = proposals_by_raw_record(
                FieldProposalRepository(session).list()
            )
            for item in items:
                item["proposals"] = [
                    _proposal_payload(proposal)
                    for proposal in proposals_by_record.get(item["raw_record_id"], [])
                ]
        return {"items": items}


@router.get("/match-cards")
def list_match_cards(
    batch_id: Optional[str] = None,
    raw_record_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        records = (
            raw_repo.list_records(batch_id)
            if batch_id
            else raw_repo.list_all_records()
        )
        if raw_record_id:
            records = [record for record in records if record.raw_record_id == raw_record_id]
        match_repo = ProductMatchStoreRepository(session)
        cards = [_match_decision_card(record, match_repo) for record in records]
        return {"items": cards}


@router.post("/match-cards/{raw_record_id}/actions")
def apply_match_card_action(
    raw_record_id: str,
    payload: MatchCardActionRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        record = _get_raw_record_or_404(session, raw_record_id)
        match_repo = ProductMatchStoreRepository(session)
        try:
            match = _apply_match_action(record, payload, match_repo)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "match": match.model_dump(mode="json"),
            "card": _match_decision_card(record, match_repo),
        }


def _get_raw_record_or_404(session, raw_record_id: str) -> RawCrawlRecord:
    for record in RawCrawlBatchRepository(session).list_all_records():
        if record.raw_record_id == raw_record_id:
            return record
    raise HTTPException(status_code=404, detail="raw record not found")


def _match_decision_card(
    record: RawCrawlRecord,
    match_repo: ProductMatchStoreRepository,
) -> dict[str, Any]:
    source_ids = _match_source_ids(record)
    signature_keys = _match_signature_keys(record)
    package_signature = _match_package_signature(record)
    source_product_id = _match_source_product_id(record)
    candidates = []
    seen_match_ids: set[str] = set()
    for source_id in source_ids:
        for match in match_repo.list(source_id=source_id, source_name=record.source_name):
            if match.match_id in seen_match_ids:
                continue
            seen_match_ids.add(match.match_id or match.signature_key)
            candidates.append(
                _candidate_card(
                    record=record,
                    match=match,
                    signature_keys=signature_keys,
                    package_signature=package_signature,
                    source_product_id=source_product_id,
                )
            )
    candidates.sort(
        key=lambda item: (
            -item["confidence_score"],
            item["target_type"],
            item["target_id"] or "",
            item["match_id"] or "",
        )
    )
    return {
        "raw_record": {
            "raw_record_id": record.raw_record_id,
            "source_name": record.source_name,
            "source_ids": source_ids,
            "source_record_key": record.source_record_key,
            "source_product_id": source_product_id,
            "source_url": record.source_url,
            "raw_title": record.raw_title,
            "raw_price": record.raw_price,
            "package_signature": package_signature,
            "signature_keys": [
                normalize_product_signature_key(key) for key in signature_keys
            ],
            "collected_fields": _collected_fields(record),
        },
        "candidates": candidates,
        "actions": [
            "select_existing_candidate",
            "create_variant_candidate",
            "create_source_listing_candidate",
            "add_allowed_title_pattern",
            "add_blocked_title_pattern",
            "direct_edit",
            "manual_hold",
        ],
        "advanced": {"raw_record": record.model_dump(mode="json")},
    }


def _candidate_card(
    *,
    record: RawCrawlRecord,
    match: ProductMatchContract,
    signature_keys: list[str],
    package_signature: str | None,
    source_product_id: str | None,
) -> dict[str, Any]:
    normalized_title = normalize_match_text(record.raw_title)
    allowed_hits = _matched_patterns(normalized_title, match.allowed_title_patterns)
    variant_hits = [
        pattern
        for pattern in _matched_patterns(normalized_title, match.normalized_title_variants)
        if pattern not in allowed_hits
    ]
    blocked_hits = _matched_patterns(normalized_title, match.blocked_title_patterns)
    package_match = _package_matches(package_signature, match.package_signature)
    exact_signature = any(
        normalize_product_signature_key(key) == match.signature_key
        for key in signature_keys
    )
    source_id_seen = bool(
        source_product_id and source_product_id in match.source_product_id_history
    )
    score = 0.0
    reasons = []
    if exact_signature:
        score += 0.35
        reasons.append("same source signature")
    if allowed_hits or variant_hits:
        score += 0.25
        reasons.append("allowed title pattern matched")
    if package_match:
        score += 0.2
        reasons.append("package signature matched")
    if source_id_seen:
        score += 0.1
        reasons.append("source product id seen before")
    if blocked_hits:
        score -= 0.4
        reasons.append("blocked title pattern matched")
    if match.status == ProductMatchStatus.APPROVED:
        score += 0.1
    if match.confidence is not None:
        score += min(match.confidence, 1.0) * 0.1
    return {
        "match_id": match.match_id,
        "target_type": match.target_type.value,
        "target_id": match.target_id,
        "canonical_product_id": match.canonical_product_id,
        "canonical_product_name": match.canonical_product_name,
        "category_id": match.category_id,
        "keywords": list(match.keywords),
        "status": match.status.value,
        "confidence": match.confidence,
        "confidence_score": max(0.0, min(1.0, score)),
        "reasons": reasons or ["same source candidate"],
        "package_signature": match.package_signature,
        "package_signature_match": package_match,
        "package_signature_required": match.package_signature_required,
        "allowed_title_pattern_evidence": allowed_hits + variant_hits,
        "blocked_title_pattern_evidence": blocked_hits,
        "source_product_id_evidence": {
            "input": source_product_id,
            "matched_history": source_id_seen,
        },
        "audit_reason": match.audit_reason,
        "reviewed_by": match.reviewed_by,
        "advanced": match.model_dump(mode="json"),
    }


def _apply_match_action(
    record: RawCrawlRecord,
    payload: MatchCardActionRequest,
    match_repo: ProductMatchStoreRepository,
) -> ProductMatchContract:
    action = payload.action
    if action == "select_existing_candidate":
        candidate = _require_match(match_repo, payload.target_match_id)
        return match_repo.save(
            _contract_for_record(record, payload, source_match=candidate)
        )
    if action in {"create_variant_candidate", "create_source_listing_candidate", "direct_edit", "manual_hold"}:
        return match_repo.save(_contract_for_record(record, payload))
    if action in {"add_allowed_title_pattern", "add_blocked_title_pattern"}:
        candidate = _require_match(match_repo, payload.target_match_id)
        return _add_title_pattern(record, payload, candidate, match_repo)
    raise ValueError(f"unsupported match card action: {action}")


def _contract_for_record(
    record: RawCrawlRecord,
    payload: MatchCardActionRequest,
    *,
    source_match: ProductMatchContract | None = None,
) -> ProductMatchContract:
    fields = dict(payload.fields or {})
    target_type = payload.target_type
    if payload.action == "create_variant_candidate":
        target_type = ProductMatchTargetType.VARIANT
    elif payload.action == "create_source_listing_candidate":
        target_type = ProductMatchTargetType.SOURCE_LISTING
    elif payload.action == "manual_hold":
        target_type = ProductMatchTargetType.CANONICAL_PRODUCT
    source = source_match
    source_id = _match_source_ids(record)[0]
    signature_key = _match_signature_keys(record)[0]
    package_signature = payload.package_signature or _match_package_signature(record)
    title_pattern = payload.allowed_title_pattern or record.raw_title
    source_product_id = _match_source_product_id(record)
    status = (
        ProductMatchStatus.REJECTED
        if payload.action == "manual_hold"
        else ProductMatchStatus.APPROVED
    )
    target_type = target_type or (source.target_type if source else ProductMatchTargetType.CANONICAL_PRODUCT)
    canonical_name = (
        payload.canonical_product_name
        or fields.get("canonical_product_name")
        or (source.canonical_product_name if source else record.raw_title)
    )
    return ProductMatchContract(
        source_id=source_id,
        source_name=record.source_name,
        signature_key=signature_key,
        target_type=target_type,
        target_id=payload.target_id or fields.get("target_id") or (source.target_id if source else None),
        canonical_product_id=payload.canonical_product_id
        or fields.get("canonical_product_id")
        or (source.canonical_product_id if source else None),
        canonical_product_name=canonical_name,
        category_id=payload.category_id or fields.get("category_id") or (source.category_id if source else None),
        keywords=payload.keywords or fields.get("keywords") or (list(source.keywords) if source else []),
        unit_metadata=fields.get("unit_metadata") or (dict(source.unit_metadata) if source else {}),
        allowed_title_patterns=fields.get("allowed_title_patterns")
        or _dedupe_strings([*(source.allowed_title_patterns if source else []), title_pattern]),
        normalized_title_variants=fields.get("normalized_title_variants")
        or _dedupe_strings([*(source.normalized_title_variants if source else []), title_pattern]),
        blocked_title_patterns=fields.get("blocked_title_patterns")
        or (list(source.blocked_title_patterns) if source else []),
        package_signature=package_signature,
        package_signature_required=fields.get(
            "package_signature_required",
            source.package_signature_required if source else True,
        ),
        source_product_id_history=_dedupe_strings(
            [
                *(source.source_product_id_history if source else []),
                source_product_id,
            ]
        ),
        provenance_source=ProductMatchProvenanceSource.HUMAN,
        raw_record_id=record.raw_record_id,
        confidence=fields.get("confidence") or (source.confidence if source else None),
        status=status,
        audit_reason=payload.audit_reason,
        audit_metadata={
            "action": payload.action,
            "reviewer_id": payload.reviewer_id,
            "previous_match_id": source.match_id if source else None,
            "previous_audit_reason": source.audit_reason if source else None,
        },
        reviewed_by=payload.reviewer_id,
        approved_by=None if status == ProductMatchStatus.REJECTED else payload.reviewer_id,
        approved_at=None if status == ProductMatchStatus.REJECTED else datetime.now(),
        is_active=status == ProductMatchStatus.APPROVED,
        disabled_reason=payload.audit_reason if status == ProductMatchStatus.REJECTED else None,
    )


def _add_title_pattern(
    record: RawCrawlRecord,
    payload: MatchCardActionRequest,
    candidate: ProductMatchContract,
    match_repo: ProductMatchStoreRepository,
) -> ProductMatchContract:
    allowed = list(candidate.allowed_title_patterns)
    blocked = list(candidate.blocked_title_patterns)
    if payload.action == "add_allowed_title_pattern":
        allowed = _dedupe_strings([*allowed, payload.allowed_title_pattern or record.raw_title])
    else:
        blocked = _dedupe_strings([*blocked, payload.blocked_title_pattern or record.raw_title])
    updated = candidate.model_copy(
        update={
            "allowed_title_patterns": allowed,
            "blocked_title_patterns": blocked,
            "audit_reason": payload.audit_reason,
            "audit_metadata": {
                **dict(candidate.audit_metadata or {}),
                "last_action": payload.action,
                "last_reviewer_id": payload.reviewer_id,
                "previous_audit_reason": candidate.audit_reason,
                "raw_record_id": record.raw_record_id,
            },
            "reviewed_by": payload.reviewer_id,
            "approved_by": payload.reviewer_id
            if candidate.status == ProductMatchStatus.APPROVED
            else candidate.approved_by,
            "approved_at": datetime.now()
            if candidate.status == ProductMatchStatus.APPROVED
            else candidate.approved_at,
            "updated_at": datetime.now(),
        }
    )
    return match_repo.save(updated)


def _require_match(
    match_repo: ProductMatchStoreRepository,
    match_id: str | None,
) -> ProductMatchContract:
    if not match_id:
        raise ValueError("target_match_id is required")
    match = match_repo.get(match_id)
    if match is None:
        raise ValueError("target match not found")
    return match


def _match_source_ids(record: RawCrawlRecord) -> list[str]:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    return _dedupe_strings(
        [
            raw_payload.get("source_id"),
            raw_payload.get("source"),
            raw_payload.get("store"),
            raw_payload.get("mall"),
            record.source_name,
        ]
    )


def _match_signature_keys(record: RawCrawlRecord) -> list[str]:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    return _dedupe_strings(
        [
            raw_payload.get("signature_key"),
            raw_payload.get("product_signature"),
            raw_payload.get("source_signature"),
            record.raw_title,
        ]
    )


def _match_package_signature(record: RawCrawlRecord) -> str | None:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    explicit = raw_payload.get("package_signature")
    if explicit:
        return normalize_package_signature(str(explicit))
    quantity = raw_payload.get("package_quantity")
    unit = raw_payload.get("package_unit")
    bundle_count = raw_payload.get("bundle_count")
    if quantity is not None and unit:
        signature = f"package_quantity={quantity};package_unit={unit}"
        if bundle_count is not None:
            signature = f"{signature};bundle_count={bundle_count}"
        return normalize_package_signature(signature)
    package = raw_payload.get("package")
    return normalize_package_signature(str(package)) if package else None


def _match_source_product_id(record: RawCrawlRecord) -> str | None:
    raw_payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    for key in ("source_product_id", "product_id", "sku", "source_sku"):
        value = raw_payload.get(key)
        if value not in (None, ""):
            return str(value)
    return record.source_record_key


def _collected_fields(record: RawCrawlRecord) -> dict[str, Any]:
    payload = record.raw_payload if isinstance(record.raw_payload, dict) else {}
    keys = [
        "brand",
        "category_id",
        "package_quantity",
        "package_unit",
        "bundle_count",
        "event_name",
        "image_url",
        "source_product_id",
    ]
    return {key: payload.get(key) for key in keys if payload.get(key) not in (None, "")}


def _matched_patterns(normalized_title: str, patterns: list[str]) -> list[str]:
    return [
        pattern
        for pattern in patterns
        if _title_pattern_matches(normalized_title, pattern)
    ]


def _title_pattern_matches(normalized_title: str, pattern: str) -> bool:
    normalized_pattern = normalize_match_text(pattern)
    if not normalized_pattern:
        return False
    if "*" in normalized_pattern:
        parts = [re.escape(part) for part in normalized_pattern.split("*")]
        return bool(re.fullmatch(".*".join(parts), normalized_title))
    return normalized_title == normalized_pattern


def _package_matches(left: str | None, right: str | None) -> bool:
    return bool(left and right and normalize_package_signature(left) == normalize_package_signature(right))


@router.get("/keyword-proposals")
def list_keyword_proposals(
    status: Optional[PipelineStatus] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        proposals = KeywordProposalRepository(session).list(status=status)
        return {"items": proposals}


@router.get("/keyword-proposals/{proposal_id}")
def get_keyword_proposal(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        proposal = KeywordProposalRepository(session).get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="keyword proposal not found")
        return proposal


@router.post("/keyword-proposals/{proposal_id}/approve")
def approve_keyword_proposal(
    proposal_id: str,
    payload: KeywordProposalApproveRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = KeywordProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="keyword proposal not found")
        if not can_approve_keyword_proposal(proposal["status"]):
            raise HTTPException(status_code=400, detail="keyword proposal already decided")
        word = (payload.proposed_keyword or proposal["proposed_keyword"]).strip()
        terms = payload.match_terms if payload.match_terms is not None else proposal["match_terms"]
        category_id = (
            payload.category_suggestion
            if "category_suggestion" in payload.model_fields_set
            else proposal["category_suggestion"]
        )
        try:
            catalog = KeywordCatalogAdapter()
            persisted = catalog.upsert_keyword(
                word=word,
                match_terms=terms,
                category_id=category_id,
            )
            persisted = persisted | catalog.link_keyword_to_products(
                keyword_id=persisted.get("id"),
                triggering_records=proposal.get("triggering_records", []),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"failed to persist keyword to DB-admin: {exc}",
            ) from exc
        updated = proposal | {
            "proposed_keyword": word,
            "match_terms": terms,
            "category_suggestion": category_id,
            "status": PipelineStatus.APPROVED.value,
            "reviewer_id": payload.reviewer_id,
            "persisted_keyword_id": persisted.get("id"),
            "updated_at": datetime.now(),
            "decided_at": datetime.now(),
        }
        saved = repo.save(updated)
        decision = _record_keyword_decision(
            session,
            saved,
            reviewer_id=payload.reviewer_id,
            decision=ReviewDecision.APPROVE,
            corrected_value={
                "word": word,
                "match_terms": terms,
                "category_id": category_id,
                "keyword_id": persisted.get("id"),
            },
            reason="keyword proposal approved for DB-admin catalog",
        )
        _save_keyword_learning(
            session,
            saved,
            knowledge_type="keyword_alias_approved",
            reviewer_decision_id=decision.decision_id,
            target_value={
                "word": word,
                "category_id": category_id,
                "keyword_id": persisted.get("id"),
                "match_terms": terms,
                "source_values": saved.get("source_values", []),
            },
        )
        _save_approved_keyword_field_proposals(session, saved, reviewer_id=payload.reviewer_id)
        return {"proposal": saved, "persisted_keyword": persisted}


@router.post("/keyword-proposals/{proposal_id}/reject")
def reject_keyword_proposal(
    proposal_id: str,
    payload: RejectRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = KeywordProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="keyword proposal not found")
        if not can_reject_keyword_proposal(proposal["status"]):
            raise HTTPException(status_code=400, detail="only pending keyword proposals can be rejected")
        saved = repo.save(
            proposal | {
                "status": PipelineStatus.REJECTED.value,
                "reviewer_id": payload.reviewer_id,
                "rejection_reason": payload.reason,
                "updated_at": datetime.now(),
                "decided_at": datetime.now(),
            }
        )
        decision = _record_keyword_decision(
            session,
            saved,
            reviewer_id=payload.reviewer_id,
            decision=ReviewDecision.REJECT,
            corrected_value=None,
            reason=payload.reason,
        )
        _save_keyword_learning(
            session,
            saved,
            knowledge_type="keyword_rejected",
            reviewer_decision_id=decision.decision_id,
            target_value={
                "action": "reject",
                "reason": payload.reason,
                "word": saved.get("proposed_keyword"),
                "match_terms": saved.get("match_terms", []),
                "source_values": saved.get("source_values", []),
            },
        )
        return saved


def _record_keyword_decision(
    session,
    keyword_proposal: dict[str, Any],
    *,
    reviewer_id: str,
    decision: ReviewDecision,
    corrected_value: Any,
    reason: str,
) -> ReviewDecisionContract:
    decision_id = f"{keyword_proposal['proposal_id']}:{decision.value}"
    record = ReviewDecisionContract(
        decision_id=decision_id,
        proposal_id=keyword_proposal["proposal_id"],
        proposal_type=ProposalType.KEYWORD,
        decision=decision,
        reviewer_id=reviewer_id,
        corrected_value=corrected_value,
        reason=reason,
        create_learning_rule=True,
    )
    ReviewDecisionRepository(session).save(record)
    return record


def _save_keyword_learning(
    session,
    keyword_proposal: dict[str, Any],
    *,
    knowledge_type: str,
    reviewer_decision_id: str,
    target_value: dict[str, Any],
) -> None:
    repo = LearnedKnowledgeRepository(session)
    terms = _dedupe_strings(
        [
            keyword_proposal.get("proposed_keyword"),
            *(keyword_proposal.get("match_terms") or []),
            *(keyword_proposal.get("source_values") or []),
        ]
    )
    examples = _dedupe_strings(
        [
            *(term for term in terms if term),
            *(
                record.get("raw_title")
                for record in keyword_proposal.get("triggering_records", [])
                if isinstance(record, dict)
            ),
        ]
    )
    for term in terms:
        norm = normalize_keyword(term)
        if not norm:
            continue
        knowledge_id = _knowledge_id(knowledge_type, keyword_proposal.get("proposed_keyword"), term)
        existing = repo.get(knowledge_id)
        positive_examples = list(existing.positive_examples) if existing else []
        negative_examples = list(existing.negative_examples) if existing else []
        if knowledge_type == "keyword_rejected":
            negative_examples = _dedupe_strings([*negative_examples, *examples])
        else:
            positive_examples = _dedupe_strings([*positive_examples, *examples])
        repo.save(
            LearnedKnowledgeContract(
                knowledge_id=knowledge_id,
                knowledge_type=knowledge_type,
                source_name=_proposal_source_name(keyword_proposal),
                pattern=term,
                target_value=target_value,
                positive_examples=positive_examples,
                negative_examples=negative_examples,
                created_from_decision_id=reviewer_decision_id,
            )
        )


def _knowledge_id(knowledge_type: str, keyword: Any, term: str) -> str:
    digest = hashlib.sha1(f"{knowledge_type}:{keyword}:{normalize_keyword(term)}".encode("utf-8")).hexdigest()[:16]
    return f"{knowledge_type}:{digest}"


def _proposal_source_name(keyword_proposal: dict[str, Any]) -> str | None:
    for record in keyword_proposal.get("triggering_records", []):
        if isinstance(record, dict) and record.get("source_name"):
            return str(record["source_name"])
    return None


def _dedupe_strings(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        norm = normalize_keyword(stripped)
        if not stripped or norm in seen:
            continue
        seen.add(norm)
        result.append(stripped)
    return result


def _save_approved_keyword_field_proposals(
    session,
    keyword_proposal: dict[str, Any],
    *,
    reviewer_id: str,
) -> None:
    repo = FieldProposalRepository(session)
    keyword = keyword_proposal["proposed_keyword"]
    for record in keyword_proposal.get("triggering_records", []):
        raw_id = record.get("raw_record_id")
        raw_title = record.get("raw_title") or keyword
        if not raw_id:
            continue
        proposal = FieldProposalContract(
            proposal_id=f"{keyword_proposal['proposal_id']}:approved:{raw_id}",
            proposal_type=ProposalType.KEYWORD,
            target_field="keywords",
            proposed_value=keyword,
            status=PipelineStatus.APPROVED,
            provenance=FieldProvenance(
                raw_record_id=raw_id,
                source_field="keyword_proposal",
                evidence_text=str(raw_title),
                worker_role=AIWorkerRole.KEYWORD_GENERATOR,
                confidence=keyword_proposal.get("confidence"),
                reviewed_by=reviewer_id,
                reviewed_at=datetime.now(),
            ),
            alternatives=[
                {
                    "keyword_proposal_id": keyword_proposal["proposal_id"],
                    "match_terms": keyword_proposal.get("match_terms", []),
                    "persisted_keyword_id": keyword_proposal.get("persisted_keyword_id"),
                }
            ],
        )
        repo.save(proposal)


@router.post("/proposals/{proposal_id}/start")
def start_review(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            updated = _service(session).start_review(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return updated.model_dump(mode="json")


@router.post("/proposals/{proposal_id}/approve")
def approve(
    proposal_id: str,
    payload: ApproveRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            decision = _service(session).approve(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                create_learning_rule=payload.create_learning_rule,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.model_dump(mode="json")


@router.get("/audit")
def audit_raw_vs_ai(
    batch_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        records = (
            raw_repo.list_records(batch_id)
            if batch_id
            else raw_repo.list_all_records()
        )
        proposals = FieldProposalRepository(session).list()
        if batch_id:
            record_ids = {record.raw_record_id for record in records}
            proposals = _field_proposals_for_scope(
                proposals,
                batch_id=batch_id,
                raw_ids=record_ids,
            )
        return build_raw_ai_audit(records, proposals, batch_id=batch_id)


@router.get("/publish-eligibility")
def publish_eligibility(
    batch_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        rows = build_publish_rows(session, batch_id=batch_id)
        summary = build_batch_publish_summary(session, rows, batch_id=batch_id)
        return {
            "items": rows,
            "eligible_count": summary["eligible_count"],
            "blocked_count": summary["blocked_count"],
            "summary": summary,
            "held_rows": summary.get("held_rows", []),
            "approved_rows": summary.get("approved_rows", []),
            "safety": _publish_safety_metadata(summary),
        }


@router.get("/batch-anomaly-audit")
def batch_anomaly_audit(
    batch_id: Optional[str] = None,
    stale_days: int = 7,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    if stale_days < 1 or stale_days > 90:
        raise HTTPException(status_code=400, detail="stale_days must be between 1 and 90")
    with db.session_scope() as session:
        return build_ai_batch_anomaly_audit(session, batch_id=batch_id, stale_days=stale_days)


@router.get("/operator-dashboard-summary")
def operator_dashboard_summary(
    batch_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        return build_operator_dashboard_summary(session, batch_id=batch_id)


@router.post("/publish-approved")
async def publish_approved_records(
    payload: PublishApprovedRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        rows = build_publish_rows(session, batch_id=payload.batch_id)
    selected_ids = set(payload.raw_record_ids)
    def _selected_publish_candidate(row: dict[str, Any]) -> bool:
        if selected_ids and row["raw_record_id"] not in selected_ids:
            return False
        if row["eligible"]:
            return True
        return bool(
            selected_ids
            and row.get("status") == PipelineStatus.PENDING_DB_REVIEW.value
            and row.get("ai_safe_final_approve_eligible")
            and row.get("db_ingestion_id")
        )

    candidates = [row for row in rows if _selected_publish_candidate(row)]
    preflight_failures: list[dict[str, Any]] = []
    if selected_ids:
        missing = selected_ids - {row["raw_record_id"] for row in rows}
        blocked = [
            row
            for row in rows
            if row["raw_record_id"] in selected_ids and not _selected_publish_candidate(row)
        ]
        if missing or blocked:
            preflight_failures = [
                {
                    "raw_record_id": raw_id,
                    "status": "not_found",
                    "error": "raw record not found",
                }
                for raw_id in sorted(missing)
            ] + [
                {
                    "raw_record_id": row["raw_record_id"],
                    "status": row["status"],
                    "error": "; ".join(row["blockers"]),
                }
                for row in blocked
            ]
            if not candidates:
                return {
                    "published": 0,
                    "failed": len(preflight_failures),
                    "results": preflight_failures,
                    "safety": _publish_safety_metadata(),
                }
    if payload.confirm_count != len(candidates):
        raise HTTPException(
            status_code=400,
            detail=f"confirmation count mismatch: expected {len(candidates)}, got {payload.confirm_count}",
        )
    if not candidates:
        raise HTTPException(status_code=400, detail="no eligible records selected")

    mutation_preflight: dict[str, Any] | None = None
    if any(candidate.get("ai_safe_final_approve_eligible") for candidate in candidates):
        mutation_preflight = await _check_db_admin_mutation_preflight()
        if not _db_admin_mutation_preflight_ready(mutation_preflight):
            message = _db_admin_mutation_preflight_error(mutation_preflight)
            results = list(preflight_failures)
            for candidate in candidates:
                with db.session_scope() as session:
                    upsert_publish_record(
                        session,
                        candidate,
                        status=PipelineStatus.PUBLISH_FAILED.value,
                        requested_by=payload.reviewer_id,
                        db_result={"mutation_preflight": mutation_preflight, "error": message},
                        last_error=message,
                    )
                results.append(
                    {
                        "raw_record_id": candidate["raw_record_id"],
                        "status": PipelineStatus.PUBLISH_FAILED.value,
                        "error": message,
                        "requires_db_admin_review": True,
                        "db_handoff_mode": candidate.get("db_handoff_mode"),
                        "ai_safe_final_approve_eligible": candidate.get("ai_safe_final_approve_eligible"),
                    }
                )
            return {
                "published": 0,
                "submitted_to_db_admin": 0,
                "pending_db_review": 0,
                "ai_safe_final_approved": 0,
                "public_db_verified": 0,
                "rollback_re_review_supported": 0,
                "operator_next_action": "Create/verify a DB-admin backup snapshot and rerun publish-approved.",
                "final_approve_failed": len(candidates),
                "failed": len(results),
                "results": results,
                "safety": {
                    **_publish_safety_metadata(),
                    "mutation_preflight": mutation_preflight,
                },
            }

    results: list[dict[str, Any]] = list(preflight_failures)
    for candidate in candidates:
        raw_id = candidate["raw_record_id"]
        if candidate.get("db_ingestion_id"):
            final_status = PipelineStatus.PENDING_DB_REVIEW.value
            final_approve_response: dict[str, Any] | None = None
            final_approve_error: str | None = None
            db_result = {
                **(candidate.get("db_ingestion_result") or {}),
                "already_submitted": True,
                "message": "Existing DB-admin ingestion reused; duplicate submit skipped.",
            }
            if candidate.get("ai_safe_final_approve_eligible"):
                try:
                    final_approve_response = await _ai_safe_final_approve_db_admin(
                        candidate["db_ingestion_id"],
                        notes=(
                            "AI-admin one-final-action retry: operator "
                            f"{payload.reviewer_id} confirmed critical validation for raw "
                            f"{raw_id}."
                        ),
                    )
                    if _final_approve_public_verified(
                        final_approve_response
                    ) and _final_approve_rollback_re_review_supported(final_approve_response):
                        final_status = PipelineStatus.PUBLISHED.value
                    else:
                        final_approve_error = (
                            "DB-admin ai-safe-final-approve response lacked public DB verification "
                            "or rollback/re-review evidence; keeping row in DB-admin review."
                        )
                    db_result = {
                        **db_result,
                        "ai_safe_final_approve": final_approve_response,
                        "one_final_action": True,
                        **({"requires_db_admin_review": True} if final_approve_error else {}),
                    }
                except Exception as exc:  # pragma: no cover - exact httpx type is integration-dependent
                    final_approve_error = str(exc)
                    db_result = {
                        **db_result,
                        "ai_safe_final_approve_error": final_approve_error,
                        "one_final_action": True,
                        "requires_db_admin_review": True,
                    }
            with db.session_scope() as session:
                upsert_publish_record(
                    session,
                    candidate,
                    status=final_status,
                    requested_by=payload.reviewer_id,
                    db_ingestion_id=str(candidate["db_ingestion_id"]),
                    db_result=db_result,
                    last_error=final_approve_error,
                )
            result = {
                "raw_record_id": raw_id,
                "status": final_status,
                "db_ingestion_id": candidate.get("db_ingestion_id"),
                "skipped_duplicate": True,
                "db_handoff_mode": candidate.get("db_handoff_mode"),
                "ai_safe_final_approve_eligible": candidate.get("ai_safe_final_approve_eligible"),
            }
            if final_approve_response is not None:
                result["ai_safe_final_approve"] = final_approve_response
            if final_approve_error is not None:
                result["final_approve_error"] = final_approve_error
                result["requires_db_admin_review"] = True
            results.append(result)
            continue
        with db.session_scope() as session:
            upsert_publish_record(
                session,
                candidate,
                status=PipelineStatus.PUBLISHING.value,
                requested_by=payload.reviewer_id,
            )
        try:
            response = await _submit_to_db_admin(build_db_admin_ingestion_payload(candidate))
        except Exception as exc:  # pragma: no cover - exact httpx type is integration-dependent
            message = str(exc)
            with db.session_scope() as session:
                upsert_publish_record(
                    session,
                    candidate,
                    status=PipelineStatus.PUBLISH_FAILED.value,
                    requested_by=payload.reviewer_id,
                    last_error=message,
                    db_result={"error": message},
                )
            results.append(
                {"raw_record_id": raw_id, "status": "publish_failed", "error": message}
            )
            continue

        ingestion_id = response.get("id")
        final_approve_response: dict[str, Any] | None = None
        final_approve_error: str | None = None
        final_status = PipelineStatus.PENDING_DB_REVIEW.value
        final_db_result: dict[str, Any] = response
        if candidate.get("ai_safe_final_approve_eligible") and ingestion_id is not None:
            if not _db_admin_submit_retained_pending(response):
                final_approve_error = (
                    "DB-admin submit did not return pending status; final approve skipped to avoid "
                    "silent DB mutation before explicit approval."
                )
                final_db_result = {
                    **response,
                    "ai_safe_final_approve_error": final_approve_error,
                    "one_final_action": True,
                    "requires_db_admin_review": True,
                }
            else:
                try:
                    final_approve_response = await _ai_safe_final_approve_db_admin(
                        ingestion_id,
                        notes=(
                            "AI-admin one-final-action handoff: operator "
                            f"{payload.reviewer_id} confirmed critical validation for raw "
                            f"{raw_id}."
                        ),
                    )
                    if _final_approve_public_verified(
                        final_approve_response
                    ) and _final_approve_rollback_re_review_supported(final_approve_response):
                        final_status = PipelineStatus.PUBLISHED.value
                    else:
                        final_approve_error = (
                            "DB-admin ai-safe-final-approve response lacked public DB verification "
                            "or rollback/re-review evidence; keeping row in DB-admin review."
                        )
                    final_db_result = {
                        **response,
                        "ai_safe_final_approve": final_approve_response,
                        "one_final_action": True,
                        **({"requires_db_admin_review": True} if final_approve_error else {}),
                    }
                except Exception as exc:  # pragma: no cover - exact httpx type is integration-dependent
                    final_approve_error = str(exc)
                    final_db_result = {
                        **response,
                        "ai_safe_final_approve_error": final_approve_error,
                        "one_final_action": True,
                        "requires_db_admin_review": True,
                    }
        with db.session_scope() as session:
            upsert_publish_record(
                session,
                candidate,
                status=final_status,
                requested_by=payload.reviewer_id,
                db_ingestion_id=str(ingestion_id) if ingestion_id is not None else None,
                db_result=final_db_result,
                last_error=final_approve_error,
            )
        result = {
            "raw_record_id": raw_id,
            "status": final_status,
            "db_ingestion_id": ingestion_id,
            "db_handoff_mode": candidate.get("db_handoff_mode"),
            "ai_safe_final_approve_eligible": candidate.get("ai_safe_final_approve_eligible"),
        }
        if final_approve_response is not None:
            result["ai_safe_final_approve"] = final_approve_response
        if final_approve_error is not None:
            result["final_approve_error"] = final_approve_error
            result["requires_db_admin_review"] = True
        results.append(result)

    published_count = sum(
        1 for result in results if result["status"] == PipelineStatus.PUBLISHED.value
    )
    public_db_verified_count = sum(
        1 for result in results if _final_approve_public_verified(result.get("ai_safe_final_approve"))
    )
    rollback_re_review_supported_count = sum(
        1
        for result in results
        if _final_approve_rollback_re_review_supported(result.get("ai_safe_final_approve"))
    )
    return {
        "published": published_count,
        "submitted_to_db_admin": sum(
            1
            for result in results
            if result["status"] in {
                PipelineStatus.PENDING_DB_REVIEW.value,
                PipelineStatus.PUBLISHED.value,
            }
        ),
        "pending_db_review": sum(
            1 for result in results if result["status"] == PipelineStatus.PENDING_DB_REVIEW.value
        ),
        "ai_safe_final_approved": published_count,
        "public_db_verified": public_db_verified_count,
        "rollback_re_review_supported": rollback_re_review_supported_count,
        "operator_next_action": (
            "Use DB-admin published-row rollback or re-review endpoints for any row that later fails audit."
            if published_count
            else "Resolve publish blockers and rerun publish-approved for eligible rows."
        ),
        "final_approve_failed": sum(
            1 for result in results if result.get("final_approve_error")
        ),
        "failed": sum(
            1
            for result in results
            if result["status"] not in {
                PipelineStatus.PENDING_DB_REVIEW.value,
                PipelineStatus.PUBLISHED.value,
            }
        ),
        "results": results,
        "safety": _publish_safety_metadata(),
    }


@router.post("/publish-records/{raw_record_id}/rollback")
def rollback_published_record(
    raw_record_id: str,
    payload: RollbackPublishRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            row = mark_publish_record_rolled_back(
                session,
                raw_record_id,
                requested_by=payload.reviewer_id,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="publish record not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "raw_record_id": row.raw_record_id,
            "status": row.status,
            "db_ingestion_id": row.db_ingestion_id,
            "rollback_requested": True,
            "operator_instructions": row.db_ingestion_result.get("operator_instructions")
            if row.db_ingestion_result
            else None,
        }


@router.post("/proposals/{proposal_id}/correct")
def correct(
    proposal_id: str,
    payload: CorrectRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            proposal = FieldProposalRepository(session).get(proposal_id)
            corrected_value = payload.corrected_value
            if proposal is not None:
                _proposal_type, _target_field, corrected_value = _normalize_category_proposal_payload(
                    proposal.proposal_type,
                    proposal.target_field,
                    payload.corrected_value,
                )
            decision = _service(session).correct(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                corrected_value=corrected_value,
                reason=payload.reason,
                create_learning_rule=payload.create_learning_rule,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.model_dump(mode="json")


@router.post("/proposals/{proposal_id}/reject")
def reject(
    proposal_id: str,
    payload: RejectRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            decision = _service(session).reject(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.model_dump(mode="json")
