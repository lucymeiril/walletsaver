"""역할별 AI worker 계약 테스트."""

import pytest
from pydantic import ValidationError

from shared.core.ai_workers import AIWorkerOutput, BaseAIWorker, WorkerRegistry
from shared.core.contracts.ai_pipeline import (
    AIJobBatch,
    AIProviderRef,
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PromptPackRef,
    ProposalType,
    ProviderKind,
    RawCrawlRecord,
)


def make_batch(role: AIWorkerRole) -> AIJobBatch:
    return AIJobBatch(
        batch_id="batch-1",
        role=role,
        provider=AIProviderRef(
            provider_kind=ProviderKind.OLLAMA,
            provider_name="ollama-local",
            model_name="llama3.1",
        ),
        prompt_pack=PromptPackRef(role=role, pack_id=f"{role.value}-default", version="1"),
        records=[
            RawCrawlRecord(
                raw_record_id="raw-1",
                source_name="emart",
                raw_title="알프스 탄탄포크 정육 행사",
                raw_price=12900,
            )
        ],
    )


def make_proposal(proposal_type: ProposalType) -> FieldProposal:
    return FieldProposal(
        proposal_id=f"proposal-{proposal_type.value}",
        proposal_type=proposal_type,
        target_field="category_id",
        proposed_value="meat.pork",
        provenance=FieldProvenance(
            raw_record_id="raw-1",
            evidence_text="정육",
            worker_role=AIWorkerRole.CLASSIFIER,
        ),
    )


class DummyClassifier(BaseAIWorker):
    role = AIWorkerRole.CLASSIFIER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        return AIWorkerOutput(
            job_id="job-1",
            role=self.role,
            taxonomy_proposals=[make_proposal(ProposalType.CATEGORY)],
        )


def test_worker_rejects_wrong_role_batch():
    worker = DummyClassifier()

    with pytest.raises(ValueError, match="Expected classifier"):
        worker.run(make_batch(AIWorkerRole.NORMALIZER))


def test_worker_accepts_matching_role_batch():
    worker = DummyClassifier()

    output = worker.run(make_batch(AIWorkerRole.CLASSIFIER))

    assert output.role == AIWorkerRole.CLASSIFIER
    assert output.taxonomy_proposals[0].proposal_type == ProposalType.CATEGORY


def test_output_rejects_role_inappropriate_proposal():
    with pytest.raises(ValidationError, match="keyword_generator cannot emit category"):
        AIWorkerOutput(
            job_id="job-1",
            role=AIWorkerRole.KEYWORD_GENERATOR,
            keyword_proposals=[make_proposal(ProposalType.CATEGORY)],
        )


def test_worker_registry_prevents_duplicate_role_registration():
    registry = WorkerRegistry()
    registry.register(DummyClassifier())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(DummyClassifier())

    assert registry.get(AIWorkerRole.CLASSIFIER).role == AIWorkerRole.CLASSIFIER
