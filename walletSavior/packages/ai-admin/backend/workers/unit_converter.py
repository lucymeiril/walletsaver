"""UnitConverterWorker — 200g/1kg/2L/3개 등 간단한 패턴을 추출한다."""
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
    r"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|mg|l|ml|개|팩|입|매)",
    re.IGNORECASE,
)

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
}


def _parse_units(text: str) -> Optional[dict]:
    match = _UNIT_PATTERN.search(text)
    if not match:
        return None
    qty = float(match.group("qty"))
    unit = match.group("unit").lower()
    return {
        "raw_match": match.group(0),
        "package_quantity": qty,
        "package_unit": unit,
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
            for field in ("package_quantity", "package_unit", "standard_unit"):
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
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            field_proposals=proposals,
            diagnostics={
                "records_total": len(batch.records),
                "records_unmatched": unmatched,
            },
        )
