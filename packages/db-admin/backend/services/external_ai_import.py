"""외부 AI 분류 결과 import 검증 및 DB 적용 서비스."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.base import managed_session
from storage.models import Category, Keyword, MartCategoryMapping, Product, UnifiedCategory

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_CATEGORY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")
_ALLOWED_UNITS = {"g", "kg", "ml", "L", "개", "봉", "마리", "단", "망", "팩", "롤", "set", "SET"}
_ALLOWED_UNIT_KINDS = {"GRAM_PER_100G", "ML_PER_100ML", "EACH", "ROLL", "SET"}
_TRUST_RANK = {"auto-aggregate": 0, "external-ai": 1, "human": 2}


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchingUpdate(StrictBaseModel):
    canon_hash: str
    category_id: str
    keywords: list[str] = Field(min_length=1, max_length=20)
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["external-ai"] = "external-ai"
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("canon_hash")
    @classmethod
    def validate_canon_hash(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA1_RE.fullmatch(value):
            raise ValueError("canon_hash는 40자 lowercase SHA1 hex여야 함")
        return value

    @field_validator("category_id")
    @classmethod
    def validate_category_id(cls, value: str) -> str:
        value = value.strip()
        if not _CATEGORY_ID_RE.fullmatch(value):
            raise ValueError("category_id는 stable snake_case ID여야 함")
        return value

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for keyword in values:
            kw = keyword.strip()
            if not (1 <= len(kw) <= 20):
                raise ValueError("keyword는 1~20자여야 함")
            if kw not in cleaned:
                cleaned.append(kw)
        return cleaned


class NewCategory(StrictBaseModel):
    id: str
    name_kr: str = Field(min_length=2, max_length=50)
    parent_id: str | None = None
    default_unit_kind: str = "EACH"
    reason: str = Field(min_length=2, max_length=500)

    @field_validator("id", "parent_id")
    @classmethod
    def validate_ids(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not _CATEGORY_ID_RE.fullmatch(value):
            raise ValueError("카테고리 ID는 stable snake_case여야 함")
        return value

    @field_validator("default_unit_kind")
    @classmethod
    def validate_unit_kind(cls, value: str) -> str:
        if value not in _ALLOWED_UNIT_KINDS:
            raise ValueError(f"default_unit_kind 허용값: {sorted(_ALLOWED_UNIT_KINDS)}")
        return value


class KeywordUpdate(StrictBaseModel):
    keyword: str = Field(min_length=2, max_length=20)
    category_id: str | None = None
    synonyms: list[str] = Field(default_factory=list, max_length=20)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("category_id")
    @classmethod
    def validate_category_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not _CATEGORY_ID_RE.fullmatch(value):
            raise ValueError("category_id는 stable snake_case ID여야 함")
        return value

    @field_validator("synonyms")
    @classmethod
    def validate_synonyms(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for synonym in values:
            text = synonym.strip()
            if not (1 <= len(text) <= 20):
                raise ValueError("synonym은 1~20자여야 함")
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


class CategoryKeywordUpdates(StrictBaseModel):
    new_categories: list[NewCategory] = Field(default_factory=list)
    keywords: list[KeywordUpdate] = Field(default_factory=list)


class ProductUpdate(StrictBaseModel):
    canon_hash: str
    brand: str | None = Field(default=None, max_length=100)
    normalized_name: str | None = Field(default=None, max_length=300)
    raw_name: str | None = Field(default=None, max_length=500)
    pack_qty: float | None = Field(default=None, gt=0)
    pack_unit: str | None = None
    pack_count: int | None = Field(default=None, gt=0)
    unit_price_basis: str | None = Field(default=None, max_length=30)
    canonical_url: str | None = Field(default=None, max_length=1000)
    mart_native_category_path: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("canon_hash")
    @classmethod
    def validate_canon_hash(cls, value: str) -> str:
        value = value.strip().lower()
        if not _SHA1_RE.fullmatch(value):
            raise ValueError("canon_hash는 40자 lowercase SHA1 hex여야 함")
        return value

    @field_validator("pack_unit")
    @classmethod
    def validate_pack_unit(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if value not in _ALLOWED_UNITS:
            raise ValueError(f"pack_unit 허용값: {sorted(_ALLOWED_UNITS)}")
        return value

    @model_validator(mode="after")
    def require_update_field(self) -> "ProductUpdate":
        if not any(getattr(self, f) is not None for f in ("brand", "normalized_name", "raw_name", "pack_qty", "pack_unit", "pack_count", "unit_price_basis", "canonical_url", "mart_native_category_path", "notes")):
            raise ValueError("product_updates 행은 canon_hash 외 보강 필드가 1개 이상 필요")
        return self


@dataclass
class ImportValidationResult:
    ok: bool = True
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    matching_updates: list[MatchingUpdate] = field(default_factory=list)
    category_keyword_updates: CategoryKeywordUpdates | None = None
    product_updates: list[ProductUpdate] = field(default_factory=list)

    def add_error(self, file_name: str, row: int | None, message: str) -> None:
        self.ok = False
        self.errors.append({"file": file_name, "row": row, "message": message})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_no}: JSON 파싱 실패: {exc.msg}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"line {line_no}: JSON object여야 함")
            rows.append(parsed)
    return rows


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError("YAML root는 mapping이어야 함")
    return data


def _validate_jsonl_rows(file_name: str, rows: list[dict[str, Any]], model: type[BaseModel], result: ImportValidationResult) -> list[Any]:
    valid: list[Any] = []
    for idx, row in enumerate(rows, start=1):
        try:
            valid.append(model.model_validate(row))
        except ValidationError as exc:
            result.add_error(file_name, idx, exc.errors()[0]["msg"])
    return valid


def validate_import_files(matching_updates_path: Path, category_keyword_updates_path: Path, product_updates_path: Path) -> ImportValidationResult:
    """3종 import 파일을 파싱하고 스키마를 검증한다."""
    result = ImportValidationResult()
    try:
        matching_rows = _read_jsonl(Path(matching_updates_path))
        result.matching_updates = _validate_jsonl_rows("matching_updates.jsonl", matching_rows, MatchingUpdate, result)
    except (FileNotFoundError, ValueError) as exc:
        result.add_error("matching_updates.jsonl", None, str(exc))

    try:
        category_payload = _read_yaml(Path(category_keyword_updates_path))
        result.category_keyword_updates = CategoryKeywordUpdates.model_validate(category_payload)
    except ValidationError as exc:
        result.add_error("category_keyword_updates.yaml", None, exc.errors()[0]["msg"])
    except (FileNotFoundError, ValueError) as exc:
        result.add_error("category_keyword_updates.yaml", None, str(exc))

    try:
        product_rows = _read_jsonl(Path(product_updates_path))
        result.product_updates = _validate_jsonl_rows("product_updates.jsonl", product_rows, ProductUpdate, result)
    except (FileNotFoundError, ValueError) as exc:
        result.add_error("product_updates.jsonl", None, str(exc))

    result.counts = {
        "matching_updates": len(result.matching_updates),
        "new_categories": len(result.category_keyword_updates.new_categories) if result.category_keyword_updates else 0,
        "keywords": len(result.category_keyword_updates.keywords) if result.category_keyword_updates else 0,
        "product_updates": len(result.product_updates),
    }
    return result


def validate_import_bundle(in_dir: Path) -> ImportValidationResult:
    """디렉터리의 표준 3종 파일을 검증한다."""
    in_dir = Path(in_dir)
    return validate_import_files(in_dir / "matching_updates.jsonl", in_dir / "category_keyword_updates.yaml", in_dir / "product_updates.jsonl")


def _empty_report(validation: ImportValidationResult, dry_run: bool) -> dict[str, Any]:
    return {
        "ok": validation.ok,
        "dry_run": dry_run,
        "counts": validation.counts,
        "errors": validation.errors,
        "created": {"categories": 0, "keywords": 0, "mappings": 0},
        "updated": {"categories": 0, "keywords": 0, "mappings": 0, "products": 0},
        "skipped": {"categories": 0, "keywords": 0, "mappings": 0, "products": 0},
        "conflicts": [],
    }


def _category_level(session: Session, parent_id: str | None) -> int:
    if parent_id is None:
        return 0
    parent = session.get(UnifiedCategory, parent_id)
    if parent is None:
        raise ValueError(f"부모 통합 카테고리를 찾을 수 없습니다: {parent_id}")
    return parent.level + 1


def _apply_categories(session: Session, payload: CategoryKeywordUpdates, report: dict[str, Any]) -> None:
    for item in payload.new_categories:
        if session.get(UnifiedCategory, item.id) is not None:
            report["skipped"]["categories"] += 1
            report["conflicts"].append({"type": "category", "id": item.id, "reason": "id_exists"})
            continue
        level = _category_level(session, item.parent_id)
        session.add(UnifiedCategory(id=item.id, parent_id=item.parent_id, slug=item.id.split(".")[-1], name_ko=item.name_kr, level=level, sort_order=0, source_origin="external-ai"))
        report["created"]["categories"] += 1
    session.flush()


def _legacy_category_id(session: Session, category_id: str | None) -> str | None:
    if category_id and session.get(Category, category_id) is not None:
        return category_id
    return None


def _apply_keywords(session: Session, payload: CategoryKeywordUpdates, report: dict[str, Any]) -> None:
    for item in payload.keywords:
        category_id = _legacy_category_id(session, item.category_id)
        keyword = session.scalar(select(Keyword).where(Keyword.word == item.keyword))
        if keyword is None:
            session.add(Keyword(word=item.keyword, synonyms=item.synonyms, category_id=category_id, is_active=True))
            report["created"]["keywords"] += 1
            continue
        old_synonyms = keyword.synonyms or []
        merged = list(old_synonyms)
        for synonym in item.synonyms:
            if synonym not in merged:
                merged.append(synonym)
        changed = merged != old_synonyms or (category_id is not None and keyword.category_id != category_id)
        if changed:
            keyword.synonyms = merged
            if category_id is not None:
                keyword.category_id = category_id
            report["updated"]["keywords"] += 1
        else:
            report["skipped"]["keywords"] += 1


def _upsert_external_mapping(session: Session, product: Product, update: MatchingUpdate, report: dict[str, Any]) -> tuple[str, MartCategoryMapping | None]:
    if not product.mart or not product.mart_native_category_id:
        report["skipped"]["mappings"] += 1
        return "skipped", None
    existing = session.scalar(select(MartCategoryMapping).where(MartCategoryMapping.mart == product.mart, MartCategoryMapping.mart_native_id == product.mart_native_category_id))
    now = datetime.now(timezone.utc)
    if existing is None:
        mapping = MartCategoryMapping(mart=product.mart, mart_native_id=product.mart_native_category_id, mart_native_path=product.mart_native_category_path, unified_category_id=update.category_id, trust="external-ai", confidence=update.confidence, decided_by="external-ai", created_at=now, updated_at=now)
        session.add(mapping)
        report["created"]["mappings"] += 1
        return "created", mapping
    if _TRUST_RANK["external-ai"] < _TRUST_RANK[existing.trust]:
        report["conflicts"].append({"type": "mapping", "mart": product.mart, "mart_native_id": product.mart_native_category_id, "existing_trust": existing.trust, "incoming_trust": "external-ai"})
        report["skipped"]["mappings"] += 1
        return "conflict", existing
    changed = existing.unified_category_id != update.category_id or existing.confidence != update.confidence or existing.trust != "external-ai"
    if changed:
        existing.mart_native_path = product.mart_native_category_path or existing.mart_native_path
        existing.unified_category_id = update.category_id
        existing.trust = "external-ai"
        existing.confidence = update.confidence
        existing.decided_by = "external-ai"
        existing.updated_at = now
        report["updated"]["mappings"] += 1
        return "updated", existing
    report["skipped"]["mappings"] += 1
    return "skipped", existing


def _fill_product_category(product: Product, category_id: str, mapping_action: str, mapping: MartCategoryMapping | None, report: dict[str, Any]) -> None:
    if product.unified_category_id == category_id:
        report["skipped"]["products"] += 1
        return
    if product.unified_category_id and mapping is not None and mapping_action == "conflict" and _TRUST_RANK.get(mapping.trust, 0) > _TRUST_RANK["external-ai"]:
        report["conflicts"].append({"type": "product", "canon_hash": product.canon_hash, "existing_category_id": product.unified_category_id, "incoming_category_id": category_id, "reason": "human_mapping_protected"})
        report["skipped"]["products"] += 1
        return
    product.unified_category_id = category_id
    product.categorization_confidence = 1.0 if product.categorization_confidence is None else max(product.categorization_confidence, 0.0)
    product.categorization_method = "suggested"
    report["updated"]["products"] += 1


def _apply_matching_updates(session: Session, updates: list[MatchingUpdate], report: dict[str, Any]) -> None:
    for update in updates:
        if session.get(UnifiedCategory, update.category_id) is None:
            raise ValueError(f"통합 카테고리를 찾을 수 없습니다: {update.category_id}")
        products = session.scalars(select(Product).where(Product.canon_hash == update.canon_hash).order_by(Product.id)).all()
        if not products:
            report["skipped"]["products"] += 1
            report["conflicts"].append({"type": "matching", "canon_hash": update.canon_hash, "reason": "product_not_found"})
            continue
        for product in products:
            action, mapping = _upsert_external_mapping(session, product, update, report)
            _fill_product_category(product, update.category_id, action, mapping, report)


def _apply_product_updates(session: Session, updates: list[ProductUpdate], report: dict[str, Any]) -> None:
    for update in updates:
        products = session.scalars(select(Product).where(Product.canon_hash == update.canon_hash).order_by(Product.id)).all()
        if not products:
            report["skipped"]["products"] += 1
            report["conflicts"].append({"type": "product_update", "canon_hash": update.canon_hash, "reason": "product_not_found"})
            continue
        for product in products:
            changed = False
            if update.brand is not None and product.brand != update.brand:
                product.brand = update.brand; changed = True
            if update.normalized_name is not None:
                if product.display_name != update.normalized_name:
                    product.display_name = update.normalized_name; changed = True
                if product.name_core != update.normalized_name:
                    product.name_core = update.normalized_name; changed = True
            if update.raw_name is not None and product.name != update.raw_name:
                product.name = update.raw_name; changed = True
            if update.pack_qty is not None and product.pack_qty != update.pack_qty:
                product.pack_qty = update.pack_qty; changed = True
            if update.pack_unit is not None and product.pack_unit != update.pack_unit:
                product.pack_unit = update.pack_unit; product.unit = update.pack_unit; changed = True
            if update.unit_price_basis is not None and product.unit_price_basis_raw != update.unit_price_basis:
                product.unit_price_basis_raw = update.unit_price_basis; changed = True
            if update.canonical_url is not None and product.canonical_url != update.canonical_url:
                product.canonical_url = update.canonical_url; changed = True
            if update.mart_native_category_path is not None and product.mart_native_category_path != update.mart_native_category_path:
                product.mart_native_category_path = update.mart_native_category_path; changed = True
            if update.pack_count is not None:
                attrs = dict(product.attributes or {})
                if attrs.get("pack_count") != update.pack_count:
                    attrs["pack_count"] = update.pack_count
                    product.attributes = attrs
                    changed = True
            if update.notes is not None:
                attrs = dict(product.attributes or {})
                if attrs.get("external_ai_notes") != update.notes:
                    attrs["external_ai_notes"] = update.notes
                    product.attributes = attrs
                    changed = True
            if changed:
                product.updated_at = datetime.utcnow()
                report["updated"]["products"] += 1
            else:
                report["skipped"]["products"] += 1


def _apply_validated(session: Session, validation: ImportValidationResult, dry_run: bool) -> dict[str, Any]:
    report = _empty_report(validation, dry_run)
    if not validation.ok:
        return report
    payload = validation.category_keyword_updates or CategoryKeywordUpdates()
    sp = session.begin_nested()
    try:
        _apply_categories(session, payload, report)
        _apply_keywords(session, payload, report)
        _apply_matching_updates(session, validation.matching_updates, report)
        _apply_product_updates(session, validation.product_updates, report)
        session.flush()
    except Exception:
        sp.rollback()
        raise
    if dry_run:
        sp.rollback()
    else:
        sp.commit()
    return report


def apply_import_bundle(in_dir: Path, session: Session | None = None, dry_run: bool = False) -> dict[str, Any]:
    """3종 import 파일을 검증하고 하나의 트랜잭션으로 DB에 적용한다."""
    validation = validate_import_bundle(in_dir)
    if not validation.ok:
        return _empty_report(validation, dry_run)
    if session is not None:
        return _apply_validated(session, validation, dry_run)
    with managed_session() as managed:
        return _apply_validated(managed, validation, dry_run)
