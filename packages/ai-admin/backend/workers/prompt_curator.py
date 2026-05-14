"""PromptCuratorWorker — 프롬프트 변경을 제안만 한다.

PromptCurator는 절대로 prompt를 활성화하거나 governance 상태를 바꾸지 않는다.
이 단계에서는 단지 "현재 batch가 사용한 prompt_pack을 사람이 검토하라"는
NORMALIZED_FIELD proposal을 diagnostic 형태로 제출한다.
"""
from __future__ import annotations

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)

from .base import make_proposal


class PromptCuratorWorker(BaseAIWorker):
    role = AIWorkerRole.PROMPT_CURATOR

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        # 단일 placeholder proposal: prompt_pack 검토 필요 표시. 활성화하지 않는다.
        proposals = []
        first = batch.records[0]
        proposals.append(
            make_proposal(
                batch=batch,
                record=first,
                proposal_type=ProposalType.NORMALIZED_FIELD,
                target_field="prompt_pack_review_note",
                proposed_value=(
                    f"prompt_pack {batch.prompt_pack.pack_id}@"
                    f"{batch.prompt_pack.version} 검토 권장"
                ),
                evidence_text=first.raw_title,
                confidence=0.0,
                proposal_suffix="prompt-review",
            )
        )
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            field_proposals=proposals,
            diagnostics={
                "records_total": len(batch.records),
                "activates_prompt": False,
                "prompt_pack_id": batch.prompt_pack.pack_id,
                "prompt_pack_version": batch.prompt_pack.version,
                "needs_human_review": True,
            },
        )
