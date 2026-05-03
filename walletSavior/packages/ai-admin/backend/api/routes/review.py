"""검수 큐 라우트.

shared `ReviewQueueService`에 상태 전이를 위임한다. AI 제안의 approve/correct/reject
결정은 이후 학습/감사의 근거가 되므로 모든 결정은 ReviewDecision으로 저장된다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import (
    FieldProposal as FieldProposalContract,
    PipelineStatus,
    ProposalType,
    RawCrawlRecord,
)
from core.review_queue import ReviewQueueService

from storage import (
    Database,
    FieldProposalRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
    ReviewQueueRepositoryAdapter,
    get_default_database,
)

router = APIRouter(prefix="/api/review", tags=["review"])


def get_db() -> Database:
    return get_default_database()


class ApproveRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    create_learning_rule: bool = True


class CorrectRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    corrected_value: Any
    reason: str = Field(min_length=1)
    create_learning_rule: bool = True


class RejectRequest(BaseModel):
    reviewer_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class UpdateProposalRequest(BaseModel):
    proposal_type: Optional[ProposalType] = None
    target_field: Optional[str] = Field(default=None, min_length=1)
    proposed_value: Any = None
    alternatives: Optional[list[Any]] = None


def _service(session) -> ReviewQueueService:
    return ReviewQueueService(ReviewQueueRepositoryAdapter(session))


ACTIVE_PROPOSAL_STATUSES = {
    PipelineStatus.AI_PROPOSED,
    PipelineStatus.HUMAN_REVIEWING,
    PipelineStatus.APPROVED,
    PipelineStatus.PUBLISHED,
}

PRICE_FIELDS = (
    "price",
    "sale_price",
    "offer_price",
    "source_price",
    "raw_price",
    "current_price",
)
STORAGE_FIELDS = (
    "attributes.storage_type",
    "attributes.storage",
    "attributes.storage_method",
    "attributes.temperature_zone",
    "storage_type",
    "storage",
    "storage_method",
    "temperature_zone",
)
FRESH_CATEGORY_PREFIXES = (
    "fresh",
    "meat",
    "seafood",
    "fish",
    "fruit",
    "vegetable",
    "produce",
)
FRESH_TITLE_TOKENS = {
    "냉장",
    "냉동",
    "신선",
    "생물",
    "삼겹살",
    "목살",
    "한우",
    "닭",
    "계란",
    "고등어",
    "갈치",
    "새우",
    "연어",
    "오징어",
    "사과",
    "바나나",
    "딸기",
    "상추",
    "양파",
}
SNACK_TITLE_TOKENS = {"과자", "스낵", "칩", "땅콩", "오징어땅콩", "꼬북칩", "포카칩", "새우깡"}
SEAFOOD_TITLE_TOKENS = {"오징어", "새우", "고등어", "갈치", "연어", "조개", "굴", "전복"}
SNACK_CATEGORY_PREFIXES = ("snack", "confectionery")
SEAFOOD_CATEGORY_PREFIXES = ("seafood", "fish", "marine")


def _proposal_payload(proposal: FieldProposalContract) -> dict[str, Any]:
    return proposal.model_dump(mode="json")


def _raw_payload(record: RawCrawlRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


@router.get("/proposals")
def list_proposals(
    proposal_type: Optional[ProposalType] = None,
    status: Optional[PipelineStatus] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        items = repo.list(status=status, proposal_type=proposal_type)
        return {"items": [_proposal_payload(p) for p in items]}


@router.get("/proposals/{proposal_id}")
def get_proposal(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        decisions = ReviewDecisionRepository(session).list_for_proposal(proposal_id)
        return {
            "proposal": proposal.model_dump(mode="json"),
            "decisions": [d.model_dump(mode="json") for d in decisions],
        }


@router.post("/proposals", status_code=201)
def submit_proposal(
    proposal: FieldProposalContract,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            _service(session).submit(proposal)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return proposal.model_dump(mode="json")


@router.put("/proposals/{proposal_id}")
def update_proposal(
    proposal_id: str,
    payload: UpdateProposalRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status not in {
            PipelineStatus.AI_PROPOSED,
            PipelineStatus.HUMAN_REVIEWING,
        }:
            raise HTTPException(
                status_code=400,
                detail="only proposed or reviewing proposals can be modified",
            )

        update: dict[str, Any] = {}
        if payload.proposal_type is not None:
            update["proposal_type"] = payload.proposal_type
        if payload.target_field is not None:
            update["target_field"] = payload.target_field
        if "proposed_value" in payload.model_fields_set:
            update["proposed_value"] = payload.proposed_value
        if payload.alternatives is not None:
            update["alternatives"] = payload.alternatives
        updated = proposal.model_copy(update=update)
        repo.save(updated)
        return _proposal_payload(updated)


@router.delete("/proposals/{proposal_id}")
def delete_proposal(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        repo = FieldProposalRepository(session)
        proposal = repo.get(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        if proposal.status not in {
            PipelineStatus.AI_PROPOSED,
            PipelineStatus.HUMAN_REVIEWING,
            PipelineStatus.REJECTED,
        }:
            raise HTTPException(
                status_code=400,
                detail="approved or published proposals cannot be deleted",
            )
        repo.delete(proposal_id)
        return {"deleted": True, "proposal_id": proposal_id}


@router.get("/raw-records")
def list_raw_records(
    batch_id: Optional[str] = None,
    include_proposals: bool = True,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        records = (
            raw_repo.list_records(batch_id)
            if batch_id
            else raw_repo.list_all_records()
        )
        items = [_raw_payload(record) for record in records]
        if include_proposals:
            proposals_by_record = _proposals_by_raw_record(
                FieldProposalRepository(session).list()
            )
            for item in items:
                item["proposals"] = [
                    _proposal_payload(proposal)
                    for proposal in proposals_by_record.get(item["raw_record_id"], [])
                ]
        return {"items": items}


@router.post("/proposals/{proposal_id}/start")
def start_review(
    proposal_id: str,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            updated = _service(session).start_review(proposal_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return updated.model_dump(mode="json")


@router.post("/proposals/{proposal_id}/approve")
def approve(
    proposal_id: str,
    payload: ApproveRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            decision = _service(session).approve(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                create_learning_rule=payload.create_learning_rule,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.model_dump(mode="json")


@router.get("/audit")
def audit_raw_vs_ai(
    batch_id: Optional[str] = None,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        raw_repo = RawCrawlBatchRepository(session)
        records = (
            raw_repo.list_records(batch_id)
            if batch_id
            else raw_repo.list_all_records()
        )
        proposals = FieldProposalRepository(session).list()
        return build_raw_ai_audit(records, proposals, batch_id=batch_id)


def _proposals_by_raw_record(
    proposals: list[FieldProposalContract],
) -> dict[str, list[FieldProposalContract]]:
    grouped: dict[str, list[FieldProposalContract]] = defaultdict(list)
    for proposal in proposals:
        raw_id = proposal.provenance.raw_record_id
        if raw_id:
            grouped[raw_id].append(proposal)
    return grouped


def build_raw_ai_audit(
    records: list[RawCrawlRecord],
    proposals: list[FieldProposalContract],
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    active_proposals = [
        proposal for proposal in proposals if proposal.status in ACTIVE_PROPOSAL_STATUSES
    ]
    grouped = _proposals_by_raw_record(active_proposals)
    issues: list[dict[str, Any]] = []
    covered_records = 0
    raw_record_ids = {record.raw_record_id for record in records}

    for raw_id, orphaned in sorted(grouped.items()):
        if raw_id not in raw_record_ids:
            issues.append(
                _unknown_record_issue(
                    raw_id,
                    "orphan_ai_proposals",
                    "AI proposals reference a raw record that is not in the audited crawl set",
                    proposal_count=len(orphaned),
                )
            )

    for record in records:
        record_proposals = grouped.get(record.raw_record_id, [])
        if record_proposals:
            covered_records += 1
        else:
            issues.append(_issue(record, "missing_all_proposals", "raw record has no active AI proposals"))
            continue

        by_field = _proposal_values_by_field(record_proposals)
        required = {
            "canonical_name": bool(by_field.get("canonical_name")),
            "category_id": bool(by_field.get("category_id")),
            "unit": any(by_field.get(field) for field in (
                "package_unit",
                "standard_unit",
                "unit",
                "package_quantity",
                "standard_unit_price",
            )),
            "keywords": bool(by_field.get("keywords")),
        }
        for signal, present in required.items():
            if not present:
                issues.append(_issue(record, f"missing_{signal}_signal", f"missing {signal} proposal"))

        issues.extend(_expected_mismatch_issues(record, by_field))
        issues.extend(_price_mismatch_issues(record, by_field))
        issues.extend(_raw_signal_mismatch_issues(record, by_field))
        issues.extend(_storage_attribute_issues(record, by_field))
        issues.extend(_weird_classification_issues(record, by_field))

    return {
        "batch_id": batch_id,
        "raw_record_count": len(records),
        "covered_record_count": covered_records,
        "missing_record_count": max(len(records) - covered_records, 0),
        "proposal_count": len(active_proposals),
        "issue_count": len(issues),
        "status": "ok" if not issues else "warning",
        "issues": issues,
    }


def _proposal_values_by_field(
    proposals: list[FieldProposalContract],
) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = defaultdict(list)
    for proposal in proposals:
        if proposal.proposed_value not in (None, ""):
            values[proposal.target_field].append(proposal.proposed_value)
    return values


def _unknown_record_issue(raw_record_id: str, code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "raw_record_id": raw_record_id,
        "source_name": None,
        "raw_title": None,
        "code": code,
        "message": message,
    }
    payload.update(extra)
    return payload


def _issue(record: RawCrawlRecord, code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "raw_record_id": record.raw_record_id,
        "source_name": record.source_name,
        "raw_title": record.raw_title,
        "code": code,
        "message": message,
    }
    payload.update(extra)
    return payload


def _expected_mismatch_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    expected = _expected_ai(record.raw_payload)
    issues: list[dict[str, Any]] = []
    comparisons = {
        "canonical_name": ("canonical_name",),
        "category_id": ("category_id",),
        "package_unit": ("package_unit", "standard_unit", "unit"),
    }
    for expected_key, proposal_fields in comparisons.items():
        if expected_key not in expected:
            continue
        actual = _values_for_fields(by_field, proposal_fields)
        if not _contains_equivalent(actual, expected[expected_key]):
            issues.append(
                _issue(
                    record,
                    f"mismatched_{expected_key}",
                    f"expected {expected_key} was not proposed",
                    expected=expected[expected_key],
                    actual=actual,
                )
            )

    expected_keywords = _as_list(expected.get("keywords"))
    if expected_keywords:
        actual_keywords = [str(value) for value in _values_for_fields(by_field, ("keywords",))]
        missing = [
            kw
            for kw in expected_keywords
            if not _contains_equivalent(actual_keywords, kw, allow_substring=True)
        ]
        if missing:
            issues.append(
                _issue(
                    record,
                    "mismatched_keywords",
                    "expected keywords were not proposed",
                    expected=expected_keywords,
                    actual=sorted(actual_keywords),
                    missing=missing,
                )
            )
    issues.extend(_expected_price_issues(record, by_field, expected))
    issues.extend(_expected_attribute_issues(record, by_field, expected))
    return issues


def _expected_ai(raw_payload: dict[str, Any]) -> dict[str, Any]:
    expected = raw_payload.get("expected_ai")
    if isinstance(expected, dict):
        return expected
    result: dict[str, Any] = {}
    for key in (
        "canonical_name",
        "category_id",
        "package_unit",
        "keywords",
        "price",
        "raw_price",
        "sale_price",
        "offer_price",
        "storage_type",
        "storage",
        "attributes",
    ):
        raw_key = f"expected_{key}"
        if raw_key in raw_payload:
            result[key] = raw_payload[raw_key]
    return result


def _expected_price_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    expected_price = _expected_price(expected)
    if expected_price is None:
        return issues
    if record.raw_price is None or not _numbers_equal(record.raw_price, expected_price):
        issues.append(
            _issue(
                record,
                "mismatched_raw_price",
                "raw crawl price does not match expected price",
                expected=expected_price,
                actual=record.raw_price,
            )
        )

    actual_prices = _numeric_values(_values_for_fields(by_field, PRICE_FIELDS))
    if actual_prices and not any(_numbers_equal(value, expected_price) for value in actual_prices):
        issues.append(
            _issue(
                record,
                "mismatched_price",
                "AI/staging price proposal does not match expected price",
                expected=expected_price,
                actual=actual_prices,
            )
        )
    return issues


def _expected_attribute_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
    expected: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_attributes = expected.get("attributes")
    if not isinstance(expected_attributes, dict):
        expected_attributes = {}
    storage_expected = (
        expected.get("storage_type")
        or expected.get("storage")
        or expected_attributes.get("storage_type")
        or expected_attributes.get("storage")
        or expected_attributes.get("temperature_zone")
    )
    if storage_expected in (None, ""):
        return []
    actual = _values_for_fields(by_field, STORAGE_FIELDS)
    if _contains_equivalent(actual, storage_expected, allow_substring=True):
        return []
    return [
        _issue(
            record,
            "mismatched_storage_attribute",
            "expected fresh/chilled/frozen storage attribute was not proposed",
            expected=storage_expected,
            actual=actual,
        )
    ]


def _price_mismatch_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    if record.raw_price is None:
        return []
    actual_prices = _numeric_values(_values_for_fields(by_field, PRICE_FIELDS))
    mismatched = [value for value in actual_prices if not _numbers_equal(value, record.raw_price)]
    if not mismatched:
        return []
    return [
        _issue(
            record,
            "price_mismatch_raw",
            "AI/staging price proposal does not match raw crawl price",
            expected=record.raw_price,
            actual=mismatched,
        )
    ]


def _raw_signal_mismatch_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    title_tokens = _tokens(record.raw_title)
    for value in by_field.get("canonical_name", []):
        if title_tokens and not title_tokens.intersection(_tokens(str(value))):
            issues.append(
                _issue(
                    record,
                    "name_signal_mismatch",
                    "canonical name does not share any signal with raw title",
                    proposed=value,
                )
            )
    keyword_values = [str(value) for value in _values_for_fields(by_field, ("keywords",))]
    if keyword_values and title_tokens:
        matching = [kw for kw in keyword_values if title_tokens.intersection(_tokens(kw))]
        if not matching:
            issues.append(
                _issue(
                    record,
                    "keyword_signal_mismatch",
                    "keywords do not share any signal with raw title",
                    proposed=keyword_values,
                )
            )
    return issues


def _storage_attribute_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    categories = [str(value) for value in _values_for_fields(by_field, ("category_id",))]
    expected_storage = _expected_storage_from_raw(record)
    needs_storage = bool(expected_storage) or _looks_like_fresh_food(record.raw_title, categories)
    if not needs_storage:
        return []
    actual = _values_for_fields(by_field, STORAGE_FIELDS)
    if actual and (
        expected_storage is None
        or _contains_equivalent(actual, expected_storage, allow_substring=True)
    ):
        return []
    return [
        _issue(
            record,
            "missing_storage_attribute",
            "fresh/chilled/frozen food is missing a usable storage attribute",
            expected=expected_storage,
            actual=actual,
        )
    ]


def _weird_classification_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    categories = [str(value) for value in _values_for_fields(by_field, ("category_id",))]
    if not categories:
        return issues
    title_norm = _normalize_text(record.raw_title)
    looks_snack = any(_normalize_text(token) in title_norm for token in SNACK_TITLE_TOKENS)
    looks_seafood = any(_normalize_text(token) in title_norm for token in SEAFOOD_TITLE_TOKENS)
    category_norms = [_normalize_text(category) for category in categories]
    is_snack_category = any(
        category.startswith(prefix) for category in category_norms for prefix in SNACK_CATEGORY_PREFIXES
    )
    is_seafood_category = any(
        category.startswith(prefix) for category in category_norms for prefix in SEAFOOD_CATEGORY_PREFIXES
    )
    if looks_snack and is_seafood_category:
        issues.append(
            _issue(
                record,
                "snack_seafood_confusion",
                "snack-like crawl item was classified as seafood/fish",
                proposed=categories,
            )
        )
    if looks_seafood and not looks_snack and is_snack_category:
        issues.append(
            _issue(
                record,
                "seafood_snack_confusion",
                "fresh seafood-like crawl item was classified as snack",
                proposed=categories,
            )
        )
    return issues


def _looks_like_fresh_food(raw_title: str, categories: list[str]) -> bool:
    title_norm = _normalize_text(raw_title)
    if any(_normalize_text(token) in title_norm for token in FRESH_TITLE_TOKENS):
        return True
    category_norms = [_normalize_text(category) for category in categories]
    return any(
        category.startswith(prefix)
        for category in category_norms
        for prefix in FRESH_CATEGORY_PREFIXES
    )


def _expected_storage_from_raw(record: RawCrawlRecord) -> Any:
    expected = _expected_ai(record.raw_payload)
    attributes = expected.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    return (
        expected.get("storage_type")
        or expected.get("storage")
        or attributes.get("storage_type")
        or attributes.get("storage")
        or attributes.get("temperature_zone")
    )


def _expected_price(expected: dict[str, Any]) -> Optional[float]:
    for key in ("price", "sale_price", "offer_price", "raw_price"):
        value = _coerce_number(expected.get(key))
        if value is not None:
            return value
    return None


def _values_for_fields(
    by_field: dict[str, list[Any]],
    fields: tuple[str, ...],
) -> list[Any]:
    values: list[Any] = []
    for field in fields:
        for value in by_field.get(field, []):
            values.extend(_flatten_value(value))
    return values


def _flatten_value(value: Any) -> list[Any]:
    if isinstance(value, list):
        flattened: list[Any] = []
        for item in value:
            flattened.extend(_flatten_value(item))
        return flattened
    if isinstance(value, dict):
        flattened = []
        for item in value.values():
            flattened.extend(_flatten_value(item))
        return flattened
    return [value]


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


def _contains_equivalent(
    actual_values: list[Any],
    expected: Any,
    *,
    allow_substring: bool = False,
) -> bool:
    expected_norm = _normalize_text(expected)
    for actual in actual_values:
        if _coerce_number(actual) is not None and _coerce_number(expected) is not None:
            if _numbers_equal(_coerce_number(actual), _coerce_number(expected)):
                return True
        actual_norm = _normalize_text(actual)
        if actual_norm == expected_norm:
            return True
        if allow_substring and expected_norm and (
            expected_norm in actual_norm or actual_norm in expected_norm
        ):
            return True
    return False


def _numeric_values(values: list[Any]) -> list[float]:
    result: list[float] = []
    for value in values:
        parsed = _coerce_number(value)
        if parsed is not None:
            result.append(parsed)
    return result


def _coerce_number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("원", "").replace("₩", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _numbers_equal(left: Any, right: Any) -> bool:
    left_number = _coerce_number(left)
    right_number = _coerce_number(right)
    if left_number is None or right_number is None:
        return False
    return abs(left_number - right_number) <= 0.01


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value).strip().lower())


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[0-9A-Za-z가-힣]+", value)
        if len(token) >= 2
    }


@router.post("/proposals/{proposal_id}/correct")
def correct(
    proposal_id: str,
    payload: CorrectRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            decision = _service(session).correct(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                corrected_value=payload.corrected_value,
                reason=payload.reason,
                create_learning_rule=payload.create_learning_rule,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.model_dump(mode="json")


@router.post("/proposals/{proposal_id}/reject")
def reject(
    proposal_id: str,
    payload: RejectRequest,
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    with db.session_scope() as session:
        try:
            decision = _service(session).reject(
                proposal_id,
                reviewer_id=payload.reviewer_id,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return decision.model_dump(mode="json")
