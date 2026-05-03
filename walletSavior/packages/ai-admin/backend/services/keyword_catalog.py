"""DB-admin keyword catalog adapter and proposal normalization."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from core.contracts.ai_pipeline import PipelineStatus, RawCrawlRecord


PROMO_TERMS = {
    "행사",
    "특가",
    "마트특가",
    "핫딜",
    "세일",
    "할인",
    "추천",
}
MODIFIER_TERMS = {
    "국산",
    "국내산",
    "국산콩",
    "냉장",
    "냉동",
    "친환경",
    "유기농",
    "프리미엄",
    "대용량",
    "고기",
}
GENERIC_PACKAGE_TERMS = {
    "개",
    "개입",
    "입",
    "봉",
    "팩",
    "통",
    "박스",
    "세트",
    "키트",
    "묶음",
}
NOISY_STANDALONE_TERMS = {
    "불",
    "소",
}
PROTECTED_CANONICAL_TERMS = {
    "불고기",
    "소고기",
    "돼지고기",
    "한우",
    "새우",
    "양배추",
}
ENGLISH_CANONICAL_ALIASES = {
    "beef": "소고기",
    "cabbage": "양배추",
    "shrimp": "새우",
}


@dataclass(frozen=True)
class CatalogKeyword:
    id: int
    word: str
    synonyms: tuple[str, ...]
    category_id: Optional[str] = None

    @property
    def terms(self) -> tuple[str, ...]:
        return (self.word, *self.synonyms)


def normalize_keyword(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", str(value or "").strip().lower())


def canonical_candidate(value: str) -> str:
    candidate = str(value or "").strip()
    normalized = normalize_keyword(candidate)
    translated = ENGLISH_CANONICAL_ALIASES.get(normalized)
    if translated:
        return translated
    if normalized in {normalize_keyword(term) for term in PROTECTED_CANONICAL_TERMS}:
        return normalized
    if normalized in {
        *PROMO_TERMS,
        *{normalize_keyword(term) for term in MODIFIER_TERMS},
        *{normalize_keyword(term) for term in GENERIC_PACKAGE_TERMS},
        *NOISY_STANDALONE_TERMS,
    }:
        return ""
    for modifier in sorted(MODIFIER_TERMS | PROMO_TERMS, key=len, reverse=True):
        mod_norm = normalize_keyword(modifier)
        if normalized.startswith(mod_norm) and len(normalized) > len(mod_norm):
            normalized = normalized[len(mod_norm):]
        if normalized.endswith(mod_norm) and len(normalized) > len(mod_norm):
            normalized = normalized[:-len(mod_norm)]
    if normalized in {
        *PROMO_TERMS,
        *{normalize_keyword(term) for term in GENERIC_PACKAGE_TERMS},
        *NOISY_STANDALONE_TERMS,
    }:
        return ""
    return normalized or candidate


class KeywordCatalogAdapter:
    """Small DB-admin boundary adapter using the public keywords table only."""

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.DB_ADMIN_DATABASE_URL
        connect_args = {"check_same_thread": False} if self.database_url.startswith("sqlite") else {}
        self.engine = create_engine(self.database_url, connect_args=connect_args)

    def list_keywords(self) -> list[CatalogKeyword]:
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, word, synonyms, category_id "
                        "FROM keywords WHERE COALESCE(is_active, 1) = 1"
                    )
                ).mappings().all()
        except SQLAlchemyError:
            return []
        keywords: list[CatalogKeyword] = []
        for row in rows:
            synonyms = row["synonyms"] or []
            if isinstance(synonyms, str):
                import json

                try:
                    synonyms = json.loads(synonyms)
                except json.JSONDecodeError:
                    synonyms = []
            keywords.append(
                CatalogKeyword(
                    id=int(row["id"]),
                    word=str(row["word"]),
                    synonyms=tuple(str(s) for s in synonyms if isinstance(s, str)),
                    category_id=row["category_id"],
                )
            )
        return keywords

    def upsert_keyword(
        self,
        *,
        word: str,
        match_terms: Iterable[str],
        category_id: str | None,
    ) -> dict[str, Any]:
        clean_word = str(word or "").strip()
        terms = _clean_match_terms(match_terms, clean_word)
        with self.engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id, synonyms, category_id FROM keywords WHERE word = :word"),
                {"word": clean_word},
            ).mappings().first()
            if existing:
                merged = _merge_synonyms(existing["synonyms"], terms)
                conn.execute(
                    text(
                        "UPDATE keywords SET synonyms = :synonyms, category_id = COALESCE(:category_id, category_id) "
                        "WHERE id = :id"
                    ),
                    {
                        "id": existing["id"],
                        "synonyms": _json_dumps(merged),
                        "category_id": category_id,
                    },
                )
                return {"id": existing["id"], "word": clean_word, "synonyms": merged, "merged": True}
            result = conn.execute(
                text(
                    "INSERT INTO keywords (word, synonyms, category_id, search_count, is_active) "
                    "VALUES (:word, :synonyms, :category_id, 0, 1)"
                ),
                {
                    "word": clean_word,
                    "synonyms": _json_dumps(terms),
                    "category_id": category_id,
                },
            )
            return {
                "id": int(result.lastrowid) if result.lastrowid is not None else None,
                "word": clean_word,
                "synonyms": terms,
                "merged": False,
            }

    def link_keyword_to_products(
        self,
        *,
        keyword_id: int | None,
        triggering_records: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        if keyword_id is None:
            return {"linked_product_ids": []}
        product_ids = _extract_product_ids(triggering_records)
        linked: list[int] = []
        try:
            with self.engine.begin() as conn:
                for product_id in product_ids:
                    product = conn.execute(
                        text("SELECT id FROM products WHERE id = :product_id"),
                        {"product_id": product_id},
                    ).first()
                    if product is None:
                        continue
                    existing = conn.execute(
                        text(
                            "SELECT id FROM product_keywords "
                            "WHERE product_id = :product_id AND keyword_id = :keyword_id"
                        ),
                        {"product_id": product_id, "keyword_id": keyword_id},
                    ).first()
                    if existing is not None:
                        linked.append(product_id)
                        continue
                    conn.execute(
                        text(
                            "INSERT INTO product_keywords (product_id, keyword_id) "
                            "VALUES (:product_id, :keyword_id)"
                        ),
                        {"product_id": product_id, "keyword_id": keyword_id},
                    )
                    linked.append(product_id)
        except SQLAlchemyError:
            return {"linked_product_ids": []}
        return {"linked_product_ids": _dedupe_ints(linked)}


def match_existing_keyword(value: str, catalog: list[CatalogKeyword]) -> tuple[CatalogKeyword | None, list[CatalogKeyword]]:
    candidate_norm = normalize_keyword(value)
    stripped_norm = canonical_candidate(value)
    if not candidate_norm:
        return None, []
    matches: list[tuple[int, CatalogKeyword]] = []
    for keyword in catalog:
        for term in keyword.terms:
            term_norm = normalize_keyword(term)
            if not term_norm:
                continue
            if candidate_norm == term_norm or stripped_norm == term_norm:
                matches.append((len(term_norm) + 100, keyword))
                break
            if len(term_norm) >= 2 and (term_norm in candidate_norm or candidate_norm in term_norm):
                matches.append((len(term_norm), keyword))
                break
    unique = {match.id: (score, match) for score, match in matches}
    ranked = sorted(unique.values(), key=lambda item: item[0], reverse=True)
    if not ranked:
        return None, []
    top_score = ranked[0][0]
    top = [keyword for score, keyword in ranked if score == top_score]
    return (top[0], top) if len(top) == 1 else (None, top)


def build_keyword_outputs(
    *,
    batch_id: str,
    records: list[RawCrawlRecord],
    response_items: list[dict[str, Any]],
    catalog: list[CatalogKeyword],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Return per-record matched keywords and durable new-keyword proposals."""
    records_by_id = {record.raw_record_id: record for record in records}
    matched_by_record: dict[str, list[dict[str, Any]]] = defaultdict(list)
    proposal_groups: dict[str, dict[str, Any]] = {}

    for item in response_items:
        raw_id = item.get("raw_record_id")
        record = records_by_id.get(raw_id)
        if not record:
            continue
        category_id = item.get("category_id")
        confidence = item.get("confidence") if isinstance(item.get("confidence"), (int, float)) else None
        values = _dedupe_terms([*(item.get("keywords") or []), *(item.get("aliases") or [])])
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            existing, ambiguous = match_existing_keyword(value, catalog)
            if existing is not None:
                _append_unique(
                    matched_by_record[raw_id],
                    {
                        "word": existing.word,
                        "keyword_id": existing.id,
                        "matched_term": value.strip(),
                        "category_id": existing.category_id,
                    },
                )
                continue
            canonical = canonical_candidate(value)
            if not canonical:
                continue
            key = canonical
            proposal = proposal_groups.setdefault(
                key,
                {
                    "proposal_id": _proposal_id(batch_id, canonical),
                    "proposed_keyword": canonical,
                    "match_terms": [],
                    "category_suggestion": category_id,
                    "confidence": confidence,
                    "reason": "AI keyword did not safely match an existing DB keyword",
                    "triggering_records": [],
                    "source_values": [],
                    "status": PipelineStatus.AI_PROPOSED.value,
                    "similar_existing": [
                        {"id": kw.id, "word": kw.word, "category_id": kw.category_id}
                        for kw in ambiguous
                    ],
                },
            )
            if confidence is not None:
                proposal["confidence"] = max(proposal.get("confidence") or 0, confidence)
            if value.strip() not in proposal["match_terms"]:
                proposal["match_terms"].append(value.strip())
            if value.strip() not in proposal["source_values"]:
                proposal["source_values"].append(value.strip())
            record_payload = record.model_dump(mode="json")
            if all(r.get("raw_record_id") != record.raw_record_id for r in proposal["triggering_records"]):
                proposal["triggering_records"].append(record_payload)

    return dict(matched_by_record), list(proposal_groups.values())


def record_keyword_gate(raw_record_id: str, proposals: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = [
        proposal
        for proposal in proposals
        if any(record.get("raw_record_id") == raw_record_id for record in proposal.get("triggering_records", []))
        and proposal.get("status") in {
            PipelineStatus.AI_PROPOSED.value,
            PipelineStatus.HUMAN_REVIEWING.value,
            PipelineStatus.REJECTED.value,
        }
    ]
    rejected = [p for p in blocking if p.get("status") == PipelineStatus.REJECTED.value]
    return {
        "raw_record_id": raw_record_id,
        "publishable": not blocking,
        "status": "needs_edit" if rejected else ("blocked_keyword_proposal" if blocking else "ready"),
        "blocking_keyword_proposals": blocking,
    }


def _proposal_id(batch_id: str, canonical: str) -> str:
    digest = hashlib.sha1(f"{batch_id}:{canonical}".encode("utf-8")).hexdigest()[:12]
    return f"{batch_id}:keyword_proposal:{digest}"


def _dedupe_terms(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        term = value.strip()
        key = normalize_keyword(term)
        if not term or key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def _append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    if not any(existing.get("keyword_id") == item.get("keyword_id") for existing in items):
        items.append(item)


def _merge_synonyms(existing: Any, terms: list[str]) -> list[str]:
    if isinstance(existing, str):
        import json

        try:
            existing = json.loads(existing)
        except json.JSONDecodeError:
            existing = []
    return _dedupe_terms([*(existing or []), *terms])


def _clean_match_terms(values: Iterable[Any], canonical_word: str) -> list[str]:
    canonical_norm = normalize_keyword(canonical_word)
    terms: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        term = value.strip()
        term_norm = normalize_keyword(term)
        if not term_norm or term_norm == canonical_norm:
            continue
        candidate = canonical_candidate(term)
        if not candidate:
            continue
        terms.append(term)
    return _dedupe_terms(terms)


def _extract_product_ids(records: Iterable[dict[str, Any]]) -> list[int]:
    product_ids: list[int] = []
    keys = ("product_id", "db_product_id", "db_admin_product_id", "product_pk")
    for record in records:
        if not isinstance(record, dict):
            continue
        payloads = [record, record.get("raw_payload") if isinstance(record.get("raw_payload"), dict) else {}]
        for payload in payloads:
            for key in keys:
                value = payload.get(key)
                if isinstance(value, int):
                    product_ids.append(value)
                elif isinstance(value, str) and value.isdigit():
                    product_ids.append(int(value))
    return _dedupe_ints(product_ids)


def _dedupe_ints(values: Iterable[int]) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
