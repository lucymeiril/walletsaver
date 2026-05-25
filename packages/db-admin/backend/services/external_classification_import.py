"""external_classification_import.py — RD8 L3 외부 LLM 분류 결과 Import 파이프라인.

3종 파일 처리:
  1. matching_updates  (JSONL/JSON) — MatchingEntry UPSERT (match_key 키)
  2. categories_keywords_updates (YAML) — 신규 category → 검토 큐, keyword → DB 즉시 반영
  3. products_updates  (JSONL/JSON) — Product find_or_create + source_marts 갱신

파이프라인:
  validate(L3-A) → preview/dry-run(L3-B) → apply(L3-C, 트랜잭션 1개)

설계 원칙:
  - 검증기는 절대 raise하지 않음. ValidationReport에 실패 사유를 담아 반환.
  - alias 무한증식 방지: MAX_ALIASES_PER_ENTRY = 50
  - whitelist는 매 요청마다 DB에서 로드 (hot-reload 지원, 프로세스 캐시 없음)
  - source 허용값: crawler-auto | human | external-ai
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from services.unit_utils import classify_unit_kind, build_display_name
from storage.models import (
    Category,
    CategoryReviewQueue,
    ImportsAudit,
    Keyword,
    MatchingEntry,
    Product,
)

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────
_VALID_SOURCES: frozenset[str] = frozenset({"crawler-auto", "human", "external-ai"})
_VALID_FILE_TYPES: frozenset[str] = frozenset({"matching", "categories", "products"})

MAX_ALIASES_PER_ENTRY: int = 50
MIN_CONFIDENCE_HUMAN_REVIEW: float = 0.6

# source 신뢰도 순위: 높을수록 우선 적용
_SOURCE_TRUST: dict[str, int] = {
    "human": 3,
    "external-ai": 2,
    "crawler-auto": 1,
}


# ════════════════════════════════════════════════════════════════════════════════
# L3-A: 결과 데이터 클래스
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationReport:
    """검증 결과 — 항목 수, 통과, 실패+사유. 절대 raise 없음."""

    total: int = 0
    passed: int = 0
    failed_items: list[dict] = field(default_factory=list)
    valid_rows: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.failed_items) == 0

    def _fail(self, row_idx: int, field_name: str, reason: str) -> None:
        self.failed_items.append({"row": row_idx, "field": field_name, "reason": reason})

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": len(self.failed_items),
            "ok": self.ok,
            "failed_items": self.failed_items[:100],
        }


@dataclass
class MatchingPreview:
    new_count: int = 0
    update_count: int = 0
    alias_add_count: int = 0
    whitelist_violation_count: int = 0
    pending_human_count: int = 0
    sample_rows: list[dict] = field(default_factory=list)


@dataclass
class CategoriesPreview:
    new_category_proposals: int = 0
    keyword_add_count: int = 0
    keyword_update_count: int = 0
    proposals: list[dict] = field(default_factory=list)


@dataclass
class ProductsPreview:
    new_products: int = 0
    find_or_create_absorbed: int = 0
    source_marts_update_count: int = 0
    unit_convertible_ratio: float = 0.0


@dataclass
class PreviewReport:
    file_type: str
    validation: ValidationReport
    matching: Optional[MatchingPreview] = None
    categories: Optional[CategoriesPreview] = None
    products: Optional[ProductsPreview] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "file_type": self.file_type,
            "validation": self.validation.to_dict(),
        }
        if self.matching:
            d["matching"] = {
                "new": self.matching.new_count,
                "update": self.matching.update_count,
                "alias_add": self.matching.alias_add_count,
                "whitelist_violation": self.matching.whitelist_violation_count,
                "pending_human": self.matching.pending_human_count,
                "sample": self.matching.sample_rows[:20],
            }
        if self.categories:
            d["categories"] = {
                "new_proposals": self.categories.new_category_proposals,
                "keyword_add": self.categories.keyword_add_count,
                "keyword_update": self.categories.keyword_update_count,
                "proposals": self.categories.proposals,
            }
        if self.products:
            d["products"] = {
                "new": self.products.new_products,
                "absorbed": self.products.find_or_create_absorbed,
                "source_marts_updated": self.products.source_marts_update_count,
                "unit_convertible_ratio": self.products.unit_convertible_ratio,
            }
        return d


@dataclass
class ApplyResult:
    ok: bool
    file_type: str
    file_hash: str
    idempotent: bool = False
    counts: dict = field(default_factory=dict)
    error: Optional[str] = None


# ════════════════════════════════════════════════════════════════════════════════
# Whitelist 유틸
# ════════════════════════════════════════════════════════════════════════════════

def load_category_whitelist(session: Session) -> frozenset[str]:
    """DB categories 테이블의 활성 카테고리 ID 집합을 반환한다.

    매 요청마다 DB를 조회하므로 categories 테이블 변경이 즉시 반영된다.
    (프로세스 수준 캐시 없음 — hot-reload 보장)
    """
    try:
        rows = session.query(Category.id).filter(Category.is_active == True).all()  # noqa: E712
        return frozenset(r.id for r in rows)
    except Exception as exc:
        logger.warning("whitelist DB 로드 실패, 빈 whitelist 반환: %s", exc)
        return frozenset()


def _compute_file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ════════════════════════════════════════════════════════════════════════════════
# L3-A: 검증기
# ════════════════════════════════════════════════════════════════════════════════

_MATCHING_REQUIRED: frozenset[str] = frozenset({
    "match_key", "brand", "name_core", "pack_qty", "pack_unit",
    "category_id", "keywords", "confidence", "source",
})


def validate_matching_updates(
    payload: list[dict],
    *,
    whitelist: Optional[frozenset[str]] = None,
    session: Optional[Session] = None,
) -> ValidationReport:
    """matching_updates JSONL 행 리스트를 검증한다.

    항목별 체크:
      - 필수 필드 존재
      - match_key 파이프(|) 형식 (최소 3개)
      - confidence 0.0~1.0 실수
      - source 허용값 (crawler-auto|human|external-ai)
      - category_id whitelist 존재 여부
      - keywords, aliases 타입·크기
    """
    if session is not None and whitelist is None:
        whitelist = load_category_whitelist(session)
    if whitelist is None:
        whitelist = frozenset()

    report = ValidationReport(total=len(payload))

    for i, row in enumerate(payload):
        if not isinstance(row, dict):
            report._fail(i, "row", f"dict여야 함, 받은 타입: {type(row).__name__}")
            continue

        row_errors: list[tuple[str, str]] = []

        # 필수 필드
        missing = _MATCHING_REQUIRED - set(row.keys())
        if missing:
            row_errors.append(("필수필드", f"누락: {sorted(missing)}"))

        # match_key 형식
        mk = row.get("match_key", "")
        if not isinstance(mk, str) or not mk.strip():
            row_errors.append(("match_key", "비어 있거나 문자열이 아님"))
        elif mk.count("|") < 3:
            row_errors.append(("match_key", f"파이프 구분자 3개 이상 필요 (현재: {mk.count('|')}개): {mk!r}"))

        # confidence
        conf_raw = row.get("confidence")
        if conf_raw is not None:
            try:
                conf = float(conf_raw)
                if not (0.0 <= conf <= 1.0):
                    row_errors.append(("confidence", f"범위 오류 (0.0-1.0): {conf}"))
            except (TypeError, ValueError):
                row_errors.append(("confidence", f"숫자 변환 실패: {conf_raw!r}"))

        # source
        src = row.get("source")
        if src not in _VALID_SOURCES:
            row_errors.append(("source", f"허용값 오류: {src!r} (허용: {sorted(_VALID_SOURCES)})"))

        # category_id whitelist
        cat_id = row.get("category_id")
        if cat_id and whitelist and cat_id not in whitelist:
            row_errors.append(("category_id", f"whitelist에 없는 id: {cat_id!r}"))

        # keywords 타입
        kws = row.get("keywords")
        if kws is not None and not isinstance(kws, list):
            row_errors.append(("keywords", f"list여야 함, 받은 타입: {type(kws).__name__}"))

        # aliases 타입·크기
        aliases = row.get("aliases")
        if aliases is not None:
            if not isinstance(aliases, list):
                row_errors.append(("aliases", f"list여야 함, 받은 타입: {type(aliases).__name__}"))
            elif len(aliases) > MAX_ALIASES_PER_ENTRY:
                row_errors.append(("aliases", f"최대 {MAX_ALIASES_PER_ENTRY}개 초과: {len(aliases)}개"))

        # pack_qty 숫자
        pq = row.get("pack_qty")
        if pq is not None:
            try:
                float(pq)
            except (TypeError, ValueError):
                row_errors.append(("pack_qty", f"숫자 변환 실패: {pq!r}"))

        if row_errors:
            for field_name, reason in row_errors:
                report._fail(i, field_name, reason)
        else:
            report.passed += 1
            report.valid_rows.append(row)

    return report


def validate_categories_keywords_updates(
    payload: dict,
    *,
    whitelist: Optional[frozenset[str]] = None,
    session: Optional[Session] = None,
) -> ValidationReport:
    """categories_keywords_updates YAML 페이로드(dict)를 검증한다.

    new_categories:
      - id, reason 필수
      - parent_id가 있으면 whitelist에 존재해야 함
      - 이미 존재하는 id는 경고(실패)

    keyword_updates:
      - keyword(word) 필수
    """
    if session is not None and whitelist is None:
        whitelist = load_category_whitelist(session)
    if whitelist is None:
        whitelist = frozenset()

    if not isinstance(payload, dict):
        report = ValidationReport(total=1)
        report._fail(0, "root", f"최상위 구조가 dict여야 함, 받은 타입: {type(payload).__name__}")
        return report

    new_cats: list = payload.get("categories") or []
    kw_updates: list = payload.get("keywords") or []

    if not isinstance(new_cats, list):
        new_cats = []
    if not isinstance(kw_updates, list):
        kw_updates = []

    report = ValidationReport(total=len(new_cats) + len(kw_updates))

    # ── new_categories 검증 ─────────────────────────────────────────────────
    for i, cat in enumerate(new_cats):
        row_errors: list[tuple[str, str]] = []

        if not isinstance(cat, dict):
            report._fail(i, "categories", f"dict여야 함")
            continue

        if not cat.get("id"):
            row_errors.append(("id", "필수 (신규 카테고리 id)"))

        if not cat.get("reason"):
            row_errors.append(("reason", "필수 (왜 이 카테고리가 필요한지 설명)"))

        parent = cat.get("parent_id")
        if parent and whitelist and parent not in whitelist:
            row_errors.append(("parent_id", f"whitelist에 없음: {parent!r}"))

        proposed_id = cat.get("id", "")
        if proposed_id and whitelist and proposed_id in whitelist:
            row_errors.append(("id", f"이미 whitelist에 존재 (신규 불필요): {proposed_id!r}"))

        if row_errors:
            for field_name, reason in row_errors:
                report._fail(i, field_name, reason)
        else:
            report.passed += 1
            report.valid_rows.append({"type": "new_category", **cat})

    # ── keyword_updates 검증 ────────────────────────────────────────────────
    for j, kw in enumerate(kw_updates):
        offset = len(new_cats) + j

        if not isinstance(kw, dict):
            report._fail(offset, "keywords", "dict여야 함")
            continue

        if not (kw.get("keyword") or kw.get("word")):
            report._fail(offset, "keyword", "keyword 또는 word 필수")
            continue

        report.passed += 1
        report.valid_rows.append({"type": "keyword_update", **kw})

    return report


def validate_products_updates(
    payload: list[dict],
    *,
    whitelist: Optional[frozenset[str]] = None,
    session: Optional[Session] = None,
) -> ValidationReport:
    """products_updates JSONL 행 리스트를 검증한다.

    필수: match_key (또는 raw_id), mart (또는 source_mart)
    선택: price, discount_price, unit_price, captured_at
    """
    report = ValidationReport(total=len(payload))

    for i, row in enumerate(payload):
        if not isinstance(row, dict):
            report._fail(i, "row", f"dict여야 함, 받은 타입: {type(row).__name__}")
            continue

        row_errors: list[tuple[str, str]] = []

        mk = row.get("match_key") or row.get("raw_id")
        if not mk:
            row_errors.append(("match_key", "match_key 또는 raw_id 필수"))

        mart = row.get("mart") or row.get("source_mart")
        if not mart:
            row_errors.append(("mart", "mart 또는 source_mart 필수"))

        price = row.get("price")
        if price is not None:
            try:
                float(price)
            except (TypeError, ValueError):
                row_errors.append(("price", f"숫자 변환 실패: {price!r}"))

        if row_errors:
            for field_name, reason in row_errors:
                report._fail(i, field_name, reason)
        else:
            report.passed += 1
            report.valid_rows.append(row)

    return report


# ════════════════════════════════════════════════════════════════════════════════
# L3-B: dry-run 미리보기
# ════════════════════════════════════════════════════════════════════════════════

def _preview_matching(valid_rows: list[dict], session: Session, whitelist: frozenset[str]) -> MatchingPreview:
    preview = MatchingPreview()

    if not valid_rows:
        return preview

    keys = [r["match_key"] for r in valid_rows if r.get("match_key")]
    if keys:
        db_entries = session.query(MatchingEntry.match_key, MatchingEntry.aliases).filter(
            MatchingEntry.match_key.in_(keys)
        ).all()
        existing_keys = {e.match_key for e in db_entries}
        existing_aliases_map = {e.match_key: (e.aliases or []) for e in db_entries}
    else:
        existing_keys = set()
        existing_aliases_map = {}

    for row in valid_rows:
        mk = row.get("match_key", "")
        cat_id = row.get("category_id", "")
        try:
            conf = float(row.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 1.0

        if cat_id and whitelist and cat_id not in whitelist:
            preview.whitelist_violation_count += 1

        if conf < MIN_CONFIDENCE_HUMAN_REVIEW:
            preview.pending_human_count += 1

        if mk in existing_keys:
            preview.update_count += 1
            incoming_aliases = row.get("aliases") or []
            old_aliases = existing_aliases_map.get(mk, [])
            new_aliases = [a for a in incoming_aliases if a not in old_aliases]
            preview.alias_add_count += len(new_aliases)
        else:
            preview.new_count += 1

        if len(preview.sample_rows) < 20:
            preview.sample_rows.append({
                "match_key": mk,
                "action": "update" if mk in existing_keys else "new",
                "category_id": cat_id,
                "confidence": conf,
            })

    return preview


def _preview_categories(valid_rows: list[dict], session: Session) -> CategoriesPreview:
    preview = CategoriesPreview()

    for row in valid_rows:
        if row.get("type") == "new_category":
            preview.new_category_proposals += 1
            preview.proposals.append({
                "id": row.get("id"),
                "parent_id": row.get("parent_id"),
                "label": row.get("label"),
                "reason": row.get("reason"),
            })
        elif row.get("type") == "keyword_update":
            word = row.get("keyword") or row.get("word", "")
            existing = session.query(Keyword).filter(Keyword.word == word).first()
            if existing:
                preview.keyword_update_count += 1
            else:
                preview.keyword_add_count += 1

    return preview


def _preview_products(valid_rows: list[dict], session: Session) -> ProductsPreview:
    preview = ProductsPreview()

    if not valid_rows:
        return preview

    keys = [r.get("match_key") for r in valid_rows if r.get("match_key")]
    me_map: dict[str, MatchingEntry] = {}
    if keys:
        entries = session.query(MatchingEntry).filter(MatchingEntry.match_key.in_(keys)).all()
        me_map = {e.match_key: e for e in entries}

    unit_convertible = 0
    total_with_me = 0

    for row in valid_rows:
        mk = row.get("match_key")
        me = me_map.get(mk) if mk else None
        if me is None:
            continue
        total_with_me += 1

        # find_or_create 시뮬레이션
        q = session.query(Product)
        q = q.filter(Product.brand == me.brand) if me.brand is not None else q.filter(Product.brand.is_(None))
        q = q.filter(Product.name_core == me.name_core) if me.name_core is not None else q.filter(Product.name_core.is_(None))
        q = q.filter(Product.pack_qty == me.pack_qty) if me.pack_qty is not None else q.filter(Product.pack_qty.is_(None))
        q = q.filter(Product.pack_unit == me.pack_unit) if me.pack_unit is not None else q.filter(Product.pack_unit.is_(None))

        product = q.first()
        if product is None:
            preview.new_products += 1
        else:
            preview.find_or_create_absorbed += 1

        mart = row.get("mart") or row.get("source_mart", "")
        if mart and product and mart not in (product.source_marts or []):
            preview.source_marts_update_count += 1

        unit_kind = classify_unit_kind(me.pack_unit)
        if unit_kind in ("weight", "volume"):
            unit_convertible += 1

    if total_with_me > 0:
        preview.unit_convertible_ratio = round(unit_convertible / total_with_me, 3)

    return preview


def preview_import(file_type: str, payload: Any, session: Session) -> PreviewReport:
    """dry-run 미리보기. DB에 아무것도 쓰지 않는다."""
    if file_type not in _VALID_FILE_TYPES:
        report = ValidationReport(total=0)
        report._fail(0, "file_type", f"알 수 없는 file_type: {file_type!r}. 허용: {sorted(_VALID_FILE_TYPES)}")
        return PreviewReport(file_type=file_type, validation=report)

    whitelist = load_category_whitelist(session)

    if file_type == "matching":
        rows = payload if isinstance(payload, list) else []
        validation = validate_matching_updates(rows, whitelist=whitelist)
        mp = _preview_matching(validation.valid_rows, session, whitelist)
        return PreviewReport(file_type=file_type, validation=validation, matching=mp)

    elif file_type == "categories":
        p = payload if isinstance(payload, dict) else {}
        validation = validate_categories_keywords_updates(p, whitelist=whitelist)
        cp = _preview_categories(validation.valid_rows, session)
        return PreviewReport(file_type=file_type, validation=validation, categories=cp)

    else:  # products
        rows = payload if isinstance(payload, list) else []
        validation = validate_products_updates(rows, whitelist=whitelist)
        pp = _preview_products(validation.valid_rows, session)
        return PreviewReport(file_type=file_type, validation=validation, products=pp)


# ════════════════════════════════════════════════════════════════════════════════
# L3-C: 적용 (트랜잭션 1개)
# ════════════════════════════════════════════════════════════════════════════════

def _apply_matching(valid_rows: list[dict], session: Session) -> dict:
    """MatchingEntry UPSERT — match_key 기준."""
    inserted = 0
    updated = 0
    alias_added = 0

    for row in valid_rows:
        mk: str = row["match_key"]

        # keyword_ids 구성: keyword 문자열 → DB Keyword.id
        kw_ids: list[int] = []
        for word in (row.get("keywords") or []):
            word = str(word).strip()
            if not word:
                continue
            kw_obj = session.query(Keyword).filter(Keyword.word == word).first()
            if kw_obj is None:
                kw_obj = Keyword(word=word, is_active=True)
                session.add(kw_obj)
                session.flush()
            if kw_obj.id not in kw_ids:
                kw_ids.append(kw_obj.id)

        incoming_aliases: list[str] = list(row.get("aliases") or [])
        incoming_trust = _SOURCE_TRUST.get(row.get("source", "external-ai"), 0)

        existing = session.query(MatchingEntry).filter(MatchingEntry.match_key == mk).first()

        if existing is not None:
            # alias 병합 (안티 무한증식: 중복 제거 + 최대 50개 캡)
            old_aliases: list[str] = list(existing.aliases or [])
            merged = old_aliases.copy()
            for a in incoming_aliases:
                if a not in merged:
                    merged.append(a)
                    alias_added += 1
            existing.aliases = merged[:MAX_ALIASES_PER_ENTRY]

            # 신뢰도가 같거나 더 높은 source만 필드 갱신
            existing_trust = _SOURCE_TRUST.get(existing.source, 0)
            if incoming_trust >= existing_trust:
                existing.brand = row.get("brand")
                existing.name_core = row.get("name_core")
                pq = row.get("pack_qty")
                existing.pack_qty = float(pq) if pq is not None else None
                existing.pack_unit = row.get("pack_unit")
                existing.pack_unit_kind = (
                    row.get("pack_unit_kind") or classify_unit_kind(row.get("pack_unit"))
                )
                existing.category_id = row.get("category_id")
                existing.confidence = float(row.get("confidence", existing.confidence))
                existing.source = row.get("source", existing.source)
                existing.source_record_key = row.get("source_record_key")
                existing.notes = row.get("notes")

            existing.keyword_ids = kw_ids if kw_ids else (existing.keyword_ids or [])
            session.flush()
            updated += 1

        else:
            unit_kind = row.get("pack_unit_kind") or classify_unit_kind(row.get("pack_unit"))
            pq = row.get("pack_qty")
            me = MatchingEntry(
                match_key=mk,
                brand=row.get("brand"),
                name_core=row.get("name_core"),
                pack_qty=float(pq) if pq is not None else None,
                pack_unit=row.get("pack_unit"),
                pack_unit_kind=unit_kind,
                category_id=row.get("category_id"),
                keyword_ids=kw_ids,
                confidence=float(row.get("confidence", 1.0)),
                source=row.get("source", "external-ai"),
                source_record_key=row.get("source_record_key"),
                aliases=incoming_aliases[:MAX_ALIASES_PER_ENTRY],
                notes=row.get("notes"),
            )
            session.add(me)
            session.flush()
            inserted += 1

    return {"inserted": inserted, "updated": updated, "alias_added": alias_added}


def _apply_categories(valid_rows: list[dict], session: Session, file_hash: str) -> dict:
    """신규 카테고리 → 검토 큐. 키워드 → DB 즉시 반영."""
    queued = 0
    skipped_existing = 0
    kw_added = 0
    kw_updated = 0

    for row in valid_rows:
        if row.get("type") == "new_category":
            proposed_id: str = row.get("id", "")
            if not proposed_id:
                continue

            # 이미 DB에 있는 카테고리
            if session.query(Category).filter(Category.id == proposed_id).first():
                skipped_existing += 1
                continue

            # 이미 pending 큐에 있음 (같은 파일 해시로 중복 방지)
            existing_q = session.query(CategoryReviewQueue).filter(
                CategoryReviewQueue.proposed_id == proposed_id,
                CategoryReviewQueue.source_file_hash == file_hash,
            ).first()
            if existing_q:
                continue

            # 유사 기존 카테고리 찾기 (같은 parent 하위)
            parent = row.get("parent_id")
            similar: list[str] = []
            if parent:
                sims = session.query(Category.id).filter(
                    Category.parent_id == parent
                ).limit(5).all()
                similar = [r.id for r in sims]

            q_item = CategoryReviewQueue(
                proposed_id=proposed_id,
                parent_id=parent,
                label=row.get("label"),
                label_en=row.get("label_en"),
                reason=row.get("reason", ""),
                similar_existing=similar,
                source_file_hash=file_hash,
                status="pending",
            )
            session.add(q_item)
            session.flush()
            queued += 1

        elif row.get("type") == "keyword_update":
            word = str(row.get("keyword") or row.get("word", "")).strip()
            if not word:
                continue

            cat_hint = row.get("category_hint") or row.get("category_id")
            synonyms: list[str] = list(row.get("synonyms") or [])

            existing_kw = session.query(Keyword).filter(Keyword.word == word).first()
            if existing_kw:
                # synonyms 병합
                old_syns: list[str] = list(existing_kw.synonyms or [])
                merged_syns = list(dict.fromkeys(old_syns + synonyms))
                existing_kw.synonyms = merged_syns
                if cat_hint and not existing_kw.category_id:
                    existing_kw.category_id = cat_hint
                session.flush()
                kw_updated += 1
            else:
                new_kw = Keyword(
                    word=word,
                    synonyms=synonyms if synonyms else None,
                    category_id=cat_hint,
                    is_active=True,
                )
                session.add(new_kw)
                session.flush()
                kw_added += 1

    return {
        "queued": queued,
        "skipped_existing": skipped_existing,
        "keyword_added": kw_added,
        "keyword_updated": kw_updated,
    }


def _apply_products(valid_rows: list[dict], session: Session) -> dict:
    """Product find_or_create + source_marts 갱신 (bundle_import 정합성 보장)."""
    keys = [r.get("match_key") for r in valid_rows if r.get("match_key")]
    me_map: dict[str, MatchingEntry] = {}
    if keys:
        entries = session.query(MatchingEntry).filter(MatchingEntry.match_key.in_(keys)).all()
        me_map = {e.match_key: e for e in entries}

    new_products = 0
    absorbed = 0
    source_marts_updated = 0
    skipped_no_match = 0

    for row in valid_rows:
        mk = row.get("match_key")
        me = me_map.get(mk) if mk else None
        if me is None:
            skipped_no_match += 1
            logger.debug("products_updates: match_key '%s' not in matching_entries, skip", mk)
            continue

        mart = str(row.get("mart") or row.get("source_mart", ""))

        # ── find_or_create (brand, name_core, pack_qty, pack_unit) ──────────
        q = session.query(Product)
        if me.brand is not None:
            q = q.filter(Product.brand == me.brand)
        else:
            q = q.filter(Product.brand.is_(None))
        if me.name_core is not None:
            q = q.filter(Product.name_core == me.name_core)
        else:
            q = q.filter(Product.name_core.is_(None))
        if me.pack_qty is not None:
            q = q.filter(Product.pack_qty == me.pack_qty)
        else:
            q = q.filter(Product.pack_qty.is_(None))
        if me.pack_unit is not None:
            q = q.filter(Product.pack_unit == me.pack_unit)
        else:
            q = q.filter(Product.pack_unit.is_(None))

        product = q.first()
        if product is None:
            unit_kind = classify_unit_kind(me.pack_unit)
            try:
                display_name = build_display_name(me.brand, me.name_core, me.pack_qty, me.pack_unit)
            except Exception:
                display_name = f"{me.brand or ''} {me.name_core or ''}".strip() or mk

            product = Product(
                name=display_name or mk,
                brand=me.brand,
                name_core=me.name_core,
                pack_qty=me.pack_qty,
                pack_unit=me.pack_unit,
                unit_kind=unit_kind,
                display_name=display_name,
                category_id=me.category_id,
                source_type="mart_crawl",
                source_marts=[],
                aliases=[],
            )
            session.add(product)
            session.flush()
            new_products += 1
        else:
            absorbed += 1

        # canonical_product_id write-back (다음 import 재사용)
        if not me.canonical_product_id:
            me.canonical_product_id = str(product.id)
            session.flush()

        # source_marts 갱신
        current_marts: list[str] = list(product.source_marts or [])
        if mart and mart not in current_marts:
            product.source_marts = sorted(set(current_marts) | {mart})
            source_marts_updated += 1
            session.flush()

        # aliases 갱신 (raw_name이 있을 때)
        raw_name = row.get("raw_name") or row.get("name")
        if raw_name and raw_name != product.display_name:
            current_aliases: list[str] = list(product.aliases or [])
            if (raw_name not in current_aliases
                    and len(current_aliases) < MAX_ALIASES_PER_ENTRY):
                product.aliases = current_aliases + [raw_name]
                session.flush()

    return {
        "new_products": new_products,
        "absorbed": absorbed,
        "source_marts_updated": source_marts_updated,
        "skipped_no_match": skipped_no_match,
    }


def _write_audit(
    session: Session,
    *,
    file_type: str,
    file_hash: str,
    importer: str,
    dry_run: bool,
    total_rows: int,
    passed_rows: int,
    ok: bool,
    counts: dict,
    error_message: Optional[str] = None,
) -> ImportsAudit:
    """import 이력을 imports_audit 테이블에 기록한다."""
    audit = ImportsAudit(
        file_type=file_type,
        file_hash=file_hash,
        importer=importer,
        dry_run=dry_run,
        total_rows=total_rows,
        passed_rows=passed_rows,
        ok=ok,
        applied_counts=counts,
        error_message=error_message,
    )
    session.add(audit)
    session.flush()
    return audit


def apply_import(
    file_type: str,
    payload: Any,
    payload_bytes: bytes,
    session: Session,
    *,
    dry_run: bool = False,
    importer: str = "system",
) -> ApplyResult:
    """검증 → 적용 (트랜잭션 1개, 실패 시 caller의 managed_session이 롤백 수행).

    Args:
        file_type:      matching | categories | products
        payload:        파싱된 페이로드 (list[dict] 또는 dict)
        payload_bytes:  원본 파일 바이트 (file_hash 계산용)
        session:        SQLAlchemy Session (managed_session 블록 내)
        dry_run:        True이면 검증만 수행, DB 변경 없음
        importer:       감사 로그에 기록할 요청자 식별자 (email 또는 "anonymous")

    Returns:
        ApplyResult (ok, counts 등)
    """
    if file_type not in _VALID_FILE_TYPES:
        return ApplyResult(
            ok=False,
            file_type=file_type,
            file_hash="",
            error=f"알 수 없는 file_type: {file_type!r}. 허용: {sorted(_VALID_FILE_TYPES)}",
        )

    fhash = _compute_file_hash(payload_bytes)
    whitelist = load_category_whitelist(session)

    # ── 검증 ────────────────────────────────────────────────────────────────
    if file_type == "matching":
        validation = validate_matching_updates(
            payload if isinstance(payload, list) else [], whitelist=whitelist
        )
    elif file_type == "categories":
        validation = validate_categories_keywords_updates(
            payload if isinstance(payload, dict) else {}, whitelist=whitelist
        )
    else:
        validation = validate_products_updates(
            payload if isinstance(payload, list) else [], whitelist=whitelist
        )

    if not validation.ok:
        _write_audit(
            session,
            file_type=file_type, file_hash=fhash, importer=importer,
            dry_run=dry_run, total_rows=validation.total, passed_rows=validation.passed,
            ok=False, counts={},
            error_message=f"검증 실패: {len(validation.failed_items)}건",
        )
        return ApplyResult(
            ok=False,
            file_type=file_type,
            file_hash=fhash,
            error=f"검증 실패: {len(validation.failed_items)}건",
            counts=validation.to_dict(),
        )

    # ── dry_run: 검증만 하고 반환 ────────────────────────────────────────────
    if dry_run:
        return ApplyResult(
            ok=True,
            file_type=file_type,
            file_hash=fhash,
            counts={"dry_run": True, "valid_rows": validation.passed},
        )

    # ── 적용 ────────────────────────────────────────────────────────────────
    if file_type == "matching":
        counts = _apply_matching(validation.valid_rows, session)
    elif file_type == "categories":
        counts = _apply_categories(validation.valid_rows, session, fhash)
    else:
        counts = _apply_products(validation.valid_rows, session)

    _write_audit(
        session,
        file_type=file_type, file_hash=fhash, importer=importer,
        dry_run=False, total_rows=validation.total, passed_rows=validation.passed,
        ok=True, counts=counts,
    )

    return ApplyResult(ok=True, file_type=file_type, file_hash=fhash, counts=counts)
