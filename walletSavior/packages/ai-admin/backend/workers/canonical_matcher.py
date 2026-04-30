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
    ProductVariantDraft,
    ProposalType,
)

from .base import clean_title, extract_brand, make_proposal
from .unit_converter import _parse_units


class CanonicalMatcherWorker(BaseAIWorker):
    role = AIWorkerRole.CANONICAL_MATCHER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        drafts: list[CanonicalProductDraft] = []
        variants: list[ProductVariantDraft] = []
        match_proposals = []
        alias_proposals = []
        seen_canonical: set[str] = set()
        seen_variants: set[str] = set()
        for record in batch.records:
            canonical = clean_title(record.raw_title)
            if canonical not in seen_canonical:
                seen_canonical.add(canonical)
                drafts.append(
                    CanonicalProductDraft(
                        canonical_name=canonical,
                        brand=extract_brand(canonical),
                        aliases=[record.raw_title.strip()]
                        if record.raw_title.strip() != canonical
                        else [],
                    )
                )
            parsed = _parse_units(record.raw_title)
            variant_key = f"{canonical}:{parsed}" if parsed else canonical
            if variant_key not in seen_variants:
                seen_variants.add(variant_key)
                variants.append(
                    ProductVariantDraft(
                        variant_name=canonical,
                        package_quantity=parsed["package_quantity"] if parsed else None,
                        package_unit=parsed["package_unit"] if parsed else None,
                        bundle_count=parsed["bundle_count"] if parsed else 1,
                        standard_unit=parsed["standard_unit"] if parsed else None,
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
            variant_drafts=variants,
            diagnostics={
                "records_total": len(batch.records),
                "unique_canonicals": len(drafts),
                "unique_variants": len(variants),
            },
        )
