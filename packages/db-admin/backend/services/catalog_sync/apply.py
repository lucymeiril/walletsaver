"""Import Apply (Phase 2) — 검증 통과분을 실제 DB에 반영.

안전 순서:
  1) validate_import()로 dry-run 검증 → blocking 오류가 있으면 **변경 없이 거부**.
  2) 적용 직전 DB 스냅샷(backup.create_backup) 생성 → snapshot_path 반환.
  3) 단일 트랜잭션에서 categories → match_rules → products 순으로 upsert.
     실패 시 rollback. 스냅샷은 남아 롤백 복구에 쓸 수 있다.

write_mode:
  - upsert: 기존 갱신 + 신규 생성(기본)
  - append_only: 신규만 생성, 기존 행은 건드리지 않음
  - patch: 기존 행만 갱신, 신규 생성 안 함
  - replace_all: 파일을 정본 전체로 보고 파일에 없는 행을 삭제. products는 불가.
    categories 삭제는 참조(상품/규칙/매핑/생존부모) 시 검증에서 차단된다.
products는 기존 상품의 카테고리 필드만 갱신하며 신규 생성하지 않는다.
human(manual/corrected) 보호는 force=True 일 때만 해제된다.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.backup import create_backup
from services.catalog_sync import SCHEMA_VERSION
from services.catalog_sync.validate import (
    ENTITY_ORDER,
    _HUMAN_METHODS,
    _VALID_MODES,
    _VALID_PATTERN_TYPES,
    _effective_action,
    ValidationReport,
    load_export,
    validate_import,
)
from storage.models import (
    MartCategoryMapping,
    Product,
    ProductMatchRule,
    UnifiedCategory,
)


@dataclass
class ApplyResult:
    ok: bool = True
    mode: str = "upsert"
    force: bool = False
    entities: list[str] = field(default_factory=list)
    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    snapshot_path: str | None = None
    file_hash: str | None = None
    error_message: str | None = None
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "force": self.force,
            "entities": self.entities,
            "counts": self.counts,
            "snapshot_path": self.snapshot_path,
            "file_hash": self.file_hash,
            "error_message": self.error_message,
            "validation": self.validation,
        }


def combined_file_hash(export_dir: Path | str, entities: list[str], *, mode: str, force: bool) -> str:
    """멱등성 해시 = sha256(엔티티 파일 bytes + mode + force + schema_version)."""
    export_dir = Path(export_dir)
    h = hashlib.sha256()
    for entity in entities:
        fpath = export_dir / f"{entity}.jsonl"
        if fpath.exists():
            h.update(entity.encode("utf-8"))
            h.update(fpath.read_bytes())
    h.update(f"|{mode}|{force}|{SCHEMA_VERSION}".encode("utf-8"))
    return h.hexdigest()


def apply_import(
    session: Session,
    export_dir: Path | str,
    *,
    entities: list[str] | None = None,
    mode: str = "upsert",
    force: bool = False,
    database_url: str,
    make_snapshot: bool = True,
) -> ApplyResult:
    if mode not in _VALID_MODES:
        raise ValueError(
            f"지원하지 않는 write_mode: {mode!r} (허용: {sorted(_VALID_MODES)})"
        )

    report: ValidationReport = validate_import(
        session, export_dir, entities=entities, mode=mode, force=force
    )
    result = ApplyResult(mode=mode, force=force, entities=report.entities,
                         validation=report.to_dict())
    result.file_hash = combined_file_hash(export_dir, report.entities, mode=mode, force=force)

    if not report.ok:
        result.ok = False
        result.error_message = "검증 실패로 적용 거부: " + "; ".join(report.errors[:5])
        return result

    if make_snapshot:
        result.snapshot_path = create_backup(database_url, reason="catalog-sync-apply")

    bundle = load_export(export_dir)
    file_cat_ids = {r.get("id") for r in bundle.rows.get("categories", []) if r.get("id")}
    file_rule_keys = {
        (r.get("pattern_type"), r.get("pattern_value"))
        for r in bundle.rows.get("match_rules", [])
        if r.get("pattern_type") and r.get("pattern_value")
    }
    try:
        if "categories" in report.entities:
            result.counts["categories"] = _apply_categories(
                session, bundle.rows.get("categories", []), mode
            )
        if "match_rules" in report.entities:
            result.counts["match_rules"] = _apply_match_rules(
                session, bundle.rows.get("match_rules", []), mode
            )
        if "products" in report.entities:
            result.counts["products"] = _apply_products(
                session, bundle.rows.get("products", []), force, mode
            )
        if mode == "replace_all":
            if "match_rules" in report.entities:
                result.counts["match_rules"]["deleted"] = _delete_missing_match_rules(
                    session, file_rule_keys
                )
            if "categories" in report.entities:
                result.counts["categories"]["deleted"] = _delete_missing_categories(
                    session, file_cat_ids
                )
        session.commit()
    except Exception as e:  # noqa: BLE001
        session.rollback()
        result.ok = False
        result.error_message = f"적용 중 오류(롤백됨): {e}"
        return result
    return result


# ── 엔티티별 적용 ─────────────────────────────────────────────────────────────

def _apply_categories(session: Session, rows: list[dict[str, Any]], mode: str = "upsert") -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped_mode": 0, "deleted": 0}
    existing = {c.id: c for c in session.scalars(select(UnifiedCategory)).all()}
    # 부모가 먼저 들어가도록 level 오름차순 정렬(자기참조 FK 보호)
    for r in sorted(rows, key=lambda x: (x.get("level") or 0, x.get("id") or "")):
        cid = r["id"]
        cur = existing.get(cid)
        if cur is None:
            if _effective_action("create", mode) != "create":
                counts["skipped_mode"] += 1
                continue
            obj = UnifiedCategory(
                id=cid,
                parent_id=r.get("parent_id"),
                slug=r.get("slug") or cid.split(".")[-1],
                name_ko=r["name_ko"],
                level=r.get("level") if r.get("level") is not None else 0,
                sort_order=r.get("sort_order") if r.get("sort_order") is not None else 0,
                source_origin=r.get("source_origin"),
            )
            session.add(obj)
            session.flush()
            existing[cid] = obj
            counts["created"] += 1
        else:
            changed = False
            pending: dict[str, Any] = {}
            for fld in ("parent_id", "name_ko", "source_origin"):
                if fld in r and r.get(fld) != getattr(cur, fld):
                    pending[fld] = r.get(fld); changed = True
            for fld in ("slug", "level", "sort_order"):
                if r.get(fld) is not None and r.get(fld) != getattr(cur, fld):
                    pending[fld] = r.get(fld); changed = True
            if not changed:
                counts["unchanged"] += 1
                continue
            if _effective_action("update", mode) != "update":
                counts["skipped_mode"] += 1
                continue
            for fld, val in pending.items():
                setattr(cur, fld, val)
            session.flush()
            counts["updated"] += 1
    return counts


def _delete_missing_categories(session: Session, file_cat_ids: set[str]) -> int:
    """replace_all: 파일에 없는 카테고리를 깊은 자식부터 삭제한다.

    검증 단계에서 참조(Product/MatchRule/MartCategoryMapping/생존부모)가 있으면 이미
    차단되었으므로, 여기서는 ORM cascade를 피해 id 기준 bulk delete만 수행한다.
    """
    rows = session.execute(
        select(UnifiedCategory.id, UnifiedCategory.parent_id, UnifiedCategory.level)
    ).all()
    to_delete = [(cid, lvl) for (cid, _pid, lvl) in rows if cid not in file_cat_ids]
    # 깊은 레벨(자식)부터 삭제
    to_delete.sort(key=lambda x: (x[1] if x[1] is not None else 0), reverse=True)
    deleted = 0
    for cid, _lvl in to_delete:
        session.execute(
            UnifiedCategory.__table__.delete().where(UnifiedCategory.id == cid)
        )
        deleted += 1
    return deleted


def _apply_match_rules(session: Session, rows: list[dict[str, Any]], mode: str = "upsert") -> dict[str, int]:
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped_mode": 0, "deleted": 0}
    existing = {
        (r.pattern_type, r.pattern_value): r
        for r in session.scalars(select(ProductMatchRule)).all()
    }
    db_product_ids = {pid for (pid,) in session.execute(select(Product.id)).all()}
    for r in rows:
        ptype, pval = r.get("pattern_type"), r.get("pattern_value")
        if ptype not in _VALID_PATTERN_TYPES or not pval:
            continue
        cpid = r.get("canonical_product_id")
        if cpid is not None and cpid not in db_product_ids:
            cpid = None  # DB-local PK가 현 DB에 없으면 무시
        cat = r.get("canonical_category_id")
        cur = existing.get((ptype, pval))
        if cur is None:
            if _effective_action("create", mode) != "create":
                counts["skipped_mode"] += 1
                continue
            obj = ProductMatchRule(
                pattern_type=ptype,
                pattern_value=pval,
                canonical_category_id=cat,
                canonical_product_id=cpid,
                trust=r.get("trust") if r.get("trust") is not None else 1,
                created_by=r.get("created_by") or "catalog-sync",
                hit_count=r.get("hit_count") or 0,
            )
            session.add(obj)
            existing[(ptype, pval)] = obj
            counts["created"] += 1
        else:
            changed = False
            new_cat = cur.canonical_category_id != cat
            new_cpid = cur.canonical_product_id != cpid
            new_trust = r.get("trust") is not None and cur.trust != r.get("trust")
            changed = new_cat or new_cpid or new_trust
            if not changed:
                counts["unchanged"] += 1
                continue
            if _effective_action("update", mode) != "update":
                counts["skipped_mode"] += 1
                continue
            if new_cat:
                cur.canonical_category_id = cat
            if new_cpid:
                cur.canonical_product_id = cpid
            if new_trust:
                cur.trust = r.get("trust")
            counts["updated"] += 1
    session.flush()
    return counts


def _delete_missing_match_rules(session: Session, file_rule_keys: set[tuple[str, str]]) -> int:
    """replace_all: 파일에 없는 매칭규칙을 삭제한다(인바운드 FK 없음 → 안전)."""
    rules = session.scalars(select(ProductMatchRule)).all()
    deleted = 0
    for rule in rules:
        if (rule.pattern_type, rule.pattern_value) not in file_rule_keys:
            session.delete(rule)
            deleted += 1
    session.flush()
    return deleted


def _apply_products(session: Session, rows: list[dict[str, Any]], force: bool, mode: str = "upsert") -> dict[str, int]:
    counts = {"updated": 0, "unchanged": 0, "skipped": 0, "protected": 0, "skipped_mode": 0}
    existing = {p.id: p for p in session.scalars(select(Product)).all()}
    now = datetime.now(timezone.utc)
    for r in rows:
        pid = r.get("id")
        cur = existing.get(pid)
        if cur is None:
            counts["skipped"] += 1
            continue
        new_cat = r.get("unified_category_id")
        if new_cat == cur.unified_category_id:
            counts["unchanged"] += 1
            continue
        if (cur.categorization_method in _HUMAN_METHODS) and not force:
            counts["protected"] += 1
            continue
        if mode == "append_only":
            counts["skipped_mode"] += 1
            continue
        cur.unified_category_id = new_cat
        if r.get("categorization_method") is not None:
            cur.categorization_method = r.get("categorization_method")
        if r.get("categorization_confidence") is not None:
            cur.categorization_confidence = r.get("categorization_confidence")
        cur.updated_at = now
        counts["updated"] += 1
    session.flush()
    return counts
