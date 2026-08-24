"""bundle_import.py — RD7 3종 파일 번들 import 서비스.

처리 대상:
    1. matching_updates.jsonl  — MatchingEntry upsert (match_key 기준)
    2. categories_keywords_updates.yaml — 새 categories/keywords 추가/병합
    3. products.jsonl          — raw_id → product 매핑 (BaselinePrice 등록)

충돌 정책: matching_sync.py 참조 (human > external-ai > crawler-auto)

트랜잭션 순서:
    matching → categories/keywords → products
    (products는 match_key가 matching_entries에 존재해야 하므로 반드시 마지막)
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import yaml
from sqlalchemy.orm import Session

from services.matching_sync import (
    ImportDiff,
    _compute_diff,
    _apply_diff,
    _SOURCE_TRUST,
)
from storage.models import Category, Keyword, MatchingEntry

# brand가 없음을 나타내는 sentinel 값 집합 (Fix-4: D-VERIFY 재현 #2)
_NULL_BRAND_MARKERS: frozenset[str] = frozenset({"브랜드없음", "no_brand", ""})

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 결과 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MatchingPreview:
    to_add: int = 0
    to_update: int = 0
    conflicts: list[dict] = field(default_factory=list)  # {match_key, reason}
    pending_human: int = 0   # confidence < 0.6 → status=pending_human


@dataclass
class TaxonomyPreview:
    new_categories: int = 0
    new_keywords: int = 0
    merges: list[dict] = field(default_factory=list)   # 이미 존재하는 항목
    errors: list[dict] = field(default_factory=list)   # parent_id 미존재 등


@dataclass
class ProductsPreview:
    to_add: int = 0
    skipped_no_match: int = 0
    errors: list[dict] = field(default_factory=list)


@dataclass
class BundlePreview:
    batch_id: str
    matching: MatchingPreview
    taxonomy: TaxonomyPreview
    products: ProductsPreview


@dataclass
class BundleResult:
    batch_id: str
    ok: bool
    matching_inserted: int = 0
    matching_updated: int = 0
    matching_conflicts: int = 0
    taxonomy_categories_added: int = 0
    taxonomy_keywords_added: int = 0
    # ── products 카운터 (Fix-1: D-VERIFY-002 — 의미별 분리) ──────────────────
    # products_added: 신규 Product INSERT 수 (구 의미와 동일하게 유지 — API 하위호환)
    products_added: int = 0         # = products_created (backward compat alias)
    products_processed: int = 0     # 처리한 products.jsonl row 수 (유효 + 중복 포함)
    products_created: int = 0       # 진짜 신규 product INSERT 수
    products_matched: int = 0       # 기존 product를 찾은 수 (dedup)
    aliases_added: int = 0          # product.aliases 에 새로 추가된 raw_name 수
    baselines_upserted: int = 0     # BaselinePrice 신규 INSERT 수
    baselines_skipped: int = 0      # 동일 (product_id, mart_code, recorded_at) 기존 row → 업데이트만
    source_marts_extended: int = 0  # product.source_marts 에 마트가 추가된 수
    products_rejected: int = 0      # mart_code/name_core 누락으로 거부된 row 수
    products_skipped: int = 0       # match_key 없음으로 skip된 row 수
    failure_rows: list[dict] = field(default_factory=list)
    idempotent: bool = False


# ──────────────────────────────────────────────────────────────────────────────
# 파일 파싱
# ──────────────────────────────────────────────────────────────────────────────

def parse_jsonl(content: bytes) -> list[dict]:
    """JSONL 바이트 → list[dict]."""
    text = content.decode("utf-8-sig")
    rows: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSONL 파싱 오류 (라인 {lineno}): {e}") from e
        if not isinstance(obj, dict):
            raise ValueError(f"JSONL 라인 {lineno}은 object(dict)여야 합니다")
        rows.append(obj)
    return rows


def parse_yaml(content: bytes) -> dict:
    """YAML 바이트 → dict (최상위가 dict인 경우)."""
    text = content.decode("utf-8-sig")
    data = yaml.safe_load(text)
    if data is None:
        return {"categories": [], "keywords": []}
    if not isinstance(data, dict):
        raise ValueError("YAML 최상위 구조는 dict여야 합니다 ({categories: [...], keywords: [...]})")
    return data


# ──────────────────────────────────────────────────────────────────────────────
# matching_updates 검증 & 미리보기
# ──────────────────────────────────────────────────────────────────────────────

def preview_matching(rows: list[dict], session: Session) -> tuple[ImportDiff, MatchingPreview]:
    """matching_updates.jsonl rows를 분석해 diff + preview 반환."""
    from services.import_validator import validate_lenient, _build_match_key

    # match_key 보정
    normalized: list[dict] = []
    for row in rows:
        r = dict(row)
        if not r.get("match_key"):
            mk = _build_match_key(r)
            if mk:
                r["match_key"] = mk
        normalized.append(r)

    # lenient 검증으로 유효 rows만 diff 계산
    result = validate_lenient(normalized, session)
    diff = _compute_diff(session, result.valid_rows)

    mp = MatchingPreview(
        to_add=len(diff.to_add),
        to_update=len(diff.to_update),
        conflicts=[
            {"match_key": ex.get("match_key"), "reason": reason}
            for ex, _inc, reason in diff.conflicts
        ],
        pending_human=sum(
            1 for r in diff.to_add + [new for _, new in diff.to_update]
            if float(r.get("confidence", 1.0)) < 0.6
        ),
    )
    return diff, mp


# ──────────────────────────────────────────────────────────────────────────────
# categories_keywords_updates 검증 & 미리보기
# ──────────────────────────────────────────────────────────────────────────────

def preview_taxonomy(
    data: dict,
    session: Session,
) -> TaxonomyPreview:
    """YAML 파싱 결과를 분석해 TaxonomyPreview 반환."""
    preview = TaxonomyPreview()

    # 현재 DB 상태
    existing_cat_ids: set[str] = {
        c.id for c in session.query(Category).all()
    }
    existing_kw_words: dict[str, int] = {
        k.word: k.id for k in session.query(Keyword).all()
    }

    # 같은 YAML 내 신규 category id도 유효 부모로 취급
    incoming_cat_ids: set[str] = set()
    for cat in data.get("categories", []):
        cat_id = str(cat.get("id", "")).strip()
        if cat_id:
            incoming_cat_ids.add(cat_id)

    for cat in data.get("categories", []):
        cat_id = str(cat.get("id", "")).strip()
        if not cat_id:
            preview.errors.append({"field": "category.id", "msg": "id 누락"})
            continue

        parent_id = cat.get("parent_id")
        if parent_id and str(parent_id) not in existing_cat_ids and str(parent_id) not in incoming_cat_ids:
            preview.errors.append({
                "field": "category.parent_id",
                "cat_id": cat_id,
                "msg": f"parent_id '{parent_id}' 가 categories 테이블에 없음",
            })
            continue

        if cat_id in existing_cat_ids:
            preview.merges.append({"type": "category", "id": cat_id, "action": "update"})
        else:
            preview.new_categories += 1

    for kw in data.get("keywords", []):
        word = str(kw.get("word", "")).strip()
        if not word:
            preview.errors.append({"field": "keyword.word", "msg": "word 누락"})
            continue

        if word in existing_kw_words:
            preview.merges.append({"type": "keyword", "word": word, "action": "update"})
        else:
            preview.new_keywords += 1

    return preview


# ──────────────────────────────────────────────────────────────────────────────
# products 검증 & 미리보기
# ──────────────────────────────────────────────────────────────────────────────

def preview_products(
    rows: list[dict],
    session: Session,
    incoming_match_keys: set[str],
) -> ProductsPreview:
    """products.jsonl rows를 분석해 ProductsPreview 반환.

    match_key가 DB 또는 incoming matching_updates에 없으면 skipped_no_match.
    """
    preview = ProductsPreview()

    existing_keys: set[str] = {
        e.match_key for e in session.query(MatchingEntry.match_key).all()
    }
    all_valid_keys = existing_keys | incoming_match_keys

    for i, row in enumerate(rows):
        mk = row.get("match_key", "")
        if not mk:
            preview.errors.append({"row": i, "msg": "match_key 누락"})
            continue
        if mk not in all_valid_keys:
            preview.skipped_no_match += 1
            continue

        # 필수 필드 검증
        if row.get("price") is None:
            preview.errors.append({"row": i, "msg": "price 누락"})
            continue
        if not row.get("mart"):
            preview.errors.append({"row": i, "msg": "mart 누락"})
            continue

        preview.to_add += 1

    return preview


# ──────────────────────────────────────────────────────────────────────────────
# 실제 적용 함수
# ──────────────────────────────────────────────────────────────────────────────

def apply_matching(session: Session, diff: ImportDiff) -> tuple[int, int, int]:
    """matching_entries에 diff를 적용한다. 호출 후 commit은 caller 책임."""
    _apply_diff(session, diff)
    return len(diff.to_add), len(diff.to_update), len(diff.conflicts)


def apply_taxonomy(session: Session, data: dict, existing_cat_ids: set[str]) -> tuple[int, int]:
    """categories/keywords를 DB에 추가/갱신한다. 오류 row는 skip."""
    cats_added = 0
    kws_added = 0

    existing_kw_words: dict[str, Keyword] = {
        k.word: k for k in session.query(Keyword).all()
    }

    # categories — parent_id 유효한 것만 적용
    # 최대 2번 패스 (parent_id가 같은 YAML 내 신규 카테고리를 참조하는 경우)
    pending_cats = list(data.get("categories", []))
    for _pass in range(2):
        remaining = []
        current_ids: set[str] = {
            c.id for c in session.query(Category).all()
        }
        for cat in pending_cats:
            cat_id = str(cat.get("id", "")).strip()
            if not cat_id:
                continue
            parent_id = cat.get("parent_id")
            if parent_id and str(parent_id) not in current_ids:
                remaining.append(cat)
                continue

            existing = session.query(Category).filter_by(id=cat_id).first()
            if existing:
                # 이미 존재: 이름/속성 업데이트
                if cat.get("name"):
                    existing.name = cat["name"]
                if cat.get("icon"):
                    existing.icon = cat["icon"]
            else:
                depth = int(cat.get("depth", 0))
                new_cat = Category(
                    id=cat_id,
                    name=str(cat.get("name", cat_id)),
                    parent_id=str(parent_id) if parent_id else None,
                    depth=depth,
                    sort_order=int(cat.get("sort_order", 0)),
                    is_active=True,
                )
                session.add(new_cat)
                cats_added += 1
        pending_cats = remaining

    session.flush()

    # keywords
    for kw in data.get("keywords", []):
        word = str(kw.get("word", "")).strip()
        if not word:
            continue
        if word in existing_kw_words:
            # 기존 키워드 병합 (synonyms 추가)
            existing_kw = existing_kw_words[word]
            if kw.get("synonyms"):
                old_synonyms = existing_kw.synonyms or []
                new_synonyms = list(set(old_synonyms + list(kw["synonyms"])))
                existing_kw.synonyms = new_synonyms
        else:
            new_kw = Keyword(
                word=word,
                synonyms=list(kw.get("synonyms", [])) or None,
                category_id=kw.get("category_id"),
                is_active=True,
            )
            session.add(new_kw)
            existing_kw_words[word] = new_kw
            kws_added += 1

    session.flush()
    return cats_added, kws_added


def apply_products(
    session: Session,
    rows: list[dict],
    mode: str,
) -> dict:
    """products.jsonl을 DB(Product + BaselinePrice)에 적용한다.

    Fix-1 (D-VERIFY-002): 카운터 의미 분리 — 신규 product 수, alias 추가 수 등 분리.
    Fix-2 (D-VERIFY-003): product 생성/갱신 시 unit = pack_unit 으로 동기화.
    Fix-3 (D-VERIFY-004): canonicalize_pack 호출 → kg↔g, L↔ml 같은 product로 흡수.
    Fix-4 (자기검열 #2):   brand=null/"브랜드없음" → mart_code 로 fallback.
                           name_core=None → reject + 오류 로그.
    Fix-5 (자기검열 #3):   mart_code=None/공백 → INSERT 거부, 오류 로그.

    Returns:
        dict with keys: processed, created, matched, aliases_added, baselines_upserted,
                        baselines_skipped, source_marts_extended, rejected, skipped, failures
    """
    from storage.models import BaselinePrice, Product
    from services.unit_utils import (
        canonicalize_pack,
        classify_unit_kind,
        normalize_unit_price,
        build_display_name,
    )

    processed = 0
    created = 0
    matched = 0
    aliases_added = 0
    baselines_upserted = 0
    baselines_skipped = 0
    source_marts_extended = 0
    rejected = 0
    skipped = 0
    failures: list[dict] = []

    existing_keys: dict[str, MatchingEntry] = {
        e.match_key: e for e in session.query(MatchingEntry).all()
    }

    for i, row in enumerate(rows):
        mk = row.get("match_key", "")

        # Fix-5: mart_code/mart 없으면 거부
        mart = (row.get("mart") or "").strip()
        if not mart:
            rejected += 1
            msg = f"products row {i}: mart_code 없음 → INSERT 거부"
            logger.warning(msg)
            failures.append({"row": i, "msg": "mart_code 없음 → INSERT 거부"})
            if mode == "strict":
                raise ValueError(msg)
            continue

        if not mk or mk not in existing_keys:
            skipped += 1
            continue

        price_raw = row.get("price")
        if price_raw is None:
            failures.append({"row": i, "msg": "price 누락"})
            if mode == "strict":
                raise ValueError(f"products row {i}: price 누락")
            continue

        try:
            price_val = float(price_raw)
        except (TypeError, ValueError):
            failures.append({"row": i, "msg": f"price '{price_raw}' 는 숫자가 아님"})
            if mode == "strict":
                raise ValueError(f"products row {i}: price 변환 실패")
            continue

        # captured_at 파싱
        captured_raw = row.get("captured_at")
        if captured_raw:
            try:
                if isinstance(captured_raw, str):
                    captured_dt = datetime.fromisoformat(captured_raw.replace("Z", "+00:00"))
                else:
                    captured_dt = datetime.now(timezone.utc)
            except ValueError:
                captured_dt = datetime.now(timezone.utc)
        else:
            captured_dt = datetime.now(timezone.utc)

        matching_entry = existing_keys[mk]

        # Fix-4: name_core=None → 거부
        name_core_raw = (matching_entry.name_core or "").strip()
        if not name_core_raw:
            rejected += 1
            msg = f"products row {i}: matching_entry.name_core가 None → INSERT 거부"
            logger.warning(msg)
            failures.append({"row": i, "msg": "name_core 없음 → INSERT 거부"})
            if mode == "strict":
                raise ValueError(msg)
            continue

        # Fix-4: brand fallback — None/"브랜드없음"/""/"no_brand" → mart_code
        brand_raw = (matching_entry.brand or "").strip()
        if not brand_raw or brand_raw in _NULL_BRAND_MARKERS:
            brand = mart  # mart_code를 brand fallback으로 사용
        else:
            brand = brand_raw

        # Fix-3: pack 단위 표준화 (kg→g, L→ml 등)
        raw_pack_qty = matching_entry.pack_qty
        raw_pack_unit = (matching_entry.pack_unit or "").strip() or None
        if raw_pack_qty is not None and raw_pack_unit:
            canon_qty, canon_unit = canonicalize_pack(raw_pack_qty, raw_pack_unit)
        else:
            canon_qty, canon_unit = raw_pack_qty, raw_pack_unit

        unit_kind = classify_unit_kind(canon_unit)

        # find_or_create Product — UNIQUE(brand, name_core, pack_qty, pack_unit)
        product = session.query(Product).filter_by(
            brand=brand,
            name_core=name_core_raw,
            pack_qty=canon_qty,
            pack_unit=canon_unit,
        ).first()

        if product is None:
            display = build_display_name(brand, name_core_raw, canon_qty, canon_unit)
            product = Product(
                name=display,
                category_id=matching_entry.category_id,
                # Fix-2: unit = pack_unit (레거시 호환, 신규 코드는 pack_unit 사용)
                unit=str(canon_unit or "EA"),
                source_type="mart_crawl",
                brand=brand,
                name_core=name_core_raw,
                pack_qty=canon_qty,
                pack_unit=canon_unit,
                unit_kind=unit_kind,
                display_name=display,
                source_marts=[mart],
                aliases=[],
            )
            session.add(product)
            session.flush()  # product.id 확보
            created += 1
        else:
            matched += 1
            # Fix-2: 기존 product.unit도 동기화
            expected_unit = str(canon_unit or "EA")
            if product.unit != expected_unit:
                product.unit = expected_unit
            if product.unit_kind != unit_kind:
                product.unit_kind = unit_kind

        # matching_entry.canonical_product_id 갱신 (soft-link)
        if matching_entry.canonical_product_id != product.id:
            matching_entry.canonical_product_id = str(product.id)

        # source_marts 갱신
        existing_marts = list(product.source_marts or [])
        if mart not in existing_marts:
            existing_marts.append(mart)
            product.source_marts = existing_marts
            source_marts_extended += 1

        # aliases 갱신 (raw_name이 있을 때만)
        raw_name = row.get("raw_name", "")
        if raw_name:
            existing_aliases = list(product.aliases or [])
            if raw_name not in existing_aliases:
                existing_aliases.append(raw_name)
                product.aliases = existing_aliases
                aliases_added += 1

        # 정규화 단가 계산
        norm_price, norm_basis = normalize_unit_price(price_val, canon_qty, canon_unit, unit_kind)

        # UPSERT BaselinePrice — UNIQUE(product_id, mart_code, recorded_at)
        bp = session.query(BaselinePrice).filter_by(
            product_id=product.id,
            mart_code=mart,
            recorded_at=captured_dt,
        ).first()

        if bp is None:
            bp = BaselinePrice(
                product_id=product.id,
                price=price_val,
                source=mart,
                mart_code=mart,
                unit=str(canon_unit or "EA"),
                recorded_at=captured_dt,
                pack_qty_snapshot=canon_qty,
                pack_unit_snapshot=canon_unit,
                unit_price_normalized=norm_price,
                unit_price_basis=norm_basis,
                raw_data={
                    "raw_id": row.get("raw_id"),
                    "match_key": mk,
                    "mart": mart,
                },
            )
            session.add(bp)
            baselines_upserted += 1
        else:
            # 동일 (product_id, mart_code, recorded_at) → 가격/단가만 갱신
            bp.price = price_val
            bp.unit_price_normalized = norm_price
            bp.unit_price_basis = norm_basis
            bp.pack_qty_snapshot = canon_qty
            bp.pack_unit_snapshot = canon_unit
            baselines_skipped += 1

        processed += 1

    session.flush()

    return {
        "processed": processed,
        "created": created,
        "matched": matched,
        "aliases_added": aliases_added,
        "baselines_upserted": baselines_upserted,
        "baselines_skipped": baselines_skipped,
        "source_marts_extended": source_marts_extended,
        "rejected": rejected,
        "skipped": skipped,
        "failures": failures,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 번들 미리보기 (통합 진입점)
# ──────────────────────────────────────────────────────────────────────────────

def compute_bundle_preview(
    session: Session,
    batch_id: str,
    matching_rows: Optional[list[dict]],
    taxonomy_data: Optional[dict],
    products_rows: Optional[list[dict]],
) -> BundlePreview:
    """3종 파일을 모두 분석해 BundlePreview를 반환한다. DB에는 아무것도 쓰지 않는다."""
    diff: Optional[ImportDiff] = None
    mp = MatchingPreview()
    tp = TaxonomyPreview()
    pp = ProductsPreview()

    incoming_match_keys: set[str] = set()

    if matching_rows:
        diff, mp = preview_matching(matching_rows, session)
        for r in diff.to_add + [new for _, new in diff.to_update]:
            if r.get("match_key"):
                incoming_match_keys.add(r["match_key"])

    if taxonomy_data:
        tp = preview_taxonomy(taxonomy_data, session)

    if products_rows:
        pp = preview_products(products_rows, session, incoming_match_keys)

    return BundlePreview(batch_id=batch_id, matching=mp, taxonomy=tp, products=pp)


# ──────────────────────────────────────────────────────────────────────────────
# 번들 적용 (통합 진입점)
# ──────────────────────────────────────────────────────────────────────────────

def apply_bundle(
    session: Session,
    batch_id: str,
    matching_rows: Optional[list[dict]],
    taxonomy_data: Optional[dict],
    products_rows: Optional[list[dict]],
    mode: str = "strict",
) -> BundleResult:
    """3종 파일을 순서대로 적용한다: matching → taxonomy → products.

    mode='strict' : 어느 단계라도 실패 시 전체 rollback (caller가 session.rollback() 담당)
    mode='lenient': 실패 row를 skip하고 나머지 적용
    """
    result = BundleResult(batch_id=batch_id, ok=True)
    failure_rows: list[dict] = []

    # ── STEP 1: matching ──
    if matching_rows:
        from services.import_validator import validate_lenient, validate_strict, _build_match_key

        normalized: list[dict] = []
        for row in matching_rows:
            r = dict(row)
            if not r.get("match_key"):
                mk = _build_match_key(r)
                if mk:
                    r["match_key"] = mk
            normalized.append(r)

        if mode == "strict":
            val_result = validate_strict(normalized, session)
            if val_result.errors:
                raise ValueError(
                    f"matching_updates strict 검증 실패: {val_result.errors[:5]}"
                )
        else:
            val_result = validate_lenient(normalized, session)
            for ridx, msg in val_result.errors:
                failure_rows.append({"file": "matching_updates.jsonl", "row": ridx, "msg": msg})

        diff = _compute_diff(session, val_result.valid_rows)
        ins, upd, conf = apply_matching(session, diff)
        result.matching_inserted = ins
        result.matching_updated = upd
        result.matching_conflicts = conf

    # ── STEP 2: taxonomy ──
    if taxonomy_data:
        existing_cat_ids: set[str] = {
            c.id for c in session.query(Category).all()
        }
        # preview로 먼저 오류 확인
        tp = preview_taxonomy(taxonomy_data, session)
        if tp.errors and mode == "strict":
            raise ValueError(
                f"categories_keywords_updates strict 검증 실패: {tp.errors[:5]}"
            )
        for err in tp.errors:
            failure_rows.append({
                "file": "categories_keywords_updates.yaml",
                "field": err.get("field"),
                "msg": err.get("msg"),
            })

        # 오류 있는 cats 제외하고 적용
        if tp.errors and mode == "lenient":
            # 오류 cat_id 목록 추출
            error_cat_ids = {
                e.get("cat_id") for e in tp.errors if e.get("cat_id")
            }
            filtered_data = {
                "categories": [
                    c for c in taxonomy_data.get("categories", [])
                    if str(c.get("id", "")) not in error_cat_ids
                ],
                "keywords": taxonomy_data.get("keywords", []),
            }
            cats_added, kws_added = apply_taxonomy(session, filtered_data, existing_cat_ids)
        else:
            cats_added, kws_added = apply_taxonomy(session, taxonomy_data, existing_cat_ids)

        result.taxonomy_categories_added = cats_added
        result.taxonomy_keywords_added = kws_added

    # ── STEP 3: products ──
    if products_rows:
        prod_result = apply_products(session, products_rows, mode)
        result.products_processed = prod_result["processed"]
        result.products_created = prod_result["created"]
        result.products_matched = prod_result["matched"]
        result.aliases_added = prod_result["aliases_added"]
        result.baselines_upserted = prod_result["baselines_upserted"]
        result.baselines_skipped = prod_result["baselines_skipped"]
        result.source_marts_extended = prod_result["source_marts_extended"]
        result.products_rejected = prod_result["rejected"]
        result.products_skipped = prod_result["skipped"]
        # products_added = products_created (하위 호환 alias)
        result.products_added = prod_result["created"]
        for pf in prod_result["failures"]:
            failure_rows.append({"file": "products.jsonl", **pf})

    result.failure_rows = failure_rows
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 실패 행 CSV 직렬화
# ──────────────────────────────────────────────────────────────────────────────

def make_failure_csv(failure_rows: list[dict]) -> bytes:
    """실패 행 목록을 UTF-8 BOM CSV 바이트로 반환 (엑셀 한글 호환)."""
    buf = io.StringIO()
    fieldnames = ["파일", "행번호", "오류메시지"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for fr in failure_rows:
        writer.writerow({
            "파일": fr.get("file", ""),
            "행번호": str(fr.get("row", "")),
            "오류메시지": fr.get("msg", fr.get("message", "")),
        })
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
