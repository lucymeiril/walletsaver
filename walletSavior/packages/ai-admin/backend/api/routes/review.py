"""검수 큐 라우트.

shared `ReviewQueueService`에 상태 전이를 위임한다. AI 제안의 approve/correct/reject
결정은 이후 학습/감사의 근거가 되므로 모든 결정은 ReviewDecision으로 저장된다.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
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
from core.review_queue import ReviewQueueService

from storage import (
    Database,
    FieldProposalRepository,
    KeywordProposalRepository,
    LearnedKnowledgeRepository,
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
from services.db_admin_adapter import build_db_admin_ingestion_payload, submit_to_db_admin
from services.review_publish import (
    build_batch_publish_summary,
    build_publish_rows,
    build_raw_ai_audit,
    mark_publish_record_rolled_back,
    mark_proposals_published,
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


class RollbackPublishRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def _service(session) -> ReviewQueueService:
    return ReviewQueueService(ReviewQueueRepositoryAdapter(session))


async def _submit_to_db_admin(payload: dict[str, Any]) -> dict[str, Any]:
    return await submit_to_db_admin(payload)


def _proposal_payload(proposal: FieldProposalContract) -> dict[str, Any]:
    return proposal.model_dump(mode="json")


def _raw_payload(record: RawCrawlRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


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
            _service(session).submit(proposal)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return proposal.model_dump(mode="json")


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
        }


@router.post("/publish-approved")
async def publish_approved_records(
    payload: PublishApprovedRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        rows = build_publish_rows(session)
    selected_ids = set(payload.raw_record_ids)
    candidates = [
        row
        for row in rows
        if row["eligible"] and (not selected_ids or row["raw_record_id"] in selected_ids)
    ]
    if selected_ids:
        missing = selected_ids - {row["raw_record_id"] for row in rows}
        blocked = [
            row
            for row in rows
            if row["raw_record_id"] in selected_ids and not row["eligible"]
        ]
        if missing or blocked:
            return {
                "published": 0,
                "failed": len(missing) + len(blocked),
                "results": [
                    {
                        "raw_record_id": raw_id,
                        "status": "not_found",
                        "error": "raw record not found",
                    }
                    for raw_id in sorted(missing)
                ]
                + [
                    {
                        "raw_record_id": row["raw_record_id"],
                        "status": row["status"],
                        "error": "; ".join(row["blockers"]),
                    }
                    for row in blocked
                ],
            }
    if payload.confirm_count != len(candidates):
        raise HTTPException(
            status_code=400,
            detail=f"confirmation count mismatch: expected {len(candidates)}, got {payload.confirm_count}",
        )
    if not candidates:
        raise HTTPException(status_code=400, detail="no eligible records selected")

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        raw_id = candidate["raw_record_id"]
        if candidate.get("db_ingestion_id"):
            with db.session_scope() as session:
                mark_proposals_published(session, candidate["proposal_ids"])
                upsert_publish_record(
                    session,
                    candidate,
                    status=PipelineStatus.PUBLISHED.value,
                    requested_by=payload.reviewer_id,
                    db_ingestion_id=str(candidate["db_ingestion_id"]),
                    db_result={
                        **(candidate.get("db_ingestion_result") or {}),
                        "already_submitted": True,
                        "message": "Existing DB-admin ingestion reused; duplicate submit skipped.",
                    },
                )
            results.append(
                {
                    "raw_record_id": raw_id,
                    "status": "published",
                    "db_ingestion_id": candidate.get("db_ingestion_id"),
                    "skipped_duplicate": True,
                }
            )
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
        with db.session_scope() as session:
            mark_proposals_published(session, candidate["proposal_ids"])
            upsert_publish_record(
                session,
                candidate,
                status=PipelineStatus.PUBLISHED.value,
                requested_by=payload.reviewer_id,
                db_ingestion_id=str(ingestion_id) if ingestion_id is not None else None,
                db_result=response,
            )
        results.append(
            {
                "raw_record_id": raw_id,
                "status": "published",
                "db_ingestion_id": ingestion_id,
            }
        )

    return {
        "published": sum(1 for result in results if result["status"] == "published"),
        "failed": sum(1 for result in results if result["status"] != "published"),
        "results": results,
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
            decision = _service(session).correct(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                corrected_value=payload.corrected_value,
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
