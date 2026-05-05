"""Review publish eligibility, quality gates, and DB item projection.

This module keeps the AI-admin review route thin: route handlers orchestrate HTTP
while this service owns publish state calculation and customer-visible quality gates.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from core.contracts.ai_pipeline import (
    CanonicalProductDraft,
    FieldProposal as FieldProposalContract,
    PipelineStatus,
    ProductOfferDraft,
    ProductVariantDraft,
    ProposalType,
    RawCrawlRecord,
    SaleOfferDraft,
)
from core.contracts.control_plane import ReviewDecision
from core.product_units import normalize_unit_metadata, quantity_to_standard_total
from storage.models import AIPublishRecord
from storage import (
    FieldProposalRepository,
    KeywordProposalRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
)
from services.keyword_catalog import KEYWORD_PROPOSAL_BLOCKING_STATUSES


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


def proposals_by_raw_record(
    proposals: list[FieldProposalContract],
) -> dict[str, list[FieldProposalContract]]:
    grouped: dict[str, list[FieldProposalContract]] = defaultdict(list)
    for proposal in proposals:
        raw_id = proposal.provenance.raw_record_id
        if raw_id:
            grouped[raw_id].append(proposal)
    return grouped


def build_publish_rows(session, batch_id: Optional[str] = None) -> list[dict[str, Any]]:
    raw_repo = RawCrawlBatchRepository(session)
    records = raw_repo.list_records(batch_id) if batch_id else raw_repo.list_all_records()
    proposals = FieldProposalRepository(session).list()
    keyword_proposals = KeywordProposalRepository(session).list()
    proposals_by_record = proposals_by_raw_record(proposals)
    audit = build_raw_ai_audit(records, proposals, batch_id=batch_id)
    issues_by_record: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in audit.get("issues", []):
        issues_by_record[issue["raw_record_id"]].append(issue)

    rows: list[dict[str, Any]] = []
    for record in records:
        linked = proposals_by_record.get(record.raw_record_id, [])
        publish_state = session.get(AIPublishRecord, record.raw_record_id)
        decisions = {
            proposal.proposal_id: ReviewDecisionRepository(session).list_for_proposal(
                proposal.proposal_id
            )
            for proposal in linked
        }
        blockers = publish_blockers(
            record,
            linked,
            issues_by_record[record.raw_record_id],
            decisions,
            keyword_proposals,
        )
        status = derive_publish_status(linked, blockers, publish_state)
        item = db_item_from_review(record, linked, decisions)
        rows.append(
            {
                "raw_record_id": record.raw_record_id,
                "batch_id": record.raw_payload.get("batch_id") or _batch_id_for_record(session, record.raw_record_id),
                "source_name": record.source_name,
                "raw_title": record.raw_title,
                "status": status,
                "eligible": not blockers and status in {PipelineStatus.APPROVED.value, PipelineStatus.PUBLISH_FAILED.value},
                "retryable": status == PipelineStatus.PUBLISH_FAILED.value and not blockers,
                "retractable": status == PipelineStatus.PUBLISHED.value,
                "blockers": blockers,
                "keyword_proposals": [
                    proposal
                    for proposal in keyword_proposals
                    if any(
                        triggering.get("raw_record_id") == record.raw_record_id
                        for triggering in proposal.get("triggering_records", [])
                    )
                ],
                "audit_issues": issues_by_record[record.raw_record_id],
                "proposal_ids": [proposal.proposal_id for proposal in linked],
                "human_decision_ids": [
                    decision.decision_id
                    for proposal_decisions in decisions.values()
                    for decision in proposal_decisions
                ],
                "db_ingestion_id": publish_state.db_ingestion_id if publish_state else None,
                "db_ingestion_result": publish_state.db_ingestion_result if publish_state else None,
                "publish_attempts": publish_state.publish_attempts if publish_state else 0,
                "requested_by": publish_state.requested_by if publish_state else None,
                "requested_at": publish_state.requested_at.isoformat() if publish_state and publish_state.requested_at else None,
                "published_at": publish_state.published_at.isoformat() if publish_state and publish_state.published_at else None,
                "last_error": publish_state.last_error if publish_state else None,
                "item": item,
            }
        )
    return rows


UNRESOLVED_PROPOSAL_STATUSES = {
    PipelineStatus.AI_PROPOSED.value,
    PipelineStatus.HUMAN_REVIEWING.value,
    PipelineStatus.PENDING_REVIEW.value,
    PipelineStatus.NEEDS_REWORK.value,
}
BLOCKING_KEYWORD_STATUSES = {
    *KEYWORD_PROPOSAL_BLOCKING_STATUSES,
}


def _status_counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for value in values:
        counts[value] += 1
    return dict(counts)


def _keyword_linked_to_raw_ids(proposal: dict[str, Any], raw_ids: set[str]) -> bool:
    return any(
        isinstance(record, dict) and record.get("raw_record_id") in raw_ids
        for record in proposal.get("triggering_records", [])
    )


def build_batch_publish_summary(
    session,
    rows: list[dict[str, Any]],
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    raw_ids = {row["raw_record_id"] for row in rows}
    field_proposals = [
        proposal
        for proposal in FieldProposalRepository(session).list()
        if proposal.provenance.raw_record_id in raw_ids
    ]
    keyword_proposals = [
        proposal
        for proposal in KeywordProposalRepository(session).list()
        if _keyword_linked_to_raw_ids(proposal, raw_ids)
    ]
    field_status_counts = _status_counts([proposal.status.value for proposal in field_proposals])
    keyword_status_counts = _status_counts([proposal.get("status") for proposal in keyword_proposals])
    row_status_counts = _status_counts([row["status"] for row in rows])
    unresolved_field = sum(
        count for status, count in field_status_counts.items() if status in UNRESOLVED_PROPOSAL_STATUSES
    )
    unresolved_keyword = sum(
        count for status, count in keyword_status_counts.items() if status in BLOCKING_KEYWORD_STATUSES
    )
    eligible_count = sum(1 for row in rows if row["eligible"])
    blocked_rows = [row for row in rows if not row["eligible"]]
    published_count = row_status_counts.get(PipelineStatus.PUBLISHED.value, 0)
    ai_record_count = len({
        proposal.provenance.raw_record_id
        for proposal in field_proposals
        if proposal.provenance.raw_record_id
    })
    data_quality_issue_count = sum(len(row.get("audit_issues") or []) for row in rows)
    raw_without_ai_count = max(len(rows) - ai_record_count, 0)

    blockers: list[dict[str, Any]] = []
    if raw_without_ai_count:
        blockers.append({
            "code": "raw_without_ai",
            "count": raw_without_ai_count,
            "severity": "error",
            "message": f"AI 제안이 없는 원본 {raw_without_ai_count}개가 남아 있습니다. 배치 완료로 보지 말고 AI 처리/재수집을 먼저 확인하세요.",
        })
    if unresolved_field:
        blockers.append({
            "code": "unresolved_field_proposals",
            "count": unresolved_field,
            "severity": "error",
            "message": f"사람이 승인/반려하지 않은 필드 제안 {unresolved_field}개가 남아 있습니다.",
        })
    if unresolved_keyword:
        blockers.append({
            "code": "unresolved_keyword_proposals",
            "count": unresolved_keyword,
            "severity": "error",
            "message": f"키워드 제안 {unresolved_keyword}개가 미해결 상태입니다. 노출 품질에 영향이 있어 먼저 승인/반려하세요.",
        })
    if data_quality_issue_count:
        blockers.append({
            "code": "data_quality_issues",
            "count": data_quality_issue_count,
            "severity": "error",
            "message": f"가격/카테고리/누락 등 품질 이슈 {data_quality_issue_count}건이 있습니다. 해당 원본을 보정하거나 보류 사유를 남기세요.",
        })
    if blocked_rows:
        reasons: dict[str, int] = defaultdict(int)
        for row in blocked_rows:
            for blocker in row.get("blockers") or ["blocked"]:
                reasons[blocker] += 1
        blockers.append({
            "code": "blocked_rows",
            "count": len(blocked_rows),
            "severity": "warn" if eligible_count else "error",
            "message": f"발행 불가 원본 {len(blocked_rows)}개가 남아 있습니다.",
            "reasons": dict(sorted(reasons.items())),
        })

    if published_count and (blocked_rows or unresolved_field or unresolved_keyword or data_quality_issue_count or raw_without_ai_count):
        batch_status = "published_with_holds"
        verdict = "일부만 발행됐고 보류/미해결 항목이 남아 있습니다. 배치 완료가 아닙니다."
    elif eligible_count and (blocked_rows or unresolved_field or unresolved_keyword or data_quality_issue_count or raw_without_ai_count):
        batch_status = "partial_only"
        verdict = "부분 발행만 가능합니다. 남은 보류/미해결 항목 때문에 배치 전체 발행은 안전하지 않습니다."
    elif rows and eligible_count == len(rows) and not blockers:
        batch_status = "ready"
        verdict = "모든 원본이 사람 승인·키워드 승인·품질 점검을 통과해 발행 준비가 됐습니다."
    else:
        batch_status = "not_ready"
        verdict = "아직 발행 준비가 아닙니다. AI 제안, 키워드, 품질 이슈를 먼저 해결하세요."

    return {
        "batch_id": batch_id or (rows[0]["batch_id"] if rows else None),
        "batch_status": batch_status,
        "quality_verdict": verdict,
        "raw_count": len(rows),
        "ai_record_count": ai_record_count,
        "raw_without_ai_count": raw_without_ai_count,
        "field_proposal_count": len(field_proposals),
        "keyword_proposal_count": len(keyword_proposals),
        "approved_count": row_status_counts.get(PipelineStatus.APPROVED.value, 0),
        "held_count": row_status_counts.get(PipelineStatus.HELD.value, 0) + row_status_counts.get(PipelineStatus.PENDING_REVIEW.value, 0),
        "rejected_count": field_status_counts.get(PipelineStatus.REJECTED.value, 0) + keyword_status_counts.get(PipelineStatus.REJECTED.value, 0),
        "published_count": published_count,
        "eligible_count": eligible_count,
        "blocked_count": len(blocked_rows),
        "unresolved_field_proposal_count": unresolved_field,
        "unresolved_keyword_proposal_count": unresolved_keyword,
        "data_quality_issue_count": data_quality_issue_count,
        "field_status_counts": field_status_counts,
        "keyword_status_counts": keyword_status_counts,
        "row_status_counts": row_status_counts,
        "blockers": blockers,
        "held_rows": [
            {
                "raw_record_id": row["raw_record_id"],
                "raw_title": row.get("raw_title"),
                "status": row.get("status"),
                "blockers": row.get("blockers", []),
                "audit_issue_count": len(row.get("audit_issues") or []),
                "keyword_proposal_count": len(row.get("keyword_proposals") or []),
            }
            for row in blocked_rows
        ],
    }


def _batch_id_for_record(session, raw_record_id: str) -> str:
    from storage.models import RawCrawlRecord as RawCrawlRecordModel

    row = session.get(RawCrawlRecordModel, raw_record_id)
    return row.batch_id if row else "unknown"


def publish_blockers(
    record: RawCrawlRecord,
    proposals: list[FieldProposalContract],
    audit_issues: list[dict[str, Any]],
    decisions_by_proposal: dict[str, list[Any]],
    keyword_proposals: list[dict[str, Any]],
) -> list[str]:
    blockers: list[str] = []
    if not proposals:
        blockers.append("pending_review: no AI proposals linked to raw record")
    if audit_issues:
        blockers.append("data_quality: resolve audit issues before publishing")
    pending_statuses = {
        PipelineStatus.AI_PROPOSED,
        PipelineStatus.HUMAN_REVIEWING,
        PipelineStatus.NEEDS_REWORK,
        PipelineStatus.PENDING_REVIEW,
    }
    if any(proposal.proposal_type == ProposalType.KEYWORD and proposal.status in pending_statuses for proposal in proposals):
        blockers.append("keyword: pending keyword proposal requires approval or rejection")
    linked_keyword_proposals = [
        proposal
        for proposal in keyword_proposals
        if any(
            triggering.get("raw_record_id") == record.raw_record_id
            for triggering in proposal.get("triggering_records", [])
        )
    ]
    if any(
        proposal.get("status") in {PipelineStatus.AI_PROPOSED.value, PipelineStatus.HUMAN_REVIEWING.value}
        for proposal in linked_keyword_proposals
    ):
        blockers.append("keyword: pending DB keyword proposal blocks publishing")
    if any(proposal.get("status") == PipelineStatus.REJECTED.value for proposal in linked_keyword_proposals):
        blockers.append("keyword: rejected DB keyword proposal requires edit before publishing")
    if any(proposal.status in pending_statuses for proposal in proposals):
        blockers.append("pending_review: all AI proposals must be human approved")
    if any(proposal.status == PipelineStatus.REJECTED for proposal in proposals):
        blockers.append("held: rejected proposal requires rework before publishing")
    if proposals and not any(proposal.status in {PipelineStatus.APPROVED, PipelineStatus.PUBLISHED} for proposal in proposals):
        blockers.append("approved: at least one human-approved proposal is required")
    item = db_item_from_review(record, proposals, decisions_by_proposal)
    for field in ("name", "sale_price", "source"):
        if item.get(field) in (None, ""):
            blockers.append(f"data_quality: missing DB ingestion field {field}")
    for field in ("image_url", "original_price", "discount_percent", "source_url"):
        if item.get(field) in (None, ""):
            blockers.append(f"data_quality: missing customer-visible offer field {field}")
    return blockers


def derive_publish_status(
    proposals: list[FieldProposalContract],
    blockers: list[str],
    publish_state: Optional[AIPublishRecord],
) -> str:
    if publish_state and publish_state.status in {
        PipelineStatus.PUBLISHING.value,
        PipelineStatus.PUBLISHED.value,
        PipelineStatus.PUBLISH_FAILED.value,
        PipelineStatus.ROLLED_BACK.value,
    }:
        return publish_state.status
    if any(blocker.startswith("held:") for blocker in blockers):
        return PipelineStatus.HELD.value
    if blockers:
        return PipelineStatus.PENDING_REVIEW.value
    return PipelineStatus.APPROVED.value


def db_item_from_review(
    record: RawCrawlRecord,
    proposals: list[FieldProposalContract],
    decisions_by_proposal: dict[str, list[Any]],
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    attributes: dict[str, Any] = {}
    for proposal in proposals:
        if proposal.status not in {PipelineStatus.APPROVED, PipelineStatus.PUBLISHED}:
            continue
        value = _human_reviewed_value(proposal, decisions_by_proposal.get(proposal.proposal_id, []))
        target = proposal.target_field
        if target.startswith("attributes."):
            attributes[target.split(".", 1)[1]] = value
        elif target == "keywords":
            fields[target] = value if isinstance(value, list) else [value]
        else:
            fields[target] = value

    raw_payload = record.raw_payload or {}
    for raw_key, attr_key in (
        ("storage_type", "storage_type"),
        ("storage", "storage_type"),
        ("storage_method", "storage_type"),
        ("temperature_zone", "storage_type"),
        ("quality_grade", "quality_grade"),
        ("origin", "origin"),
    ):
        if attr_key not in attributes and raw_payload.get(raw_key) not in (None, ""):
            attributes[attr_key] = raw_payload[raw_key]
    name = (
        fields.get("name")
        or fields.get("canonical_name")
        or fields.get("product_name")
        or _first_present(raw_payload, "name", "product_name", "title")
        or record.raw_title
    )
    price = _first_number(
        fields.get("sale_price"),
        fields.get("current_price"),
        fields.get("price"),
        fields.get("offer_price"),
        fields.get("raw_price"),
        raw_payload.get("sale_price"),
        raw_payload.get("current_price"),
        raw_payload.get("price"),
        record.raw_price,
    )
    original_price = _first_number(
        fields.get("original_price"),
        raw_payload.get("original_price"),
        raw_payload.get("list_price"),
        raw_payload.get("regular_price"),
    )
    discount_percent = _first_number(
        fields.get("discount_percent"),
        fields.get("discount_rate"),
        raw_payload.get("discount_percent"),
        raw_payload.get("discount_rate"),
        raw_payload.get("discount"),
    )
    source_url = (
        fields.get("source_url")
        or fields.get("detail_url")
        or record.source_url
        or _first_present(raw_payload, "source_url", "detail_url", "url")
    )
    source = fields.get("source") or _first_present(raw_payload, "source", "store", "mall") or record.source_name
    category_id = fields.get("category_id") or raw_payload.get("category_id")
    category = category_id or fields.get("category") or raw_payload.get("category") or raw_payload.get("category_hint")
    unit_metadata = normalize_unit_metadata(
        name=record.raw_title,
        sale_price=price,
        raw_unit=_first_present(raw_payload, "unit", "raw_unit", "sellUnitCapacity"),
    )
    attributes = {**(unit_metadata.get("attributes") or {}), **attributes}
    display_unit = (
        fields.get("display_unit")
        or raw_payload.get("display_unit")
        or unit_metadata.get("display_unit")
    )
    package_quantity = _first_number(
        fields.get("package_quantity"),
        raw_payload.get("package_quantity"),
        unit_metadata.get("package_quantity"),
    )
    package_unit = (
        fields.get("package_unit")
        or raw_payload.get("package_unit")
        or unit_metadata.get("package_unit")
    )
    if isinstance(package_unit, str) and package_unit not in {"g", "kg", "ml", "L"}:
        package_unit = unit_metadata.get("package_unit") or package_unit
    price_per_100g = _first_number(
        fields.get("price_per_100g"),
        raw_payload.get("price_per_100g"),
        unit_metadata.get("price_per_100g"),
    )
    standard_unit_price = _first_number(
        fields.get("standard_unit_price"),
        raw_payload.get("standard_unit_price"),
    )
    standard_unit = fields.get("standard_unit") or raw_payload.get("standard_unit")
    bundle_count = int(_first_number(fields.get("bundle_count"), raw_payload.get("bundle_count"), 1) or 1)
    if standard_unit_price is None and price is not None and package_quantity and package_unit:
        standard_total = quantity_to_standard_total(package_quantity, str(package_unit), bundle_count)
        if standard_total is not None:
            total_quantity, inferred_standard_unit = standard_total
            standard_unit = standard_unit or inferred_standard_unit
            if total_quantity:
                standard_unit_price = round(float(price) / total_quantity, 2)
    raw_unit = _first_present(raw_payload, "unit", "raw_unit", "sellUnitCapacity")
    reviewed = ProductOfferDraft(
        product=CanonicalProductDraft(
            canonical_name=str(name),
            brand=fields.get("brand") or raw_payload.get("brand"),
            category_id=category_id,
            aliases=fields.get("aliases", []),
            keywords=fields.get("keywords", []),
            attributes=attributes,
        ),
        variant=ProductVariantDraft(
            variant_name=str(fields.get("variant_name") or record.raw_title),
            package_quantity=package_quantity,
            package_unit=package_unit,
            display_unit=display_unit,
            bundle_count=bundle_count,
            standard_unit=standard_unit,
            attributes=attributes,
        ),
        offer=SaleOfferDraft(
            source_name=str(source),
            source_record_key=record.source_record_key,
            source_title=str(fields.get("source_title") or record.raw_title),
            source_url=source_url,
            image_url=fields.get("image_url") or raw_payload.get("image_url") or raw_payload.get("image"),
            price=int(price or 0),
            original_price=int(original_price) if original_price is not None else None,
            discount_rate=_discount_rate_fraction(discount_percent),
            event_name=fields.get("event_name") or raw_payload.get("event_name") or raw_payload.get("event"),
            standard_unit_price=standard_unit_price,
            price_per_100g=price_per_100g,
            valid_from=fields.get("valid_from") or raw_payload.get("valid_from") or raw_payload.get("start_date"),
            valid_to=fields.get("valid_to") or raw_payload.get("valid_to") or raw_payload.get("end_date"),
            raw_record_id=record.raw_record_id,
            raw_evidence={
                "raw_title": record.raw_title,
                "raw_price": record.raw_price,
                "raw_unit": raw_unit,
                "raw_payload": raw_payload,
            },
            audit_provenance={
                "raw_record_id": record.raw_record_id,
                "proposal_ids": [proposal.proposal_id for proposal in proposals],
                "approved_fields": fields,
            },
        ),
        raw_record=record,
        audit_provenance={
            "raw_record_id": record.raw_record_id,
            "proposal_ids": [proposal.proposal_id for proposal in proposals],
        },
    )
    item = reviewed.to_db_admin_discount_item()
    item["store"] = _first_present(raw_payload, "store", "mall") or source
    item["raw_unit"] = raw_unit
    item["category"] = category
    item["raw_data"]["display_unit"] = display_unit
    item["raw_data"]["package_quantity"] = package_quantity
    item["raw_data"]["package_unit"] = package_unit
    if attributes:
        item["attributes"] = attributes
    return item


def _human_reviewed_value(proposal: FieldProposalContract, decisions: list[Any]) -> Any:
    for decision in sorted(decisions, key=lambda d: d.decided_at, reverse=True):
        if decision.decision == ReviewDecision.CORRECT:
            return decision.corrected_value
    return proposal.proposed_value


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        if isinstance(value, (int, float)) and value >= 0:
            return value
        if isinstance(value, str):
            try:
                number = float(value.replace(",", ""))
            except ValueError:
                continue
            if number >= 0:
                return number
    return None


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _discount_rate_fraction(value: Any) -> Optional[float]:
    number = _first_number(value)
    if number is None:
        return None
    return round(number / 100, 4) if number > 1 else round(number, 4)


def upsert_publish_record(
    session,
    candidate: dict[str, Any],
    *,
    status: str,
    requested_by: str,
    last_error: Optional[str] = None,
    db_ingestion_id: Optional[str] = None,
    db_result: Optional[dict[str, Any]] = None,
) -> None:
    now = datetime.now()
    row = session.get(AIPublishRecord, candidate["raw_record_id"])
    if row is None:
        row = AIPublishRecord(
            raw_record_id=candidate["raw_record_id"],
            batch_id=candidate["batch_id"],
            source_name=candidate["source_name"],
        )
        session.add(row)
    row.status = status
    row.ai_proposal_ids = list(candidate["proposal_ids"])
    row.human_decision_ids = list(candidate["human_decision_ids"])
    row.eligibility_errors = list(candidate["blockers"])
    row.last_error = last_error
    row.requested_by = requested_by
    row.requested_at = now
    row.updated_at = now
    if status == PipelineStatus.PUBLISHING.value:
        row.publish_attempts = (row.publish_attempts or 0) + 1
    if db_ingestion_id is not None:
        row.db_ingestion_id = db_ingestion_id
    if db_result is not None:
        row.db_ingestion_result = db_result
    if status == PipelineStatus.PUBLISHED.value:
        row.published_at = now
    session.flush()


def mark_proposals_published(session, proposal_ids: list[str]) -> None:
    repo = FieldProposalRepository(session)
    for proposal_id in proposal_ids:
        proposal = repo.get(proposal_id)
        if proposal and proposal.status == PipelineStatus.APPROVED:
            repo.save(proposal.model_copy(update={"status": PipelineStatus.PUBLISHED}))


def mark_proposals_unpublished(session, proposal_ids: list[str]) -> None:
    repo = FieldProposalRepository(session)
    for proposal_id in proposal_ids:
        proposal = repo.get(proposal_id)
        if proposal and proposal.status == PipelineStatus.PUBLISHED:
            repo.save(proposal.model_copy(update={"status": PipelineStatus.APPROVED}))


def mark_publish_record_rolled_back(
    session,
    raw_record_id: str,
    *,
    requested_by: str,
    reason: str,
) -> AIPublishRecord:
    row = session.get(AIPublishRecord, raw_record_id)
    if row is None:
        raise KeyError(raw_record_id)
    if row.status != PipelineStatus.PUBLISHED.value:
        raise ValueError(f"only published AI rows can be rolled back; current status is {row.status}")
    now = datetime.now()
    row.status = PipelineStatus.ROLLED_BACK.value
    row.last_error = (
        "Rollback requested in AI-admin before public exposure. "
        "DB-admin has no hard retract API; reject or delete pending ingestion "
        f"{row.db_ingestion_id or '(unknown)'} in DB-admin before approving public DB changes. "
        f"Reason: {reason}"
    )
    row.db_ingestion_result = {
        **(row.db_ingestion_result or {}),
        "rollback_requested": True,
        "rollback_requested_by": requested_by,
        "rollback_requested_at": now.isoformat(),
        "rollback_reason": reason,
        "db_ingestion_id": row.db_ingestion_id,
        "operator_instructions": (
            "Do not treat this AI publish as public-safe. DB-admin final approval is separate; "
            "reject/remove the referenced pending ingestion before public exposure."
        ),
    }
    row.requested_by = requested_by
    row.requested_at = now
    row.updated_at = now
    mark_proposals_unpublished(session, list(row.ai_proposal_ids or []))
    session.flush()
    return row


def build_raw_ai_audit(
    records: list[RawCrawlRecord],
    proposals: list[FieldProposalContract],
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    active_proposals = [
        proposal for proposal in proposals if proposal.status in ACTIVE_PROPOSAL_STATUSES
    ]
    grouped = proposals_by_raw_record(active_proposals)
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
