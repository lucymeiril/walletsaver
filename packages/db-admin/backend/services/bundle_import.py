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
    products_added: int = 0
    products_skipped: int = 0
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
) -> tuple[int, int, list[dict]]:
    """products.jsonl을 DB(BaselinePrice)에 적용한다.

    Returns:
        (added, skipped_no_match, failure_rows)
    """
    from storage.models import BaselinePrice, Product

    added = 0
    skipped = 0
    failures: list[dict] = []

    existing_keys: dict[str, MatchingEntry] = {
        e.match_key: e for e in session.query(MatchingEntry).all()
    }

    for i, row in enumerate(rows):
        mk = row.get("match_key", "")
        if not mk or mk not in existing_keys:
            skipped += 1
            continue

        price_raw = row.get("price")
        mart = row.get("mart", "")
        if price_raw is None or not mart:
            failures.append({"row": i, "msg": "price 또는 mart 누락"})
            if mode == "strict":
                raise ValueError(f"products row {i}: price 또는 mart 누락")
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

        # 연결된 Product 찾기 / 생성
        product = None
        if matching_entry.canonical_product_id:
            product = session.query(Product).filter_by(
                id=matching_entry.canonical_product_id
            ).first()

        if product is None:
            # 이름: matching_entry name_core + brand 기반
            name = f"{matching_entry.brand or ''} {matching_entry.name_core or ''}".strip() or mk
            product = Product(
                name=name,
                category_id=matching_entry.category_id,
                unit=str(matching_entry.pack_unit or "개"),
                source_type="mart_crawl",
            )
            session.add(product)
            session.flush()  # product.id 확보

        bp = BaselinePrice(
            product_id=product.id,
            price=price_val,
            source=mart,
            unit=str(matching_entry.pack_unit or "개"),
            recorded_at=captured_dt,
            raw_data={
                "raw_id": row.get("raw_id"),
                "match_key": mk,
                "mart": mart,
            },
        )
        session.add(bp)
        added += 1

    session.flush()
    return added, skipped, failures


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
        added, skipped, prod_failures = apply_products(session, products_rows, mode)
        result.products_added = added
        result.products_skipped = skipped
        for pf in prod_failures:
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
