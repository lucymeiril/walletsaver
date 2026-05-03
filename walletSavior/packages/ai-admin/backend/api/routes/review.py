"""검수 큐 라우트.

shared `ReviewQueueService`에 상태 전이를 위임한다. AI 제안의 approve/correct/reject
결정은 이후 학습/감사의 근거가 되므로 모든 결정은 ReviewDecision으로 저장된다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import (
    FieldProposal as FieldProposalContract,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from core.review_queue import ReviewQueueService

from storage import (
    Database,
    FieldProposalRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    ReviewQueueRepositoryAdapter,
    get_default_database,
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


class UpdateProposalRequest(BaseModel):
    proposal_type: Optional[ProposalType] = None
    target_field: Optional[str] = Field(default=None, min_length=1)
    proposed_value: Any = None
    alternatives: Optional[list[Any]] = None


def _service(session) -> ReviewQueueService:
    return ReviewQueueService(ReviewQueueRepositoryAdapter(session))


ACTIVE_PROPOSAL_STATUSES = {
    PipelineStatus.AI_PROPOSED,
    PipelineStatus.HUMAN_REVIEWING,
    PipelineStatus.APPROVED,
    PipelineStatus.PUBLISHED,
}


def _proposal_payload(proposal: FieldProposalContract) -> dict[str, Any]:
    return proposal.model_dump(mode="json")


def _raw_payload(record: RawCrawlRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


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
            proposals_by_record = _proposals_by_raw_record(
                FieldProposalRepository(session).list()
            )
            for item in items:
                item["proposals"] = [
                    _proposal_payload(proposal)
                    for proposal in proposals_by_record.get(item["raw_record_id"], [])
                ]
        return {"items": items}


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


def _proposals_by_raw_record(
    proposals: list[FieldProposalContract],
) -> dict[str, list[FieldProposalContract]]:
    grouped: dict[str, list[FieldProposalContract]] = defaultdict(list)
    for proposal in proposals:
        raw_id = proposal.provenance.raw_record_id
        if raw_id:
            grouped[raw_id].append(proposal)
    return grouped


def build_raw_ai_audit(
    records: list[RawCrawlRecord],
    proposals: list[FieldProposalContract],
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    active_proposals = [
        proposal for proposal in proposals if proposal.status in ACTIVE_PROPOSAL_STATUSES
    ]
    grouped = _proposals_by_raw_record(active_proposals)
    issues: list[dict[str, Any]] = []
    covered_records = 0

    for record in records:
        record_proposals = grouped.get(record.raw_record_id, [])
        if record_proposals:
            covered_records += 1
        else:
            issues.append(_issue(record, "missing_all_proposals", "raw record has no active AI proposals"))
            continue

        by_field = _proposal_values_by_field(record_proposals)
        required = {
            "canonical_name": bool(by_field.get("canonical_name")),
            "category_id": bool(by_field.get("category_id")),
            "unit": any(by_field.get(field) for field in (
                "package_unit",
                "standard_unit",
                "unit",
                "package_quantity",
                "standard_unit_price",
            )),
            "keywords": bool(by_field.get("keywords")),
        }
        for signal, present in required.items():
            if not present:
                issues.append(_issue(record, f"missing_{signal}_signal", f"missing {signal} proposal"))

        issues.extend(_expected_mismatch_issues(record, by_field))
        issues.extend(_raw_signal_mismatch_issues(record, by_field))

    return {
        "batch_id": batch_id,
        "raw_record_count": len(records),
        "covered_record_count": covered_records,
        "missing_record_count": max(len(records) - covered_records, 0),
        "proposal_count": len(active_proposals),
        "issue_count": len(issues),
        "status": "ok" if not issues else "warning",
        "issues": issues,
    }


def _proposal_values_by_field(
    proposals: list[FieldProposalContract],
) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = defaultdict(list)
    for proposal in proposals:
        if proposal.proposed_value not in (None, ""):
            values[proposal.target_field].append(proposal.proposed_value)
    return values


def _issue(record: RawCrawlRecord, code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "raw_record_id": record.raw_record_id,
        "source_name": record.source_name,
        "raw_title": record.raw_title,
        "code": code,
        "message": message,
    }
    payload.update(extra)
    return payload


def _expected_mismatch_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    expected = _expected_ai(record.raw_payload)
    issues: list[dict[str, Any]] = []
    comparisons = {
        "canonical_name": ("canonical_name",),
        "category_id": ("category_id",),
        "package_unit": ("package_unit", "standard_unit", "unit"),
    }
    for expected_key, proposal_fields in comparisons.items():
        if expected_key not in expected:
            continue
        actual = [
            value
            for field in proposal_fields
            for value in by_field.get(field, [])
        ]
        if expected[expected_key] not in actual:
            issues.append(
                _issue(
                    record,
                    f"mismatched_{expected_key}",
                    f"expected {expected_key} was not proposed",
                    expected=expected[expected_key],
                    actual=actual,
                )
            )

    expected_keywords = expected.get("keywords")
    if isinstance(expected_keywords, list):
        actual_keywords = {str(value) for value in by_field.get("keywords", [])}
        missing = [kw for kw in expected_keywords if str(kw) not in actual_keywords]
        if missing:
            issues.append(
                _issue(
                    record,
                    "mismatched_keywords",
                    "expected keywords were not proposed",
                    expected=expected_keywords,
                    actual=sorted(actual_keywords),
                    missing=missing,
                )
            )
    return issues


def _expected_ai(raw_payload: dict[str, Any]) -> dict[str, Any]:
    expected = raw_payload.get("expected_ai")
    if isinstance(expected, dict):
        return expected
    result: dict[str, Any] = {}
    for key in ("canonical_name", "category_id", "package_unit", "keywords"):
        raw_key = f"expected_{key}"
        if raw_key in raw_payload:
            result[key] = raw_payload[raw_key]
    return result


def _raw_signal_mismatch_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    title_tokens = _tokens(record.raw_title)
    for value in by_field.get("canonical_name", []):
        if title_tokens and not title_tokens.intersection(_tokens(str(value))):
            issues.append(
                _issue(
                    record,
                    "name_signal_mismatch",
                    "canonical name does not share any signal with raw title",
                    proposed=value,
                )
            )
    keyword_values = [str(value) for value in by_field.get("keywords", [])]
    if keyword_values and title_tokens:
        matching = [kw for kw in keyword_values if title_tokens.intersection(_tokens(kw))]
        if not matching:
            issues.append(
                _issue(
                    record,
                    "keyword_signal_mismatch",
                    "keywords do not share any signal with raw title",
                    proposed=keyword_values,
                )
            )
    return issues


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
        if len(token) >= 2
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
