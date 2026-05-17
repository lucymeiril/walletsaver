"""
test_canonical_seed.py — Phase B6 시드 API 통합 테스트.

TDD 케이스:
  1. test_full_fixture_seed: 4사 fixture(20건) → SeedResult 전수 검증
  2. test_idempotency: 동일 fixture 2회 → canonical_inserted=0, canonical_updated=20
  3. test_dry_run: dry_run=True → rollback 후 DB 0건
  4. test_empty_fixture_dir: 빈 디렉터리 → errors=[], 정상 종료
  5. test_single_card_each_mart: 4사 카드 1개씩 → 4 canonical, 1 review_queue
  6. test_category_seed_idempotency: 카테고리 2회 시드 → 49개 유지
  7. test_orm_join: CanonicalProduct ↔ CategoryNode JOIN 정상
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session

# ── 경로 보정 ──────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_BACKEND_DIR), str(_SHARED_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from storage.canonical_models import (
    CanonicalBase,
    CanonicalProduct as ORM_CanonicalProduct,
    CategoryNode as ORM_CategoryNode,
    MartSkuAlias as ORM_MartSkuAlias,
    PriceObservation as ORM_PriceObservation,
    ProductReviewQueue as ORM_ProductReviewQueue,
    bootstrap_canonical_tables,
)
from storage.canonical_seed import (
    SeedResult,
    seed_categories_from_yaml,
    seed_canonicals_from_fixture_dir,
    seed_from_raw_batch,
    _parse_emart_raw,
    _parse_homeplus_raw,
    _parse_lottemart_raw,
    _parse_costco_raw,
)

# fixture 디렉터리 (진본 fixture)
FIXTURE_BASE = (
    Path(__file__).parent.parent.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)

# 멱등 테스트용 고정 관측 시각
FIXED_DT = datetime(2025, 1, 1, 12, 0, 0)


# ══════════════════════════════════════════════════════
# pytest fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture
def engine():
    """in-memory SQLite + canonical 테이블 bootstrap."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    bootstrap_canonical_tables(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine)


@pytest.fixture
def session(session_factory) -> Session:
    with session_factory() as s:
        yield s


# ══════════════════════════════════════════════════════
# fixture 로더 헬퍼
# ══════════════════════════════════════════════════════

def _load_5card_payloads() -> dict[str, list[dict]]:
    """4사 5건씩 = 20건 raw payload dict."""
    return {
        "emart": _parse_emart_raw(FIXTURE_BASE),
        "homeplus": _parse_homeplus_raw(FIXTURE_BASE),
        "lottemart": _parse_lottemart_raw(FIXTURE_BASE),
        "costco": _parse_costco_raw(FIXTURE_BASE),
    }


def _load_1card_payloads() -> dict[str, list[dict]]:
    """4사 1건씩 = 4건 raw payload dict."""
    full = _load_5card_payloads()
    return {mart: items[:1] for mart, items in full.items() if items}


# ══════════════════════════════════════════════════════
# 테스트 1: 전체 fixture 시드 결과 검증
# ══════════════════════════════════════════════════════

def test_full_fixture_seed(session_factory):
    """
    4사 5건씩(총 20건) → SeedResult 전수 검증.
    - canonical_inserted=20
    - sku_alias_inserted=20
    - price_obs_inserted=20
    - review_queue_inserted=5 (이마트 5건, EMART_NO_CATEGORY)
    - category_nodes_present=49
    - errors=[]
    """
    # fixture 파싱 검증
    payloads = _load_5card_payloads()
    assert len(payloads["emart"]) == 5, "이마트 fixture 5건 필요"
    assert len(payloads["homeplus"]) == 5, "홈플러스 fixture 5건 필요"
    assert len(payloads["lottemart"]) == 5, "롯데마트 fixture 5건 필요"
    assert len(payloads["costco"]) == 5, "코스트코 fixture 5건 필요"

    with session_factory() as session:
        # 카테고리 먼저 시드
        cat_count = seed_categories_from_yaml(session)
        session.commit()
        assert cat_count == 49, f"CategoryNode 49개 기대, 실제 {cat_count}"

    with session_factory() as session:
        result = seed_from_raw_batch(payloads, session, dry_run=False, observed_at=FIXED_DT)

    assert result.canonical_inserted == 20, f"canonical_inserted={result.canonical_inserted}"
    assert result.canonical_updated == 0
    assert result.sku_alias_inserted == 20, f"sku_alias_inserted={result.sku_alias_inserted}"
    assert result.price_obs_inserted == 20, f"price_obs_inserted={result.price_obs_inserted}"
    assert result.review_queue_inserted == 5, (
        f"review_queue_inserted={result.review_queue_inserted} (이마트 5건 기대)"
    )
    assert result.category_nodes_present == 49
    assert result.errors == [], f"예상치 못한 오류: {result.errors}"
    assert result.dry_run is False


# ══════════════════════════════════════════════════════
# 테스트 2: 멱등성 (동일 fixture 2회 시드)
# ══════════════════════════════════════════════════════

def test_idempotency(session_factory):
    """
    동일 fixture 2회 시드.
    2회차: canonical_inserted=0, canonical_updated=20,
           sku_alias_inserted=0 (last_seen_at 갱신),
           price_obs_inserted=0 (같은 observed_at → skip).
    """
    payloads = _load_5card_payloads()

    with session_factory() as session:
        seed_categories_from_yaml(session)
        session.commit()

    # 1회차
    with session_factory() as session:
        r1 = seed_from_raw_batch(payloads, session, dry_run=False, observed_at=FIXED_DT)
    assert r1.canonical_inserted == 20
    assert r1.sku_alias_inserted == 20
    assert r1.price_obs_inserted == 20

    # 2회차 — 동일 observed_at
    with session_factory() as session:
        r2 = seed_from_raw_batch(payloads, session, dry_run=False, observed_at=FIXED_DT)

    assert r2.canonical_inserted == 0, f"2회차 canonical_inserted={r2.canonical_inserted} (0 기대)"
    assert r2.canonical_updated == 20, f"2회차 canonical_updated={r2.canonical_updated} (20 기대)"
    assert r2.sku_alias_inserted == 0, "2회차 alias 중복 insert 없어야 함"
    assert r2.price_obs_inserted == 0, "같은 observed_at → PriceObs skip"
    assert r2.errors == []


# ══════════════════════════════════════════════════════
# 테스트 3: dry_run=True
# ══════════════════════════════════════════════════════

def test_dry_run(session_factory):
    """
    dry_run=True → flush 후 rollback → DB 0건.
    """
    payloads = _load_5card_payloads()

    # 카테고리는 커밋 (canonical 시드에서 FK 참조하므로)
    with session_factory() as session:
        seed_categories_from_yaml(session)
        session.commit()

    # dry_run 세션
    with session_factory() as session:
        result = seed_from_raw_batch(
            payloads, session, dry_run=True, observed_at=FIXED_DT
        )
        assert result.dry_run is True
        assert result.canonical_inserted == 20
        assert result.price_obs_inserted == 20
        # 아직 commit 전 — 롤백
        session.rollback()

    # 롤백 후 canonical 조회 → 0건
    with session_factory() as session:
        count = session.execute(
            select(func.count()).select_from(ORM_CanonicalProduct)
        ).scalar()
    assert count == 0, f"dry_run 롤백 후 canonical {count}건 (0 기대)"


# ══════════════════════════════════════════════════════
# 테스트 4: 빈 fixture 디렉터리
# ══════════════════════════════════════════════════════

def test_empty_fixture_dir(session_factory):
    """
    빈 임시 디렉터리 → errors=[], canonical_inserted=0, 정상 종료.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_dir = Path(tmpdir)

        with session_factory() as session:
            seed_categories_from_yaml(session)
            result = seed_canonicals_from_fixture_dir(
                fixture_dir, session, dry_run=True
            )

    assert result.errors == [], f"빈 디렉터리에서 오류 발생: {result.errors}"
    assert result.canonical_inserted == 0
    assert result.sku_alias_inserted == 0
    assert result.price_obs_inserted == 0
    assert result.review_queue_inserted == 0


# ══════════════════════════════════════════════════════
# 테스트 5: 4사 카드 1개씩 (총 4건)
# ══════════════════════════════════════════════════════

def test_single_card_each_mart(session_factory):
    """
    4사 카드 1개씩 → canonical=4, review_queue=1 (이마트 1건).
    """
    payloads = _load_1card_payloads()
    assert len(payloads) == 4, "4사 모두 있어야 함"

    with session_factory() as session:
        seed_categories_from_yaml(session)
        session.commit()

    with session_factory() as session:
        result = seed_from_raw_batch(payloads, session, dry_run=False, observed_at=FIXED_DT)

    assert result.canonical_inserted == 4, f"canonical_inserted={result.canonical_inserted}"
    assert result.sku_alias_inserted == 4
    assert result.price_obs_inserted == 4
    assert result.review_queue_inserted == 1, (
        f"review_queue={result.review_queue_inserted} (이마트 1건 기대)"
    )
    assert result.errors == []


# ══════════════════════════════════════════════════════
# 테스트 6: 카테고리 시드 멱등성
# ══════════════════════════════════════════════════════

def test_category_seed_idempotency(session_factory):
    """
    seed_categories_from_yaml 2회 호출 → 항상 49개, 오류 없음.
    """
    with session_factory() as session:
        c1 = seed_categories_from_yaml(session)
        session.commit()

    with session_factory() as session:
        c2 = seed_categories_from_yaml(session)
        session.commit()

    assert c1 == 49, f"1회차 {c1}개"
    assert c2 == 49, f"2회차 {c2}개"


# ══════════════════════════════════════════════════════
# 테스트 7: 카테고리 트리 구조 검증
# ══════════════════════════════════════════════════════

def test_category_tree_structure(session_factory):
    """
    시드 후 CategoryNode ORM 쿼리 — parent 관계, level별 count.
    """
    with session_factory() as session:
        seed_categories_from_yaml(session)
        session.commit()

    with session_factory() as session:
        all_nodes = session.execute(select(ORM_CategoryNode)).scalars().all()
        assert len(all_nodes) == 49

        # L1 노드는 parent_id=None
        l1_nodes = [n for n in all_nodes if n.parent_id is None]
        assert len(l1_nodes) == 6, f"L1(대분류) 6개 기대, 실제 {len(l1_nodes)}"

        # level 별 count
        from collections import Counter
        level_counts = Counter(n.level for n in all_nodes)
        assert level_counts[1] == 6
        assert level_counts[2] == 16
        assert level_counts[3] == 21
        assert level_counts[4] == 6

        # parent relationship — kitchen_towel의 parent는 sanitary
        kt = session.get(ORM_CategoryNode, "kitchen_towel")
        assert kt is not None
        assert kt.parent_id == "sanitary"
        assert kt.parent.name_kr == "위생용품"

        # path 형식 확인
        assert kt.path == "/생활용품/위생용품/키친타월"


# ══════════════════════════════════════════════════════
# 테스트 8: ORM JOIN 통합 검증
# ══════════════════════════════════════════════════════

def test_orm_join_category(session_factory):
    """
    CanonicalProduct.category_path_internal_id → CategoryNode JOIN 정상.
    - 카테고리 있는 상품(홈플러스·롯데마트·코스트코 15건)은 category_node 참조 가능.
    - 이마트 5건은 category_path_internal_id=None.
    """
    payloads = _load_5card_payloads()

    with session_factory() as session:
        seed_categories_from_yaml(session)
        session.commit()

    with session_factory() as session:
        seed_from_raw_batch(payloads, session, dry_run=False, observed_at=FIXED_DT)

    with session_factory() as session:
        all_cp = session.execute(select(ORM_CanonicalProduct)).scalars().all()
        assert len(all_cp) == 20

        products_with_cat = [p for p in all_cp if p.category_path_internal_id is not None]
        products_no_cat = [p for p in all_cp if p.category_path_internal_id is None]

        # 이마트 5건 = 카테고리 없음
        assert len(products_no_cat) == 5, f"카테고리 없는 상품 5건 기대, 실제 {len(products_no_cat)}"
        # 홈플러스+롯데마트+코스트코 15건 = 카테고리 있음
        assert len(products_with_cat) == 15, f"카테고리 있는 상품 15건 기대, 실제 {len(products_with_cat)}"

        # category_node relationship 정상
        for p in products_with_cat:
            assert p.category_node is not None, f"{p.name_core}: category_node None"
            assert p.category_node.name_kr, f"{p.name_core}: name_kr 비어있음"
            assert p.category_node.level in (1, 2, 3, 4)


# ══════════════════════════════════════════════════════
# 테스트 9: seed_canonicals_from_fixture_dir 통합
# ══════════════════════════════════════════════════════

def test_seed_canonicals_from_fixture_dir(session_factory):
    """
    seed_canonicals_from_fixture_dir(FIXTURE_BASE, ...) 기본 동작.
    실제 fixture 파일을 사용 → canonical_inserted >= 20.
    """
    with session_factory() as session:
        seed_categories_from_yaml(session)
        session.commit()

    with session_factory() as session:
        result = seed_canonicals_from_fixture_dir(
            FIXTURE_BASE, session, dry_run=False, observed_at=FIXED_DT
        )

    assert result.errors == [], f"fixture_dir 시드 오류: {result.errors}"
    assert result.canonical_inserted >= 20, f"canonical_inserted={result.canonical_inserted}"
    assert result.sku_alias_inserted >= 20
    assert result.review_queue_inserted >= 5


# ══════════════════════════════════════════════════════
# 테스트 10: SeedResult.summary_line 형식
# ══════════════════════════════════════════════════════

def test_seed_result_summary_line():
    """SeedResult.summary_line() 문자열 형식 검증."""
    r = SeedResult(
        canonical_inserted=20,
        canonical_updated=0,
        sku_alias_inserted=20,
        price_obs_inserted=20,
        review_queue_inserted=5,
        category_nodes_present=49,
        dry_run=True,
        errors=[],
    )
    line = r.summary_line()
    assert "[DRY-RUN]" in line
    assert "canonical" in line
    assert "20" in line
