"""Conservative automation gates for AI review decisions.

Automation here only approves review proposals. It never publishes to DB-admin.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from core.contracts.ai_pipeline import FieldProposal, FieldProvenance, PipelineStatus, ProposalType, RawCrawlRecord
from core.contracts.control_plane import LearnedKnowledgeContract, ReviewDecision, ReviewDecisionContract
from core.product_units import normalize_unit_metadata
from services.keyword_catalog import normalize_keyword
from services.review_publish import (
    OFFICIAL_CATEGORY_ID_RE,
    build_raw_ai_audit,
    proposals_by_raw_record,
)
from services.seed_taxonomy import is_safe_seed_category
from storage import FieldProposalRepository, KeywordProposalRepository, LearnedKnowledgeRepository, RawCrawlBatchRepository, ReviewDecisionRepository


REVIEWABLE_STATUSES = {PipelineStatus.AI_PROPOSED, PipelineStatus.HUMAN_REVIEWING}
PENDING_STATUSES = {
    PipelineStatus.AI_PROPOSED,
    PipelineStatus.HUMAN_REVIEWING,
    PipelineStatus.PENDING_REVIEW,
    PipelineStatus.NEEDS_REWORK,
}
BLOCKING_KEYWORD_STATUSES = {
    PipelineStatus.AI_PROPOSED.value,
    PipelineStatus.HUMAN_REVIEWING.value,
    PipelineStatus.REJECTED.value,
}

RULE_EXACT_CATALOG_KEYWORD = "exact_catalog_keyword"
RULE_LEARNED_ALIAS = "learned_alias"
RULE_EXACT_CATEGORY = "exact_category"
DEFAULT_RULE_IDS = [RULE_EXACT_CATALOG_KEYWORD, RULE_LEARNED_ALIAS, RULE_EXACT_CATEGORY]
GENERALIZATION_EVIDENCE_CLASSES = {"model_inferred", "new_unknown"}
REVIEW_REQUIRED_TRUST_LABELS = {
    "human_review_required",
    "taxonomy_hint_needs_review",
    "raw_title_normalization_not_generalization",
    "raw_title_alias_not_learned_reuse",
}


class AutomationGateConfig(BaseModel):
    """Operator-supplied, opt-in controls for review automation."""

    enabled: bool = False
    selected_rule_ids: list[str] = Field(default_factory=list)
    reviewer_id: str = Field(default="automation:review-gates", min_length=1)
    default_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    learned_alias_min_confidence: float = Field(default=0.92, ge=0.0, le=1.0)
    learned_alias_min_success_count: int = Field(default=2, ge=1, le=1000)
    allowed_sources: Optional[list[str]] = None
    allowed_categories: Optional[list[str]] = None
    allowed_fields: Optional[list[str]] = None
    allowed_providers: Optional[list[str]] = None
    max_decisions: int = Field(default=100, ge=1, le=500)

    def active_rule_ids(self) -> set[str]:
        return set(self.selected_rule_ids or DEFAULT_RULE_IDS)


class AutomationPreviewRequest(BaseModel):
    config: AutomationGateConfig = Field(default_factory=AutomationGateConfig)
    batch_id: Optional[str] = None


class AutomationApplyRequest(BaseModel):
    config: AutomationGateConfig
    batch_id: Optional[str] = None


def build_automation_preview(session, config: AutomationGateConfig, *, batch_id: str | None = None) -> dict[str, Any]:
    raw_repo = RawCrawlBatchRepository(session)
    records = raw_repo.list_records(batch_id) if batch_id else raw_repo.list_all_records()
    records_by_id = {record.raw_record_id: record for record in records}
    raw_ids = set(records_by_id)
    proposals = [
        proposal
        for proposal in FieldProposalRepository(session).list()
        if proposal.provenance.raw_record_id in raw_ids
    ]
    grouped = proposals_by_raw_record(proposals)
    audit = build_raw_ai_audit(records, proposals, batch_id=batch_id)
    issues_by_raw: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in audit.get("issues", []):
        issues_by_raw[issue["raw_record_id"]].append(issue)
    keyword_proposals = KeywordProposalRepository(session).list()
    learned_by_id = {
        item.knowledge_id: item
        for item in LearnedKnowledgeRepository(session).list(active_only=True)
    }

    rows: list[dict[str, Any]] = []
    for proposal in proposals:
        if proposal.status not in REVIEWABLE_STATUSES:
            continue
        record = records_by_id.get(proposal.provenance.raw_record_id)
        if record is None:
            continue
        rows.append(
            _evaluate_proposal(
                proposal,
                record,
                grouped.get(record.raw_record_id, []),
                issues_by_raw.get(record.raw_record_id, []),
                keyword_proposals,
                learned_by_id,
                config,
            )
        )

    eligible = [row for row in rows if row["eligible"]]
    blocked = [row for row in rows if not row["eligible"]]
    return {
        "enabled": config.enabled,
        "rules": _rule_descriptions(config),
        "batch_id": batch_id,
        "eligible_count": len(eligible),
        "blocked_count": len(blocked),
        "candidate_count": len(rows),
        "items": rows,
        "eligible_items": eligible,
        "blocked_items": blocked[:100],
        "dry_run": True,
        "will_publish_to_db_admin": False,
        "automation_scope": "review_decisions_only",
        "blocked_generalization_count": sum(
            1
            for row in blocked
            if any("generalization" in blocker or "review-required evidence" in blocker for blocker in row["blockers"])
        ),
        "message": (
            f"{len(eligible)}개 제안이 선택한 안전 자동화 게이트를 통과했습니다. "
            "자동화는 승인 결정만 기록하며 DB-admin 발행은 하지 않습니다."
        ),
    }


def apply_automation_gates(session, config: AutomationGateConfig, *, batch_id: str | None = None) -> dict[str, Any]:
    if not config.enabled:
        raise ValueError("automation config must set enabled=true before applying gates")
    preview = build_automation_preview(session, config, batch_id=batch_id)
    candidates = preview["eligible_items"][: config.max_decisions]
    proposal_repo = FieldProposalRepository(session)
    decision_repo = ReviewDecisionRepository(session)
    applied: list[dict[str, Any]] = []
    for row in candidates:
        proposal = proposal_repo.get(row["proposal_id"])
        if proposal is None or proposal.status not in REVIEWABLE_STATUSES:
            continue
        now = datetime.now()
        provenance = proposal.provenance.model_copy(
            update={"reviewed_by": config.reviewer_id, "reviewed_at": now}
        )
        proposal_repo.save(
            proposal.model_copy(
                update={"status": PipelineStatus.APPROVED, "provenance": provenance}
            )
        )
        reason_payload = {
            "automation_rule_id": row["rule_id"],
            "reason": row["reason"],
            "threshold": row["threshold"],
            "field": proposal.target_field,
            "proposal_id": proposal.proposal_id,
            "raw_record_id": row["raw_record_id"],
            "will_publish_to_db_admin": False,
        }
        decision = ReviewDecisionContract(
            decision_id=f"{proposal.proposal_id}:approve:{config.reviewer_id}:{row['rule_id']}",
            proposal_id=proposal.proposal_id,
            proposal_type=proposal.proposal_type,
            decision=ReviewDecision.APPROVE,
            reviewer_id=config.reviewer_id,
            corrected_value={
                "automation_rule_id": row["rule_id"],
                "threshold": row["threshold"],
                "field": proposal.target_field,
                "proposal_id": proposal.proposal_id,
                "raw_record_id": row["raw_record_id"],
            },
            reason=json.dumps(reason_payload, ensure_ascii=False, sort_keys=True),
            create_learning_rule=False,
            decided_at=now,
        )
        decision_repo.save(decision)
        applied.append({**row, "decision_id": decision.decision_id})
    return {
        **preview,
        "dry_run": False,
        "applied_count": len(applied),
        "applied_items": applied,
        "skipped_count": max(preview["eligible_count"] - len(applied), 0),
        "will_publish_to_db_admin": False,
        "automation_scope": "review_decisions_only",
    }


def _evaluate_proposal(
    proposal: FieldProposal,
    record: RawCrawlRecord,
    linked_proposals: list[FieldProposal],
    audit_issues: list[dict[str, Any]],
    keyword_proposals: list[dict[str, Any]],
    learned_by_id: dict[str, LearnedKnowledgeContract],
    config: AutomationGateConfig,
) -> dict[str, Any]:
    base = {
        "proposal_id": proposal.proposal_id,
        "raw_record_id": record.raw_record_id,
        "source_name": record.source_name,
        "target_field": proposal.target_field,
        "proposal_type": proposal.proposal_type.value,
        "proposed_value": proposal.proposed_value,
        "confidence": proposal.provenance.confidence,
        "eligible": False,
        "rule_id": None,
        "reason": "",
        "threshold": None,
        "blockers": [],
    }
    blockers = _global_blockers(proposal, record, linked_proposals, audit_issues, keyword_proposals, config)
    if blockers:
        return {**base, "blockers": blockers, "reason": "; ".join(blockers)}

    for rule_id in config.active_rule_ids():
        ok, reason, threshold = _rule_match(proposal, record, learned_by_id, config, rule_id)
        if ok:
            return {
                **base,
                "eligible": True,
                "rule_id": rule_id,
                "reason": reason,
                "threshold": threshold,
                "blockers": [],
            }
        if reason:
            blockers.append(reason)
    return {**base, "blockers": blockers or ["no selected automation rule matched"], "reason": "; ".join(blockers)}


def _global_blockers(
    proposal: FieldProposal,
    record: RawCrawlRecord,
    linked_proposals: list[FieldProposal],
    audit_issues: list[dict[str, Any]],
    keyword_proposals: list[dict[str, Any]],
    config: AutomationGateConfig,
) -> list[str]:
    blockers: list[str] = []
    raw_payload = record.raw_payload or {}
    if config.allowed_sources and record.source_name not in set(config.allowed_sources):
        blockers.append("source is not enabled for automation")
    category = _category_for_record(record, linked_proposals)
    if config.allowed_categories and category not in set(config.allowed_categories):
        blockers.append("category is not enabled for automation")
    if config.allowed_fields and proposal.target_field not in set(config.allowed_fields):
        blockers.append("field is not enabled for automation")
    provider = proposal.provenance.provider.provider_name if proposal.provenance.provider else None
    if config.allowed_providers and provider not in set(config.allowed_providers):
        blockers.append("provider is not enabled for automation")
    if record.raw_price is None or record.raw_price <= 0:
        blockers.append("raw record price must be positive")
    if not (record.source_url or raw_payload.get("source_url") or raw_payload.get("detail_url") or raw_payload.get("url")):
        blockers.append("raw record is missing source URL")
    if not _has_unit_or_package(record):
        blockers.append("raw record is missing unit/package")
    if audit_issues:
        blockers.append("raw/AI audit has mismatch or quality issue")
    unsafe_evidence = _review_required_evidence(proposal)
    if unsafe_evidence:
        blockers.extend(unsafe_evidence)
    if _has_blocking_keyword_proposal(record.raw_record_id, keyword_proposals):
        blockers.append("unresolved or rejected DB keyword proposal blocks automation")
    unsafe_category = [
        item
        for item in linked_proposals
        if item.proposal_id != proposal.proposal_id
        and item.target_field == "category_id"
        and item.status in PENDING_STATUSES
        and not _is_exact_category(item, record, config)
    ]
    if unsafe_category:
        blockers.append("unresolved category proposal blocks automation")
    return blockers


def _rule_match(
    proposal: FieldProposal,
    record: RawCrawlRecord,
    learned_by_id: dict[str, LearnedKnowledgeContract],
    config: AutomationGateConfig,
    rule_id: str,
) -> tuple[bool, str, float | int | None]:
    confidence = proposal.provenance.confidence
    if rule_id == RULE_EXACT_CATALOG_KEYWORD:
        threshold = config.default_min_confidence
        if not _confidence_ok(confidence, threshold):
            return False, f"confidence below exact catalog threshold {threshold}", threshold
        if _is_exact_catalog_keyword(proposal):
            return True, "exact active catalog keyword match with required raw fields and clean audit", threshold
        return False, "not an exact catalog keyword match", threshold
    if rule_id == RULE_LEARNED_ALIAS:
        threshold = config.learned_alias_min_confidence
        if not _confidence_ok(confidence, threshold):
            return False, f"confidence below learned alias threshold {threshold}", threshold
        knowledge = _matched_knowledge(proposal, learned_by_id)
        if knowledge is None:
            return False, "no active learned alias evidence", threshold
        if knowledge.success_count < config.learned_alias_min_success_count:
            return False, f"learned alias success_count below {config.learned_alias_min_success_count}", config.learned_alias_min_success_count
        if knowledge.negative_examples:
            return False, "learned alias has negative/rejected evidence", threshold
        target = knowledge.target_value if isinstance(knowledge.target_value, dict) else {}
        if normalize_keyword(target.get("word")) != normalize_keyword(proposal.proposed_value):
            return False, "learned alias target does not exactly match proposed keyword", threshold
        return True, "exact learned alias with prior human-approved success count", threshold
    if rule_id == RULE_EXACT_CATEGORY:
        threshold = config.default_min_confidence
        if not _confidence_ok(confidence, threshold):
            return False, f"confidence below exact category threshold {threshold}", threshold
        if _is_exact_category(proposal, record, config):
            return True, "exact raw/expected category match with required raw fields and clean audit", threshold
        return False, "not an exact category match", threshold
    return False, f"unknown automation rule {rule_id}", None


def _is_exact_catalog_keyword(proposal: FieldProposal) -> bool:
    if proposal.proposal_type != ProposalType.KEYWORD or proposal.target_field != "keywords":
        return False
    alternatives = [item for item in proposal.alternatives if isinstance(item, dict) and item.get("keyword_id")]
    if len(alternatives) != 1:
        return False
    alt = alternatives[0]
    if alt.get("knowledge_id") or alt.get("similar_existing"):
        return False
    if alt.get("evidence_class") not in {None, "exact_catalog"}:
        return False
    if alt.get("trust_label") not in {None, "reuse_exact_catalog"}:
        return False
    return normalize_keyword(alt.get("word")) == normalize_keyword(proposal.proposed_value)


def _matched_knowledge(
    proposal: FieldProposal,
    learned_by_id: dict[str, LearnedKnowledgeContract],
) -> LearnedKnowledgeContract | None:
    matches = [
        learned_by_id.get(str(item.get("knowledge_id")))
        for item in proposal.alternatives
        if isinstance(item, dict)
        and item.get("knowledge_id")
        and item.get("evidence_class") in {None, "learned_alias"}
        and item.get("trust_label") in {None, "reuse_learned_alias"}
    ]
    matches = [item for item in matches if item is not None and item.knowledge_type == "keyword_alias_approved"]
    return matches[0] if len(matches) == 1 else None


def _is_exact_category(proposal: FieldProposal, record: RawCrawlRecord, config: AutomationGateConfig) -> bool:
    if proposal.target_field != "category_id" or proposal.proposal_type != ProposalType.CATEGORY:
        return False
    expected = _raw_expected_category(record)
    if not expected:
        return False
    proposed = str(proposal.proposed_value)
    expected = str(expected)
    if not (
        OFFICIAL_CATEGORY_ID_RE.match(proposed)
        and OFFICIAL_CATEGORY_ID_RE.match(expected)
        and is_safe_seed_category(proposed)
        and is_safe_seed_category(expected)
    ):
        return False
    if config.allowed_categories and expected not in set(config.allowed_categories):
        return False
    return proposed == expected


def _review_required_evidence(proposal: FieldProposal) -> list[str]:
    blockers: list[str] = []
    for alternative in proposal.alternatives:
        if not isinstance(alternative, dict):
            continue
        evidence_class = alternative.get("evidence_class")
        trust_label = alternative.get("trust_label")
        if evidence_class in GENERALIZATION_EVIDENCE_CLASSES:
            blockers.append(f"generalization evidence '{evidence_class}' requires human review")
        if trust_label in REVIEW_REQUIRED_TRUST_LABELS:
            blockers.append(f"review-required evidence '{trust_label}' blocks automation")
    return sorted(set(blockers))


def _raw_expected_category(record: RawCrawlRecord) -> str | None:
    raw_payload = record.raw_payload or {}
    expected = raw_payload.get("expected_ai") if isinstance(raw_payload.get("expected_ai"), dict) else {}
    return (
        expected.get("category_id")
        or raw_payload.get("category_id")
        or raw_payload.get("category")
        or raw_payload.get("category_hint")
    )


def _category_for_record(record: RawCrawlRecord, proposals: list[FieldProposal]) -> str | None:
    for proposal in proposals:
        if proposal.target_field == "category_id" and proposal.status == PipelineStatus.APPROVED:
            return str(proposal.proposed_value)
    return _raw_expected_category(record)


def _has_blocking_keyword_proposal(raw_record_id: str, keyword_proposals: list[dict[str, Any]]) -> bool:
    return any(
        proposal.get("status") in BLOCKING_KEYWORD_STATUSES
        and any(
            isinstance(item, dict) and item.get("raw_record_id") == raw_record_id
            for item in proposal.get("triggering_records", [])
        )
        for proposal in keyword_proposals
    )


def _has_unit_or_package(record: RawCrawlRecord) -> bool:
    raw_payload = record.raw_payload or {}
    for key in ("unit", "raw_unit", "display_unit", "package_unit", "package_quantity", "sellUnitCapacity"):
        if raw_payload.get(key) not in (None, ""):
            return True
    unit = normalize_unit_metadata(
        name=record.raw_title,
        sale_price=record.raw_price,
        raw_unit=raw_payload.get("unit"),
    )
    return bool(unit.get("display_unit") or (unit.get("package_quantity") and unit.get("package_unit")))


def _confidence_ok(value: float | None, threshold: float) -> bool:
    return isinstance(value, (int, float)) and value >= threshold


def _rule_descriptions(config: AutomationGateConfig) -> list[dict[str, Any]]:
    active = config.active_rule_ids()
    return [
        {
            "rule_id": RULE_EXACT_CATALOG_KEYWORD,
            "enabled": RULE_EXACT_CATALOG_KEYWORD in active,
            "label": "기존 DB 키워드 정확 매칭",
            "threshold": config.default_min_confidence,
        },
        {
            "rule_id": RULE_LEARNED_ALIAS,
            "enabled": RULE_LEARNED_ALIAS in active,
            "label": "학습된 별칭/동의어",
            "threshold": config.learned_alias_min_confidence,
            "min_success_count": config.learned_alias_min_success_count,
        },
        {
            "rule_id": RULE_EXACT_CATEGORY,
            "enabled": RULE_EXACT_CATEGORY in active,
            "label": "원본/기대 카테고리 정확 일치",
            "threshold": config.default_min_confidence,
        },
    ]
