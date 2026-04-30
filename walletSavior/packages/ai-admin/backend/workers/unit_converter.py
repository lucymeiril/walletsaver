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

from .base import make_proposal

# (값, 단위, 표준단위) — 표준단위는 공개 카탈로그의 단위 표기.
_UNIT_PATTERN = re.compile(
    r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|mg|l|L|ml|mL|개|팩|입|매|봉|병|캔)",
    re.IGNORECASE,
)
_BUNDLE_PATTERN = re.compile(r"(?:x|X|×|\*)\s*(?P<count>\d+)|(?P<count_suffix>\d+)\s*(?:개입|입|봉|팩|병|캔)")

_STANDARD_UNIT_MAP = {
    "kg": "kg",
    "g": "kg",
    "mg": "kg",
    "l": "L",
    "ml": "L",
    "개": "ea",
    "팩": "ea",
    "입": "ea",
    "매": "ea",
    "봉": "ea",
    "병": "ea",
    "캔": "ea",
}


def _normalize_total_quantity(qty: float, unit: str, bundle_count: int) -> float:
    if unit == "mg":
        return qty / 1_000_000 * bundle_count
    if unit == "g":
        return qty / 1000 * bundle_count
    if unit == "kg":
        return qty * bundle_count
    if unit == "ml":
        return qty / 1000 * bundle_count
    if unit == "l":
        return qty * bundle_count
    return qty * bundle_count


def _parse_units(text: str) -> Optional[dict]:
    match = _UNIT_PATTERN.search(text)
    if not match:
        return None
    qty = float(match.group("qty"))
    unit = match.group("unit").lower()
    bundle_match = _BUNDLE_PATTERN.search(text[match.end():])
    bundle_count = 1
    if bundle_match:
        bundle_count = int(bundle_match.group("count") or bundle_match.group("count_suffix"))
    return {
        "raw_match": match.group(0),
        "package_quantity": qty,
        "package_unit": unit,
        "bundle_count": bundle_count,
        "total_quantity": round(_normalize_total_quantity(qty, unit, bundle_count), 6),
        "standard_unit": _STANDARD_UNIT_MAP.get(unit, unit),
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
                proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.NORMALIZED_FIELD,
                        target_field="standard_unit_price",
                        proposed_value=round(record.raw_price / parsed["total_quantity"], 2),
                        evidence_text=f"{record.raw_price}/{parsed['total_quantity']}{parsed['standard_unit']}",
                        confidence=0.82,
                        proposal_suffix="standard_unit_price",
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
