"""
test_matching_entries.py — MatchingEntry ORM 단위 테스트.

테스트 전략:
    1. ORM round-trip: insert → query → assert (컬럼 값 검증)
    2. match_key UNIQUE 위반 시 IntegrityError
    3. source enum 외 값 거부 — Python @validates (ValueError)
    4. confidence 범위 [0,1] CHECK constraint (DB 레벨 검증)
    5. JSON keyword_ids round-trip (빈 리스트, 다중 원소)

왜 인메모리 SQLite인가:
    CI/CD에서 외부 DB 없이 실행 가능해야 한다.
    SQLite의 CHECK constraint는 기본 활성화되어 있으므로
    confidence/source 검증도 실제 DB 레벨에서 동작한다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, Session

# backend/ 루트를 sys.path에 추가 (storage 패키지 import를 위해)
BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, MatchingEntry


# ══════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def engine():
    """인메모리 SQLite — Base.metadata로 matching_entries 포함 전체 레거시 스키마 생성."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine) -> Session:
    """각 테스트마다 새 세션 + 트랜잭션 rollback으로 격리."""
    SessionFactory = sessionmaker(bind=engine)
    with SessionFactory() as s:
        yield s
        s.rollback()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_entry(**kwargs) -> MatchingEntry:
    """기본값을 가진 MatchingEntry 팩토리."""
    defaults = dict(
        match_key="CJ|햇반|210.000000|g",
        brand="CJ",
        name_core="햇반",
        pack_qty=210.0,
        pack_unit="g",
        confidence=0.95,
        source="crawler-auto",
        created_at=_utcnow(),
        updated_at=_utcnow(),
        keyword_ids=[],
    )
    defaults.update(kwargs)
    return MatchingEntry(**defaults)


# ══════════════════════════════════════════════════════
# 테스트 1: ORM round-trip — insert → query → assert
# ══════════════════════════════════════════════════════

def test_orm_roundtrip(session: Session) -> None:
    """insert 후 query하면 저장한 값이 그대로 반환되어야 한다."""
    entry = _make_entry(
        match_key="농심|신라면|120.000000|g",
        brand="농심",
        name_core="신라면",
        pack_qty=120.0,
        pack_unit="g",
        canonical_product_id="a" * 40,
        confidence=0.9,
        source="human",
        hit_count=5,
        notes="수동 매칭",
        keyword_ids=[1, 2, 3],
    )
    session.add(entry)
    session.flush()

    fetched = session.query(MatchingEntry).filter_by(match_key="농심|신라면|120.000000|g").one()

    assert fetched.brand == "농심"
    assert fetched.name_core == "신라면"
    assert fetched.pack_qty == pytest.approx(120.0)
    assert fetched.pack_unit == "g"
    assert fetched.canonical_product_id == "a" * 40
    assert fetched.confidence == pytest.approx(0.9)
    assert fetched.source == "human"
    assert fetched.hit_count == 5
    assert fetched.notes == "수동 매칭"
    assert fetched.id is not None


# ══════════════════════════════════════════════════════
# 테스트 2: match_key UNIQUE 위반 → IntegrityError
# ══════════════════════════════════════════════════════

def test_match_key_unique_violation(session: Session) -> None:
    """동일 match_key를 두 번 삽입하면 IntegrityError가 발생해야 한다."""
    entry1 = _make_entry(match_key="오뚜기|진라면|120.000000|g", source="crawler-auto")
    entry2 = _make_entry(match_key="오뚜기|진라면|120.000000|g", source="human")

    session.add(entry1)
    session.flush()

    session.add(entry2)
    with pytest.raises(IntegrityError):
        session.flush()


# ══════════════════════════════════════════════════════
# 테스트 3: source enum 외 값 거부 (Python @validates)
# ══════════════════════════════════════════════════════

def test_source_invalid_raises_value_error() -> None:
    """허용되지 않은 source 값을 넘기면 @validates가 ValueError를 발생시켜야 한다.

    왜 DB flush 이전에 Python 레벨에서 차단하는가:
        외부 AI import 스크립트가 잘못된 값을 넘길 때 빠른 실패를 보장하기 위해.
        DB flush까지 기다리지 않고 ORM 세션에서 즉시 오류를 반환한다.
    """
    with pytest.raises(ValueError, match="MatchingEntry.source 허용값"):
        MatchingEntry(
            match_key="test|key|1.000000|개",
            source="invalid",  # 허용되지 않는 값
            confidence=0.8,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )


@pytest.mark.parametrize("bad_source", ["CRAWLER-AUTO", "AI", "llm", "auto", ""])
def test_source_various_invalid_values(bad_source: str) -> None:
    """다양한 잘못된 source 값이 모두 거부되어야 한다."""
    with pytest.raises(ValueError):
        MatchingEntry(
            match_key=f"brand|name|1.0|개|{bad_source}",
            source=bad_source,
            confidence=0.5,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )


@pytest.mark.parametrize("valid_source", ["crawler-auto", "human", "external-ai"])
def test_source_valid_values(valid_source: str) -> None:
    """허용된 세 가지 source 값은 오류 없이 생성되어야 한다."""
    entry = MatchingEntry(
        match_key=f"brand|name|1.0|개|{valid_source}",
        source=valid_source,
        confidence=0.5,
        created_at=_utcnow(),
        updated_at=_utcnow(),
    )
    assert entry.source == valid_source


# ══════════════════════════════════════════════════════
# 테스트 4: confidence [0,1] CHECK constraint
# ══════════════════════════════════════════════════════

def test_confidence_out_of_range_low(session: Session) -> None:
    """confidence < 0 이면 IntegrityError(CHECK constraint 위반)가 발생해야 한다."""
    entry = _make_entry(
        match_key="brand|name|1.000000|개_conf_low",
        confidence=-0.1,
    )
    session.add(entry)
    with pytest.raises(IntegrityError):
        session.flush()


def test_confidence_out_of_range_high(session: Session) -> None:
    """confidence > 1 이면 IntegrityError(CHECK constraint 위반)가 발생해야 한다."""
    entry = _make_entry(
        match_key="brand|name|1.000000|개_conf_high",
        confidence=1.1,
    )
    session.add(entry)
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("valid_conf", [0.0, 0.5, 1.0])
def test_confidence_boundary_values(session: Session, valid_conf: float) -> None:
    """경계값(0.0, 0.5, 1.0)은 CHECK constraint를 통과해야 한다."""
    entry = _make_entry(
        match_key=f"brand|name|1.000000|개_conf_{valid_conf}",
        confidence=valid_conf,
    )
    session.add(entry)
    session.flush()

    fetched = session.query(MatchingEntry).filter_by(
        match_key=f"brand|name|1.000000|개_conf_{valid_conf}"
    ).one()
    assert fetched.confidence == pytest.approx(valid_conf)


# ══════════════════════════════════════════════════════
# 테스트 5: JSON keyword_ids round-trip
# ══════════════════════════════════════════════════════

def test_keyword_ids_empty_list(session: Session) -> None:
    """keyword_ids=[] (빈 리스트)가 저장·조회 후 동일하게 반환되어야 한다.

    왜 NULL과 구분하는가:
        []은 '키워드 없음(확인 완료)', NULL은 '아직 미처리'를 의미하므로 구분이 중요하다.
    """
    entry = _make_entry(match_key="keyword_empty|test|1.000000|개", keyword_ids=[])
    session.add(entry)
    session.flush()

    fetched = session.query(MatchingEntry).filter_by(
        match_key="keyword_empty|test|1.000000|개"
    ).one()
    assert fetched.keyword_ids == []
    assert fetched.keyword_ids is not None  # NULL이 아닌 빈 리스트여야 함


def test_keyword_ids_multiple(session: Session) -> None:
    """keyword_ids=[10, 20, 30] 다중 원소가 저장·조회 후 동일하게 반환되어야 한다."""
    entry = _make_entry(
        match_key="keyword_multi|test|1.000000|개",
        keyword_ids=[10, 20, 30],
    )
    session.add(entry)
    session.flush()

    fetched = session.query(MatchingEntry).filter_by(
        match_key="keyword_multi|test|1.000000|개"
    ).one()
    assert fetched.keyword_ids == [10, 20, 30]


def test_keyword_ids_null(session: Session) -> None:
    """keyword_ids=None (NULL)도 유효한 상태이며 저장·조회 후 None이어야 한다."""
    entry = _make_entry(
        match_key="keyword_null|test|1.000000|개",
        keyword_ids=None,
    )
    session.add(entry)
    session.flush()

    fetched = session.query(MatchingEntry).filter_by(
        match_key="keyword_null|test|1.000000|개"
    ).one()
    assert fetched.keyword_ids is None
