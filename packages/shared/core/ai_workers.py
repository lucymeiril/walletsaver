"""
역할별 AI worker 계약과 공통 검증.

각 worker는 하나의 기능만 담당한다. Normalizer가 prompt를 고치거나, Classifier가
provider 설정을 바꾸는 식의 역할 침범을 막기 위해 입력/출력 역할을 명시적으로
검증한다.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field, model_validator

from .contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    CanonicalProductDraft,
    FieldProposal,
    ProposalType,
    ProductVariantDraft,
    SaleOfferDraft,
)


class AIWorkerOutput(BaseModel):
    """모든 역할별 worker가 반환하는 공통 출력."""

    job_id: str = Field(min_length=1)
    role: AIWorkerRole
    field_proposals: list[FieldProposal] = Field(default_factory=list)
    canonical_drafts: list[CanonicalProductDraft] = Field(default_factory=list)
    variant_drafts: list[ProductVariantDraft] = Field(default_factory=list)
    offer_drafts: list[SaleOfferDraft] = Field(default_factory=list)
    taxonomy_proposals: list[FieldProposal] = Field(default_factory=list)
    keyword_proposals: list[FieldProposal] = Field(default_factory=list)
    alias_proposals: list[FieldProposal] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_role_output(self) -> "AIWorkerOutput":
        allowed = ALLOWED_PROPOSALS_BY_ROLE[self.role]
        for proposal in self.field_proposals + self.taxonomy_proposals + self.keyword_proposals + self.alias_proposals:
            if proposal.proposal_type not in allowed:
                raise ValueError(
                    f"{self.role.value} cannot emit {proposal.proposal_type.value} proposals"
                )
        return self


class AIWorker(Protocol):
    """ai-admin worker 구현체가 따르는 최소 인터페이스."""

    role: AIWorkerRole

    def run(self, batch: AIJobBatch) -> AIWorkerOutput:
        """batch를 처리해 검수 가능한 proposal/draft를 반환한다."""


ALLOWED_PROPOSALS_BY_ROLE: dict[AIWorkerRole, set[ProposalType]] = {
    AIWorkerRole.NORMALIZER: {ProposalType.NORMALIZED_FIELD, ProposalType.ALIAS},
    AIWorkerRole.UNIT_CONVERTER: {ProposalType.NORMALIZED_FIELD},
    AIWorkerRole.CLASSIFIER: {
        ProposalType.NORMALIZED_FIELD,
        ProposalType.CATEGORY,
        ProposalType.ATTRIBUTE_DEFINITION,
        ProposalType.ATTRIBUTE_VALUE,
    },
    AIWorkerRole.CANONICAL_MATCHER: {ProposalType.CANONICAL_MATCH, ProposalType.ALIAS},
    AIWorkerRole.KEYWORD_GENERATOR: {ProposalType.KEYWORD, ProposalType.ALIAS},
    AIWorkerRole.PROMPT_CURATOR: {ProposalType.NORMALIZED_FIELD},
    AIWorkerRole.DATA_AUDITOR: {ProposalType.NORMALIZED_FIELD},
}


def ensure_batch_role(batch: AIJobBatch, expected_role: AIWorkerRole) -> None:
    """잘못된 역할의 batch가 worker에 들어오는 것을 즉시 차단한다."""
    if batch.role != expected_role:
        raise ValueError(f"Expected {expected_role.value} batch, got {batch.role.value}")


class BaseAIWorker:
    """역할 검증만 제공하는 worker base class."""

    role: AIWorkerRole

    def run(self, batch: AIJobBatch) -> AIWorkerOutput:
        ensure_batch_role(batch, self.role)
        return self.process(batch)

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        raise NotImplementedError


class WorkerRegistry:
    """역할별 worker 등록소."""

    def __init__(self) -> None:
        self._workers: dict[AIWorkerRole, AIWorker] = {}

    def register(self, worker: AIWorker) -> None:
        if worker.role in self._workers:
            raise ValueError(f"Worker already registered for role: {worker.role.value}")
        self._workers[worker.role] = worker

    def get(self, role: AIWorkerRole) -> AIWorker:
        try:
            return self._workers[role]
        except KeyError as exc:
            raise KeyError(f"No worker registered for role: {role.value}") from exc

    def list_roles(self) -> list[AIWorkerRole]:
        return sorted(self._workers, key=lambda role: role.value)
