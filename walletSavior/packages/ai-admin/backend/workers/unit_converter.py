"""UnitConverterWorker — 수량/묶음/표준 단가 후보를 추출한다."""
from __future__ import annotations

import re
from typing import Optional

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)
from core.product_units import normalize_unit_metadata, quantity_to_standard_total

from .base import make_proposal

_BUNDLE_PATTERN = re.compile(r"(?:x|X|×|\*)\s*(?P<count>\d+)|(?P<count_suffix>\d+)\s*(?:개입|입|봉|팩|병|캔)")


def _parse_units(text: str) -> Optional[dict]:
    parsed = normalize_unit_metadata(name=text)
    if parsed.get("package_quantity") is None or parsed.get("package_unit") is None:
        return None
    bundle_count = 1
    raw_match = str(parsed["raw_match"])
    tail = text[text.rfind(raw_match) + len(raw_match):] if raw_match in text else ""
    bundle_match = _BUNDLE_PATTERN.search(tail)
    if bundle_match:
        bundle_count = int(bundle_match.group("count") or bundle_match.group("count_suffix"))
    total = quantity_to_standard_total(parsed["package_quantity"], parsed["package_unit"], bundle_count)
    if total is None:
        return None
    total_quantity, standard_unit = total
    return {
        "raw_match": parsed["raw_match"],
        "package_quantity": parsed["package_quantity"],
        "package_unit": parsed["package_unit"],
        "display_unit": parsed["display_unit"],
        "bundle_count": bundle_count,
        "total_quantity": round(total_quantity, 6),
        "standard_unit": standard_unit,
    }


class UnitConverterWorker(BaseAIWorker):
    role = AIWorkerRole.UNIT_CONVERTER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        proposals = []
        unmatched = 0
        for record in batch.records:
            parsed = _parse_units(record.raw_title)
            if parsed is None:
                unmatched += 1
                continue
            fields = (
                "package_quantity",
                "package_unit",
                "display_unit",
                "bundle_count",
                "total_quantity",
                "standard_unit",
            )
            for field in fields:
                proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.NORMALIZED_FIELD,
                        target_field=field,
                        proposed_value=parsed[field],
                        evidence_text=parsed["raw_match"],
                        confidence=0.85,
                        proposal_suffix=field,
                        source_field="raw_title",
                    )
                )
            if record.raw_price is not None and parsed["total_quantity"] > 0:
                standard_unit_price = round(record.raw_price / parsed["total_quantity"], 2)
                proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.NORMALIZED_FIELD,
                        target_field="standard_unit_price",
                        proposed_value=standard_unit_price,
                        evidence_text=f"{record.raw_price}/{parsed['total_quantity']}{parsed['standard_unit']}",
                        confidence=0.82,
                        proposal_suffix="standard_unit_price",
                        source_field="raw_price",
                    )
                )
                if parsed["package_unit"] == "g":
                    proposals.append(
                        make_proposal(
                            batch=batch,
                            record=record,
                            proposal_type=ProposalType.NORMALIZED_FIELD,
                            target_field="price_per_100g",
                            proposed_value=round(record.raw_price * 100 / (parsed["package_quantity"] * parsed["bundle_count"]), 2),
                            evidence_text=f"{record.raw_price}/{parsed['package_quantity'] * parsed['bundle_count']}g",
                            confidence=0.86,
                            proposal_suffix="price_per_100g",
                            source_field="raw_price",
                        )
                    )
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            field_proposals=proposals,
            diagnostics={
                "records_total": len(batch.records),
                "records_matched": len(batch.records) - unmatched,
                "records_unmatched": unmatched,
            },
        )
