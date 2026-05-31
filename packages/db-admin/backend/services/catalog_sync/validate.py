"""Import dry-run 검증 — DB를 변경하지 않고 export 번들을 검사한다.

흐름: load_export() 로 manifest + JSONL 로드(파일 해시 검증) → validate_import()
가 정본 불변식·FK·human 보호·same-DB 지문을 점검하고 diff 리포트를 만든다.

핵심 안전장치(rubber-duck 검토 반영):
  - products는 **기존 상품의 카테고리 필드 갱신만** 한다(신규 생성 금지). id가 DB에 없으면 skipped.
  - products는 manifest의 database_fingerprint가 현 DB와 일치할 때만 id 기반 apply 허용.
    불일치 시 preview-only(error)로 강등한다.
  - human 보호: categorization_method ∈ {manual, corrected}는 force 없이 덮어쓰지 않는다.
  - match_rules.canonical_product_id는 DB-local PK라 존재 검증한다.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.catalog_sync import SCHEMA_VERSION
from services.catalog_sync.export import db_fingerprint
from storage.models import (
    MartCategoryMapping,
    Product,
    ProductMatchRule,
    UnifiedCategory,
)

ENTITY_ORDER = ("categories", "match_rules", "products")
_VALID_PATTERN_TYPES = {"exact", "normalized", "regex"}
_HUMAN_METHODS = {"manual", "corrected"}
_VALID_MODES = {"upsert", "append_only", "patch", "replace_all"}


def _effective_action(raw: str, mode: str) -> str:
    """import write_mode에 따라 행 단위 동작(raw)을 실제 버킷으로 매핑한다.

    raw ∈ {create, update}. mode가 막는 동작은 'skipped_mode'로 강등된다.
    - upsert / replace_all: create→create, update→update
    - append_only: 신규만 허용 → update는 skipped_mode
    - patch: 기존 갱신만 허용 → create는 skipped_mode
    """
    if mode == "append_only" and raw == "update":
        return "skipped_mode"
    if mode == "patch" and raw == "create":
        return "skipped_mode"
    return raw


@dataclass
class ExportBundle:
    manifest: dict[str, Any]
    rows: dict[str, list[dict[str, Any]]]


@dataclass
class EntityDiff:
    create: int = 0
    update: int = 0
    unchanged: int = 0
    skipped: int = 0          # products: DB에 id 없음 (생성 금지)
    skipped_mode: int = 0     # write_mode가 막아 적용 안 되는 변경(append_only/patch)
    delete: int = 0           # replace_all: 파일에 없어 삭제될 행
    protected: int = 0        # human 보호로 변경 차단
    invalid: int = 0          # 검증 실패 행
    samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "create": self.create,
            "update": self.update,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "skipped_mode": self.skipped_mode,
            "delete": self.delete,
            "protected": self.protected,
            "invalid": self.invalid,
            "samples": self.samples,
        }


@dataclass
class ValidationReport:
    ok: bool = True
    schema_version: str = SCHEMA_VERSION
    same_database: bool = False
    fingerprint_expected: dict[str, Any] = field(default_factory=dict)
    fingerprint_actual: dict[str, Any] = field(default_factory=dict)
    entities: list[str] = field(default_factory=list)
    mode: str = "upsert"
    force: bool = False
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diff: dict[str, EntityDiff] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.ok = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "schema_version": self.schema_version,
            "same_database": self.same_database,
            "fingerprint_expected": self.fingerprint_expected,
            "fingerprint_actual": self.fingerprint_actual,
            "entities": self.entities,
            "mode": self.mode,
            "force": self.force,
            "errors": self.errors,
            "warnings": self.warnings,
            "diff": {k: v.to_dict() for k, v in self.diff.items()},
        }


# ── 로드 ──────────────────────────────────────────────────────────────────────

def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_export(export_dir: Path | str) -> ExportBundle:
    """manifest.json + 엔티티 JSONL 로드. 파일 해시를 manifest와 대조한다."""
    export_dir = Path(export_dir)
    manifest_path = export_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json 없음: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    rows: dict[str, list[dict[str, Any]]] = {}
    files = manifest.get("files", {})
    for entity in manifest.get("entities", []):
        info = files.get(entity, {})
        fname = info.get("name", f"{entity}.jsonl")
        fpath = export_dir / fname
        if not fpath.exists():
            raise FileNotFoundError(f"{entity} 파일 없음: {fpath}")
        expected = info.get("sha256")
        if expected and _file_sha256(fpath) != expected:
            raise ValueError(f"{entity} 파일 해시 불일치(손상/변조): {fpath}")
        parsed: list[dict[str, Any]] = []
        with fpath.open(encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"{entity} {ln}행 JSON 파싱 실패: {e}") from e
        rows[entity] = parsed
    return ExportBundle(manifest=manifest, rows=rows)


# ── 검증 ──────────────────────────────────────────────────────────────────────

def validate_import(
    session: Session,
    export_dir: Path | str,
    *,
    entities: list[str] | None = None,
    mode: str = "upsert",
    force: bool = False,
) -> ValidationReport:
    """비파괴 dry-run 검증. DB를 변경하지 않는다."""
    bundle = load_export(export_dir)
    report = ValidationReport(mode=mode, force=force)
    if mode not in _VALID_MODES:
        report.add_error(f"지원하지 않는 write_mode: {mode!r} (허용: {sorted(_VALID_MODES)})")
    report.schema_version = bundle.manifest.get("schema_version", "")
    if report.schema_version != SCHEMA_VERSION:
        report.add_error(
            f"schema_version 불일치: 파일={report.schema_version!r} 코드={SCHEMA_VERSION!r}"
        )

    selected = entities or [e for e in ENTITY_ORDER if e in bundle.rows]
    report.entities = [e for e in ENTITY_ORDER if e in selected]

    # replace_all은 상품을 포함할 수 없다(상품은 생성·삭제하지 않음).
    if mode == "replace_all" and "products" in report.entities:
        report.add_error(
            "replace_all은 products를 포함할 수 없습니다. "
            "categories/match_rules만 담긴 번들을 사용하세요."
        )

    report.fingerprint_expected = bundle.manifest.get("database_fingerprint", {})
    report.fingerprint_actual = db_fingerprint(session)
    report.same_database = (
        report.fingerprint_expected.get("signature") == report.fingerprint_actual.get("signature")
    )

    # DB의 카테고리 id 집합 + 파일에서 추가/변경될 카테고리 id → FK 해석용 통합 집합
    db_cat_ids = {c for (c,) in session.execute(select(UnifiedCategory.id)).all()}
    file_cat_ids = {r.get("id") for r in bundle.rows.get("categories", []) if r.get("id")}
    known_cat_ids = db_cat_ids | file_cat_ids

    if "categories" in report.entities:
        report.diff["categories"] = _validate_categories(
            session, bundle.rows.get("categories", []), db_cat_ids, file_cat_ids, report, mode
        )
    if "match_rules" in report.entities:
        report.diff["match_rules"] = _validate_match_rules(
            session, bundle.rows.get("match_rules", []), known_cat_ids, report, mode
        )
    if "products" in report.entities:
        report.diff["products"] = _validate_products(
            session, bundle.rows.get("products", []), known_cat_ids, report, force, mode
        )

    if mode == "replace_all":
        _validate_replace_all_deletions(
            session, report, db_cat_ids, file_cat_ids, bundle
        )
    return report


def _validate_replace_all_deletions(
    session: Session,
    report: ValidationReport,
    db_cat_ids: set[str],
    file_cat_ids: set[str],
    bundle: ExportBundle,
) -> None:
    """replace_all에서 파일에 없는 행의 삭제를 계획하고, 참조되는 카테고리는 차단한다.

    카테고리 삭제는 strict two-step: 현 DB의 Product/MatchRule/MartCategoryMapping/생존
    카테고리(parent_id)가 삭제 대상을 참조하면 전체 작업을 차단한다(자동 재배치·해제 금지).
    match_rules 삭제는 인바운드 FK가 없어 안전하다.
    """
    if "categories" in report.entities:
        diff = report.diff.get("categories") or EntityDiff()
        to_delete = db_cat_ids - file_cat_ids
        diff.delete = len(to_delete)
        if to_delete:
            blocked: dict[str, list[str]] = {}

            def _add(cat_id: str, why: str) -> None:
                if cat_id in to_delete:
                    blocked.setdefault(cat_id, [])
                    if why not in blocked[cat_id]:
                        blocked[cat_id].append(why)

            for (cid,) in session.execute(
                select(Product.unified_category_id)
                .where(Product.unified_category_id.in_(to_delete))
                .distinct()
            ).all():
                _add(cid, "products")
            for (cid,) in session.execute(
                select(ProductMatchRule.canonical_category_id)
                .where(ProductMatchRule.canonical_category_id.in_(to_delete))
                .distinct()
            ).all():
                _add(cid, "match_rules")
            for (cid,) in session.execute(
                select(MartCategoryMapping.unified_category_id)
                .where(MartCategoryMapping.unified_category_id.in_(to_delete))
                .distinct()
            ).all():
                _add(cid, "mart_category_mappings")
            # 생존(=파일에 남는) 카테고리가 삭제 대상을 부모로 가지면 차단
            for cid, pid in session.execute(
                select(UnifiedCategory.id, UnifiedCategory.parent_id)
            ).all():
                if cid in file_cat_ids and pid in to_delete:
                    _add(pid, f"부모참조({cid})")
            if blocked:
                preview = "; ".join(
                    f"{k}←{','.join(v)}" for k, v in list(blocked.items())[:10]
                )
                report.add_error(
                    f"replace_all: 삭제 대상 카테고리가 참조 중이라 차단됨({len(blocked)}건). "
                    f"먼저 상품/규칙/매핑을 이전한 뒤 다시 시도하세요 — {preview}"
                )
            for cid in sorted(to_delete):
                _sample(diff, {"id": cid, "action": "delete",
                               "blocked_by": blocked.get(cid)})
        report.diff["categories"] = diff

    if "match_rules" in report.entities:
        diff = report.diff.get("match_rules") or EntityDiff()
        db_keys = {
            (r.pattern_type, r.pattern_value)
            for r in session.scalars(select(ProductMatchRule)).all()
        }
        file_keys = {
            (r.get("pattern_type"), r.get("pattern_value"))
            for r in bundle.rows.get("match_rules", [])
            if r.get("pattern_type") and r.get("pattern_value")
        }
        to_delete = db_keys - file_keys
        diff.delete = len(to_delete)
        for key in list(to_delete)[:20]:
            _sample(diff, {"key": list(key), "action": "delete"})
        report.diff["match_rules"] = diff


def _sample(diff: EntityDiff, payload: dict[str, Any], limit: int = 20) -> None:
    if len(diff.samples) < limit:
        diff.samples.append(payload)


def _validate_categories(
    session: Session,
    rows: list[dict[str, Any]],
    db_cat_ids: set[str],
    file_cat_ids: set[str],
    report: ValidationReport,
    mode: str = "upsert",
) -> EntityDiff:
    diff = EntityDiff()
    existing = {
        c.id: c for c in session.scalars(select(UnifiedCategory)).all()
    }
    # 병합 부모 맵(DB ∪ 파일 override)으로 사이클 검사
    parent_map: dict[str, str | None] = {cid: c.parent_id for cid, c in existing.items()}
    seen_ids: set[str] = set()
    for r in rows:
        cid = r.get("id")
        if not cid:
            diff.invalid += 1
            report.add_error("categories: id 없는 행")
            continue
        if cid in seen_ids:
            diff.invalid += 1
            report.add_error(f"categories: 파일 내 중복 id {cid}")
            continue
        seen_ids.add(cid)
        if not r.get("name_ko"):
            diff.invalid += 1
            report.add_error(f"categories[{cid}]: name_ko 필수")
            continue
        pid = r.get("parent_id")
        if pid is not None and pid not in (db_cat_ids | file_cat_ids):
            diff.invalid += 1
            report.add_error(f"categories[{cid}]: parent_id {pid} 없음")
            continue
        parent_map[cid] = pid

    # 사이클 검사 (파일에 등장한 노드 기준)
    for cid in seen_ids:
        walker, hops = cid, 0
        chain: set[str] = set()
        while walker is not None and hops <= len(parent_map) + 1:
            if walker in chain:
                diff.invalid += 1
                report.add_error(f"categories[{cid}]: 부모 사이클 감지")
                break
            chain.add(walker)
            walker = parent_map.get(walker)
            hops += 1

    # create/update/unchanged 집계
    for r in rows:
        cid = r.get("id")
        if not cid or cid not in seen_ids:
            continue
        cur = existing.get(cid)
        if cur is None:
            eff = _effective_action("create", mode)
            if eff == "create":
                diff.create += 1
                _sample(diff, {"id": cid, "action": "create", "name_ko": r.get("name_ko")})
            else:
                diff.skipped_mode += 1
        else:
            changed = any([
                r.get("parent_id") != cur.parent_id,
                r.get("name_ko") != cur.name_ko,
                r.get("slug") not in (None, cur.slug),
                r.get("level") not in (None, cur.level),
                r.get("sort_order") not in (None, cur.sort_order),
            ])
            if changed:
                eff = _effective_action("update", mode)
                if eff == "update":
                    diff.update += 1
                    _sample(diff, {"id": cid, "action": "update",
                                   "from_parent": cur.parent_id, "to_parent": r.get("parent_id")})
                else:
                    diff.skipped_mode += 1
            else:
                diff.unchanged += 1
    return diff


def _validate_match_rules(
    session: Session,
    rows: list[dict[str, Any]],
    known_cat_ids: set[str],
    report: ValidationReport,
    mode: str = "upsert",
) -> EntityDiff:
    diff = EntityDiff()
    existing = {
        (r.pattern_type, r.pattern_value): r
        for r in session.scalars(select(ProductMatchRule)).all()
    }
    db_product_ids = {pid for (pid,) in session.execute(select(Product.id)).all()}
    seen_keys: set[tuple[str, str]] = set()
    for r in rows:
        ptype = r.get("pattern_type")
        pval = r.get("pattern_value")
        if ptype not in _VALID_PATTERN_TYPES:
            diff.invalid += 1
            report.add_error(f"match_rules: pattern_type 허용값 아님 {ptype!r}")
            continue
        if not pval:
            diff.invalid += 1
            report.add_error("match_rules: pattern_value 비어있음")
            continue
        key = (ptype, pval)
        if key in seen_keys:
            diff.invalid += 1
            report.add_error(f"match_rules: 파일 내 중복 키 {key}")
            continue
        seen_keys.add(key)
        cat = r.get("canonical_category_id")
        if cat is not None and cat not in known_cat_ids:
            diff.invalid += 1
            report.add_error(f"match_rules[{key}]: canonical_category_id {cat} 없음")
            continue
        cpid = r.get("canonical_product_id")
        if cpid is not None and cpid not in db_product_ids:
            # DB-local PK — 같은 DB가 아니면 흔히 깨진다. 경고만, apply 시 null 처리 권장.
            report.warnings.append(
                f"match_rules[{key}]: canonical_product_id {cpid} 가 현 DB에 없음 → apply 시 무시 권장"
            )
        cur = existing.get(key)
        if cur is None:
            eff = _effective_action("create", mode)
            if eff == "create":
                diff.create += 1
                _sample(diff, {"key": list(key), "action": "create", "category": cat})
            else:
                diff.skipped_mode += 1
        else:
            changed = (cur.canonical_category_id != cat) or (cur.trust != r.get("trust", cur.trust))
            if changed:
                eff = _effective_action("update", mode)
                if eff == "update":
                    diff.update += 1
                    _sample(diff, {"key": list(key), "action": "update",
                                   "from_category": cur.canonical_category_id, "to_category": cat})
                else:
                    diff.skipped_mode += 1
            else:
                diff.unchanged += 1
    return diff


def _validate_products(
    session: Session,
    rows: list[dict[str, Any]],
    known_cat_ids: set[str],
    report: ValidationReport,
    force: bool,
    mode: str = "upsert",
) -> EntityDiff:
    diff = EntityDiff()
    if rows and not report.same_database:
        report.add_error(
            "products: manifest 지문이 현 DB와 불일치 → id 기반 apply 불가(preview-only). "
            "products를 제외하거나 같은 DB에서 받은 파일을 사용하세요."
        )
    existing = {p.id: p for p in session.scalars(select(Product)).all()}
    seen_ids: set[int] = set()
    for r in rows:
        pid = r.get("id")
        if pid is None:
            diff.invalid += 1
            report.add_error("products: id 없는 행")
            continue
        if pid in seen_ids:
            diff.invalid += 1
            report.add_error(f"products: 파일 내 중복 id {pid}")
            continue
        seen_ids.add(pid)
        cur = existing.get(pid)
        if cur is None:
            # 생성 금지 — skipped로 보고
            diff.skipped += 1
            _sample(diff, {"id": pid, "action": "skipped", "reason": "DB에 없는 상품(생성 금지)",
                           "name": r.get("raw_name")})
            continue
        new_cat = r.get("unified_category_id")
        if new_cat is not None and new_cat not in known_cat_ids:
            diff.invalid += 1
            report.add_error(f"products[{pid}]: unified_category_id {new_cat} 없음")
            continue
        # id 재사용 의심: 이름 불일치 경고
        if r.get("raw_name") and cur.name and r.get("raw_name") != cur.name:
            report.warnings.append(
                f"products[{pid}]: 파일 이름과 DB 이름이 다름(id 재사용 의심): "
                f"{r.get('raw_name')!r} vs {cur.name!r}"
            )
        if new_cat == cur.unified_category_id:
            diff.unchanged += 1
            continue
        # human 보호
        if (cur.categorization_method in _HUMAN_METHODS) and not force:
            diff.protected += 1
            _sample(diff, {"id": pid, "action": "protected",
                           "method": cur.categorization_method,
                           "from": cur.unified_category_id, "to": new_cat})
            continue
        # append_only는 기존 상품 갱신을 막는다(상품은 생성하지 않으므로 사실상 무변경).
        if mode == "append_only":
            diff.skipped_mode += 1
            continue
        diff.update += 1
        _sample(diff, {"id": pid, "action": "update",
                       "from": cur.unified_category_id, "to": new_cat,
                       "method": cur.categorization_method})
    return diff
