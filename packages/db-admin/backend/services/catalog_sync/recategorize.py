"""Phase 3 — product_match_rules(이름 규칙) 기반 상품 일괄 재분류 + 영향 미리보기.

핵심 원칙:
  - 매칭표 = product_match_rules. 각 상품 이름을 규칙(exact→normalized→regex, trust 우선)에
    매칭해 unified_category_id를 재계산한다.
  - **규칙이 안 맞는 상품은 변경하지 않는다**(기존 카테고리를 비우지 않음). no_rule_match로만 집계.
  - human(manual/corrected)은 force=True 일 때만 변경.
  - 카테고리 필드만 갱신(apply_rule_to_product) — 상품 생성·이름·가격이력 변경 없음.
  - preview는 DB 미변경. apply는 스냅샷 선행 후 단일 트랜잭션.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.backup import create_backup
from services.product_match_rules import (
    apply_rule_to_product,
    normalize_title,
    record_rule_hit,
)
from storage.models import Product, ProductMatchRule

_HUMAN_METHODS = {"manual", "corrected"}


# ── 규칙 인덱스(상품 6천건 × 규칙 4천건 → 매번 쿼리 금지) ──────────────────────

@dataclass
class RuleIndex:
    exact: dict[str, ProductMatchRule] = field(default_factory=dict)
    normalized: dict[str, ProductMatchRule] = field(default_factory=dict)
    regex: list[ProductMatchRule] = field(default_factory=list)


def build_rule_index(session: Session) -> RuleIndex:
    """trust desc, id asc 순으로 적재 → setdefault가 최고 trust 규칙을 유지한다."""
    rules = session.scalars(
        select(ProductMatchRule).order_by(ProductMatchRule.trust.desc(), ProductMatchRule.id.asc())
    ).all()
    idx = RuleIndex()
    for r in rules:
        if r.pattern_type == "exact":
            idx.exact.setdefault(r.pattern_value, r)
        elif r.pattern_type == "normalized":
            idx.normalized.setdefault(normalize_title(r.pattern_value), r)
        elif r.pattern_type == "regex":
            idx.regex.append(r)
    return idx


def match_title(title: str | None, idx: RuleIndex) -> ProductMatchRule | None:
    raw = str(title or "").strip()
    if not raw:
        return None
    rule = idx.exact.get(raw)
    if rule:
        return rule
    rule = idx.normalized.get(normalize_title(raw))
    if rule:
        return rule
    norm = normalize_title(raw)
    for r in idx.regex:
        try:
            if re.search(r.pattern_value, raw, flags=re.IGNORECASE) or re.search(r.pattern_value, norm, flags=re.IGNORECASE):
                return r
        except re.error:
            continue
    return None


# ── scope ────────────────────────────────────────────────────────────────────

def _scoped_products(session: Session, scope: dict[str, Any] | None) -> list[Product]:
    scope = scope or {"mode": "all"}
    mode = scope.get("mode", "all")
    stmt = select(Product).order_by(Product.id)
    if mode == "all":
        pass
    elif mode == "unclassified":
        stmt = stmt.where(Product.unified_category_id.is_(None))
    elif mode == "by_category":
        cid = scope.get("category_id")
        if not cid:
            raise ValueError("by_category scope에는 category_id가 필요합니다.")
        stmt = stmt.where(Product.unified_category_id == cid)
    elif mode == "by_mart":
        mart = scope.get("mart")
        if not mart:
            raise ValueError("by_mart scope에는 mart가 필요합니다.")
        stmt = stmt.where(Product.mart == mart)
    else:
        raise ValueError(f"지원하지 않는 scope: {mode}")
    return list(session.scalars(stmt).all())


# ── 미리보기 ──────────────────────────────────────────────────────────────────

@dataclass
class RecategorizePreview:
    scope: dict[str, Any] = field(default_factory=dict)
    force: bool = False
    total_considered: int = 0
    matched_rule: int = 0
    no_rule_match: int = 0
    newly_classified: int = 0      # None → cat
    reclassified: int = 0          # catA → catB
    unchanged: int = 0             # 규칙은 맞으나 동일 카테고리
    protected_skipped: int = 0     # human, 변경 대상이나 보호로 스킵
    transitions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def will_change(self) -> int:
        return self.newly_classified + self.reclassified

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "force": self.force,
            "total_considered": self.total_considered,
            "matched_rule": self.matched_rule,
            "no_rule_match": self.no_rule_match,
            "newly_classified": self.newly_classified,
            "reclassified": self.reclassified,
            "unchanged": self.unchanged,
            "protected_skipped": self.protected_skipped,
            "will_change": self.will_change,
            "transitions": self.transitions,
        }


def preview_recategorization(
    session: Session,
    *,
    scope: dict[str, Any] | None = None,
    force: bool = False,
    sample_limit: int = 5,
    max_transition_groups: int = 300,
) -> RecategorizePreview:
    idx = build_rule_index(session)
    products = _scoped_products(session, scope)
    prev = RecategorizePreview(scope=scope or {"mode": "all"}, force=force)
    prev.total_considered = len(products)

    groups: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for p in products:
        rule = match_title(p.name, idx)
        if rule is None or rule.canonical_category_id is None:
            prev.no_rule_match += 1
            continue
        prev.matched_rule += 1
        from_cat = p.unified_category_id
        to_cat = rule.canonical_category_id
        if to_cat == from_cat:
            prev.unchanged += 1
            continue
        if (p.categorization_method in _HUMAN_METHODS) and not force:
            prev.protected_skipped += 1
            continue
        if from_cat is None:
            prev.newly_classified += 1
        else:
            prev.reclassified += 1
        key = (from_cat, to_cat)
        g = groups.get(key)
        if g is None:
            g = {"from": from_cat, "to": to_cat, "count": 0, "samples": []}
            groups[key] = g
        g["count"] += 1
        if len(g["samples"]) < sample_limit:
            g["samples"].append({"id": p.id, "name": p.name,
                                 "method": p.categorization_method,
                                 "rule": {"type": rule.pattern_type, "value": rule.pattern_value,
                                          "trust": rule.trust}})

    prev.transitions = sorted(groups.values(), key=lambda x: x["count"], reverse=True)[:max_transition_groups]
    return prev


# ── 적용 ──────────────────────────────────────────────────────────────────────

@dataclass
class RecategorizeResult:
    ok: bool = True
    scope: dict[str, Any] = field(default_factory=dict)
    force: bool = False
    changed: int = 0
    newly_classified: int = 0
    reclassified: int = 0
    unchanged: int = 0
    no_rule_match: int = 0
    protected_skipped: int = 0
    snapshot_path: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "scope": self.scope,
            "force": self.force,
            "changed": self.changed,
            "newly_classified": self.newly_classified,
            "reclassified": self.reclassified,
            "unchanged": self.unchanged,
            "no_rule_match": self.no_rule_match,
            "protected_skipped": self.protected_skipped,
            "snapshot_path": self.snapshot_path,
            "error_message": self.error_message,
        }


def apply_recategorization(
    session: Session,
    *,
    scope: dict[str, Any] | None = None,
    force: bool = False,
    database_url: str,
    make_snapshot: bool = True,
) -> RecategorizeResult:
    result = RecategorizeResult(scope=scope or {"mode": "all"}, force=force)
    if make_snapshot:
        result.snapshot_path = create_backup(database_url, reason="catalog-sync-recategorize")

    try:
        idx = build_rule_index(session)
        products = _scoped_products(session, scope)
        for p in products:
            rule = match_title(p.name, idx)
            if rule is None or rule.canonical_category_id is None:
                result.no_rule_match += 1
                continue
            from_cat = p.unified_category_id
            to_cat = rule.canonical_category_id
            if to_cat == from_cat:
                result.unchanged += 1
                continue
            if (p.categorization_method in _HUMAN_METHODS) and not force:
                result.protected_skipped += 1
                continue
            apply_rule_to_product(rule, p)
            record_rule_hit(rule)
            result.changed += 1
            if from_cat is None:
                result.newly_classified += 1
            else:
                result.reclassified += 1
        session.commit()
    except Exception as e:  # noqa: BLE001
        session.rollback()
        result.ok = False
        result.error_message = f"재분류 중 오류(롤백됨): {e}"
    return result
