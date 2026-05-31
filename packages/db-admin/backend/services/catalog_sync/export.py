"""정본 카탈로그 Export — scope 옵션 지원.

엔티티를 JSONL로 내보내고 manifest.json을 함께 생성한다.
  - categories  : unified_categories 트리          (scope: all | subtree)
  - match_rules : product_match_rules 매칭표(정본)  (scope: all | by_category | unmatched)
  - products    : products 분류 대상                (scope: all | unclassified | by_category | by_date_range)
  - mappings    : mart_category_mappings (보조/휴면) (scope: all | by_mart | needs_review)

정본 매칭 테이블은 product_match_rules(이름패턴→통합카테고리)다. mart_category_mappings는
상품에 mart_native 필드가 없어 현 데이터엔 적용 불가하므로 보조 export로만 유지한다.

비파괴(read-only). DB를 변경하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from services.catalog_sync import SCHEMA_VERSION
from storage.models import MartCategoryMapping, Product, ProductMatchRule, UnifiedCategory

ENTITIES = ("categories", "match_rules", "products", "mappings")


@dataclass
class ExportResult:
    out_dir: str
    schema_version: str
    created_at: str
    entities: list[str]
    database_fingerprint: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    scope: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "out_dir": self.out_dir,
            "entities": self.entities,
            "database_fingerprint": self.database_fingerprint,
            "scope": self.scope,
            "counts": self.counts,
            "files": self.files,
        }


def db_fingerprint(session: Session) -> dict[str, Any]:
    """source DB를 식별하는 지문.

    product id는 DB-local PK라 다른 DB로 import하면 엉뚱한 상품을 가리킨다.
    import 시 이 지문이 일치해야 id 기반 same-DB upsert를 허용한다(불일치 시 preview-only).
    """
    try:
        rev = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception:
        rev = None
    prod_count = session.execute(select(func.count(Product.id))).scalar() or 0
    max_prod_id = session.execute(select(func.max(Product.id))).scalar() or 0
    cat_count = session.execute(select(func.count(UnifiedCategory.id))).scalar() or 0
    rule_count = session.execute(select(func.count(ProductMatchRule.id))).scalar() or 0
    sig_src = f"{rev}|{prod_count}|{max_prod_id}|{cat_count}|{rule_count}"
    return {
        "alembic_revision": rev,
        "product_count": int(prod_count),
        "max_product_id": int(max_prod_id),
        "category_count": int(cat_count),
        "match_rule_count": int(rule_count),
        "signature": hashlib.sha256(sig_src.encode("utf-8")).hexdigest(),
    }


# ── 직렬화 ────────────────────────────────────────────────────────────────────

def _category_row(c: UnifiedCategory) -> dict[str, Any]:
    return {
        "id": c.id,
        "parent_id": c.parent_id,
        "slug": c.slug,
        "name_ko": c.name_ko,
        "level": c.level,
        "sort_order": c.sort_order,
        "source_origin": c.source_origin,
    }


def _mapping_row(m: MartCategoryMapping) -> dict[str, Any]:
    return {
        "mart": m.mart,
        "mart_native_id": m.mart_native_id,
        "mart_native_path": m.mart_native_path,
        "unified_category_id": m.unified_category_id,
        "trust": m.trust,
        "confidence": m.confidence,
        "decided_by": m.decided_by,
    }


def _match_rule_row(r: ProductMatchRule) -> dict[str, Any]:
    """정본 매칭 테이블. 자연키 = (pattern_type, pattern_value).

    canonical_product_id는 DB-local PK라 import 시 행단위 검증 대상이다.
    """
    return {
        "pattern_type": r.pattern_type,
        "pattern_value": r.pattern_value,
        "canonical_category_id": r.canonical_category_id,
        "canonical_product_id": r.canonical_product_id,
        "trust": r.trust,
        "created_by": r.created_by,
        "hit_count": r.hit_count,
    }


def _product_row(p: Product) -> dict[str, Any]:
    attrs = p.attributes if isinstance(p.attributes, dict) else {}
    return {
        "id": p.id,
        "raw_name": p.name,
        "normalized_name": p.display_name or p.name_core or p.name,
        "brand": p.brand,
        "pack_qty": p.pack_qty,
        "pack_unit": p.pack_unit or p.unit,
        "pack_count": attrs.get("pack_count"),
        "canon_hash": p.canon_hash,
        "mart": p.mart,
        "mart_native_code": p.mart_native_code,
        "mart_native_category_id": p.mart_native_category_id,
        "mart_native_category_path": p.mart_native_category_path,
        "unified_category_id": p.unified_category_id,
        "categorization_method": p.categorization_method,
        "categorization_confidence": p.categorization_confidence,
        "canonical_url": p.canonical_url,
    }


# ── scope별 조회 ──────────────────────────────────────────────────────────────

def _descendant_ids(session: Session, root_id: str) -> set[str]:
    """root_id와 그 모든 후손 카테고리 id 집합."""
    all_cats = session.execute(select(UnifiedCategory.id, UnifiedCategory.parent_id)).all()
    children: dict[str, list[str]] = {}
    for cid, pid in all_cats:
        children.setdefault(pid, []).append(cid)
    result: set[str] = set()
    stack = [root_id]
    while stack:
        cur = stack.pop()
        if cur in result:
            continue
        result.add(cur)
        stack.extend(children.get(cur, []))
    return result


def _query_categories(session: Session, scope: dict[str, Any]) -> list[dict[str, Any]]:
    mode = scope.get("mode", "all")
    stmt = select(UnifiedCategory).order_by(UnifiedCategory.level, UnifiedCategory.sort_order, UnifiedCategory.id)
    if mode == "subtree":
        root_id = scope.get("root_id")
        if not root_id:
            raise ValueError("categories subtree scope에는 root_id가 필요합니다.")
        ids = _descendant_ids(session, root_id)
        cats = [c for c in session.scalars(stmt).all() if c.id in ids]
        return [_category_row(c) for c in cats]
    return [_category_row(c) for c in session.scalars(stmt).all()]


def _query_mappings(session: Session, scope: dict[str, Any]) -> list[dict[str, Any]]:
    mode = scope.get("mode", "all")
    if mode == "needs_review":
        # 상품에 등장하는 (mart, native_id) 중 매핑이 없는 것
        native = session.execute(
            select(Product.mart, Product.mart_native_category_id, func.max(Product.mart_native_category_path))
            .where(Product.mart_native_category_id.is_not(None))
            .group_by(Product.mart, Product.mart_native_category_id)
        ).all()
        mapped = {
            (m.mart, m.mart_native_id)
            for m in session.scalars(select(MartCategoryMapping)).all()
        }
        rows: list[dict[str, Any]] = []
        for mart, native_id, native_path in native:
            if mart and native_id and (mart, native_id) not in mapped:
                rows.append({
                    "mart": mart,
                    "mart_native_id": native_id,
                    "mart_native_path": native_path,
                    "unified_category_id": None,
                    "trust": None,
                    "confidence": None,
                    "decided_by": None,
                })
        return rows
    stmt = select(MartCategoryMapping).order_by(MartCategoryMapping.mart, MartCategoryMapping.mart_native_id)
    if mode == "by_mart":
        mart = scope.get("mart")
        if not mart:
            raise ValueError("mappings by_mart scope에는 mart가 필요합니다.")
        stmt = stmt.where(MartCategoryMapping.mart == mart)
    elif mode != "all":
        raise ValueError(f"지원하지 않는 mappings scope: {mode}")
    return [_mapping_row(m) for m in session.scalars(stmt).all()]


def _query_match_rules(session: Session, scope: dict[str, Any]) -> list[dict[str, Any]]:
    mode = scope.get("mode", "all")
    stmt = select(ProductMatchRule).order_by(
        ProductMatchRule.pattern_type, ProductMatchRule.pattern_value, ProductMatchRule.id
    )
    if mode == "by_category":
        category_id = scope.get("category_id")
        if not category_id:
            raise ValueError("match_rules by_category scope에는 category_id가 필요합니다.")
        ids = _descendant_ids(session, category_id)
        stmt = stmt.where(ProductMatchRule.canonical_category_id.in_(ids))
    elif mode == "unmatched":
        stmt = stmt.where(ProductMatchRule.canonical_category_id.is_(None))
    elif mode != "all":
        raise ValueError(f"지원하지 않는 match_rules scope: {mode}")
    return [_match_rule_row(r) for r in session.scalars(stmt).all()]


def _query_products(session: Session, scope: dict[str, Any]) -> list[dict[str, Any]]:
    mode = scope.get("mode", "all")
    stmt = select(Product).order_by(Product.id)
    if mode == "unclassified":
        stmt = stmt.where(Product.unified_category_id.is_(None))
    elif mode == "by_mart":
        mart = scope.get("mart")
        if not mart:
            raise ValueError("products by_mart scope에는 mart가 필요합니다.")
        stmt = stmt.where(Product.mart == mart)
    elif mode == "by_category":
        category_id = scope.get("category_id")
        if not category_id:
            raise ValueError("products by_category scope에는 category_id가 필요합니다.")
        ids = _descendant_ids(session, category_id)
        stmt = stmt.where(Product.unified_category_id.in_(ids))
    elif mode == "by_date_range":
        since = scope.get("since")
        until = scope.get("until")
        if since:
            stmt = stmt.where(Product.updated_at >= _parse_dt(since))
        if until:
            stmt = stmt.where(Product.updated_at <= _parse_dt(until))
    elif mode != "all":
        raise ValueError(f"지원하지 않는 products scope: {mode}")
    return [_product_row(p) for p in session.scalars(stmt).all()]


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


_QUERY = {
    "categories": _query_categories,
    "match_rules": _query_match_rules,
    "products": _query_products,
    "mappings": _query_mappings,
}


# ── 쓰기 ──────────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, sort_keys=True)
            f.write(line + "\n")
            h.update(line.encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def export_catalog(
    out_dir: Path | str,
    session: Session,
    *,
    entities: list[str],
    scopes: dict[str, dict[str, Any]] | None = None,
) -> ExportResult:
    """선택한 엔티티를 scope에 맞춰 JSONL + manifest.json으로 내보낸다.

    entities: ["categories", "mappings", "products"] 중 1개 이상
    scopes:   {entity: {"mode": ..., ...}}  (없으면 mode=all)
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scopes = scopes or {}

    invalid = [e for e in entities if e not in ENTITIES]
    if invalid:
        raise ValueError(f"지원하지 않는 엔티티: {invalid} (허용: {list(ENTITIES)})")
    if not entities:
        raise ValueError("엔티티를 1개 이상 선택해야 합니다.")

    result = ExportResult(
        out_dir=str(out_dir),
        schema_version=SCHEMA_VERSION,
        created_at=datetime.now(timezone.utc).isoformat(),
        entities=list(entities),
        database_fingerprint=db_fingerprint(session),
    )

    for entity in entities:
        scope = scopes.get(entity, {"mode": "all"})
        rows = _QUERY[entity](session, scope)
        filename = f"{entity}.jsonl"
        file_hash = _write_jsonl(out_dir / filename, rows)
        result.counts[entity] = len(rows)
        result.scope[entity] = scope
        result.files[entity] = {
            "name": filename,
            "path": str(out_dir / filename),
            "rows": len(rows),
            "sha256": file_hash,
        }

    manifest = result.to_dict()
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
