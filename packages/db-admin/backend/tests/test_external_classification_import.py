"""test_external_classification_import.py — RD8 L3 외부 LLM 분류 import 파이프라인 테스트.

테스트 케이스:
  1. 30행 matching JSONL → preview 카운트 확인 → apply → DB에 30개 MatchingEntry
  2. whitelist 위반 category_id → ValidationReport.ok=False → apply 거부
  3. 동일 파일 2회 apply → DB 상태 불변 (멱등성), audit 2행
  4. new_categories 전용 YAML → CategoryReviewQueue 추가, categories 테이블 불변
  5. 신규 products 5개 + alias 3건 추가 → 정확한 카운트 검증
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import (
    Base,
    Category,
    CategoryReviewQueue,
    ImportsAudit,
    Keyword,
    MatchingEntry,
    Product,
)
from services.external_classification_import import (
    apply_import,
    preview_import,
    validate_matching_updates,
    validate_categories_keywords_updates,
    validate_products_updates,
)


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════

@pytest.fixture
def db_session():
    """인메모리 SQLite 세션. 매 테스트마다 새 DB."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()
    yield sess
    sess.close()


def _seed_categories(session) -> None:
    """whitelist용 기본 카테고리를 DB에 삽입한다."""
    cats = [
        Category(id="processed", name="가공식품", depth=0, is_active=True),
        Category(id="snack",     name="과자",     depth=0, is_active=True),
        Category(id="dairy",     name="유제품",   depth=0, is_active=True),
        Category(id="beverage",  name="음료",     depth=0, is_active=True),
        Category(id="seafood",   name="수산물",   depth=0, is_active=True),
        Category(id="livestock", name="축산물",   depth=0, is_active=True),
        Category(id="health",    name="건강식품", depth=0, is_active=True),
    ]
    for c in cats:
        session.add(c)
    session.commit()


def _make_matching_rows(n: int, *, category_id: str = "processed") -> list[dict]:
    """n개의 유효한 matching_updates 행을 생성한다."""
    return [
        {
            "match_key": f"테스트브랜드{i}|테스트상품{i}|{100 + i}|g",
            "brand": f"테스트브랜드{i}",
            "name_core": f"테스트상품{i}",
            "pack_qty": 100 + i,
            "pack_unit": "g",
            "pack_unit_kind": "weight",
            "category_id": category_id,
            "keywords": [f"키워드{i}", "테스트"],
            "confidence": 0.9,
            "source": "external-ai",
            "aliases": [f"[행사] 테스트상품{i}"],
            "notes": "",
        }
        for i in range(n)
    ]


def _to_bytes(rows: list[dict]) -> bytes:
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")


# ═══════════════════════════════════════════════
# TC-1: 30행 matching JSONL → apply → DB에 30개
# ═══════════════════════════════════════════════

def test_matching_30_rows_apply(db_session):
    """30행 matching JSONL을 apply하면 DB에 MatchingEntry 30개가 생성된다."""
    _seed_categories(db_session)
    rows = _make_matching_rows(30)
    payload_bytes = _to_bytes(rows)

    # Preview 단계
    preview = preview_import("matching", rows, db_session)
    assert preview.validation.ok, f"validation failed: {preview.validation.failed_items}"
    assert preview.validation.passed == 30
    assert preview.matching is not None
    assert preview.matching.new_count == 30
    assert preview.matching.update_count == 0

    # Apply 단계
    result = apply_import("matching", rows, payload_bytes, db_session, importer="test@example.com")
    db_session.commit()

    assert result.ok, f"apply failed: {result.error}"
    assert result.counts["inserted"] == 30
    assert result.counts["updated"] == 0

    # DB 검증
    db_count = db_session.query(MatchingEntry).count()
    assert db_count == 30, f"기대 30개, 실제 {db_count}개"

    # audit 기록 확인
    audit = db_session.query(ImportsAudit).first()
    assert audit is not None
    assert audit.total_rows == 30
    assert audit.passed_rows == 30
    assert audit.ok is True
    assert audit.importer == "test@example.com"


# ═══════════════════════════════════════════════
# TC-2: whitelist 위반 category_id → 검증 실패
# ═══════════════════════════════════════════════

def test_whitelist_violation_rejected(db_session):
    """whitelist에 없는 category_id를 포함하면 ValidationReport.ok=False, apply 거부."""
    _seed_categories(db_session)

    row = {
        "match_key": "테스트|상품|100|g",
        "brand": "테스트",
        "name_core": "상품",
        "pack_qty": 100,
        "pack_unit": "g",
        "category_id": "존재하지않는카테고리",  # 위반
        "keywords": ["테스트"],
        "confidence": 0.9,
        "source": "external-ai",
    }

    from services.external_classification_import import load_category_whitelist
    whitelist = load_category_whitelist(db_session)

    report = validate_matching_updates([row], whitelist=whitelist)
    assert not report.ok, "whitelist 위반이 감지되어야 함"
    assert len(report.failed_items) > 0
    assert any("whitelist" in item["reason"] for item in report.failed_items)

    # apply도 거부되어야 함
    payload_bytes = _to_bytes([row])
    result = apply_import("matching", [row], payload_bytes, db_session, importer="test@example.com")
    db_session.commit()

    assert not result.ok
    db_count = db_session.query(MatchingEntry).count()
    assert db_count == 0, "검증 실패 시 DB에 쓰지 않아야 함"

    # 실패 audit도 기록됨
    audit = db_session.query(ImportsAudit).first()
    assert audit is not None
    assert audit.ok is False


# ═══════════════════════════════════════════════
# TC-3: 동일 파일 2회 apply → 멱등성
# ═══════════════════════════════════════════════

def test_idempotent_double_apply(db_session):
    """같은 matching 파일을 2회 apply해도 DB 상태(MatchingEntry 수)는 변화 없다.
    audit 기록은 2건이어야 한다."""
    _seed_categories(db_session)
    rows = _make_matching_rows(10)
    payload_bytes = _to_bytes(rows)

    # 첫 번째 apply
    r1 = apply_import("matching", rows, payload_bytes, db_session, importer="admin@example.com")
    db_session.commit()
    assert r1.ok
    count_after_first = db_session.query(MatchingEntry).count()
    assert count_after_first == 10

    # 두 번째 apply (동일 파일)
    r2 = apply_import("matching", rows, payload_bytes, db_session, importer="admin@example.com")
    db_session.commit()
    assert r2.ok
    count_after_second = db_session.query(MatchingEntry).count()
    assert count_after_second == 10, f"멱등성 위반: 첫 번째 {count_after_first}개, 두 번째 {count_after_second}개"

    # 두 번째는 모두 update (insert 없음)
    assert r2.counts["inserted"] == 0
    assert r2.counts["updated"] == 10

    # audit 행은 2개
    audit_count = db_session.query(ImportsAudit).count()
    assert audit_count == 2, f"audit 2건 기대, 실제 {audit_count}건"

    # file_hash가 동일
    audits = db_session.query(ImportsAudit).all()
    assert audits[0].file_hash == audits[1].file_hash


# ═══════════════════════════════════════════════
# TC-4: new_categories YAML → CategoryReviewQueue
# ═══════════════════════════════════════════════

def test_categories_yaml_review_queue(db_session):
    """new_categories가 있는 YAML을 apply하면 CategoryReviewQueue에 추가되고
    categories 테이블은 변경되지 않는다."""
    _seed_categories(db_session)
    initial_cat_count = db_session.query(Category).count()

    payload = {
        "categories": [
            {
                "id": "instant_food",
                "label": "즉석조리식품",
                "parent_id": "processed",
                "reason": "레토르트·간편식 분류 필요",
            },
            {
                "id": "premium_snack",
                "label": "프리미엄 과자",
                "parent_id": "snack",
                "reason": "수입과자 SKU 증가로 분류 필요",
            },
        ],
        "keywords": [],
    }
    payload_bytes = b"# yaml payload"

    result = apply_import("categories", payload, payload_bytes, db_session, importer="admin@example.com")
    db_session.commit()

    assert result.ok, f"apply 실패: {result.error}"

    # categories 테이블 불변
    final_cat_count = db_session.query(Category).count()
    assert final_cat_count == initial_cat_count, "categories 테이블이 변경되어서는 안 됨"

    # CategoryReviewQueue에 2건
    queue_count = db_session.query(CategoryReviewQueue).count()
    assert queue_count == 2, f"queue 2건 기대, 실제 {queue_count}건"

    proposed_ids = {
        r.proposed_id for r in db_session.query(CategoryReviewQueue).all()
    }
    assert "instant_food" in proposed_ids
    assert "premium_snack" in proposed_ids

    # 모두 pending 상태
    pending = db_session.query(CategoryReviewQueue).filter(
        CategoryReviewQueue.status == "pending"
    ).count()
    assert pending == 2


def test_categories_yaml_same_file_twice(db_session):
    """동일한 categories YAML을 2회 apply해도 CategoryReviewQueue 중복 없음."""
    _seed_categories(db_session)

    payload = {
        "categories": [
            {
                "id": "instant_food",
                "label": "즉석조리식품",
                "parent_id": "processed",
                "reason": "레토르트·간편식 분류 필요",
            },
        ],
        "keywords": [],
    }
    payload_bytes = b"# same yaml payload"

    apply_import("categories", payload, payload_bytes, db_session, importer="admin@example.com")
    db_session.commit()
    apply_import("categories", payload, payload_bytes, db_session, importer="admin@example.com")
    db_session.commit()

    # 같은 파일 해시로 2회 — UniqueConstraint로 중복 방지
    queue_count = db_session.query(CategoryReviewQueue).count()
    assert queue_count == 1, f"중복 큐 방지 실패: {queue_count}건"


# ═══════════════════════════════════════════════
# TC-5: products 5개 신규 + alias 3건 추가
# ═══════════════════════════════════════════════

def test_products_new_and_alias_additions(db_session):
    """5개 MatchingEntry를 기반으로 products apply 시 Product 5개 신규 생성.
    이후 matching apply에서 3개 항목에 alias를 추가하면 alias_added==3."""
    _seed_categories(db_session)

    # ── 사전 준비: 5개 MatchingEntry 삽입 ──────────────────────────────────
    matching_rows = [
        {
            "match_key": f"노브랜드|상품{i}|{200 + i}|g",
            "brand": "노브랜드",
            "name_core": f"상품{i}",
            "pack_qty": float(200 + i),
            "pack_unit": "g",
            "pack_unit_kind": "weight",
            "category_id": "processed",
            "keywords": ["노브랜드"],
            "confidence": 0.9,
            "source": "external-ai",
            "aliases": [],
            "notes": "",
        }
        for i in range(5)
    ]
    mb = _to_bytes(matching_rows)
    r_match = apply_import("matching", matching_rows, mb, db_session, importer="test@example.com")
    db_session.commit()
    assert r_match.ok
    assert r_match.counts["inserted"] == 5

    # ── products_updates: MatchingEntry 참조하는 5개 행 ────────────────────
    product_rows = [
        {
            "match_key": f"노브랜드|상품{i}|{200 + i}|g",
            "mart": "emart",
        }
        for i in range(5)
    ]
    pb = _to_bytes(product_rows)
    r_products = apply_import("products", product_rows, pb, db_session, importer="test@example.com")
    db_session.commit()
    assert r_products.ok, f"products apply 실패: {r_products.error}"
    assert r_products.counts["new_products"] == 5, (
        f"신규 Product 5개 기대, 실제: {r_products.counts['new_products']}"
    )

    # DB 검증: Product 5개
    product_count = db_session.query(Product).count()
    assert product_count == 5

    # ── alias 3건 추가: 기존 3개 match_key에 alias 추가 ────────────────────
    alias_rows = [
        {
            "match_key": f"노브랜드|상품{i}|{200 + i}|g",
            "brand": "노브랜드",
            "name_core": f"상품{i}",
            "pack_qty": float(200 + i),
            "pack_unit": "g",
            "pack_unit_kind": "weight",
            "category_id": "processed",
            "keywords": ["노브랜드"],
            "confidence": 0.9,
            "source": "external-ai",
            "aliases": [f"[행사] 노브랜드 상품{i}", f"[할인] 상품{i}"],
            "notes": "",
        }
        for i in range(3)  # 첫 3개만
    ]
    ab = _to_bytes(alias_rows)
    r_alias = apply_import("matching", alias_rows, ab, db_session, importer="test@example.com")
    db_session.commit()
    assert r_alias.ok
    # 3행 모두 update (기존에 있으므로)
    assert r_alias.counts["updated"] == 3
    # 각 항목에 2개씩 새 alias → 6건 추가
    assert r_alias.counts["alias_added"] == 6, (
        f"alias 6건(항목당 2개×3) 기대, 실제: {r_alias.counts['alias_added']}"
    )

    # DB alias 값 직접 확인
    for i in range(3):
        mk = f"노브랜드|상품{i}|{200 + i}|g"
        entry = db_session.query(MatchingEntry).filter(MatchingEntry.match_key == mk).one()
        assert f"[행사] 노브랜드 상품{i}" in (entry.aliases or [])
        assert f"[할인] 상품{i}" in (entry.aliases or [])


# ═══════════════════════════════════════════════
# TC-6: 검증기 단위 테스트
# ═══════════════════════════════════════════════

def test_validate_matching_missing_fields():
    """필수 필드 누락 시 ValidationReport.ok=False."""
    rows = [{"brand": "X", "name_core": "Y"}]  # match_key 등 누락
    report = validate_matching_updates(rows)
    assert not report.ok
    assert len(report.failed_items) > 0


def test_validate_matching_bad_confidence():
    """confidence 범위 초과(1.5) 시 ValidationReport에 실패 항목."""
    rows = [{
        "match_key": "A|B|100|g",
        "brand": "A",
        "name_core": "B",
        "pack_qty": 100,
        "pack_unit": "g",
        "category_id": "processed",
        "keywords": [],
        "confidence": 1.5,  # 범위 초과
        "source": "external-ai",
    }]
    report = validate_matching_updates(rows)
    assert not report.ok
    assert any(item["field"] == "confidence" for item in report.failed_items)


def test_validate_matching_bad_source():
    """허용되지 않는 source 값 시 ValidationReport에 실패 항목."""
    rows = [{
        "match_key": "A|B|100|g",
        "brand": "A",
        "name_core": "B",
        "pack_qty": 100,
        "pack_unit": "g",
        "category_id": "processed",
        "keywords": [],
        "confidence": 0.9,
        "source": "invalid-source",  # 잘못된 source
    }]
    report = validate_matching_updates(rows)
    assert not report.ok
    assert any(item["field"] == "source" for item in report.failed_items)


def test_validate_categories_missing_reason():
    """new_categories 항목에 reason 없으면 ValidationReport.ok=False."""
    payload = {
        "categories": [
            {"id": "new_cat", "label": "새 카테고리"}  # reason 누락
        ],
        "keywords": [],
    }
    report = validate_categories_keywords_updates(payload)
    assert not report.ok


def test_validate_products_missing_mart():
    """mart 없으면 ValidationReport.ok=False."""
    rows = [{"match_key": "A|B|100|g"}]  # mart 누락
    report = validate_products_updates(rows)
    assert not report.ok
    assert any(item["field"] == "mart" for item in report.failed_items)


def test_keyword_apply_creates_keywords(db_session):
    """categories YAML의 keywords 항목이 keywords 테이블에 반영된다."""
    _seed_categories(db_session)

    payload = {
        "categories": [],
        "keywords": [
            {"keyword": "즉석면", "category_hint": "processed", "synonyms": ["봉지라면"]},
            {"keyword": "통조림", "category_hint": "processed"},
        ],
    }
    payload_bytes = b"# kw only yaml"
    result = apply_import("categories", payload, payload_bytes, db_session, importer="admin@example.com")
    db_session.commit()
    assert result.ok

    kw_count = db_session.query(Keyword).count()
    assert kw_count == 2

    kw = db_session.query(Keyword).filter(Keyword.word == "즉석면").first()
    assert kw is not None
    assert "봉지라면" in (kw.synonyms or [])
