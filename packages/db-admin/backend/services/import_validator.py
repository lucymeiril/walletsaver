"""
import_validator.py — 외부 분류 결과 import 전 적대적 검증 서비스.

검증 항목:
  - 필수 필드: match_key 또는 (brand+name_core+pack_qty+pack_unit), category_id, confidence, source
  - category_id 가 categories 테이블에 존재 (없으면 row error)
  - keyword_ids 가 keywords 테이블에 존재 (int/str 모두 처리)
  - confidence ∈ [0, 1]
  - source ∈ {'human', 'external-ai'} (crawler-auto는 import 경로 불가)
  - match_key 중복 (같은 파일 내) — 마지막 행 우선 + 경고

두 모드:
  - validate_strict(rows, session) -> ValidationResult  : error 하나라도 → 전체 reject
  - validate_lenient(rows, session) -> ValidationResult : error row 분리, 유효 row만 통과
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from core.match_key import build_match_key

logger = logging.getLogger(__name__)

# import 경로에서 허용되는 source 값. crawler-auto는 절대 불가.
IMPORT_ALLOWED_SOURCES: frozenset[str] = frozenset({"human", "external-ai"})

_REQUIRED_COMPOUND_FIELDS = ("brand", "name_core", "pack_qty", "pack_unit")


# ══════════════════════════════════════════════
# ValidationResult
# ══════════════════════════════════════════════

@dataclass
class ValidationResult:
    """validate_strict / validate_lenient 의 공통 반환 타입."""
    valid_rows: list[dict] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)   # (row_index, message)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


# ══════════════════════════════════════════════
# 내부 헬퍼
# ══════════════════════════════════════════════

def _build_match_key(row: dict) -> str | None:
    """compound 필드로 canonical match_key를 구성한다.

    Runtime lookup/export와 반드시 같은 ``core.match_key.build_match_key``를 사용한다.
    서로 다른 문자열 포맷을 허용하면 import는 성공해도 이후 crawl lookup이 영구 miss가 된다.
    """
    brand = row.get("brand")
    name_core = row.get("name_core")
    pack_qty = row.get("pack_qty")
    pack_unit = row.get("pack_unit")
    if not all(
        value is not None and str(value).strip() != ""
        for value in (brand, name_core, pack_qty, pack_unit)
    ):
        return None
    try:
        return build_match_key(
            str(brand),
            str(name_core),
            float(pack_qty),
            str(pack_unit),
        )
    except (TypeError, ValueError):
        return None


def _preload_valid_ids(session: Session) -> tuple[set[str], set[int]]:
    """categories.id (활성) 와 keywords.id 를 DB에서 한 번에 로드한다."""
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
    """단일 row 를 검증하고 오류 메시지 리스트를 반환한다. 오류가 없으면 []."""
    errs: list[str] = []

    # ── 필수 필드 ──
    has_match_key = bool(str(row.get("match_key", "") or "").strip())
    has_compound = all(
        row.get(f) is not None and str(row.get(f, "")).strip() != ""
        for f in _REQUIRED_COMPOUND_FIELDS
    )
    if not has_match_key and not has_compound:
        errs.append(
            "필수 필드 누락: match_key 또는 (brand+name_core+pack_qty+pack_unit) 중 하나 필요"
        )

    if row.get("category_id") is None or str(row.get("category_id", "")).strip() == "":
        errs.append("필수 필드 누락: category_id")

    if row.get("confidence") is None:
        errs.append("필수 필드 누락: confidence")

    if row.get("source") is None or str(row.get("source", "")).strip() == "":
        errs.append("필수 필드 누락: source")

    # ── category_id 존재성 ──
    cat_id = row.get("category_id")
    if cat_id is not None and str(cat_id).strip() != "":
        if cat_id not in valid_category_ids:
            errs.append(f"category_id '{cat_id}' 가 categories 테이블에 없거나 비활성")

    # ── keyword_ids 존재성 ──
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

    # ── confidence 범위 ──
    conf = row.get("confidence")
    if conf is not None:
        try:
            conf_f = float(conf)
            if not (0.0 <= conf_f <= 1.0):
                errs.append(f"confidence {conf} 가 [0, 1] 범위를 벗어남")
        except (TypeError, ValueError):
            errs.append(f"confidence '{conf}' 가 숫자가 아님")

    # ── source enum ──
    source = row.get("source")
    if source is not None and str(source).strip() != "":
        if source not in IMPORT_ALLOWED_SOURCES:
            errs.append(
                f"source '{source}' 허용 안 됨 "
                f"(import 경로 허용값: {sorted(IMPORT_ALLOWED_SOURCES)})"
            )

    return errs


def _deduplicate_by_match_key(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """같은 match_key 를 가진 행을 제거한다 (마지막 행 우선).

    Returns:
        (deduped_rows, warnings) — 중복이 있으면 warnings 에 메시지 추가.
    """
    warnings: list[str] = []
    # key → 마지막으로 나타난 row_index
    key_to_last_idx: dict[str, int] = {}
    key_to_first_idx: dict[str, int] = {}

    for i, row in enumerate(rows):
        key = row.get("match_key") or _build_match_key(row)
        if key:
            if key in key_to_last_idx:
                warnings.append(
                    f"match_key '{key}' 중복 (행 {key_to_first_idx[key]} vs 행 {i}) "
                    f"— 행 {i} 를 우선 사용"
                )
            else:
                key_to_first_idx[key] = i
            key_to_last_idx[key] = i

    # 마지막 등장 index 집합
    keep_indices = set(key_to_last_idx.values())
    # key 없는 행도 유지
    keyless_indices = {
        i for i, row in enumerate(rows)
        if not (row.get("match_key") or _build_match_key(row))
    }
    all_keep = sorted(keep_indices | keyless_indices)

    deduped = [rows[i] for i in all_keep]
    return deduped, warnings


# ══════════════════════════════════════════════
# 공개 API
# ══════════════════════════════════════════════

def validate_strict(rows: list[dict], session: Session) -> ValidationResult:
    """엄격 모드 검증.

    오류가 하나라도 있으면 valid_rows 를 비워 전체를 reject 한다.
    warnings(중복 등)는 그대로 전달된다.
    """
    result = ValidationResult()

    deduped_rows, dup_warnings = _deduplicate_by_match_key(rows)
    result.warnings.extend(dup_warnings)

    valid_category_ids, valid_keyword_ids = _preload_valid_ids(session)

    for i, row in enumerate(deduped_rows):
        errs = _validate_single_row(row, i, valid_category_ids, valid_keyword_ids)
        for msg in errs:
            result.errors.append((i, msg))

    if not result.errors:
        result.valid_rows = deduped_rows

    return result


def validate_lenient(rows: list[dict], session: Session) -> ValidationResult:
    """관대 모드 검증.

    오류가 있는 row 는 errors 에 기록하고, 유효한 row 만 valid_rows 에 포함한다.
    """
    result = ValidationResult()

    deduped_rows, dup_warnings = _deduplicate_by_match_key(rows)
    result.warnings.extend(dup_warnings)

    valid_category_ids, valid_keyword_ids = _preload_valid_ids(session)

    for i, row in enumerate(deduped_rows):
        errs = _validate_single_row(row, i, valid_category_ids, valid_keyword_ids)
        if errs:
            for msg in errs:
                result.errors.append((i, msg))
        else:
            result.valid_rows.append(row)

    return result
