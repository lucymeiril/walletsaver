"""Round R G2 unified category tree and mart mapping service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, selectinload

from storage.models import MartCategoryMapping, Product, UnifiedCategory

MARTS = ("emart", "homeplus", "lottemart", "costco")
TRUST_RANK = {"auto-aggregate": 0, "external-ai": 1, "human": 2}


def _category_to_dict(category: UnifiedCategory) -> dict[str, Any]:
    return {
        "id": category.id,
        "parent_id": category.parent_id,
        "slug": category.slug,
        "name_ko": category.name_ko,
        "level": category.level,
        "sort_order": category.sort_order,
        "source_origin": category.source_origin,
        "children": [_category_to_dict(child) for child in sorted(category.children, key=lambda c: (c.sort_order, c.id))],
    }


def get_unified_tree(session: Session) -> list[dict[str, Any]]:
    roots = session.scalars(
        select(UnifiedCategory)
        .where(UnifiedCategory.parent_id.is_(None))
        .options(selectinload(UnifiedCategory.children).selectinload(UnifiedCategory.children))
        .order_by(UnifiedCategory.sort_order, UnifiedCategory.id)
    ).all()
    return [_category_to_dict(root) for root in roots]


def upsert_mapping(
    session: Session,
    *,
    mart: str,
    mart_native_id: str,
    mart_native_path: str | None,
    unified_category_id: str,
    trust: str,
    confidence: float,
    decided_by: str | None,
) -> tuple[MartCategoryMapping, str]:
    if mart not in MARTS:
        raise ValueError(f"지원하지 않는 mart: {mart}")
    if trust not in TRUST_RANK:
        raise ValueError(f"지원하지 않는 trust: {trust}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence는 0.0~1.0 범위여야 합니다.")
    category = session.get(UnifiedCategory, unified_category_id)
    if category is None:
        raise ValueError(f"통합 카테고리를 찾을 수 없습니다: {unified_category_id}")

    existing = session.scalar(
        select(MartCategoryMapping).where(
            MartCategoryMapping.mart == mart,
            MartCategoryMapping.mart_native_id == mart_native_id,
        )
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        mapping = MartCategoryMapping(
            mart=mart,
            mart_native_id=mart_native_id,
            mart_native_path=mart_native_path,
            unified_category_id=unified_category_id,
            trust=trust,
            confidence=confidence,
            decided_by=decided_by,
            created_at=now,
            updated_at=now,
        )
        session.add(mapping)
        return mapping, "created"

    if TRUST_RANK[trust] < TRUST_RANK[existing.trust]:
        return existing, "conflict"

    existing.mart_native_path = mart_native_path or existing.mart_native_path
    existing.unified_category_id = unified_category_id
    existing.trust = trust
    existing.confidence = confidence
    existing.decided_by = decided_by
    existing.updated_at = now
    return existing, "updated"


def list_mappings(session: Session, mart: str | None = None) -> list[dict[str, Any]]:
    if mart is not None and mart not in MARTS:
        raise ValueError(f"지원하지 않는 mart: {mart}")

    product_stmt = (
        select(
            Product.mart,
            Product.mart_native_category_id,
            func.max(Product.mart_native_category_path),
            func.count(Product.id),
        )
        .where(Product.mart_native_category_id.is_not(None))
        .group_by(Product.mart, Product.mart_native_category_id)
    )
    if mart is not None:
        product_stmt = product_stmt.where(Product.mart == mart)
    native_rows = session.execute(product_stmt).all()

    mapping_stmt = select(MartCategoryMapping, UnifiedCategory).join(UnifiedCategory)
    if mart is not None:
        mapping_stmt = mapping_stmt.where(MartCategoryMapping.mart == mart)
    mapping_rows = session.execute(mapping_stmt).all()
    by_key = {(m.mart, m.mart_native_id): (m, c) for m, c in mapping_rows}

    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for m, native_id, native_path, product_count in native_rows:
        if not m or not native_id:
            continue
        key = (m, native_id)
        seen.add(key)
        mapping_pair = by_key.get(key)
        mapping = mapping_pair[0] if mapping_pair else None
        category = mapping_pair[1] if mapping_pair else None
        result.append(_mapping_dict(m, native_id, native_path, int(product_count), mapping, category))

    for key, (mapping, category) in by_key.items():
        if key in seen:
            continue
        result.append(_mapping_dict(mapping.mart, mapping.mart_native_id, mapping.mart_native_path, 0, mapping, category))

    return sorted(result, key=lambda r: (r["review_status"] != "needs_review", r["mart"], r["mart_native_path"] or "", r["mart_native_id"]))


def _mapping_dict(
    mart: str,
    native_id: str,
    native_path: str | None,
    product_count: int,
    mapping: MartCategoryMapping | None,
    category: UnifiedCategory | None,
) -> dict[str, Any]:
    return {
        "id": mapping.id if mapping else None,
        "mart": mart,
        "mart_native_id": native_id,
        "mart_native_path": native_path,
        "product_count": product_count,
        "unified_category_id": mapping.unified_category_id if mapping else None,
        "unified_category_name_ko": category.name_ko if category else None,
        "trust": mapping.trust if mapping else None,
        "confidence": mapping.confidence if mapping else None,
        "decided_by": mapping.decided_by if mapping else None,
        "review_status": "mapped" if mapping else "needs_review",
    }
