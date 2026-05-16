"""Review publish eligibility, quality gates, and DB item projection.

This module keeps the AI-admin review route thin: route handlers orchestrate HTTP
while this service owns publish state calculation and customer-visible quality gates.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
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
from core.contracts.control_plane import ReviewDecision, normalize_match_text, normalize_package_signature
from core.product_units import normalize_unit_metadata, quantity_to_standard_total
from core.promotion_semantics import PriceState
from storage.models import AIPublishRecord
from storage import (
    FieldProposalRepository,
    KeywordProposalRepository,
    RawCrawlBatchRepository,
    ReviewDecisionRepository,
)
from services.keyword_catalog import KEYWORD_PROPOSAL_BLOCKING_STATUSES
from services.seed_taxonomy import (
    SAFE_SEED_CATEGORY_IDS,
    get_category_display_label,
    is_safe_seed_category,
    normalize_category_id,
    taxonomy_alias_overfit_metrics,
)


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
FRUIT_TITLE_TOKENS = {"망고", "사과", "바나나", "딸기", "감귤", "귤", "포도", "복숭아", "수박", "멜론"}
SNACK_CATEGORY_PREFIXES = ("snack", "confectionery")
SEAFOOD_CATEGORY_PREFIXES = ("seafood", "fish", "marine")
FRUIT_CATEGORY_PREFIXES = ("produce.fruit", "fruit")
PREPARED_CATEGORY_PREFIXES = ("prepared_food", "deli", "meal_kit", "ready_meal")
PREPARED_TITLE_TOKENS = {"김밥", "꼬마김밥", "김밥키트", "밀키트", "키트", "도시락", "샌드위치"}
PACKAGED_HAM_TITLE_TOKENS = {"슬라이스햄", "프레스햄", "통햄", "햄스테이크", "런천미트", "스팸", "리챔"}
GENERIC_ALIAS_TERMS = {"키트", "세트", "팩"}
INGREDIENT_ONLY_KEYWORDS = {"햄"}
OFFICIAL_CATEGORY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
UNSAFE_CATEGORY_ID_SEPARATORS = ("/", "\\")
STRICT_AUDIT_BLOCKER_CODES = {
    "overbroad_canonical_name",
    "weak_prepared_food_category",
    "unsafe_ingredient_keyword",
    "unsafe_generic_alias",
    "price_mismatch_raw",
    "mismatched_raw_price",
    "mismatched_price",
    "inflated_confidence_after_validation_failure",
    "invalid_category_id_format",
    "unknown_taxonomy_category",
}
REVIEW_RELAXED_PROPOSAL_FIELDS = {
    "category",
    "category_hint",
    "category_id",
    "category_name",
    "keywords",
    "aliases",
}
DB_ITEM_USABLE_PROPOSAL_STATUSES = {
    PipelineStatus.APPROVED,
    PipelineStatus.PUBLISHED,
}
RELAXED_DB_ITEM_PROPOSAL_STATUSES = {
    *DB_ITEM_USABLE_PROPOSAL_STATUSES,
    PipelineStatus.AI_PROPOSED,
    PipelineStatus.HUMAN_REVIEWING,
}
HOTDEAL_CLAIM_BLOCKED_CODE = "hotdeal_claim_blocked"
HOTDEAL_CLAIM_BLOCKED_MESSAGE = (
    "hotdeal_claim_blocked: missing verified original_price/discount_percent/"
    "source_event/historical_baseline; publish as price_observation only"
)
SOURCE_OWNED_PROPOSAL_FIELDS = {
    "price",
    "sale_price",
    "current_price",
    "offer_price",
    "source_price",
    "raw_price",
    "original_price",
    "discount_percent",
    "discount_rate",
    "source_url",
    "detail_url",
    "link",
    "url",
    "image_url",
    "image",
    "event_name",
    "event",
    "source_event",
    "source_period",
    "period",
    "valid_from",
    "valid_to",
    "start_date",
    "end_date",
}


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
    raw_ids = {record.raw_record_id for record in records}
    proposals = _field_proposals_for_scope(
        FieldProposalRepository(session).list(),
        batch_id=batch_id,
        raw_ids=raw_ids,
    )
    keyword_proposals = _keyword_proposals_for_scope(
        KeywordProposalRepository(session).list(),
        batch_id=batch_id,
        raw_ids=raw_ids,
    )
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
        post_publish_audit_flags = build_post_publish_audit_flags(
            record,
            linked,
            issues_by_record[record.raw_record_id],
            keyword_proposals,
        )
        if post_publish_audit_flags:
            item["post_publish_audit_flags"] = post_publish_audit_flags
            item.setdefault("raw_data", {})["post_publish_audit_flags"] = post_publish_audit_flags
        publication_kind = item.get("publication_kind")
        discount_claim_status = item.get("discount_claim_status")
        display_blockers = [
            *blockers,
            *_publish_state_explanations(status, publish_state),
        ]
        row = {
                "raw_record_id": record.raw_record_id,
                "batch_id": record.raw_payload.get("batch_id") or _batch_id_for_record(session, record.raw_record_id),
                "source_name": record.source_name,
                "raw_title": record.raw_title,
                "status": status,
                "eligible": not blockers and status in {PipelineStatus.APPROVED.value, PipelineStatus.PUBLISH_FAILED.value},
                "publication_kind": publication_kind,
                "price_observation_only": item.get("price_observation_only"),
                "discount_claim_status": discount_claim_status,
                "claim_basis": item.get("claim_basis"),
                "claim_blockers": list(item.get("claim_blockers") or []),
                "post_publish_audit_flags": post_publish_audit_flags,
                "blocking_audit_issues": _blocking_audit_issues(issues_by_record[record.raw_record_id]),
                "retryable": status == PipelineStatus.PUBLISH_FAILED.value and not blockers,
                "retractable": status == PipelineStatus.PUBLISHED.value,
                "blockers": display_blockers,
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
        row["ai_safe_final_approve_eligible"] = is_ai_safe_final_approve_eligible(row)
        row["db_handoff_mode"] = (
            "ai_safe_final_approve"
            if row["ai_safe_final_approve_eligible"]
            else "db_admin_review"
        )
        rows.append(row)
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


def is_ai_safe_final_approve_eligible(row: dict[str, Any]) -> bool:
    """Only rows with no remaining audit/review caveats may ask DB-admin to final approve."""
    return bool(
        row.get("eligible")
        and row.get("status") in {
            PipelineStatus.APPROVED.value,
            PipelineStatus.PUBLISH_FAILED.value,
        }
        and not row.get("blocking_audit_issues")
        and not row.get("post_publish_audit_flags")
        and not row.get("claim_blockers")
    )


def _keyword_linked_to_raw_ids(proposal: dict[str, Any], raw_ids: set[str]) -> bool:
    return any(
        isinstance(record, dict) and record.get("raw_record_id") in raw_ids
        for record in proposal.get("triggering_records", [])
    )


def _generated_proposal_for_batch(proposal_id: str, batch_id: Optional[str]) -> bool:
    return bool(batch_id and proposal_id.startswith(f"{batch_id}:"))


def _generated_proposal_for_other_batch(proposal_id: str) -> bool:
    return ":ai:" in proposal_id


def _field_proposals_for_scope(
    proposals: list[FieldProposalContract],
    *,
    batch_id: Optional[str],
    raw_ids: set[str],
) -> list[FieldProposalContract]:
    scoped: list[FieldProposalContract] = []
    for proposal in proposals:
        if proposal.provenance.raw_record_id not in raw_ids:
            continue
        if batch_id and _generated_proposal_for_other_batch(proposal.proposal_id):
            if not _generated_proposal_for_batch(proposal.proposal_id, batch_id):
                continue
        scoped.append(proposal)
    return scoped


def _keyword_proposals_for_scope(
    proposals: list[dict[str, Any]],
    *,
    batch_id: Optional[str],
    raw_ids: set[str],
) -> list[dict[str, Any]]:
    scoped: list[dict[str, Any]] = []
    for proposal in proposals:
        if not _keyword_linked_to_raw_ids(proposal, raw_ids):
            continue
        proposal_id = str(proposal.get("proposal_id") or "")
        if batch_id and _generated_proposal_for_other_batch(proposal_id):
            if not _generated_proposal_for_batch(proposal_id, batch_id):
                continue
        scoped.append(proposal)
    return scoped


def build_batch_publish_summary(
    session,
    rows: list[dict[str, Any]],
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    raw_ids = {row["raw_record_id"] for row in rows}
    field_proposals = _field_proposals_for_scope(
        FieldProposalRepository(session).list(),
        batch_id=batch_id,
        raw_ids=raw_ids,
    )
    keyword_proposals = _keyword_proposals_for_scope(
        KeywordProposalRepository(session).list(),
        batch_id=batch_id,
        raw_ids=raw_ids,
    )
    field_status_counts = _status_counts([proposal.status.value for proposal in field_proposals])
    keyword_status_counts = _status_counts([proposal.get("status") for proposal in keyword_proposals])
    row_status_counts = _status_counts([row["status"] for row in rows])
    unresolved_field = sum(
        1
        for proposal in field_proposals
        if proposal.status.value in UNRESOLVED_PROPOSAL_STATUSES
        and proposal.target_field not in REVIEW_RELAXED_PROPOSAL_FIELDS
    )
    unresolved_relaxed_field = sum(
        1
        for proposal in field_proposals
        if proposal.status.value in UNRESOLVED_PROPOSAL_STATUSES
        and proposal.target_field in REVIEW_RELAXED_PROPOSAL_FIELDS
    )
    unresolved_keyword = sum(
        count for status, count in keyword_status_counts.items() if status in BLOCKING_KEYWORD_STATUSES
    )
    eligible_count = sum(1 for row in rows if row["eligible"])
    ai_safe_final_approve_count = sum(
        1 for row in rows if row.get("ai_safe_final_approve_eligible")
    )
    db_review_handoff_count = sum(
        1
        for row in rows
        if row.get("eligible") and not row.get("ai_safe_final_approve_eligible")
    )
    blocked_rows = [row for row in rows if not row["eligible"]]
    price_observation_ready_count = sum(
        1
        for row in rows
        if row["eligible"] and row.get("publication_kind") == "price_observation"
    )
    hotdeal_ready_count = sum(
        1
        for row in rows
        if row["eligible"] and row.get("publication_kind") == "hotdeal"
    )
    hotdeal_claim_blocked_count = sum(
        1
        for row in rows
        if row.get("discount_claim_status") == HOTDEAL_CLAIM_BLOCKED_CODE
    )
    published_count = row_status_counts.get(PipelineStatus.PUBLISHED.value, 0)
    pending_db_review_count = row_status_counts.get(PipelineStatus.PENDING_DB_REVIEW.value, 0)
    publish_failed_count = row_status_counts.get(PipelineStatus.PUBLISH_FAILED.value, 0)
    rolled_back_count = row_status_counts.get(PipelineStatus.ROLLED_BACK.value, 0)
    ai_record_count = len({
        proposal.provenance.raw_record_id
        for proposal in field_proposals
        if proposal.provenance.raw_record_id
    })
    data_quality_issue_count = sum(len(row.get("audit_issues") or []) for row in rows)
    blocking_data_quality_issue_count = sum(len(row.get("blocking_audit_issues") or []) for row in rows)
    post_publish_audit_count = sum(len(row.get("post_publish_audit_flags") or []) for row in rows)
    raw_without_ai_count = max(len(rows) - ai_record_count, 0)
    suspicious_count = sum(
        1
        for row in rows
        if row.get("audit_issues")
        or any(str(blocker).startswith("data_quality:") for blocker in row.get("blockers") or [])
    )
    auto_approved_proposals: set[str] = set()
    auto_approved_raw_ids: set[str] = set()
    decision_repo = ReviewDecisionRepository(session)
    for proposal in field_proposals:
        for decision in decision_repo.list_for_proposal(proposal.proposal_id):
            if _is_automation_approval(decision):
                auto_approved_proposals.add(proposal.proposal_id)
                if proposal.provenance.raw_record_id:
                    auto_approved_raw_ids.add(proposal.provenance.raw_record_id)
                break
    rollback_available_count = pending_db_review_count + published_count
    needs_re_review_count = publish_failed_count + rolled_back_count

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
            "severity": "info",
            "message": f"키워드 제안 {unresolved_keyword}개가 미해결 상태입니다. 발행 후 anomaly audit/키워드 보정 대상으로 추적하세요.",
        })
    if blocking_data_quality_issue_count:
        blockers.append({
            "code": "data_quality_issues",
            "count": blocking_data_quality_issue_count,
            "severity": "error",
            "message": f"가격/단위/핵심 품질 이슈 {blocking_data_quality_issue_count}건이 있습니다. 해당 원본을 보정하거나 보류 사유를 남기세요.",
        })
    if post_publish_audit_count:
        blockers.append({
            "code": "post_publish_audit_flags",
            "count": post_publish_audit_count,
            "severity": "info",
            "message": (
                f"택소노미/키워드 등 정보 품질 감사 플래그 {post_publish_audit_count}건은 "
                "DB-admin 큐 제출 후 anomaly audit/보정으로 확인하세요."
            ),
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
    if hotdeal_claim_blocked_count:
        blockers.append({
            "code": HOTDEAL_CLAIM_BLOCKED_CODE,
            "count": hotdeal_claim_blocked_count,
            "severity": "info",
            "message": (
                f"{hotdeal_claim_blocked_count}개는 price_observation_ready 상태이지만 "
                "검증된 핫딜/할인 claim 근거가 없어 hotdeal_claim_blocked로 표시됩니다."
            ),
        })

    if published_count and (blocked_rows or unresolved_field or blocking_data_quality_issue_count or raw_without_ai_count):
        batch_status = "published_with_holds"
        verdict = "일부만 DB-admin 검토로 제출됐고 보류/미해결 항목이 남아 있습니다. 배치 완료가 아닙니다."
    elif eligible_count and (blocked_rows or unresolved_field or blocking_data_quality_issue_count or raw_without_ai_count):
        batch_status = "partial_only"
        verdict = (
            f"부분 발행만 가능합니다. price_observation_ready={price_observation_ready_count}, "
            f"hotdeal_ready={hotdeal_ready_count}, hotdeal_claim_blocked={hotdeal_claim_blocked_count}. "
            "남은 보류/미해결 항목 때문에 배치 전체 발행은 안전하지 않습니다."
        )
    elif rows and eligible_count == len(rows) and not blockers:
        batch_status = "ready"
        verdict = (
            f"모든 원본이 사람 승인·키워드 승인·품질 점검을 통과했습니다. "
            f"price_observation_ready={price_observation_ready_count}, hotdeal_ready={hotdeal_ready_count}."
        )
    elif rows and eligible_count == len(rows):
        batch_status = "ready"
        verdict = (
            f"모든 원본이 발행 준비가 됐습니다. price_observation_ready={price_observation_ready_count}, "
            f"hotdeal_ready={hotdeal_ready_count}, hotdeal_claim_blocked={hotdeal_claim_blocked_count}. "
            "검증 근거 없는 할인 claim은 노출하지 마세요."
        )
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
        "pending_db_review_count": pending_db_review_count,
        "publish_failed_count": publish_failed_count,
        "rolled_back_count": rolled_back_count,
        "rollback_available_count": rollback_available_count,
        "needs_re_review_count": needs_re_review_count,
        "auto_approved_count": len(auto_approved_proposals),
        "auto_approved_raw_count": len(auto_approved_raw_ids),
        "suspicious_count": suspicious_count,
        "eligible_count": eligible_count,
        "ai_safe_final_approve_count": ai_safe_final_approve_count,
        "db_review_handoff_count": db_review_handoff_count,
        "price_observation_ready_count": price_observation_ready_count,
        "hotdeal_ready_count": hotdeal_ready_count,
        "hotdeal_claim_blocked_count": hotdeal_claim_blocked_count,
        "blocked_count": len(blocked_rows),
        "unresolved_field_proposal_count": unresolved_field,
        "unresolved_relaxed_field_proposal_count": unresolved_relaxed_field,
        "unresolved_keyword_proposal_count": unresolved_keyword,
        "data_quality_issue_count": data_quality_issue_count,
        "blocking_data_quality_issue_count": blocking_data_quality_issue_count,
        "taxonomy_alias_overfit_metrics": taxonomy_alias_overfit_metrics(),
        "post_publish_audit_count": post_publish_audit_count,
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
                "publication_kind": row.get("publication_kind"),
                "discount_claim_status": row.get("discount_claim_status"),
                "audit_issue_count": len(row.get("audit_issues") or []),
                "post_publish_audit_flags": row.get("post_publish_audit_flags", []),
                "keyword_proposal_count": len(row.get("keyword_proposals") or []),
            }
            for row in blocked_rows
        ],
        "approved_rows": [
            {
                "raw_record_id": row["raw_record_id"],
                "raw_title": row.get("raw_title"),
                "status": row.get("status"),
                "db_handoff_mode": row.get("db_handoff_mode"),
                "ai_safe_final_approve_eligible": row.get("ai_safe_final_approve_eligible"),
                "publication_kind": row.get("publication_kind"),
                "discount_claim_status": row.get("discount_claim_status"),
                "post_publish_audit_flags": row.get("post_publish_audit_flags", []),
            }
            for row in rows
            if row.get("eligible")
        ],
        "retained_row_anomaly_summary": build_retained_row_anomaly_summary(
            session,
            rows,
            batch_id=batch_id,
        ),
    }


def build_operator_dashboard_summary(
    session,
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    """Read-only operator summary that reuses publish rows and batch audit data."""
    rows = build_publish_rows(session, batch_id=batch_id)
    summary = build_batch_publish_summary(session, rows, batch_id=batch_id)
    stats_keys = (
        "batch_id",
        "batch_status",
        "quality_verdict",
        "raw_count",
        "ai_record_count",
        "raw_without_ai_count",
        "field_proposal_count",
        "keyword_proposal_count",
        "approved_count",
        "held_count",
        "rejected_count",
        "published_count",
        "pending_db_review_count",
        "publish_failed_count",
        "rolled_back_count",
        "rollback_available_count",
        "needs_re_review_count",
        "auto_approved_count",
        "auto_approved_raw_count",
        "suspicious_count",
        "eligible_count",
        "ai_safe_final_approve_count",
        "db_review_handoff_count",
        "price_observation_ready_count",
        "hotdeal_ready_count",
        "hotdeal_claim_blocked_count",
        "blocked_count",
        "unresolved_field_proposal_count",
        "unresolved_relaxed_field_proposal_count",
        "unresolved_keyword_proposal_count",
        "data_quality_issue_count",
        "blocking_data_quality_issue_count",
        "post_publish_audit_count",
        "field_status_counts",
        "keyword_status_counts",
        "row_status_counts",
    )
    publish_blockers = _operator_publish_blockers(rows)
    anomaly_summary = summary.get("retained_row_anomaly_summary") or {}
    categories = anomaly_summary.get("categories") or {}

    return {
        "batch_id": summary.get("batch_id"),
        "read_only": True,
        "stats": {key: summary.get(key) for key in stats_keys if key in summary},
        "blocker_buckets": summary.get("blockers", []),
        "publish_blockers": publish_blockers,
        "approved_rows": summary.get("approved_rows", []),
        "publish_blocker_counts_by_reason": _publish_blocker_counts_by_reason(publish_blockers),
        "anomaly_summary": {
            key: anomaly_summary.get(key)
            for key in (
                "style",
                "mode",
                "batch_id",
                "retained_row_count",
                "suspicious_row_count",
                "normal_row_count",
                "suspicious_raw_record_ids",
                "category_counts",
            )
            if key in anomaly_summary
        },
        "anomaly_buckets": [
            {
                "code": bucket.get("code", code),
                "count": bucket.get("count", 0),
                "message": bucket.get("message"),
                "rows": bucket.get("rows", []),
            }
            for code, bucket in sorted(categories.items())
        ],
    }


def _operator_publish_blockers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "raw_record_id": row["raw_record_id"],
            "raw_title": row.get("raw_title"),
            "status": row.get("status"),
            "eligible": row.get("eligible"),
            "blockers": row.get("blockers", []),
            "publication_kind": row.get("publication_kind"),
            "discount_claim_status": row.get("discount_claim_status"),
            "audit_issue_count": len(row.get("audit_issues") or []),
            "blocking_audit_issue_count": len(row.get("blocking_audit_issues") or []),
            "post_publish_audit_flags": row.get("post_publish_audit_flags", []),
            "keyword_proposal_count": len(row.get("keyword_proposals") or []),
            "db_handoff_mode": row.get("db_handoff_mode"),
        }
        for row in rows
        if not row.get("eligible")
    ]


def _publish_blocker_counts_by_reason(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        for blocker in row.get("blockers") or ["blocked"]:
            counts[str(blocker)] += 1
    return dict(sorted(counts.items()))


def build_retained_row_anomaly_summary(
    session,
    rows: list[dict[str, Any]],
    *,
    batch_id: Optional[str] = None,
) -> dict[str, Any]:
    """Batch-level, read-only suspicious-row report for retained crawl rows."""
    raw_ids = {row["raw_record_id"] for row in rows}
    records = [
        record
        for record in (
            RawCrawlBatchRepository(session).list_records(batch_id)
            if batch_id
            else RawCrawlBatchRepository(session).list_all_records()
        )
        if record.raw_record_id in raw_ids
    ]
    field_proposals = _field_proposals_for_scope(
        FieldProposalRepository(session).list(),
        batch_id=batch_id,
        raw_ids=raw_ids,
    )
    keyword_proposals = _keyword_proposals_for_scope(
        KeywordProposalRepository(session).list(),
        batch_id=batch_id,
        raw_ids=raw_ids,
    )
    raw_audit = build_raw_ai_audit(records, field_proposals, batch_id=batch_id)
    issues_by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in raw_audit.get("issues", []):
        issues_by_raw[issue.get("raw_record_id")].append(issue)
    proposals_by_raw = proposals_by_raw_record(field_proposals)
    keyword_proposals_by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in keyword_proposals:
        for triggering in proposal.get("triggering_records", []):
            raw_id = triggering.get("raw_record_id")
            if raw_id in raw_ids:
                keyword_proposals_by_raw[raw_id].append(proposal)

    buckets = {
        "invalid_category": _anomaly_bucket(
            "invalid_category",
            "Invalid or unsafe category assignments need later taxonomy review.",
        ),
        "new_category_proposals": _anomaly_bucket(
            "new_category_proposals",
            "Category additions or category-string proposals should be reviewed without holding the whole batch.",
        ),
        "new_keyword_proposals": _anomaly_bucket(
            "new_keyword_proposals",
            "Keyword additions should be reviewed after normal retained rows proceed.",
        ),
        "missing_or_ambiguous_unit_conversion": _anomaly_bucket(
            "missing_or_ambiguous_unit_conversion",
            "Unit/package conversion is missing or conflicts with deterministic parsing.",
        ),
        "price_outlier_or_missing_source_period": _anomaly_bucket(
            "price_outlier_or_missing_source_period",
            "Price/source-period evidence needs adversarial review.",
        ),
        "missing_hotdeal_image": _anomaly_bucket(
            "missing_hotdeal_image",
            "Hotdeal publication rows need an image before public exposure.",
        ),
        "high_confidence_validation_failures": _anomaly_bucket(
            "high_confidence_validation_failures",
            "High-confidence AI output failed deterministic validation.",
        ),
    }

    price_outliers_by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for anomaly in _price_outlier_anomalies(rows):
        price_outliers_by_raw[anomaly.get("raw_record_id")].append(anomaly)

    for row in rows:
        raw_id = row["raw_record_id"]
        issue_codes = {issue.get("code") for issue in issues_by_raw.get(raw_id, [])}
        row_blockers = [str(blocker) for blocker in row.get("blockers") or []]
        row_flags = row.get("post_publish_audit_flags") or []
        row_proposals = proposals_by_raw.get(raw_id, [])
        item = row.get("item") or {}

        category_issue_codes = {
            "invalid_category_id_format",
            "category_string_requires_review",
            "fruit_snack_confusion",
            "snack_seafood_confusion",
            "seafood_snack_confusion",
            "weak_prepared_food_category",
        }
        if issue_codes & category_issue_codes:
            _add_bucket_row(
                buckets["invalid_category"],
                row,
                issue_codes=sorted(issue_codes & category_issue_codes),
                proposed_values=_proposal_values(row_proposals, {"category_id", "category", "category_hint", "category_name"}),
            )

        category_proposals = [
            proposal
            for proposal in row_proposals
            if proposal.target_field in {"category", "category_hint", "category_name"}
            or (
                proposal.target_field == "category_id"
                and proposal.status.value in UNRESOLVED_PROPOSAL_STATUSES
            )
        ]
        if category_proposals or (issue_codes & {"unknown_taxonomy_category", "category_string_requires_review"}):
            taxonomy_alias_proposals = [
                issue.get("taxonomy_alias_proposal")
                for issue in issues_by_raw.get(raw_id, [])
                if issue.get("taxonomy_alias_proposal")
            ]
            _add_bucket_row(
                buckets["new_category_proposals"],
                row,
                issue_codes=sorted(issue_codes & {"unknown_taxonomy_category", "category_string_requires_review"}),
                proposal_ids=[proposal.proposal_id for proposal in category_proposals],
                proposed_values=_proposal_values(row_proposals, {"category_id", "category", "category_hint", "category_name"}),
                taxonomy_alias_proposals=taxonomy_alias_proposals,
            )

        keyword_field_proposals = [
            proposal
            for proposal in row_proposals
            if proposal.target_field in {"keywords", "aliases"}
            and proposal.status.value in UNRESOLVED_PROPOSAL_STATUSES
        ]
        linked_keyword_proposals = [
            proposal
            for proposal in keyword_proposals_by_raw.get(raw_id, [])
            if proposal.get("status") in BLOCKING_KEYWORD_STATUSES
        ]
        if keyword_field_proposals or linked_keyword_proposals:
            _add_bucket_row(
                buckets["new_keyword_proposals"],
                row,
                proposal_ids=[
                    *[proposal.proposal_id for proposal in keyword_field_proposals],
                    *[str(proposal.get("proposal_id")) for proposal in linked_keyword_proposals],
                ],
                proposed_values={
                    "keywords": [
                        *[proposal.proposed_value for proposal in keyword_field_proposals],
                        *[proposal.get("proposed_keyword") for proposal in linked_keyword_proposals],
                    ],
                },
            )

        unit_issue_codes = issue_codes & {"missing_unit_signal", "provider_unit_discrepancy"}
        package_blockers = [
            blocker
            for blocker in row_blockers
            if "missing DB-admin package field" in blocker
        ]
        if unit_issue_codes or package_blockers:
            _add_bucket_row(
                buckets["missing_or_ambiguous_unit_conversion"],
                row,
                issue_codes=sorted(unit_issue_codes),
                blockers=package_blockers,
                proposed_values=_proposal_values(
                    row_proposals,
                    {"package_unit", "package_quantity", "display_unit", "standard_unit", "standard_unit_price"},
                ),
            )

        price_issue_codes = issue_codes & {"price_mismatch_raw", "mismatched_raw_price", "mismatched_price"}
        missing_period = _missing_price_source_period(item)
        if price_outliers_by_raw.get(raw_id) or price_issue_codes or missing_period:
            _add_bucket_row(
                buckets["price_outlier_or_missing_source_period"],
                row,
                issue_codes=sorted(price_issue_codes),
                anomalies=price_outliers_by_raw.get(raw_id, []),
                missing_evidence=missing_period,
            )

        if (
            row.get("publication_kind") == "hotdeal"
            and item.get("image_url") in (None, "")
        ) or any("missing hotdeal publication evidence field image_url" in blocker for blocker in row_blockers):
            _add_bucket_row(
                buckets["missing_hotdeal_image"],
                row,
                blockers=[
                    blocker
                    for blocker in row_blockers
                    if "image_url" in blocker
                ],
            )

        if "inflated_confidence_after_validation_failure" in issue_codes:
            confidence_issues = [
                issue
                for issue in issues_by_raw.get(raw_id, [])
                if issue.get("code") == "inflated_confidence_after_validation_failure"
            ]
            _add_bucket_row(
                buckets["high_confidence_validation_failures"],
                row,
                issue_codes=["inflated_confidence_after_validation_failure"],
                validation_issue_codes=sorted({
                    code
                    for issue in confidence_issues
                    for code in issue.get("validation_issue_codes", [])
                }),
            )

        flag_codes = {flag.get("code") for flag in row_flags}
        if flag_codes & {"ai_suggested_category", "ai_suggested_category_id", "ai_suggested_category_hint", "ai_suggested_category_name"}:
            _add_bucket_row(
                buckets["new_category_proposals"],
                row,
                post_publish_audit_flags=sorted(flag_codes),
            )
        if flag_codes & {"ai_suggested_keywords", "ai_suggested_aliases", "db_keyword_proposal_unresolved"}:
            _add_bucket_row(
                buckets["new_keyword_proposals"],
                row,
                post_publish_audit_flags=sorted(flag_codes),
            )

    suspicious_raw_ids = sorted({
        row["raw_record_id"]
        for bucket in buckets.values()
        for row in bucket["rows"]
    })
    buckets = {key: _finalize_bucket(bucket) for key, bucket in buckets.items()}
    return {
        "style": "일름보 AI",
        "mode": "report_only_non_destructive",
        "batch_id": batch_id,
        "retained_row_count": len(rows),
        "suspicious_row_count": len(suspicious_raw_ids),
        "normal_row_count": max(len(rows) - len(suspicious_raw_ids), 0),
        "normal_retained_row_ids": sorted(raw_ids - set(suspicious_raw_ids)),
        "suspicious_raw_record_ids": suspicious_raw_ids,
        "categories": buckets,
        "category_counts": {key: bucket["count"] for key, bucket in buckets.items()},
    }


def _anomaly_bucket(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "count": 0,
        "message": message,
        "rows": [],
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    bucket = {**bucket}
    bucket["rows"] = sorted(bucket["rows"], key=lambda row: row["raw_record_id"])
    bucket["count"] = len(bucket["rows"])
    return bucket


def _add_bucket_row(bucket: dict[str, Any], row: dict[str, Any], **extra: Any) -> None:
    raw_id = row["raw_record_id"]
    existing = next((entry for entry in bucket["rows"] if entry["raw_record_id"] == raw_id), None)
    payload = {
        "raw_record_id": raw_id,
        "raw_title": row.get("raw_title"),
        "status": row.get("status"),
        "eligible": row.get("eligible"),
        "publication_kind": row.get("publication_kind"),
        "db_handoff_mode": row.get("db_handoff_mode"),
        "report_only": True,
    }
    payload.update({key: value for key, value in extra.items() if value not in (None, [], {}, "")})
    if existing is None:
        bucket["rows"].append(payload)
        return
    for key, value in payload.items():
        if key not in existing or existing[key] in (None, [], {}, ""):
            existing[key] = value
        elif isinstance(existing[key], list) and isinstance(value, list):
            existing[key] = _dedupe_list([*existing[key], *value])
        elif isinstance(existing[key], dict) and isinstance(value, dict):
            existing[key] = {**existing[key], **value}


def _proposal_values(
    proposals: list[FieldProposalContract],
    fields: set[str],
) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = defaultdict(list)
    for proposal in proposals:
        if proposal.target_field in fields and proposal.proposed_value not in (None, ""):
            values[proposal.target_field].append(proposal.proposed_value)
    return {key: _dedupe_list(value) for key, value in values.items()}


def _dedupe_list(values: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _missing_price_source_period(item: dict[str, Any]) -> list[str]:
    publication_kind = item.get("publication_kind")
    if publication_kind != "hotdeal":
        return []
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    sale_offer = raw_data.get("sale_offer") if isinstance(raw_data.get("sale_offer"), dict) else {}
    has_period = any(
        source.get(field) not in (None, "")
        for source in (item, sale_offer)
        for field in (
            "event_name",
            "event",
            "source_event",
            "source_period",
            "period",
            "valid_from",
            "valid_to",
            "start_date",
            "end_date",
        )
    )
    return [] if has_period else ["source_period"]


def _is_automation_approval(decision: Any) -> bool:
    if decision.decision != ReviewDecision.APPROVE:
        return False
    corrected = decision.corrected_value
    if isinstance(corrected, dict) and corrected.get("automation_rule_id"):
        return True
    return "automation_rule_id" in (decision.reason or "") or str(decision.reviewer_id).startswith("automation:")


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
    blocking_audit_issues = _blocking_audit_issues(audit_issues)
    pending_statuses = {
        PipelineStatus.AI_PROPOSED,
        PipelineStatus.HUMAN_REVIEWING,
        PipelineStatus.NEEDS_REWORK,
        PipelineStatus.PENDING_REVIEW,
    }
    if any(
        proposal.proposal_type == ProposalType.KEYWORD
        and proposal.target_field not in REVIEW_RELAXED_PROPOSAL_FIELDS
        and proposal.status in pending_statuses
        for proposal in proposals
    ):
        blockers.append("keyword: pending non-catalog proposal requires approval or rejection")
    linked_keyword_proposals = [
        proposal
        for proposal in keyword_proposals
        if any(
            triggering.get("raw_record_id") == record.raw_record_id
            for triggering in proposal.get("triggering_records", [])
        )
    ]
    if any(
        proposal.status in pending_statuses
        and proposal.target_field not in REVIEW_RELAXED_PROPOSAL_FIELDS
        for proposal in proposals
    ):
        blockers.append("pending_review: critical AI proposals must be human approved")
    if any(proposal.status == PipelineStatus.REJECTED for proposal in proposals):
        blockers.append("held: rejected proposal requires rework before publishing")
    if proposals and not any(proposal.status in {PipelineStatus.APPROVED, PipelineStatus.PUBLISHED} for proposal in proposals):
        blockers.append("approved: at least one human-approved proposal is required")
    for issue in blocking_audit_issues:
        code = issue.get("code")
        blockers.append(f"data_quality: {code}")
    item = db_item_from_review(record, proposals, decisions_by_proposal)
    for field in ("name", "source"):
        if item.get(field) in (None, ""):
            blockers.append(f"data_quality: missing DB ingestion field {field}")
    if not _positive_number(item.get("sale_price")):
        blockers.append("data_quality: missing positive DB ingestion field sale_price")
    if item.get("source_url") in (None, ""):
        blockers.append("data_quality: missing price observation evidence field source_url")
    blockers.extend(_package_metadata_blockers(record, item))
    blockers.extend(_source_package_mismatch_blockers(record, proposals, item))
    return blockers


def _blocking_audit_issues(audit_issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in audit_issues
        if issue.get("code") in STRICT_AUDIT_BLOCKER_CODES
    ]


def _package_metadata_blockers(record: RawCrawlRecord, item: dict[str, Any]) -> list[str]:
    unit_metadata = normalize_unit_metadata(
        name=record.raw_title,
        sale_price=record.raw_price,
        raw_unit=_first_present(record.raw_payload or {}, "unit", "raw_unit", "sellUnitCapacity"),
    )
    deterministic_package_expected = unit_metadata.get("package_quantity") is not None
    has_partial_package_quantity = any(
        item.get(field) not in (None, "")
        for field in ("package_quantity", "package_unit")
    )
    if not deterministic_package_expected and not has_partial_package_quantity:
        return []
    return [
        f"data_quality: missing DB-admin package field {field}"
        for field in ("display_unit", "package_quantity", "package_unit")
        if item.get(field) in (None, "")
    ]


def _source_package_mismatch_blockers(
    record: RawCrawlRecord,
    proposals: list[FieldProposalContract],
    item: dict[str, Any],
) -> list[str]:
    """Hold package variants when source evidence and AI package proposals conflict."""

    normalized = (item.get("raw_data") or {}).get("normalized") if isinstance(item.get("raw_data"), dict) else {}
    variant = normalized.get("product_variant") if isinstance(normalized, dict) else {}
    if not isinstance(variant, dict):
        return []
    if (
        variant.get("package_evidence_source") == "deterministic_source"
        and variant.get("package_match_status") == "source_confirmed"
    ):
        return []
    proposed_package_fields = {
        proposal.target_field
        for proposal in proposals
        if (
            proposal.target_field
            in (
                "package_quantity",
                "package_unit",
                "display_unit",
                "standard_unit",
                "standard_unit_price",
            )
            and proposal.status in DB_ITEM_USABLE_PROPOSAL_STATUSES
        )
    }
    if not proposed_package_fields:
        return []
    if variant.get("package_evidence_source") == "source_payload":
        mismatched = [
            field
            for field in proposed_package_fields
            if field in {"package_quantity", "package_unit", "display_unit"}
            and not _contains_equivalent([item.get(field)], _proposal_value_for_field(proposals, field))
        ]
        if not mismatched:
            return []
    return [
        "data_quality: package_mismatch_source",
        "held: package mismatch must remain a candidate until source listing evidence is strong",
    ]


def _proposal_value_for_field(proposals: list[FieldProposalContract], field: str) -> Any:
    for proposal in proposals:
        if proposal.target_field == field and proposal.status in DB_ITEM_USABLE_PROPOSAL_STATUSES:
            return proposal.proposed_value
    return None


def build_post_publish_audit_flags(
    record: RawCrawlRecord,
    proposals: list[FieldProposalContract],
    audit_issues: list[dict[str, Any]],
    keyword_proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    blocking_codes = {issue.get("code") for issue in _blocking_audit_issues(audit_issues)}
    for issue in audit_issues:
        code = issue.get("code")
        if code in blocking_codes:
            continue
        flags.append({
            "code": code,
            "source": "raw_ai_audit",
            "message": issue.get("message"),
            "severity": "post_publish_audit",
        })
    for proposal in proposals:
        if proposal.target_field in REVIEW_RELAXED_PROPOSAL_FIELDS and proposal.status in {
            PipelineStatus.AI_PROPOSED,
            PipelineStatus.HUMAN_REVIEWING,
        }:
            flags.append({
                "code": f"ai_suggested_{proposal.target_field}",
                "source": "field_proposal",
                "proposal_id": proposal.proposal_id,
                "status": proposal.status.value,
                "severity": "post_publish_audit",
            })
    for proposal in keyword_proposals:
        if not any(
            triggering.get("raw_record_id") == record.raw_record_id
            for triggering in proposal.get("triggering_records", [])
        ):
            continue
        if proposal.get("status") in KEYWORD_PROPOSAL_BLOCKING_STATUSES:
            flags.append({
                "code": "db_keyword_proposal_unresolved",
                "source": "keyword_proposal",
                "proposal_id": proposal.get("proposal_id"),
                "status": proposal.get("status"),
                "severity": "post_publish_audit",
            })
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for flag in flags:
        key = (flag.get("code"), flag.get("source"), flag.get("proposal_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(flag)
    return deduped


def _positive_number(value: Any) -> bool:
    number = _first_number(value)
    return number is not None and number > 0


def _publication_metadata(item: dict[str, Any]) -> dict[str, Any]:
    sale_price = _first_number(item.get("sale_price"), item.get("current_price"))
    original_price = _first_number(item.get("original_price"))
    discount_percent = _first_number(item.get("discount_percent"), item.get("discount_rate"))
    event_name = item.get("event_name")
    has_original = (
        sale_price is not None
        and original_price is not None
        and original_price > sale_price
    )
    has_discount = discount_percent is not None and discount_percent > 0
    has_source_event = event_name not in (None, "")
    has_verified_discount = has_original and has_discount
    if has_verified_discount:
        return {
            "publication_kind": "hotdeal",
            "price_observation_only": False,
            "discount_claim_status": "verified",
            "claim_basis": "source_declared_original_discount",
            "claim_blockers": [],
        }
    missing = []
    if not has_original:
        missing.append("original_price")
    if not has_discount:
        missing.append("discount_percent")
    if not has_source_event:
        missing.append("source_event")
    missing.append("historical_baseline")
    return {
        "publication_kind": "price_observation",
        "price_observation_only": True,
        "discount_claim_status": HOTDEAL_CLAIM_BLOCKED_CODE,
        "claim_basis": "current_price_observation",
        "claim_blockers": [
            f"{HOTDEAL_CLAIM_BLOCKED_MESSAGE}; missing={','.join(missing)}"
        ],
    }


def derive_publish_status(
    proposals: list[FieldProposalContract],
    blockers: list[str],
    publish_state: Optional[AIPublishRecord],
) -> str:
    if publish_state and publish_state.status in {
        PipelineStatus.PUBLISHING.value,
        PipelineStatus.PENDING_DB_REVIEW.value,
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


def _publish_state_explanations(
    status: str,
    publish_state: Optional[AIPublishRecord],
) -> list[str]:
    if publish_state is None:
        return []
    if status == PipelineStatus.PENDING_DB_REVIEW.value:
        return [
            "pending_db_review: already submitted to DB-admin; wait for final DB-admin approval or rollback the pending ingestion before resubmitting"
        ]
    if status == PipelineStatus.PUBLISHED.value:
        return [
            "published: DB-admin/public DB flow already accepted this row; use rollback only if exposure must be stopped"
        ]
    if status == PipelineStatus.ROLLED_BACK.value:
        return [
            "rolled_back: AI-admin rollback requested; do not resubmit until the DB-admin pending ingestion is rejected/deleted and proposals are re-approved"
        ]
    if status == PipelineStatus.PUBLISHING.value:
        return ["publishing: DB-admin submission is currently in progress"]
    return []


def db_item_from_review(
    record: RawCrawlRecord,
    proposals: list[FieldProposalContract],
    decisions_by_proposal: dict[str, list[Any]],
) -> dict[str, Any]:
    raw_payload = record.raw_payload or {}
    fields: dict[str, Any] = {}
    attributes: dict[str, Any] = dict(raw_payload.get("attributes") or {})
    for proposal in proposals:
        allowed_statuses = (
            RELAXED_DB_ITEM_PROPOSAL_STATUSES
            if proposal.target_field in REVIEW_RELAXED_PROPOSAL_FIELDS
            else DB_ITEM_USABLE_PROPOSAL_STATUSES
        )
        if proposal.status not in allowed_statuses:
            continue
        value = _human_reviewed_value(proposal, decisions_by_proposal.get(proposal.proposal_id, []))
        target = proposal.target_field
        if target.startswith("attributes."):
            attributes[target.split(".", 1)[1]] = value
        elif target in {"keywords", "aliases"}:
            existing = fields.setdefault(target, [])
            values = value if isinstance(value, list) else [value]
            for entry in values:
                if entry not in existing:
                    existing.append(entry)
        else:
            fields[target] = value

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
    ignored_source_owned_ai_fields = {
        key: value
        for key, value in fields.items()
        if key in SOURCE_OWNED_PROPOSAL_FIELDS and value not in (None, "")
    }
    price = _first_positive_number(
        record.raw_price,
        raw_payload.get("sale_price"),
        raw_payload.get("current_price"),
        raw_payload.get("price"),
        raw_payload.get("offer_price"),
        raw_payload.get("source_price"),
        raw_payload.get("raw_price"),
    )
    original_price = _first_number(
        raw_payload.get("original_price"),
        raw_payload.get("list_price"),
        raw_payload.get("regular_price"),
    )
    discount_percent = _source_discount_percent(raw_payload)
    if original_price is not None and price is not None and original_price <= price:
        original_price = None
    if discount_percent is not None and discount_percent <= 0:
        discount_percent = None
    price_state = _source_price_state(price, original_price, discount_percent)
    source_url = (
        record.source_url
        or _first_present(raw_payload, "source_url", "detail_url", "url")
    )
    source = fields.get("source") or _first_present(raw_payload, "source", "store", "mall") or record.source_name
    category_candidates = (
        fields.get("category_id"),
        fields.get("category"),
        fields.get("category_hint"),
        fields.get("category_name"),
        raw_payload.get("category_id"),
        raw_payload.get("category"),
        raw_payload.get("category_hint"),
        raw_payload.get("category_name"),
    )
    category_id = _first_safe_public_category_id(*category_candidates)
    category_evidence = [
        {
            "raw": value,
            "normalized": normalize_category_id(value),
            "display_label": get_category_display_label(value),
            "safe_seed": is_safe_seed_category(value),
        }
        for value in category_candidates
        if value not in (None, "")
    ]
    category = category_id or fields.get("category") or raw_payload.get("category") or raw_payload.get("category_hint")
    unit_metadata = normalize_unit_metadata(
        name=record.raw_title,
        sale_price=price,
        raw_unit=_first_present(raw_payload, "unit", "raw_unit", "sellUnitCapacity"),
    )
    attributes = {**(unit_metadata.get("attributes") or {}), **attributes}
    has_deterministic_package = unit_metadata.get("package_quantity") is not None
    display_unit = (
        unit_metadata.get("display_unit")
        if has_deterministic_package
        else raw_payload.get("display_unit") or fields.get("display_unit") or unit_metadata.get("display_unit")
    )
    package_quantity = (
        unit_metadata.get("package_quantity")
        if has_deterministic_package
        else _first_positive_number(raw_payload.get("package_quantity"), fields.get("package_quantity"))
    )
    package_unit = (
        unit_metadata.get("package_unit")
        if has_deterministic_package
        else raw_payload.get("package_unit") or fields.get("package_unit")
    )
    if isinstance(package_unit, str) and package_unit not in {"g", "kg", "ml", "L"}:
        package_unit = unit_metadata.get("package_unit") or package_unit
    price_per_100g = (
        unit_metadata.get("price_per_100g")
        if has_deterministic_package and unit_metadata.get("price_per_100g") is not None
        else _first_number(fields.get("price_per_100g"), raw_payload.get("price_per_100g"))
    )
    standard_unit_price = _first_number(
        fields.get("standard_unit_price"),
        raw_payload.get("standard_unit_price"),
    )
    standard_unit = fields.get("standard_unit") or raw_payload.get("standard_unit")
    bundle_count = int(
        _first_number(
            fields.get("bundle_count"),
            raw_payload.get("bundle_count"),
            unit_metadata.get("bundle_count"),
            1,
        )
        or 1
    )
    if price is not None and package_quantity and package_unit:
        standard_total = quantity_to_standard_total(package_quantity, str(package_unit), bundle_count)
        if standard_total is not None:
            total_quantity, inferred_standard_unit = standard_total
            standard_unit = inferred_standard_unit
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
            image_url=raw_payload.get("image_url") or raw_payload.get("image"),
            price_state=price_state,
            promotion_type=raw_payload.get("promotion_type") or raw_payload.get("promotion") or "unknown",
            price=int(price) if price is not None else None,
            original_price=int(original_price) if original_price is not None else None,
            discount_rate=_discount_rate_fraction(discount_percent),
            event_name=raw_payload.get("event_name") or raw_payload.get("event") or raw_payload.get("source_event"),
            standard_unit_price=standard_unit_price,
            price_per_100g=price_per_100g,
            valid_from=raw_payload.get("valid_from") or raw_payload.get("start_date"),
            valid_to=raw_payload.get("valid_to") or raw_payload.get("end_date"),
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
                "ignored_source_owned_ai_fields": ignored_source_owned_ai_fields,
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
    item["category_display_label"] = get_category_display_label(category)
    item["raw_data"]["display_unit"] = display_unit
    item["raw_data"]["package_quantity"] = package_quantity
    item["raw_data"]["package_unit"] = package_unit
    item["raw_data"]["category_evidence"] = {
        "safe_category_id": category_id,
        "safe_category_display_label": get_category_display_label(category_id),
        "candidates": category_evidence,
    }
    item["observed_at"] = record.crawled_at.isoformat()
    item.update(_publication_metadata(item))
    item["raw_data"]["publication"] = {
        "publication_kind": item["publication_kind"],
        "price_observation_only": item["price_observation_only"],
        "discount_claim_status": item["discount_claim_status"],
        "claim_basis": item["claim_basis"],
        "claim_blockers": item["claim_blockers"],
        "observed_at": item["observed_at"],
    }
    if attributes:
        item["attributes"] = attributes
    _attach_normalized_publish_metadata(
        item,
        record=record,
        fields=fields,
        raw_payload=raw_payload,
        raw_unit=raw_unit,
        unit_metadata=unit_metadata,
        package_evidence_source=_package_evidence_source(
            has_deterministic_package=has_deterministic_package,
            raw_payload=raw_payload,
            fields=fields,
        ),
    )
    return item


def _package_evidence_source(
    *,
    has_deterministic_package: bool,
    raw_payload: dict[str, Any],
    fields: dict[str, Any],
) -> str:
    if has_deterministic_package:
        return "deterministic_source"
    if raw_payload.get("package_quantity") not in (None, "") or raw_payload.get("package_unit") not in (None, ""):
        return "source_payload"
    if fields.get("package_quantity") not in (None, "") or fields.get("package_unit") not in (None, ""):
        return "ai_proposal"
    return "missing"


def _attach_normalized_publish_metadata(
    item: dict[str, Any],
    *,
    record: RawCrawlRecord,
    fields: dict[str, Any],
    raw_payload: dict[str, Any],
    raw_unit: Any,
    unit_metadata: dict[str, Any],
    package_evidence_source: str,
) -> None:
    """Attach DB-admin normalized table semantics without changing legacy fields."""

    raw_data = item.setdefault("raw_data", {})
    if not isinstance(raw_data, dict):
        return
    canonical = dict(raw_data.get("canonical_product") or {})
    variant = dict(raw_data.get("product_variant") or {})
    offer = dict(raw_data.get("sale_offer") or {})
    raw_evidence = offer.get("raw_evidence") if isinstance(offer.get("raw_evidence"), dict) else {
        "raw_title": record.raw_title,
        "raw_price": record.raw_price,
        "raw_unit": raw_unit,
        "raw_payload": raw_payload,
    }
    audit_provenance = dict(raw_data.get("audit_provenance") or item.get("ai_review_audit") or {})

    source_package_signature = _package_signature(
        quantity=unit_metadata.get("package_quantity") or raw_payload.get("package_quantity"),
        unit=unit_metadata.get("package_unit") or raw_payload.get("package_unit"),
        bundle_count=unit_metadata.get("bundle_count") or raw_payload.get("bundle_count") or 1,
        display_unit=unit_metadata.get("display_unit") or raw_payload.get("display_unit") or raw_unit,
    )
    publish_package_signature = _package_signature(
        quantity=item.get("package_quantity"),
        unit=item.get("package_unit"),
        bundle_count=item.get("bundle_count") or 1,
        display_unit=item.get("display_unit") or item.get("unit"),
    )
    package_match_status = (
        "source_confirmed"
        if package_evidence_source in {"deterministic_source", "source_payload"}
        and (not source_package_signature or source_package_signature == publish_package_signature)
        else "candidate_package_mismatch"
        if source_package_signature and publish_package_signature and source_package_signature != publish_package_signature
        else "candidate_needs_review"
        if package_evidence_source == "ai_proposal"
        else "not_applicable"
    )

    normalized = {
        "contract_version": "normalized-mart3-v1",
        "ai_override_policy": "source_owned_price_link_period_image_fields_win",
        "canonical_product": {
            "public_product_id": item.get("public_product_id"),
            "canonical_name": item.get("canonical_name") or item.get("name"),
            "brand": item.get("brand") or canonical.get("brand"),
            "category_id": item.get("category_id"),
            "category_name": item.get("category") or item.get("category_display_label"),
            "aliases": canonical.get("aliases") or item.get("aliases") or [],
            "keywords": item.get("keywords") or canonical.get("keywords") or [],
            "attributes": canonical.get("attributes") or item.get("attributes") or {},
            "primary_image_url": item.get("image_url"),
        },
        "product_variant": {
            "public_variant_id": item.get("public_variant_id"),
            "variant_name": variant.get("variant_name") or item.get("source_title") or item.get("name"),
            "package_quantity": item.get("package_quantity"),
            "package_unit": item.get("package_unit"),
            "display_unit": item.get("display_unit"),
            "bundle_count": item.get("bundle_count") or 1,
            "standard_unit": item.get("standard_unit"),
            "attributes": variant.get("attributes") or item.get("attributes") or {},
            "package_signature": publish_package_signature,
            "source_package_signature": source_package_signature,
            "package_evidence_source": package_evidence_source,
            "package_match_status": package_match_status,
        },
        "source_listing": {
            "public_source_listing_id": item.get("public_source_listing_id"),
            "source_name": item.get("source"),
            "source_record_key": item.get("source_record_key") or record.source_record_key,
            "source_title": item.get("source_title") or record.raw_title,
            "source_title_key": normalize_match_text(str(item.get("source_title") or record.raw_title)),
            "source_url": item.get("source_url"),
            "image_url": item.get("image_url"),
            "source_unit_text": raw_unit or item.get("display_unit") or item.get("unit"),
        },
        "offer_event": {
            "public_offer_event_id": item.get("public_offer_event_id"),
            "price_state": item.get("price_state"),
            "promotion_type": item.get("promotion_type"),
            "price": item.get("sale_price"),
            "current_price": item.get("current_price"),
            "original_price": item.get("original_price"),
            "discount_rate": offer.get("discount_rate"),
            "discount_percent": item.get("discount_percent"),
            "event_name": item.get("event_name"),
            "valid_from": _jsonable_datetime(item.get("valid_from") or offer.get("valid_from")),
            "valid_to": _jsonable_datetime(item.get("valid_to") or offer.get("valid_to")),
            "standard_unit_price": item.get("standard_unit_price"),
            "price_per_100g": item.get("price_per_100g"),
            "raw_record_id": record.raw_record_id,
            "raw_evidence": raw_evidence,
            "audit_provenance": audit_provenance,
            "offer_state": item.get("offer_state") or "active",
        },
        "source_owned_fields": {
            "price": item.get("sale_price"),
            "source_url": item.get("source_url"),
            "image_url": item.get("image_url"),
            "event_name": item.get("event_name"),
            "valid_from": _jsonable_datetime(item.get("valid_from") or offer.get("valid_from")),
            "valid_to": _jsonable_datetime(item.get("valid_to") or offer.get("valid_to")),
        },
    }
    raw_data["normalized"] = normalized
    raw_data["normalized_metadata"] = normalized
    item["normalized_metadata"] = normalized
    item.setdefault("price", item.get("sale_price"))
    item.setdefault("source_name", item.get("source"))
    item.setdefault("variant_name", normalized["product_variant"]["variant_name"])
    item.setdefault("source_unit_text", normalized["source_listing"]["source_unit_text"])
    item.setdefault("listing_image_url", item.get("image_url"))
    item.setdefault("raw_evidence", raw_evidence)
    item.setdefault("audit_provenance", audit_provenance)
    item.setdefault("crawled_at", item.get("observed_at"))


def _package_signature(
    *,
    quantity: Any,
    unit: Any,
    bundle_count: Any,
    display_unit: Any,
) -> str | None:
    if quantity in (None, "") and unit in (None, "") and display_unit in (None, ""):
        return None
    try:
        return normalize_package_signature(
            f"qty={quantity or ''};unit={unit or ''};bundle={bundle_count or 1};display={display_unit or ''}"
        )
    except ValueError:
        return None


def _jsonable_datetime(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _human_reviewed_value(proposal: FieldProposalContract, decisions: list[Any]) -> Any:
    for decision in sorted(decisions, key=lambda d: d.decided_at, reverse=True):
        if decision.decision == ReviewDecision.CORRECT:
            return decision.corrected_value
    return proposal.proposed_value


def _first_safe_public_category_id(*values: Any) -> str | None:
    for value in values:
        normalized = normalize_category_id(value)
        if normalized and is_safe_seed_category(normalized):
            return normalized
    return None


def _first_number(*values: Any) -> Optional[float]:
    for value in values:
        if isinstance(value, (int, float)) and value >= 0:
            return value
        if isinstance(value, str):
            try:
                number = float(
                    value.replace(",", "")
                    .replace("원", "")
                    .replace("₩", "")
                    .replace("%", "")
                    .strip()
                )
            except ValueError:
                continue
            if number >= 0:
                return number
    return None


def _first_positive_number(*values: Any) -> Optional[float]:
    number = _first_number(*values)
    return number if number is not None and number > 0 else None


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
    return round(number / 100, 4)


def _source_discount_percent(raw_payload: dict[str, Any]) -> Optional[float]:
    """Return source-owned discount_percent in percent units without treating sub-1 percentages as fractions."""
    for key in ("discount_percent", "discount"):
        number = _first_number(raw_payload.get(key))
        if number is not None:
            return number
    rate = _first_number(raw_payload.get("discount_rate"))
    if rate is None:
        return None
    return round(rate * 100, 4) if rate <= 1 else rate


def _source_price_state(
    price: Any,
    original_price: Any,
    discount_percent: Any,
) -> PriceState:
    if price is not None:
        return PriceState.NORMAL
    if discount_percent is not None:
        return PriceState.DISCOUNT_RATE_ONLY
    if original_price is not None:
        return PriceState.ORIGINAL_PRICE_ONLY
    return PriceState.PRICE_HIDDEN


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
    if row.status not in {PipelineStatus.PENDING_DB_REVIEW.value, PipelineStatus.PUBLISHED.value}:
        raise ValueError(
            "only DB-admin-submitted or published AI rows can be rolled back; "
            f"current status is {row.status}"
        )
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
        weird_issues = _weird_classification_issues(record, by_field)
        issues.extend(weird_issues)
        validation_issues = [
            *weird_issues,
            *_taxonomy_category_issues(record, by_field),
            *_prepared_food_name_category_issues(record, by_field),
            *_unsafe_keyword_alias_issues(record, by_field),
            *_unit_discrepancy_issues(record, by_field),
        ]
        issues.extend(validation_issues)
        confidence_blocking_issues = [
            issue
            for issue in validation_issues
            if issue["code"] in STRICT_AUDIT_BLOCKER_CODES
        ]
        if confidence_blocking_issues and _max_confidence(record_proposals) >= 0.9:
            issues.append(
                _issue(
                    record,
                    "inflated_confidence_after_validation_failure",
                    "provider confidence is too high for proposals that failed deterministic validation",
                    max_confidence=_max_confidence(record_proposals),
                    validation_issue_codes=sorted({issue["code"] for issue in confidence_blocking_issues}),
                )
            )

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


AI_BATCH_ANOMALY_SCOPE_STATUSES = {
    PipelineStatus.APPROVED.value,
    PipelineStatus.PENDING_DB_REVIEW.value,
    PipelineStatus.PUBLISHED.value,
}


def build_ai_batch_anomaly_audit(
    session,
    *,
    batch_id: Optional[str] = None,
    stale_days: int = 7,
) -> dict[str, Any]:
    """Read-only anomaly audit for ready/published AI-managed batch data.

    This is intentionally a detection/remediation surface, not a hard publish gate:
    it gives admins a recurring checklist of suspicious already-ready data and
    long-lived review pollution without mutating the control DB.
    """
    rows = build_publish_rows(session, batch_id=batch_id)
    retained_summary = build_retained_row_anomaly_summary(session, rows, batch_id=batch_id)
    scoped_rows = [
        row
        for row in rows
        if row.get("eligible") or row.get("status") in AI_BATCH_ANOMALY_SCOPE_STATUSES
    ]
    anomalies: list[dict[str, Any]] = []
    anomalies.extend(_category_keyword_anomalies(scoped_rows))
    anomalies.extend(_price_outlier_anomalies(scoped_rows))
    anomalies.extend(_missing_source_evidence_anomalies(scoped_rows))
    anomalies.extend(_duplicate_offer_anomalies(scoped_rows))
    anomalies.extend(_taxonomy_keyword_explosion_anomalies(scoped_rows))
    anomalies.extend(_hotdeal_claim_anomalies(scoped_rows))
    anomalies.extend(_stale_unreviewed_proposal_anomalies(session, rows, batch_id=batch_id, stale_days=stale_days))

    severity_order = {"critical": 3, "warning": 2, "info": 1}
    status = "ok" if not anomalies else "warning"
    if any(anomaly.get("severity") == "critical" for anomaly in anomalies):
        status = "critical"
    return {
        "batch_id": batch_id,
        "run_at": datetime.now().isoformat(),
        "status": status,
        "scope": "ready_or_published",
        "stale_days": stale_days,
        "row_count": len(rows),
        "audited_row_count": len(scoped_rows),
        "anomaly_count": len(anomalies),
        "suspicious_retained_row_count": retained_summary["suspicious_row_count"],
        "retained_row_anomaly_summary": retained_summary,
        "ilreumbo_ai": retained_summary,
        "severity_counts": _status_counts([anomaly.get("severity", "info") for anomaly in anomalies]),
        "anomaly_type_counts": _status_counts([anomaly.get("type", "unknown") for anomaly in anomalies]),
        "review_queue": sorted(
            anomalies,
            key=lambda item: (
                -severity_order.get(str(item.get("severity")), 0),
                str(item.get("type")),
                str(item.get("raw_record_id") or item.get("proposal_id") or ""),
            ),
        ),
    }


def _anomaly(
    anomaly_type: str,
    severity: str,
    message: str,
    *,
    action: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "type": anomaly_type,
        "severity": severity,
        "message": message,
        "recommended_action": action,
    }
    payload.update(extra)
    return payload


def _category_keyword_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for row in rows:
        item = row.get("item") or {}
        category = str(item.get("category_id") or item.get("category") or "")
        keywords = [str(value) for value in item.get("keywords") or [] if value not in (None, "")]
        raw_title = str(row.get("raw_title") or item.get("source_title") or "")
        mismatch = _category_keyword_mismatch(category, keywords, raw_title)
        if mismatch:
            anomalies.append(
                _anomaly(
                    "category_keyword_mismatch",
                    "warning",
                    "published/ready item has category, keyword, or title signals that disagree",
                    action="Review category_id and keywords; correct or roll back if this reached DB-admin/public exposure.",
                    raw_record_id=row["raw_record_id"],
                    status=row.get("status"),
                    category=category,
                    keywords=keywords,
                    raw_title=raw_title,
                    reason=mismatch,
                )
            )
    return anomalies


def _category_keyword_mismatch(category: str, keywords: list[str], raw_title: str) -> str | None:
    category_norm = _normalize_text(category)
    keyword_text = _normalize_text(" ".join(keywords))
    title_norm = _normalize_text(raw_title)
    combined = f"{keyword_text} {title_norm}"
    looks_snack = any(_normalize_text(token) in combined for token in SNACK_TITLE_TOKENS)
    looks_seafood = any(_normalize_text(token) in combined for token in SEAFOOD_TITLE_TOKENS)
    looks_fruit = any(_normalize_text(token) in combined for token in FRUIT_TITLE_TOKENS)
    is_snack_category = any(category_norm.startswith(prefix) for prefix in SNACK_CATEGORY_PREFIXES)
    is_seafood_category = any(category_norm.startswith(prefix) for prefix in SEAFOOD_CATEGORY_PREFIXES)
    is_fruit_category = any(category_norm.startswith(prefix) for prefix in FRUIT_CATEGORY_PREFIXES)
    if looks_snack and is_seafood_category:
        return "snack keyword/title signals are attached to a seafood category"
    if looks_fruit and not is_fruit_category and not category_norm.startswith("produce"):
        return "fruit keyword/title signals are attached to a non-fruit category"
    if looks_seafood and not looks_snack and is_snack_category:
        return "seafood keyword/title signals are attached to a snack category"
    return None


def _price_outlier_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    category_prices: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        item = row.get("item") or {}
        price = _first_number(item.get("sale_price"), item.get("current_price"))
        if price is None:
            continue
        category = str(item.get("category_id") or item.get("category") or "uncategorized")
        category_prices[category].append(float(price))
    medians = {
        category: sorted(prices)[len(prices) // 2]
        for category, prices in category_prices.items()
        if len(prices) >= 3
    }
    for row in rows:
        item = row.get("item") or {}
        price = _first_number(item.get("sale_price"), item.get("current_price"))
        standard_unit_price = _first_number(item.get("standard_unit_price"), item.get("price_per_100g"))
        if price is None:
            continue
        category = str(item.get("category_id") or item.get("category") or "uncategorized")
        median = medians.get(category)
        reason = None
        if price <= 0 or price > 10_000_000:
            reason = "absolute price is zero/negative or above 10,000,000"
        elif standard_unit_price is not None and standard_unit_price > 1_000_000:
            reason = "unit price is unusually high"
        elif median and median > 0 and (price >= median * 5 or price <= median / 5):
            reason = f"price is outside 5x category median ({median:g})"
        if reason:
            anomalies.append(
                _anomaly(
                    "price_outlier",
                    "warning",
                    "published/ready price looks anomalous for admin review",
                    action="Compare against source evidence and correct the AI proposal or DB-admin ingestion if needed.",
                    raw_record_id=row["raw_record_id"],
                    status=row.get("status"),
                    price=price,
                    category=category,
                    reason=reason,
                )
            )
    return anomalies


def _missing_source_evidence_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for row in rows:
        item = row.get("item") or {}
        missing = [
            field
            for field in ("source_url", "image_url")
            if item.get(field) in (None, "")
        ]
        raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
        if not raw_data.get("raw_record"):
            missing.append("raw_record_evidence")
        if missing:
            image_only = missing == ["image_url"]
            anomalies.append(
                _anomaly(
                    "missing_source_evidence",
                    "info" if image_only else "warning",
                    (
                        "ready/published item is missing optional image UI evidence"
                        if image_only
                        else "ready/published item is missing source evidence needed for fast remediation"
                    ),
                    action=(
                        "Attach an image when available; retain DB price/source/unit data without treating the image as an integrity blocker."
                        if image_only
                        else "Attach source URL/raw evidence or roll back/publicly hide the row until evidence is restored."
                    ),
                    raw_record_id=row["raw_record_id"],
                    status=row.get("status"),
                    missing=missing,
                )
            )
    return anomalies


def _duplicate_offer_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = row.get("item") or {}
        key = (
            _normalize_text(item.get("source") or row.get("source_name") or ""),
            _normalize_text(item.get("name") or item.get("source_title") or ""),
            str(_first_number(item.get("sale_price"), item.get("current_price")) or ""),
            _normalize_text(item.get("source_url") or ""),
        )
        if key[1] and (key[2] or key[3]):
            by_key[key].append(row)
    anomalies: list[dict[str, Any]] = []
    for key, matches in by_key.items():
        if len(matches) <= 1:
            continue
        anomalies.append(
            _anomaly(
                "duplicate_products_offers",
                "warning",
                "multiple ready/published rows appear to represent the same product offer",
                action="Merge/reject duplicate AI rows or roll back duplicate DB-admin submissions.",
                duplicate_key={
                    "source": key[0],
                    "name": key[1],
                    "price": key[2],
                    "source_url": key[3],
                },
                raw_record_ids=[row["raw_record_id"] for row in matches],
                statuses=[row.get("status") for row in matches],
            )
        )
    return anomalies


def _taxonomy_keyword_explosion_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    categories = {
        str((row.get("item") or {}).get("category_id") or (row.get("item") or {}).get("category") or "")
        for row in rows
        if ((row.get("item") or {}).get("category_id") or (row.get("item") or {}).get("category"))
    }
    keywords = {
        _normalize_text(keyword)
        for row in rows
        for keyword in ((row.get("item") or {}).get("keywords") or [])
        if keyword not in (None, "")
    }
    row_count = len(rows)
    anomalies: list[dict[str, Any]] = []
    if len(categories) >= max(8, row_count // 2 + 1):
        anomalies.append(
            _anomaly(
                "taxonomy_explosion",
                "warning",
                "ready/published batch has an unusually high number of distinct categories",
                action="Review taxonomy changes for AI-created over-specific categories before they pollute public navigation.",
                row_count=row_count,
                distinct_category_count=len(categories),
                categories=sorted(categories)[:30],
            )
        )
    if len(keywords) >= max(20, row_count * 4):
        anomalies.append(
            _anomaly(
                "keyword_explosion",
                "warning",
                "ready/published batch has an unusually high number of distinct keywords",
                action="Bulk-review keyword additions; reject generic/noisy terms and keep an audit note for accepted expansion.",
                row_count=row_count,
                distinct_keyword_count=len(keywords),
                keywords=sorted(keywords)[:50],
            )
        )
    return anomalies


def _hotdeal_claim_anomalies(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for row in rows:
        item = row.get("item") or {}
        publication = item.get("raw_data", {}).get("publication", {}) if isinstance(item.get("raw_data"), dict) else {}
        publication_kind = item.get("publication_kind") or publication.get("publication_kind")
        discount_claim_status = item.get("discount_claim_status") or publication.get("discount_claim_status")
        if publication_kind == "hotdeal" and discount_claim_status != "verified":
            anomalies.append(
                _anomaly(
                    "price_observation_claiming_hotdeal",
                    "critical",
                    "item claims hotdeal publication without verified discount evidence",
                    action="Demote to price_observation or roll back the DB-admin/public row; verify original_price/discount/source event first.",
                    raw_record_id=row["raw_record_id"],
                    status=row.get("status"),
                    publication_kind=publication_kind,
                    discount_claim_status=discount_claim_status,
                )
            )
    return anomalies


def _stale_unreviewed_proposal_anomalies(
    session,
    rows: list[dict[str, Any]],
    *,
    batch_id: Optional[str],
    stale_days: int,
) -> list[dict[str, Any]]:
    cutoff = datetime.now() - timedelta(days=stale_days)
    raw_ids = {row["raw_record_id"] for row in rows}
    field_proposals = FieldProposalRepository(session).list()
    if batch_id:
        field_proposals = _field_proposals_for_scope(field_proposals, batch_id=batch_id, raw_ids=raw_ids)
    stale_field = [
        proposal
        for proposal in field_proposals
        if proposal.status.value in UNRESOLVED_PROPOSAL_STATUSES and proposal.created_at < cutoff
    ]
    keyword_proposals = KeywordProposalRepository(session).list()
    if batch_id:
        keyword_proposals = _keyword_proposals_for_scope(keyword_proposals, batch_id=batch_id, raw_ids=raw_ids)
    stale_keywords = [
        proposal
        for proposal in keyword_proposals
        if proposal.get("status") in BLOCKING_KEYWORD_STATUSES
        and _parse_iso_datetime(proposal.get("created_at")) < cutoff
    ]
    anomalies: list[dict[str, Any]] = []
    for proposal in stale_field[:50]:
        anomalies.append(
            _anomaly(
                "stale_unreviewed_proposal",
                "info",
                "field proposal has been unresolved past the review SLA",
                action="Approve, correct, reject, or mark needs_rework so stale AI proposals do not accumulate unnoticed.",
                proposal_id=proposal.proposal_id,
                raw_record_id=proposal.provenance.raw_record_id,
                status=proposal.status.value,
                created_at=proposal.created_at.isoformat(),
                target_field=proposal.target_field,
            )
        )
    for proposal in stale_keywords[:50]:
        anomalies.append(
            _anomaly(
                "stale_unreviewed_proposal",
                "info",
                "keyword proposal has been unresolved past the review SLA",
                action="Approve/reject the keyword proposal so AI-managed keyword data does not stay polluted long-term.",
                proposal_id=proposal.get("proposal_id"),
                raw_record_ids=[
                    record.get("raw_record_id")
                    for record in proposal.get("triggering_records", [])
                    if isinstance(record, dict)
                ],
                status=proposal.get("status"),
                created_at=proposal.get("created_at"),
                proposed_keyword=proposal.get("proposed_keyword"),
            )
        )
    return anomalies


def _parse_iso_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.min
    return datetime.min


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
        if not _shares_text_signal(record.raw_title, str(value), title_tokens=title_tokens):
            issues.append(
                _issue(
                    record,
                    "name_signal_mismatch",
                    "canonical name does not share any signal with raw title",
                    proposed=value,
                )
            )
    keyword_values = [str(value) for value in _values_for_fields(by_field, ("keywords",))]
    raw_keyword_values = _raw_keyword_values(record)
    if keyword_values and title_tokens and raw_keyword_values:
        matching = [
            kw
            for kw in keyword_values
            if _shares_text_signal(record.raw_title, kw, title_tokens=title_tokens)
            or any(_shares_text_signal(str(raw_keyword), kw) for raw_keyword in raw_keyword_values)
        ]
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


def _raw_keyword_values(record: RawCrawlRecord) -> list[Any]:
    raw_payload = record.raw_payload or {}
    values: list[Any] = []
    for key in ("keywords", "keyword", "tags", "search_terms"):
        if raw_payload.get(key) not in (None, ""):
            values.extend(_flatten_value(raw_payload[key]))
    return values


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
    looks_fruit = any(_normalize_text(token) in title_norm for token in FRUIT_TITLE_TOKENS)
    category_norms = [_normalize_text(category) for category in categories]
    is_snack_category = any(
        category.startswith(prefix) for category in category_norms for prefix in SNACK_CATEGORY_PREFIXES
    )
    is_seafood_category = any(
        category.startswith(prefix) for category in category_norms for prefix in SEAFOOD_CATEGORY_PREFIXES
    )
    is_fruit_category = any(
        category.startswith(prefix) for category in category_norms for prefix in FRUIT_CATEGORY_PREFIXES
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
    if looks_fruit and is_snack_category and not is_fruit_category:
        issues.append(
            _issue(
                record,
                "fruit_snack_confusion",
                "fruit/produce-like crawl item was classified as snack",
                proposed=categories,
            )
        )
    return issues


def _prepared_food_name_category_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    title_norm = _normalize_text(record.raw_title)
    if not _looks_like_prepared_food(title_norm):
        return issues
    for value in by_field.get("canonical_name", []):
        canonical_norm = _normalize_text(value)
        if "키트" in title_norm and "키트" not in canonical_norm:
            issues.append(
                _issue(
                    record,
                    "overbroad_canonical_name",
                    "kit/prepared-food canonical name dropped key product modifiers",
                    proposed=value,
                )
            )
        elif "꼬마김밥" in title_norm and "꼬마김밥" not in canonical_norm:
            issues.append(
                _issue(
                    record,
                    "overbroad_canonical_name",
                    "prepared-food canonical name is too broad for the raw title",
                    proposed=value,
                )
            )
    categories = [str(value) for value in _values_for_fields(by_field, ("category_id",))]
    category_norms = [_normalize_text(category) for category in categories]
    is_safe_prepared_category = any(
        category.startswith(prefix)
        for category in category_norms
        for prefix in PREPARED_CATEGORY_PREFIXES
    )
    is_snack_category = any(
        category.startswith(prefix)
        for category in category_norms
        for prefix in SNACK_CATEGORY_PREFIXES
    )
    if categories and (is_snack_category or not is_safe_prepared_category):
        issues.append(
            _issue(
                record,
                "weak_prepared_food_category",
                "prepared-food or meal-kit product needs a prepared_food.meal_kit category, not snacks or brand hints",
                proposed=categories,
            )
        )
    return issues


def _unsafe_keyword_alias_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    title_norm = _normalize_text(record.raw_title)
    for value in _values_for_fields(by_field, ("keywords",)):
        keyword_norm = _normalize_text(value)
        if (
            keyword_norm in INGREDIENT_ONLY_KEYWORDS
            and not _looks_like_packaged_ham(title_norm)
            and not _looks_like_prepared_ingredient_context(keyword_norm, title_norm)
        ):
            issues.append(
                _issue(
                    record,
                    "unsafe_ingredient_keyword",
                    "ingredient terms must remain attributes unless the product itself is packaged ham",
                    proposed=value,
                )
            )
    for value in _values_for_fields(by_field, ("aliases",)):
        alias_norm = _normalize_text(value)
        if alias_norm in GENERIC_ALIAS_TERMS:
            issues.append(
                _issue(
                    record,
                    "unsafe_generic_alias",
                    "generic aliases must be scoped to the product term",
                    proposed=value,
                )
            )
    return issues


def _taxonomy_category_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for value in _values_for_fields(by_field, ("category_id",)):
        raw_category_id = str(value or "").strip()
        category_id = normalize_category_id(value)
        if not category_id:
            continue
        if is_safe_seed_category(category_id):
            continue
        if _has_unsafe_category_id_separator(raw_category_id) or not OFFICIAL_CATEGORY_ID_RE.match(category_id):
            issues.append(
                _issue(
                    record,
                    "invalid_category_id_format",
                    "category_id must use the official dot-notation taxonomy format",
                    proposed=value,
                    normalized=category_id,
                    allowed_seed_categories=sorted(SAFE_SEED_CATEGORY_IDS),
                    review_context=_taxonomy_review_context(record, by_field),
                )
            )
            continue
        issues.append(
            _issue(
                record,
                "unknown_taxonomy_category",
                (
                    "category_id is not in the AI-admin safe seed taxonomy; hold in review "
                    "until a human maps it to an existing seed category or explicitly approves "
                    "a DB-admin taxonomy change"
                ),
                proposed=value,
                allowed_seed_categories=sorted(SAFE_SEED_CATEGORY_IDS),
                review_context=_taxonomy_review_context(record, by_field),
                taxonomy_alias_proposal=_taxonomy_alias_proposal(record, value),
            )
        )
    for value in _values_for_fields(by_field, ("category", "category_hint", "category_name")):
        if value in (None, ""):
            continue
        normalized = normalize_category_id(value)
        if normalized and is_safe_seed_category(normalized):
            continue
        issues.append(
            _issue(
                record,
                "category_string_requires_review",
                (
                    "category strings are not public taxonomy IDs; provide a reviewed category_id "
                    "from the safe seed taxonomy before publishing"
                ),
                proposed=value,
                allowed_seed_categories=sorted(SAFE_SEED_CATEGORY_IDS),
                review_context=_taxonomy_review_context(record, by_field),
                taxonomy_alias_proposal=_taxonomy_alias_proposal(record, value),
            )
        )
    return issues


def _has_unsafe_category_id_separator(value: str) -> bool:
    return any(separator in value for separator in UNSAFE_CATEGORY_ID_SEPARATORS)


def _taxonomy_review_context(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> dict[str, Any]:
    return {
        "raw_record": record.model_dump(mode="json"),
        "proposed_categories": {
            field: list(values)
            for field, values in by_field.items()
            if field in {"category_id", "category", "category_hint", "category_name"}
        },
    }


def _taxonomy_alias_proposal(record: RawCrawlRecord, value: Any) -> dict[str, Any]:
    normalized = normalize_category_id(value)
    return {
        "proposal_type": "taxonomy_alias_proposal",
        "status": PipelineStatus.HUMAN_REVIEWING.value,
        "proposed_alias": value,
        "normalized_candidate": normalized,
        "raw_title": record.raw_title,
        "source_name": record.source_name,
        "action": (
            "review_existing_seed_mapping_or_create_db_admin_taxonomy_change; "
            "do_not_add_code_alias_until repeated cross-source evidence exists"
        ),
    }


def _unit_discrepancy_issues(
    record: RawCrawlRecord,
    by_field: dict[str, list[Any]],
) -> list[dict[str, Any]]:
    unit_metadata = normalize_unit_metadata(
        name=record.raw_title,
        sale_price=record.raw_price,
        raw_unit=_first_present(record.raw_payload or {}, "unit", "raw_unit", "sellUnitCapacity"),
    )
    if unit_metadata.get("package_quantity") is None:
        return []
    expected: dict[str, Any] = {
        "package_quantity": unit_metadata.get("package_quantity"),
        "display_unit": unit_metadata.get("display_unit"),
        "price_per_100g": unit_metadata.get("price_per_100g"),
    }
    standard_total = quantity_to_standard_total(
        unit_metadata["package_quantity"],
        unit_metadata["package_unit"],
        int(unit_metadata.get("bundle_count") or 1),
    )
    if standard_total is not None and record.raw_price is not None:
        total_quantity, standard_unit = standard_total
        expected["standard_unit"] = standard_unit
        expected["standard_unit_price"] = round(float(record.raw_price) / total_quantity, 2)

    mismatches: list[dict[str, Any]] = []
    for field, expected_value in expected.items():
        if expected_value is None:
            continue
        actual_values = _values_for_fields(by_field, (field,))
        if actual_values and not any(_contains_equivalent([actual], expected_value) for actual in actual_values):
            mismatches.append({"field": field, "expected": expected_value, "actual": actual_values})
    if not mismatches:
        return []
    return [
        _issue(
            record,
            "provider_unit_discrepancy",
            "provider unit/package price proposals conflict with deterministic raw title/price calculation",
            discrepancies=mismatches,
        )
    ]


def _looks_like_prepared_food(title_norm: str) -> bool:
    return any(_normalize_text(token) in title_norm for token in PREPARED_TITLE_TOKENS)


def _looks_like_prepared_ingredient_context(keyword_norm: str, title_norm: str) -> bool:
    return keyword_norm in title_norm and _looks_like_prepared_food(title_norm)


def _looks_like_packaged_ham(title_norm: str) -> bool:
    if "햄" not in title_norm:
        return False
    if any(token in title_norm for token in ("김밥", "샌드", "피자", "볶음밥", "키트")):
        return False
    if any(_normalize_text(token) in title_norm for token in SNACK_TITLE_TOKENS):
        return False
    return any(_normalize_text(token) in title_norm for token in PACKAGED_HAM_TITLE_TOKENS)


def _max_confidence(proposals: list[FieldProposalContract]) -> float:
    confidences = [
        float(proposal.provenance.confidence)
        for proposal in proposals
        if proposal.provenance.confidence is not None
    ]
    return max(confidences, default=0.0)


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


def _shares_text_signal(
    raw_title: str,
    candidate: str,
    *,
    title_tokens: set[str] | None = None,
) -> bool:
    raw_norm = _normalize_text(raw_title)
    candidate_norm = _normalize_text(candidate)
    if not candidate_norm:
        return False
    if candidate_norm in raw_norm or raw_norm in candidate_norm:
        return True
    tokens = title_tokens if title_tokens is not None else _tokens(raw_title)
    return bool(tokens.intersection(_tokens(candidate)))
