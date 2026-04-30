"""
AI 검수 큐 서비스.

AI 제안은 타입별로 승인/반려/병합 흐름이 다르지만, 모든 결정은 이후 자동화 학습의
근거가 되어야 한다. 이 모듈은 제안 상태 전이와 review decision 생성을 담당한다.
"""

from __future__ import annotations

from typing import Any, Protocol

from .contracts.ai_pipeline import FieldProposal, PipelineStatus, ProposalType
from .contracts.control_plane import ReviewDecision, ReviewDecisionContract


class ReviewQueueRepository(Protocol):
    def get_proposal(self, proposal_id: str) -> FieldProposal | None:
        """proposal_id로 제안을 조회한다."""

    def save_proposal(self, proposal: FieldProposal) -> None:
        """제안 상태를 저장한다."""

    def save_decision(self, decision: ReviewDecisionContract) -> None:
        """검수 결정을 저장한다."""

    def list_by_type(self, proposal_type: ProposalType, status: PipelineStatus) -> list[FieldProposal]:
        """타입/상태별 검수 대상을 반환한다."""


class ReviewQueueService:
    def __init__(self, repository: ReviewQueueRepository):
        self.repository = repository

    def submit(self, proposal: FieldProposal) -> None:
        if proposal.status != PipelineStatus.AI_PROPOSED:
            raise ValueError("Review queue only accepts ai_proposed proposals")
        self.repository.save_proposal(proposal)

    def start_review(self, proposal_id: str) -> FieldProposal:
        proposal = self._require(proposal_id)
        if proposal.status != PipelineStatus.AI_PROPOSED:
            raise ValueError("Only ai_proposed proposals can enter human review")
        updated = proposal.model_copy(update={"status": PipelineStatus.HUMAN_REVIEWING})
        self.repository.save_proposal(updated)
        return updated

    def approve(self, proposal_id: str, reviewer_id: str, *, create_learning_rule: bool = True) -> ReviewDecisionContract:
        return self._decide(
            proposal_id,
            reviewer_id,
            decision=ReviewDecision.APPROVE,
            target_status=PipelineStatus.APPROVED,
            create_learning_rule=create_learning_rule,
        )

    def correct(
        self,
        proposal_id: str,
        reviewer_id: str,
        corrected_value: Any,
        *,
        reason: str,
        create_learning_rule: bool = True,
    ) -> ReviewDecisionContract:
        if reason.strip() == "":
            raise ValueError("Correction reason is required")
        return self._decide(
            proposal_id,
            reviewer_id,
            decision=ReviewDecision.CORRECT,
            target_status=PipelineStatus.APPROVED,
            corrected_value=corrected_value,
            reason=reason,
            create_learning_rule=create_learning_rule,
        )

    def reject(self, proposal_id: str, reviewer_id: str, *, reason: str) -> ReviewDecisionContract:
        if reason.strip() == "":
            raise ValueError("Reject reason is required")
        return self._decide(
            proposal_id,
            reviewer_id,
            decision=ReviewDecision.REJECT,
            target_status=PipelineStatus.REJECTED,
            reason=reason,
            create_learning_rule=False,
        )

    def _decide(
        self,
        proposal_id: str,
        reviewer_id: str,
        *,
        decision: ReviewDecision,
        target_status: PipelineStatus,
        corrected_value: Any = None,
        reason: str = "",
        create_learning_rule: bool = False,
    ) -> ReviewDecisionContract:
        proposal = self._require(proposal_id)
        if proposal.status not in {PipelineStatus.AI_PROPOSED, PipelineStatus.HUMAN_REVIEWING}:
            raise ValueError("Only proposed or reviewing proposals can be decided")
        updated = proposal.model_copy(update={"status": target_status})
        self.repository.save_proposal(updated)
        review = ReviewDecisionContract(
            decision_id=f"{proposal_id}:{decision.value}:{reviewer_id}",
            proposal_id=proposal_id,
            proposal_type=proposal.proposal_type,
            decision=decision,
            reviewer_id=reviewer_id,
            corrected_value=corrected_value,
            reason=reason,
            create_learning_rule=create_learning_rule,
        )
        self.repository.save_decision(review)
        return review

    def _require(self, proposal_id: str) -> FieldProposal:
        proposal = self.repository.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(f"Proposal not found: {proposal_id}")
        return proposal
