"""AI review queue 상태 전이 테스트."""

import pytest

from shared.core.contracts.ai_pipeline import (
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
)
from shared.core.contracts.control_plane import ReviewDecision
from shared.core.review_queue import ReviewQueueService


class InMemoryReviewRepo:
    def __init__(self):
        self.proposals = {}
        self.decisions = []

    def get_proposal(self, proposal_id: str):
        return self.proposals.get(proposal_id)

    def save_proposal(self, proposal: FieldProposal):
        self.proposals[proposal.proposal_id] = proposal

    def save_decision(self, decision):
        self.decisions.append(decision)

    def list_by_type(self, proposal_type, status):
        return [
            proposal
            for proposal in self.proposals.values()
            if proposal.proposal_type == proposal_type and proposal.status == status
        ]


def make_proposal() -> FieldProposal:
    return FieldProposal(
        proposal_id="proposal-1",
        proposal_type=ProposalType.CATEGORY,
        target_field="category_id",
        proposed_value="meat.pork.belly",
        provenance=FieldProvenance(
            raw_record_id="raw-1",
            evidence_text="삼겹살",
            worker_role=AIWorkerRole.CLASSIFIER,
        ),
    )


def test_submit_and_approve_creates_learning_decision():
    repo = InMemoryReviewRepo()
    service = ReviewQueueService(repo)
    service.submit(make_proposal())

    decision = service.approve("proposal-1", "admin")

    assert repo.proposals["proposal-1"].status == PipelineStatus.APPROVED
    assert decision.decision == ReviewDecision.APPROVE
    assert decision.create_learning_rule is True


def test_correct_requires_reason_and_stores_corrected_value():
    repo = InMemoryReviewRepo()
    service = ReviewQueueService(repo)
    service.submit(make_proposal())

    with pytest.raises(ValueError, match="reason"):
        service.correct("proposal-1", "admin", "meat.pork.neck", reason="")

    decision = service.correct(
        "proposal-1",
        "admin",
        "meat.pork.neck",
        reason="목살 상품으로 확인",
    )

    assert decision.corrected_value == "meat.pork.neck"
    assert decision.decision == ReviewDecision.CORRECT


def test_reject_does_not_create_learning_rule():
    repo = InMemoryReviewRepo()
    service = ReviewQueueService(repo)
    service.submit(make_proposal())

    decision = service.reject("proposal-1", "admin", reason="비상품 광고")

    assert repo.proposals["proposal-1"].status == PipelineStatus.REJECTED
    assert decision.create_learning_rule is False
