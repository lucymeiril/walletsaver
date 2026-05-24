"""ClassifierWorker — 단순 한국어 키워드 매핑 기반 카테고리 제안.

실제 모델이 들어오기 전 단계에서 검수 큐 흐름을 실험할 수 있도록 결정론적
결과만 반환한다. 매칭이 없으면 categorical 제안을 만들지 않고 diagnostics에
unmatched 카운트로 남긴다.
"""
from __future__ import annotations

import re

from core.ai_workers import AIWorkerOutput, BaseAIWorker
from core.contracts.ai_pipeline import (
    AIJobBatch,
    AIWorkerRole,
    ProposalType,
)
from core.product_units import extract_product_attributes

from .base import clean_title, make_proposal, tokenize

# 결정론적 키워드->카테고리 매핑 (tree ID 기준 — category_tree.yaml).
# 새 카테고리 추가는 tree에 먼저 등록 후 이 목록에 추가할 것.
_CATEGORY_KEYWORDS: list[tuple[str, str, float]] = [
    ("꼬마김밥키트", "meal_kit", 0.93),
    ("김밥키트",     "meal_kit", 0.92),
    ("밀키트",       "meal_kit", 0.88),
    ("꼬마김밥",     "meal_kit", 0.88),
    ("김밥",         "meal_kit", 0.84),
    ("땅콩",         "nut", 0.82),
    ("초코우유",     "processed_food", 0.88),
    ("감자칩",       "confectionery", 0.85),
    ("초코",         "confectionery", 0.78),
    ("과자",         "confectionery", 0.75),
    ("우유",         "processed_food", 0.8),
    ("치즈",         "processed_food", 0.8),
    ("요거트",       "processed_food", 0.8),
    ("요구르트",     "processed_food", 0.75),
    ("계란",         "egg", 0.8),
    ("삼겹살",       "meat_egg", 0.9),
    ("목살",         "meat_egg", 0.85),
    ("돼지고기",     "meat_egg", 0.85),
    ("소고기",       "beef", 0.85),
    ("한우",         "beef", 0.9),
    ("닭고기",       "meat_egg", 0.85),
    ("닭가슴살",     "meat_egg", 0.88),
    ("고등어",       "fish", 0.85),
    ("갈치",         "fish", 0.85),
    ("오징어",       "fish", 0.78),
    ("새우",         "seafood", 0.8),
    ("사과",         "fruit", 0.85),
    ("바나나",       "fruit", 0.85),
    ("딸기",         "fruit", 0.85),
    ("망고",         "tropical_fruit", 0.85),
    ("토마토",       "fruit_vegetable", 0.8),
    ("양파",         "root_vegetable", 0.85),
    ("감자",         "potato", 0.85),
    ("상추",         "leaf_vegetable", 0.85),
    ("배추",         "leaf_vegetable", 0.85),
    ("쌀",           "rice", 0.85),
    ("라면",         "processed_food", 0.85),
    ("즉석밥",       "convenience_meal", 0.85),
    ("물",           "processed_food", 0.7),
    ("주스",         "processed_food", 0.8),
    ("콜라",         "processed_food", 0.8),
    ("커피",         "processed_food", 0.8),
    # 전자/가전
    ("갤럭시",       "mobile_phone", 0.82),
    ("아이폰",       "mobile_phone", 0.82),
    ("자급제",       "mobile_phone", 0.78),
    ("냉장고",       "home_appliance", 0.8),
    ("세탁기",       "home_appliance", 0.8),
    ("선풍기",       "home_appliance", 0.78),
    ("이어폰",       "electronics", 0.78),
    ("스피커",       "electronics", 0.78),
    # 패션
    ("티셔츠",       "fashion_apparel", 0.78),
    ("양말",         "socks", 0.78),
    ("팬츠",         "fashion_apparel", 0.75),
    ("가방",         "fashion_apparel", 0.78),
    ("캐리어",       "fashion_apparel", 0.78),
    ("선글라스",     "fashion_apparel", 0.78),
    # 뷰티
    ("세럼",         "skin_care", 0.78),
    ("샴푸",         "beauty_health", 0.78),
    # 생활용품
    ("세제",         "household", 0.78),
    ("수세미",       "household", 0.76),
    ("샤워기",       "household", 0.76),
    ("식탁",         "home_kitchen", 0.76),
    ("테이블웨어",   "home_kitchen", 0.76),
    ("버섯",         "vegetable", 0.78),
]

_ATTRIBUTE_HINTS: list[tuple[str, str, str, float]] = [
    ("냉동", "storage_type", "frozen", 0.8),
    ("냉장", "storage_type", "chilled", 0.8),
    ("무항생제", "quality_label", "antibiotic_free", 0.75),
    ("1등급", "quality_grade", "1", 0.78),
    ("한우", "origin_grade", "hanwoo", 0.85),
    ("불고기", "cut", "bulgogi", 0.78),
    ("새우살", "cut", "shrimp_meat", 0.78),
]

_TEXT_RE = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)
_MATCH_KIND_SCORE = {
    "phrase": 50,
    "exact_token": 40,
    "substring": 30,
    "compound_token": 20,
}


def _normalize_text(value: str) -> str:
    return _TEXT_RE.sub("", value.lower())


def _keyword_match_kind(keyword: str, title: str, category_id: str) -> str | None:
    keyword_norm = _normalize_text(keyword)
    if not keyword_norm:
        return None
    cleaned = clean_title(title)
    token_norms = [_normalize_text(token) for token in tokenize(cleaned)]
    if keyword_norm in token_norms:
        return "exact_token"
    title_norm = _normalize_text(cleaned)
    if " " in keyword and keyword_norm in title_norm:
        return "phrase"
    compound_allowed = not category_id.startswith(("seafood.", "produce."))
    if compound_allowed and len(keyword_norm) >= 2 and any(
        token.startswith(keyword_norm) or token.endswith(keyword_norm)
        for token in token_norms
    ):
        return "compound_token"
    if len(keyword_norm) >= 3 and keyword_norm in title_norm:
        return "substring"
    return None


def _best_category_match(title: str) -> tuple[str, str, float, str] | None:
    matches: list[tuple[int, float, int, str, str, str]] = []
    for keyword, category_id, confidence in _CATEGORY_KEYWORDS:
        match_kind = _keyword_match_kind(keyword, title, category_id)
        if match_kind is None:
            continue
        matches.append(
            (
                _MATCH_KIND_SCORE[match_kind],
                confidence,
                len(_normalize_text(keyword)),
                keyword,
                category_id,
                match_kind,
            )
        )
    if not matches:
        return None
    _score, confidence, _length, keyword, category_id, match_kind = max(matches)
    return keyword, category_id, confidence, match_kind


class ClassifierWorker(BaseAIWorker):
    role = AIWorkerRole.CLASSIFIER

    def process(self, batch: AIJobBatch) -> AIWorkerOutput:
        taxonomy = []
        attributes = []
        unmatched = 0
        for record in batch.records:
            title = record.raw_title
            match = _best_category_match(title)
            if match is not None:
                keyword, category_id, confidence, match_kind = match
                taxonomy.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.CATEGORY,
                        target_field="category_id",
                        proposed_value=category_id,
                        evidence_text=keyword,
                        confidence=confidence,
                        alternatives=[
                            {
                                "evidence_class": "deterministic_keyword",
                                "trust_label": "taxonomy_hint_needs_review",
                                "match_kind": match_kind,
                            }
                        ],
                        source_field="raw_title",
                    )
                )
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
            parsed_attributes = extract_product_attributes(title)
            for field, value in parsed_attributes.items():
                if field.endswith("_label"):
                    continue
                target_field = f"attributes.{field}"
                if any(p.provenance.raw_record_id == record.raw_record_id and p.target_field == target_field for p in attributes):
                    continue
                attributes.append(
                    make_proposal(
                        batch=batch,
                        record=record,
                        proposal_type=ProposalType.ATTRIBUTE_VALUE,
                        target_field=target_field,
                        proposed_value=value,
                        evidence_text=title,
                        confidence=0.82,
                        proposal_suffix=f"attr:{field}",
                        source_field="raw_title",
                    )
                )
            if match is None:
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
