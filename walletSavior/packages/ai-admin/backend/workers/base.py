"""Worker 구현 공용 헬퍼.

provider/prompt_pack 정보는 batch에서 그대로 옮기되, dry-run 단계에서는 외부
호출이 일어나지 않으므로 confidence/evidence_text를 결정론적으로 채운다.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    FieldProposal,
    FieldProvenance,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)


def build_provenance(
    record: RawCrawlRecord,
    batch: AIJobBatch,
    *,
    evidence_text: str,
    confidence: Optional[float] = None,
    source_field: Optional[str] = None,
) -> FieldProvenance:
    """worker_role/provider/prompt_pack을 batch에서 채운 표준 provenance."""
    return FieldProvenance(
        raw_record_id=record.raw_record_id,
        source_field=source_field,
        evidence_text=evidence_text or record.raw_title,
        worker_role=batch.role,
        provider=batch.provider,
        prompt_pack=batch.prompt_pack,
        confidence=confidence,
    )


def make_proposal(
    *,
    batch: AIJobBatch,
    record: RawCrawlRecord,
    proposal_type: ProposalType,
    target_field: str,
    proposed_value: Any,
    evidence_text: str,
    confidence: Optional[float] = None,
    alternatives: Optional[list[Any]] = None,
    proposal_suffix: str = "",
    source_field: Optional[str] = None,
) -> FieldProposal:
    """결정론적 ID로 FieldProposal을 생성한다."""
    suffix = f":{proposal_suffix}" if proposal_suffix else ""
    proposal_id = (
        f"{batch.batch_id}:{batch.role.value}:{record.raw_record_id}:"
        f"{target_field}{suffix}"
    )
    return FieldProposal(
        proposal_id=proposal_id,
        proposal_type=proposal_type,
        target_field=target_field,
        proposed_value=proposed_value,
        status=PipelineStatus.AI_PROPOSED,
        provenance=build_provenance(
            record,
            batch,
            evidence_text=evidence_text,
            confidence=confidence,
            source_field=source_field,
        ),
        alternatives=list(alternatives or []),
    )


_WHITESPACE_RE = re.compile(r"\s+")
# 광고/프로모션 토큰: 결정론적 정규화 시 raw_title에서 제거 대상.
_PROMO_TOKENS = (
    "[행사]",
    "[특가]",
    "[할인]",
    "[증정]",
    "[정상가]",
    "(특가)",
    "(행사)",
    "(증정)",
)


def clean_title(raw_title: str) -> str:
    """홍보성 토큰과 다중 공백을 제거한 정규화 후보 제목."""
    cleaned = raw_title
    for token in _PROMO_TOKENS:
        cleaned = cleaned.replace(token, " ")
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned or raw_title.strip()


_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")


def tokenize(text: str) -> list[str]:
    """단순한 알파벳/숫자/한글 토큰 분리."""
    return [t for t in _TOKEN_RE.findall(text) if t]
