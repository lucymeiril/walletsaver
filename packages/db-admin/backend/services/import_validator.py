"""Adversarial validation for externally classified MatchingEntry rows.

Identity policy:
- ``core.match_key.build_match_key`` is the only match-key generator.
- missing brands are normalized to ``__no_brand__`` rather than rejected.
- when identity fields are present, an incoming match_key is recomputed instead
  of trusted, so old/hand-built key formats cannot poison future runtime lookup.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from core.match_key import NO_BRAND_SENTINEL, build_match_key

logger = logging.getLogger(__name__)

IMPORT_ALLOWED_SOURCES: frozenset[str] = frozenset({"human", "external-ai"})
_REQUIRED_COMPOUND_FIELDS = ("name_core", "pack_qty", "pack_unit")


@dataclass
class ValidationResult:
    valid_rows: list[dict] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _build_match_key(row: dict) -> str | None:
    """Build the canonical key from compound identity fields."""
    name_core = row.get("name_core")
    pack_qty = row.get("pack_qty")
    pack_unit = row.get("pack_unit")
    if not all(
        value is not None and str(value).strip() != ""
        for value in (name_core, pack_qty, pack_unit)
    ):
        return None
    try:
        return build_match_key(
            row.get("brand"),
            str(name_core),
            float(pack_qty),
            str(pack_unit),
        )
    except (TypeError, ValueError):
        return None


def _normalize_identity(row: dict) -> dict:
    """Return a copy with stable brand and canonical key when possible."""
    normalized = dict(row)
    brand = normalized.get("brand")
    if brand is None or not str(brand).strip():
        normalized["brand"] = NO_BRAND_SENTINEL

    canonical_key = _build_match_key(normalized)
    if canonical_key:
        normalized["match_key"] = canonical_key
    return normalized


def _preload_valid_ids(session: Session) -> tuple[set[str], set[int]]:
    from storage.models import Category, Keyword

    category_ids: set[str] = {
        c.id
        for c in session.query(Category).filter(Category.is_active.is_(True)).all()
    }
    keyword_ids: set[int] = {k.id for k in session.query(Keyword).all()}
    return category_ids, keyword_ids


def _validate_single_row(
    row: dict,
    row_idx: int,
    valid_category_ids: set[str],
    valid_keyword_ids: set[int],
) -> list[str]:
    errs: list[str] = []

    has_match_key = bool(str(row.get("match_key", "") or "").strip())
    has_compound = all(
        row.get(field) is not None and str(row.get(field, "")).strip() != ""
        for field in _REQUIRED_COMPOUND_FIELDS
    )
    if not has_match_key and not has_compound:
        errs.append(
            "필수 필드 누락: match_key 또는 (name_core+pack_qty+pack_unit) 중 하나 필요"
        )

    if row.get("category_id") is None or str(row.get("category_id", "")).strip() == "":
        errs.append("필수 필드 누락: category_id")

    if row.get("confidence") is None:
        errs.append("필수 필드 누락: confidence")

    if row.get("source") is None or str(row.get("source", "")).strip() == "":
        errs.append("필수 필드 누락: source")

    cat_id = row.get("category_id")
    if cat_id is not None and str(cat_id).strip() != "" and cat_id not in valid_category_ids:
        errs.append(f"category_id '{cat_id}' 가 categories 테이블에 없거나 비활성")

    kw_ids = row.get("keyword_ids")
    if kw_ids is not None:
        if not isinstance(kw_ids, (list, tuple)):
            errs.append("keyword_ids 는 리스트여야 함")
        else:
            for kid in kw_ids:
                try:
                    kid_int = int(kid)
                except (TypeError, ValueError):
                    errs.append(f"keyword_id '{kid}' 가 정수로 변환 불가")
                    continue
                if kid_int not in valid_keyword_ids:
                    errs.append(f"keyword_id {kid_int} 가 keywords 테이블에 없음")

    conf = row.get("confidence")
    if conf is not None:
        try:
            conf_f = float(conf)
            if not (0.0 <= conf_f <= 1.0):
                errs.append(f"confidence {conf} 가 [0, 1] 범위를 벗어남")
        except (TypeError, ValueError):
            errs.append(f"confidence '{conf}' 가 숫자가 아님")

    source = row.get("source")
    if source is not None and str(source).strip() != "" and source not in IMPORT_ALLOWED_SOURCES:
        errs.append(
            f"source '{source}' 허용 안 됨 "
            f"(import 경로 허용값: {sorted(IMPORT_ALLOWED_SOURCES)})"
        )

    return errs


def _deduplicate_by_match_key(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Deduplicate canonical keys, keeping the last row in the uploaded file."""
    warnings: list[str] = []
    normalized_rows = [_normalize_identity(row) for row in rows]
    key_to_last_idx: dict[str, int] = {}
    key_to_first_idx: dict[str, int] = {}

    for index, row in enumerate(normalized_rows):
        key = row.get("match_key") or _build_match_key(row)
        if key:
            if key in key_to_last_idx:
                warnings.append(
                    f"match_key '{key}' 중복 (행 {key_to_first_idx[key]} vs 행 {index}) "
                    f"— 행 {index} 를 우선 사용"
                )
            else:
                key_to_first_idx[key] = index
            key_to_last_idx[key] = index

    keep_indices = set(key_to_last_idx.values())
    keyless_indices = {
        index
        for index, row in enumerate(normalized_rows)
        if not (row.get("match_key") or _build_match_key(row))
    }
    return [normalized_rows[index] for index in sorted(keep_indices | keyless_indices)], warnings


def validate_strict(rows: list[dict], session: Session) -> ValidationResult:
    result = ValidationResult()
    deduped_rows, dup_warnings = _deduplicate_by_match_key(rows)
    result.warnings.extend(dup_warnings)
    valid_category_ids, valid_keyword_ids = _preload_valid_ids(session)

    for index, row in enumerate(deduped_rows):
        for message in _validate_single_row(row, index, valid_category_ids, valid_keyword_ids):
            result.errors.append((index, message))

    if not result.errors:
        result.valid_rows = deduped_rows
    return result


def validate_lenient(rows: list[dict], session: Session) -> ValidationResult:
    result = ValidationResult()
    deduped_rows, dup_warnings = _deduplicate_by_match_key(rows)
    result.warnings.extend(dup_warnings)
    valid_category_ids, valid_keyword_ids = _preload_valid_ids(session)

    for index, row in enumerate(deduped_rows):
        errs = _validate_single_row(row, index, valid_category_ids, valid_keyword_ids)
        if errs:
            for message in errs:
                result.errors.append((index, message))
        else:
            result.valid_rows.append(row)
    return result
