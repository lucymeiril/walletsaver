"""KeywordGeneratorWorker — 토큰에서 검색 키워드 후보를 추출 (중복 제거)."""
from __future__ import annotations

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)

from .base import clean_title, make_proposal, tokenize
from services.keyword_catalog import canonical_candidate

_MIN_TOKEN_LEN = 2
# 너무 흔하거나 의미 없는 토큰: 검색 키워드로 부적합.
_STOPWORDS = {
    "행사",
    "특가",
    "할인",
    "증정",
    "정상가",
    "무료배송",
    "팩",
    "개입",
    "개",
    "통",
    "키트",
    "불",
    "소",
    "냉장",
    "냉동",
    "국산",
    "국내산",
    "베트남",
    "불고기",
    "등급",
    "햄",
}


class KeywordGeneratorWorker(BaseAIWorker):
    role = AIWorkerRole.KEYWORD_GENERATOR

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        proposals = []
        aliases = []
        total_unique = 0
        for record in batch.records:
            title = clean_title(record.raw_title)
            tokens = tokenize(title)
            seen: set[str] = set()
            ordered: list[str] = []
            for token in tokens:
                if len(token) < _MIN_TOKEN_LEN:
                    continue
                if token in _STOPWORDS:
                    continue
                if not canonical_candidate(token):
                    continue
                if token in seen:
                    continue
                seen.add(token)
                ordered.append(token)
            for token in ordered:
                proposals.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.KEYWORD,
                        target_field="keywords",
                        proposed_value=token,
                        evidence_text=title,
                        confidence=0.5,
                        proposal_suffix=f"kw:{token}",
                        source_field="raw_title",
                    )
                )
            compact = "".join(ordered)
            if compact and compact != title.replace(" ", ""):
                aliases.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.ALIAS,
                        target_field="aliases",
                        proposed_value=compact,
                        evidence_text=title,
                        confidence=0.45,
                        proposal_suffix="compact-alias",
                        source_field="raw_title",
                    )
                )
            total_unique += len(ordered)
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            keyword_proposals=proposals,
            alias_proposals=aliases,
            diagnostics={
                "records_total": len(batch.records),
                "keywords_total": total_unique,
                "aliases_total": len(aliases),
            },
        )
