"""상품 제목 기반 매칭 테이블 CRUD API."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from api.auth import require_admin, require_moderator, require_viewer
from services.base import get_engine, get_session, managed_session
from services.product_match_rules import ensure_product_match_rules_table, make_rule, normalize_title
from storage.models import Product, ProductMatchRule, UnifiedCategory

router = APIRouter(prefix="/matching-rules", tags=["matching-rules"])


class MatchingRuleIn(BaseModel):
    pattern_type: str = Field(..., pattern="^(exact|normalized|regex)$")
    pattern_value: str = Field(..., min_length=1, max_length=500)
    canonical_category_id: Optional[str] = Field(None, max_length=100)
    canonical_product_id: Optional[int] = Field(None, ge=1)
    trust: int = Field(1, ge=0, le=2)
    created_by: str = Field("admin", min_length=1, max_length=100)

    @field_validator("pattern_value")
    @classmethod
    def validate_pattern_value(cls, v: str, info):
        value = v.strip()
        if not value:
            raise ValueError("pattern_value는 비어 있을 수 없습니다")
        if info.data.get("pattern_type") == "regex":
            re.compile(value)
        return value


class MatchingRuleUpdate(BaseModel):
    pattern_type: Optional[str] = Field(None, pattern="^(exact|normalized|regex)$")
    pattern_value: Optional[str] = Field(None, min_length=1, max_length=500)
    canonical_category_id: Optional[str] = Field(None, max_length=100)
    canonical_product_id: Optional[int] = Field(None, ge=1)
    trust: Optional[int] = Field(None, ge=0, le=2)
    created_by: Optional[str] = Field(None, min_length=1, max_length=100)

    @field_validator("pattern_value")
    @classmethod
    def strip_pattern_value(cls, v: str | None):
        return v.strip() if isinstance(v, str) else v


def _ensure_table() -> None:
    ensure_product_match_rules_table(get_engine())


def _serialize(rule: ProductMatchRule, category_name: str | None = None, product_name: str | None = None) -> dict:
    return {
        "id": rule.id,
        "pattern_type": rule.pattern_type,
        "pattern_value": rule.pattern_value,
        "canonical_category_id": rule.canonical_category_id,
        "canonical_category_name": category_name,
        "canonical_product_id": rule.canonical_product_id,
        "canonical_product_name": product_name,
        "trust": rule.trust,
        "created_by": rule.created_by,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "hit_count": rule.hit_count or 0,
    }


def _validate_refs(session, category_id: str | None, product_id: int | None) -> None:
    if category_id:
        exists = session.execute(select(UnifiedCategory.id).where(UnifiedCategory.id == category_id)).scalar_one_or_none()
        if exists is None:
            raise HTTPException(422, f"통합 카테고리를 찾을 수 없습니다: {category_id}")
    if product_id:
        exists = session.execute(select(Product.id).where(Product.id == product_id)).scalar_one_or_none()
        if exists is None:
            raise HTTPException(422, f"표준 상품을 찾을 수 없습니다: {product_id}")


@router.get("")
def list_matching_rules(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, max_length=200),
    pattern_type: str | None = Query(None, pattern="^(exact|normalized|regex)$"),
    identity: dict = Depends(require_viewer),
):
    _ensure_table()
    session = get_session()
    try:
        q = session.query(ProductMatchRule, UnifiedCategory.name_ko, Product.name.label("product_name"))
        q = q.outerjoin(UnifiedCategory, UnifiedCategory.id == ProductMatchRule.canonical_category_id)
        q = q.outerjoin(Product, Product.id == ProductMatchRule.canonical_product_id)
        if pattern_type:
            q = q.filter(ProductMatchRule.pattern_type == pattern_type)
        if search:
            like = f"%{search.strip()}%"
            normalized_like = f"%{normalize_title(search)}%"
            q = q.filter(or_(
                ProductMatchRule.pattern_value.ilike(like),
                ProductMatchRule.pattern_value.ilike(normalized_like),
                UnifiedCategory.name_ko.ilike(like),
                Product.name.ilike(like),
            ))
        total = q.count()
        rows = (
            q.order_by(ProductMatchRule.trust.desc(), ProductMatchRule.hit_count.desc(), ProductMatchRule.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "items": [_serialize(rule, category_name, product_name) for rule, category_name, product_name in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, -(-total // per_page)),
        }
    finally:
        session.close()


@router.get("/stats")
def matching_rule_stats(identity: dict = Depends(require_viewer)):
    _ensure_table()
    session = get_session()
    try:
        by_type = {k: v for k, v in session.query(ProductMatchRule.pattern_type, func.count(ProductMatchRule.id)).group_by(ProductMatchRule.pattern_type).all()}
        by_trust = {str(k): v for k, v in session.query(ProductMatchRule.trust, func.count(ProductMatchRule.id)).group_by(ProductMatchRule.trust).all()}
        return {
            "total": session.query(func.count(ProductMatchRule.id)).scalar() or 0,
            "by_pattern_type": by_type,
            "by_trust": by_trust,
            "hit_count_sum": session.query(func.coalesce(func.sum(ProductMatchRule.hit_count), 0)).scalar() or 0,
        }
    finally:
        session.close()


@router.post("")
def create_matching_rule(body: MatchingRuleIn, identity: dict = Depends(require_moderator)):
    _ensure_table()
    with managed_session() as session:
        _validate_refs(session, body.canonical_category_id, body.canonical_product_id)
        data = body.model_dump()
        if data["pattern_type"] == "normalized":
            data["pattern_value"] = normalize_title(data["pattern_value"])
        data["created_at"] = datetime.now(timezone.utc)
        rule = make_rule(**data)
        session.add(rule)
        session.flush()
        return _serialize(rule)


@router.put("/{rule_id}")
def update_matching_rule(rule_id: int, body: MatchingRuleUpdate, identity: dict = Depends(require_moderator)):
    _ensure_table()
    with managed_session() as session:
        rule = session.get(ProductMatchRule, rule_id)
        if not rule:
            raise HTTPException(404, "매칭 규칙을 찾을 수 없습니다")
        data = body.model_dump(exclude_unset=True)
        new_category = data.get("canonical_category_id", rule.canonical_category_id)
        new_product = data.get("canonical_product_id", rule.canonical_product_id)
        _validate_refs(session, new_category, new_product)
        if data.get("pattern_type") == "normalized" or (rule.pattern_type == "normalized" and "pattern_value" in data):
            data["pattern_value"] = normalize_title(data.get("pattern_value", rule.pattern_value))
        for key, value in data.items():
            setattr(rule, key, value)
        session.flush()
        return _serialize(rule)


@router.delete("/{rule_id}")
def delete_matching_rule(rule_id: int, identity: dict = Depends(require_admin)):
    _ensure_table()
    with managed_session() as session:
        rule = session.get(ProductMatchRule, rule_id)
        if not rule:
            raise HTTPException(404, "매칭 규칙을 찾을 수 없습니다")
        session.delete(rule)
        return {"ok": True, "deleted": rule_id}
