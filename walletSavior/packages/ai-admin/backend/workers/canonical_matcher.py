"""CanonicalMatcherWorker — 정규화된 이름으로부터 canonical 초안과 alias를 제안.

실제 매칭 인덱스는 없으므로 raw_title을 기반으로 하는 결정론적 초안만
만든다. 동일 raw_title을 두 번 보내도 같은 canonical_name이 나와야 한다.
"""
from __future__ import annotations

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    CanonicalProductDraft,
    ProposalType,
)

from .base import clean_title, make_proposal


class CanonicalMatcherWorker(BaseAIWorker):
    role = AIWorkerRole.CANONICAL_MATCHER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        drafts: list[CanonicalProductDraft] = []
        match_proposals = []
        alias_proposals = []
        seen_canonical: set[str] = set()
        for record in batch.records:
            canonical = clean_title(record.raw_title)
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                drafts.append(
                    CanonicalProductDraft(
                        canonical_name=canonical,
                        aliases=[record.raw_title.strip()]
                        if record.raw_title.strip() != canonical
                        else [],
                    )
                )
            match_proposals.append(
                make_proposal(
                    batch=batch,
                    record=record,
                    proposal_type=ProposalType.CANONICAL_MATCH,
                    target_field="canonical_name",
                    proposed_value=canonical,
                    evidence_text=record.raw_title,
                    confidence=0.6,
                    source_field="raw_title",
                )
            )
            if record.raw_title.strip() != canonical:
                alias_proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.ALIAS,
                        target_field="aliases",
                        proposed_value=record.raw_title.strip(),
                        evidence_text=record.raw_title,
                        confidence=0.55,
                        proposal_suffix="alias",
                        source_field="raw_title",
                    )
                )
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            field_proposals=match_proposals,
            alias_proposals=alias_proposals,
            canonical_drafts=drafts,
            diagnostics={
                "records_total": len(batch.records),
                "unique_canonicals": len(drafts),
            },
        )
