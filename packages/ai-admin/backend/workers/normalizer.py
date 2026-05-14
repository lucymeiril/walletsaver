"""NormalizerWorker — raw_title을 정규화한 후보 값을 제안한다.

raw_title 자체를 변경하지 않는다 (RawCrawlRecord는 frozen). 대신
`canonical_name` 후보를 NORMALIZED_FIELD proposal로 제출한다.
"""
from __future__ import annotations

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)

from .base import clean_title, extract_brand, make_proposal


class NormalizerWorker(BaseAIWorker):
    role = AIWorkerRole.NORMALIZER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        proposals = []
        aliases = []
        skipped = 0
        for record in batch.records:
            cleaned = clean_title(record.raw_title)
            if not cleaned:
                skipped += 1
                continue
            confidence = 0.9 if cleaned == record.raw_title.strip() else 0.7
            proposals.append(
                make_proposal(
                    batch=batch,
                    record=record,
                    proposal_type=ProposalType.NORMALIZED_FIELD,
                    target_field="canonical_name",
                    proposed_value=cleaned,
                    evidence_text=record.raw_title,
                    confidence=confidence,
                    source_field="raw_title",
                )
            )
            brand = extract_brand(cleaned)
            if brand:
                proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.NORMALIZED_FIELD,
                        target_field="brand",
                        proposed_value=brand,
                        evidence_text=brand,
                        confidence=0.75,
                        proposal_suffix="brand",
                        source_field="raw_title",
                    )
                )
            if cleaned != record.raw_title.strip():
                aliases.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.ALIAS,
                        target_field="aliases",
                        proposed_value=record.raw_title.strip(),
                        evidence_text=record.raw_title,
                        confidence=0.6,
                        proposal_suffix="alias",
                        source_field="raw_title",
                    )
                )
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            field_proposals=proposals,
            alias_proposals=aliases,
            diagnostics={
                "records_total": len(batch.records),
                "records_proposed": len({p.provenance.raw_record_id for p in proposals}),
                "fields_proposed": len(proposals),
                "records_skipped": skipped,
            },
        )
