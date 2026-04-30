"""ClassifierWorker — 단순 한국어 키워드 매핑 기반 카테고리 제안.

실제 모델이 들어오기 전 단계에서 검수 큐 흐름을 실험할 수 있도록 결정론적
결과만 반환한다. 매칭이 없으면 categorical 제안을 만들지 않고 diagnostics에
unmatched 카운트로 남긴다.
"""
from __future__ import annotations

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)

from .base import make_proposal

# 결정론적 키워드->카테고리 매핑. 새 카테고리 추가는 별도 학습 시스템에서.
_CATEGORY_KEYWORDS: list[tuple[str, str, float]] = [
    ("우유", "dairy.milk", 0.8),
    ("치즈", "dairy.cheese", 0.8),
    ("요구르트", "dairy.yogurt", 0.75),
    ("계란", "dairy.egg", 0.8),
    ("사과", "produce.fruit", 0.85),
    ("바나나", "produce.fruit", 0.85),
    ("양파", "produce.vegetable", 0.85),
    ("감자", "produce.vegetable", 0.85),
    ("쌀", "grain.rice", 0.85),
    ("라면", "instant.noodle", 0.85),
    ("물", "beverage.water", 0.7),
    ("주스", "beverage.juice", 0.8),
]


class ClassifierWorker(BaseAIWorker):
    role = AIWorkerRole.CLASSIFIER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        taxonomy = []
        unmatched = 0
        for record in batch.records:
            title = record.raw_title
            matched = False
            for keyword, category_id, confidence in _CATEGORY_KEYWORDS:
                if keyword in title:
                    taxonomy.append(
                        make_proposal(
                            batch=batch,
                            record=record,
                            proposal_type=ProposalType.CATEGORY,
                            target_field="category_id",
                            proposed_value=category_id,
                            evidence_text=keyword,
                            confidence=confidence,
                            source_field="raw_title",
                        )
                    )
                    matched = True
                    break
            if not matched:
                unmatched += 1
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            taxonomy_proposals=taxonomy,
            diagnostics={
                "records_total": len(batch.records),
                "records_matched": len(taxonomy),
                "records_unmatched": unmatched,
                "needs_human_review": unmatched > 0,
            },
        )
