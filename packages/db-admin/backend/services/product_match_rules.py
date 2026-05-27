"""상품명 기반 매칭 규칙 서비스."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from storage.models import Product, ProductMatchRule


_ONE_DEPTH_SEPARATORS = (".", ">", "/")


def ensure_product_match_rules_table(engine) -> None:
    ProductMatchRule.__table__.create(bind=engine, checkfirst=True)


def normalize_title(value: str | None) -> str:
    text = str(value or "").casefold().strip()
    text = re.sub(r"[\[\](){},./_+\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def is_missing_or_one_depth_category(category_id: str | None) -> bool:
    value = str(category_id or "").strip()
    if not value:
        return True
    return not any(sep in value for sep in _ONE_DEPTH_SEPARATORS)


def find_matching_rule(session: Session, title: str | None) -> ProductMatchRule | None:
    raw_title = str(title or "").strip()
    if not raw_title:
        return None
    normalized = normalize_title(raw_title)

    exact = session.execute(
        select(ProductMatchRule)
        .where(ProductMatchRule.pattern_type == "exact", ProductMatchRule.pattern_value == raw_title)
        .order_by(ProductMatchRule.trust.desc(), ProductMatchRule.id.asc())
    ).scalars().first()
    if exact:
        return exact

    normalized_rule = session.execute(
        select(ProductMatchRule)
        .where(ProductMatchRule.pattern_type == "normalized", ProductMatchRule.pattern_value == normalized)
        .order_by(ProductMatchRule.trust.desc(), ProductMatchRule.id.asc())
    ).scalars().first()
    if normalized_rule:
        return normalized_rule

    regex_rules = session.execute(
        select(ProductMatchRule)
        .where(ProductMatchRule.pattern_type == "regex")
        .order_by(ProductMatchRule.trust.desc(), ProductMatchRule.id.asc())
    ).scalars().all()
    for rule in regex_rules:
        try:
            if re.search(rule.pattern_value, raw_title, flags=re.IGNORECASE) or re.search(rule.pattern_value, normalized, flags=re.IGNORECASE):
                return rule
        except re.error:
            continue
    return None


def apply_rule_to_product(rule: ProductMatchRule, product: Product) -> None:
    if rule.canonical_category_id:
        product.unified_category_id = rule.canonical_category_id
    if rule.canonical_product_id:
        product.canonical_product_id = rule.canonical_product_id
    product.categorization_method = "match_rule"
    product.categorization_confidence = min(1.0, 0.80 + (rule.trust * 0.10))
    attrs = dict(product.attributes or {})
    attrs["product_match_rule_id"] = rule.id
    attrs["product_match_rule_pattern"] = {
        "type": rule.pattern_type,
        "value": rule.pattern_value,
    }
    product.attributes = attrs


def record_rule_hit(rule: ProductMatchRule) -> None:
    rule.hit_count = (rule.hit_count or 0) + 1


def make_rule(**kwargs) -> ProductMatchRule:
    pattern_type = kwargs.get("pattern_type")
    pattern_value = kwargs.get("pattern_value")
    if pattern_type == "normalized":
        kwargs["pattern_value"] = normalize_title(pattern_value)
    if "created_at" not in kwargs or kwargs["created_at"] is None:
        kwargs["created_at"] = datetime.now(timezone.utc)
    return ProductMatchRule(**kwargs)
