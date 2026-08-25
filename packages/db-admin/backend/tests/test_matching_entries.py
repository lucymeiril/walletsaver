"""MatchingEntry ORM contracts for the current matching table."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.models import Base, MatchingEntry


@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine) -> Session:
    SessionFactory = sessionmaker(bind=engine)
    with SessionFactory() as s:
        yield s
        s.rollback()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _make_entry(**kwargs) -> MatchingEntry:
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


def test_orm_roundtrip_uses_current_product_id_string(session: Session) -> None:
    entry = _make_entry(
        match_key="농심|신라면|120.000000|g",
        canonical_product_id="42",
        confidence=0.9,
        source="human",
        hit_count=5,
        notes="수동 매칭",
        keyword_ids=[1, 2, 3],
    )
    session.add(entry)
    session.flush()

    fetched = session.query(MatchingEntry).filter_by(match_key=entry.match_key).one()
    assert fetched.canonical_product_id == "42"
    assert int(fetched.canonical_product_id) == 42
    assert fetched.confidence == pytest.approx(0.9)
    assert fetched.source == "human"
    assert fetched.hit_count == 5


def test_match_key_is_unique(session: Session) -> None:
    session.add(_make_entry(match_key="오뚜기|진라면|120.000000|g"))
    session.flush()
    session.add(_make_entry(match_key="오뚜기|진라면|120.000000|g", source="human"))
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("bad_source", ["CRAWLER-AUTO", "AI", "llm", "auto", ""])
def test_invalid_source_is_rejected(bad_source: str) -> None:
    with pytest.raises(ValueError):
        _make_entry(match_key=f"invalid|{bad_source}", source=bad_source)


@pytest.mark.parametrize("valid_source", ["crawler-auto", "human", "external-ai"])
def test_current_source_values_are_accepted(valid_source: str) -> None:
    entry = _make_entry(match_key=f"valid|{valid_source}", source=valid_source)
    assert entry.source == valid_source


@pytest.mark.parametrize("bad_confidence", [-0.1, 1.1])
def test_confidence_out_of_range_hits_db_check(session: Session, bad_confidence: float) -> None:
    session.add(
        _make_entry(
            match_key=f"confidence|{bad_confidence}",
            confidence=bad_confidence,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize("valid_confidence", [0.0, 0.5, 1.0])
def test_confidence_boundaries_are_valid(session: Session, valid_confidence: float) -> None:
    entry = _make_entry(
        match_key=f"confidence|valid|{valid_confidence}",
        confidence=valid_confidence,
    )
    session.add(entry)
    session.flush()
    assert entry.confidence == pytest.approx(valid_confidence)


def test_keyword_ids_distinguish_empty_from_null(session: Session) -> None:
    empty = _make_entry(match_key="keywords|empty", keyword_ids=[])
    null = _make_entry(match_key="keywords|null", keyword_ids=None)
    session.add_all([empty, null])
    session.flush()

    assert session.query(MatchingEntry).filter_by(match_key="keywords|empty").one().keyword_ids == []
    assert session.query(MatchingEntry).filter_by(match_key="keywords|null").one().keyword_ids is None
