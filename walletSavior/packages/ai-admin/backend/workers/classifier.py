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
    ("오징어 땅콩", "snack.nut", 0.9),
    ("초코우유", "dairy.milk.chocolate", 0.88),
    ("새우깡", "snack.chip", 0.9),
    ("감자칩", "snack.chip", 0.85),
    ("초코", "snack.chocolate", 0.78),
    ("과자", "snack.general", 0.75),
    ("우유", "dairy.milk", 0.8),
    ("치즈", "dairy.cheese", 0.8),
    ("요구르트", "dairy.yogurt", 0.75),
    ("계란", "dairy.egg", 0.8),
    ("삼겹살", "meat.pork.belly", 0.9),
    ("목살", "meat.pork", 0.85),
    ("돼지고기", "meat.pork", 0.85),
    ("소고기", "meat.beef", 0.85),
    ("한우", "meat.beef.hanwoo", 0.9),
    ("닭고기", "meat.chicken", 0.85),
    ("닭가슴살", "meat.chicken.breast", 0.88),
    ("고등어", "seafood.fish", 0.85),
    ("갈치", "seafood.fish", 0.85),
    ("오징어", "seafood.squid", 0.78),
    ("새우", "seafood.shrimp", 0.8),
    ("사과", "produce.fruit", 0.85),
    ("바나나", "produce.fruit", 0.85),
    ("딸기", "produce.fruit", 0.85),
    ("토마토", "produce.vegetable", 0.8),
    ("양파", "produce.vegetable", 0.85),
    ("감자", "produce.vegetable", 0.85),
    ("상추", "produce.vegetable", 0.85),
    ("배추", "produce.vegetable", 0.85),
    ("쌀", "grain.rice", 0.85),
    ("라면", "instant.noodle", 0.85),
    ("즉석밥", "instant.rice", 0.85),
    ("물", "beverage.water", 0.7),
    ("주스", "beverage.juice", 0.8),
    ("콜라", "beverage.soda", 0.8),
    ("커피", "beverage.coffee", 0.8),
]

_ATTRIBUTE_HINTS: list[tuple[str, str, str, float]] = [
    ("냉동", "storage_type", "frozen", 0.8),
    ("냉장", "storage_type", "chilled", 0.8),
    ("국산", "origin", "domestic", 0.75),
    ("수입", "origin", "imported", 0.75),
    ("무항생제", "quality_label", "antibiotic_free", 0.75),
    ("1등급", "quality_grade", "1", 0.78),
    ("한우", "origin_grade", "hanwoo", 0.85),
]


class ClassifierWorker(BaseAIWorker):
    role = AIWorkerRole.CLASSIFIER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        taxonomy = []
        attributes = []
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
            for keyword, field, value, confidence in _ATTRIBUTE_HINTS:
                if keyword in title:
                    attributes.append(
                        make_proposal(
                            batch=batch,
                            record=record,
                            proposal_type=ProposalType.ATTRIBUTE_VALUE,
                            target_field=f"attributes.{field}",
                            proposed_value=value,
                            evidence_text=keyword,
                            confidence=confidence,
                            proposal_suffix=f"attr:{field}",
                            source_field="raw_title",
                        )
                    )
            if not matched:
                unmatched += 1
        return AIWorkerOutput(
            job_id=batch.batch_id,
            role=self.role,
            taxonomy_proposals=taxonomy + attributes,
            diagnostics={
                "records_total": len(batch.records),
                "records_matched": len(taxonomy),
                "attribute_values_matched": len(attributes),
                "records_unmatched": unmatched,
                "needs_human_review": unmatched > 0,
            },
        )
