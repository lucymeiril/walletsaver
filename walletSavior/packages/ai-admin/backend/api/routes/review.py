"""검수 큐 라우트.

shared `ReviewQueueService`에 상태 전이를 위임한다. AI 제안의 approve/correct/reject
결정은 이후 학습/감사의 근거가 되므로 모든 결정은 ReviewDecision으로 저장된다.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import (
    FieldProposal as FieldProposalContract,
    PipelineStatus,
    ProposalType,
)
from core.review_queue import ReviewQueueService

from storage import (
    Database,
    FieldProposalRepository,
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


def _service(session) -> ReviewQueueService:
    return ReviewQueueService(ReviewQueueRepositoryAdapter(session))


@router.get("/proposals")
def list_proposals(
    proposal_type: Optional[ProposalType] = None,
    status: Optional[PipelineStatus] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        items = repo.list(status=status, proposal_type=proposal_type)
        return {"items": [p.model_dump(mode="json") for p in items]}


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
