"""DataAuditorWorker — record 단위로 누락 신호를 점검한다."""
from __future__ import annotations

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)

from .base import make_proposal
from .classifier import _CATEGORY_KEYWORDS
from .unit_converter import _parse_units


class DataAuditorWorker(BaseAIWorker):
    role = AIWorkerRole.DATA_AUDITOR

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        issues_per_record: dict[str, list[str]] = {}
        proposals = []
        missing_price = 0
        missing_unit = 0
        missing_category = 0
        price_outlier = 0
        suspicious_category = 0
        for record in batch.records:
            issues: list[str] = []
            if not record.raw_title.strip():
                issues.append("title_missing")
            if record.raw_price is None:
                issues.append("price_missing")
                missing_price += 1
            elif record.raw_price == 0 or record.raw_price > 10_000_000:
                issues.append("price_outlier")
                price_outlier += 1
            if _parse_units(record.raw_title) is None:
                issues.append("unit_signal_missing")
                missing_unit += 1
            if not any(kw in record.raw_title for kw, *_ in _CATEGORY_KEYWORDS):
                issues.append("category_signal_missing")
                missing_category += 1
            if "오징어 땅콩" in record.raw_title and any(
                str(value).startswith("seafood")
                for value in record.raw_payload.values()
            ):
                issues.append("suspicious_category_snack_marked_seafood")
                suspicious_category += 1
            if issues:
                issues_per_record[record.raw_record_id] = issues
                proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.NORMALIZED_FIELD,
                        target_field="audit_findings",
                        proposed_value=issues,
                        evidence_text=record.raw_title or "(empty)",
                        confidence=0.0,
                        proposal_suffix="audit",
                    )
                )
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            field_proposals=proposals,
            diagnostics={
                "records_total": len(batch.records),
                "records_with_issues": len(issues_per_record),
                "missing_price": missing_price,
                "missing_unit": missing_unit,
                "missing_category": missing_category,
                "price_outlier": price_outlier,
                "suspicious_category": suspicious_category,
                "issues_per_record": issues_per_record,
            },
        )
