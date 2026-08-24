"""Focused contract tests for external MatchingEntry validation."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
SHARED_ROOT = BACKEND_ROOT.parent.parent / "shared"
for path in (str(BACKEND_ROOT), str(SHARED_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from services.import_validator import (  # noqa: E402
    _build_match_key,
    _deduplicate_by_match_key,
    validate_lenient,
    validate_strict,
)
from storage.models import Base, Category, Keyword  # noqa: E402


@pytest.fixture(scope="module")
def engine():
    value = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    return value


@pytest.fixture(scope="module")
def seeded_session(engine) -> Session:
    factory = sessionmaker(bind=engine)
    session = factory()
    session.add(Category(id="food", name="식품", depth=0, is_active=True))
    session.add(Category(id="food.rice", name="쌀", parent_id="food", depth=1, is_active=True))
    session.add(Category(id="inactive.cat", name="비활성", depth=0, is_active=False))
    session.add(Keyword(id=1, word="밥", is_active=True))
    session.add(Keyword(id=2, word="국수", is_active=True))
    session.commit()
    yield session
    session.close()


def _good_row(**overrides) -> dict:
    row = {
        "match_key": "legacy-format-that-must-not-win",
        "brand": "CJ",
        "name_core": "햇반",
        "pack_qty": 210.0,
        "pack_unit": "g",
        "category_id": "food.rice",
        "confidence": 0.9,
        "source": "external-ai",
        "keyword_ids": [1, 2],
    }
    row.update(overrides)
    return row


def test_build_match_key_uses_shared_canonical_contract():
    assert _build_match_key(_good_row()) == "cj|햇반|210.0|g"


def test_build_match_key_canonicalizes_equivalent_units():
    kg = _good_row(name_core="쌀", pack_qty=1, pack_unit="kg")
    gram = _good_row(name_core="쌀", pack_qty=1000, pack_unit="g")
    assert _build_match_key(kg) == _build_match_key(gram) == "cj|쌀|1000.0|g"


def test_brandless_identity_uses_stable_sentinel(seeded_session):
    row = _good_row(brand=None, name_core="양파", pack_qty=1, pack_unit="망")
    result = validate_strict([row], seeded_session)
    assert result.is_valid
    assert result.valid_rows[0]["brand"] == "__no_brand__"
    assert result.valid_rows[0]["match_key"] == "__no_brand__|양파|1.0|망"


def test_provided_legacy_match_key_is_recomputed(seeded_session):
    result = validate_strict([_good_row(match_key="CJ|햇반|210.000000|g")], seeded_session)
    assert result.is_valid
    assert result.valid_rows[0]["match_key"] == "cj|햇반|210.0|g"


def test_deduplication_uses_canonical_identity_last_row_wins():
    first = _good_row(match_key="old-a", confidence=0.5)
    second = _good_row(match_key="old-b", confidence=0.9)
    rows, warnings = _deduplicate_by_match_key([first, second])
    assert len(rows) == 1
    assert rows[0]["confidence"] == 0.9
    assert rows[0]["match_key"] == "cj|햇반|210.0|g"
    assert warnings


def test_different_identity_rows_do_not_collapse(seeded_session):
    rows = [
        _good_row(name_core="햇반"),
        _good_row(name_core="신라면", brand="농심", pack_qty=120),
    ]
    result = validate_strict(rows, seeded_session)
    assert result.is_valid
    assert len(result.valid_rows) == 2


def test_strict_rejects_missing_category(seeded_session):
    result = validate_strict([_good_row(category_id=None)], seeded_session)
    assert not result.is_valid
    assert result.valid_rows == []
    assert any("category_id" in message for _, message in result.errors)


def test_strict_rejects_unknown_or_inactive_category(seeded_session):
    for category_id in ("does.not.exist", "inactive.cat"):
        result = validate_strict([_good_row(category_id=category_id)], seeded_session)
        assert not result.is_valid


def test_strict_rejects_unknown_keyword(seeded_session):
    result = validate_strict([_good_row(keyword_ids=[999])], seeded_session)
    assert not result.is_valid
    assert any("keywords" in message for _, message in result.errors)


@pytest.mark.parametrize("confidence", [-0.1, 1.1, "not-a-number"])
def test_invalid_confidence_is_rejected(seeded_session, confidence):
    assert not validate_strict([_good_row(confidence=confidence)], seeded_session).is_valid


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_confidence_boundaries_are_valid(seeded_session, confidence):
    assert validate_strict([_good_row(confidence=confidence)], seeded_session).is_valid


@pytest.mark.parametrize("source", ["human", "external-ai"])
def test_allowed_sources_pass(seeded_session, source):
    assert validate_strict([_good_row(source=source)], seeded_session).is_valid


@pytest.mark.parametrize("source", ["crawler-auto", "unknown-source"])
def test_non_import_sources_are_rejected(seeded_session, source):
    assert not validate_strict([_good_row(source=source)], seeded_session).is_valid


def test_match_key_alone_is_still_accepted_when_compound_identity_is_unavailable(seeded_session):
    row = _good_row(match_key="external|opaque|key|v1")
    row.pop("name_core")
    row.pop("pack_qty")
    row.pop("pack_unit")
    result = validate_strict([row], seeded_session)
    assert result.is_valid
    assert result.valid_rows[0]["match_key"] == "external|opaque|key|v1"


def test_missing_both_match_key_and_identity_is_rejected(seeded_session):
    row = _good_row(match_key="")
    row.pop("name_core")
    row.pop("pack_qty")
    row.pop("pack_unit")
    result = validate_strict([row], seeded_session)
    assert not result.is_valid


def test_lenient_mode_keeps_valid_rows_and_reports_invalid_rows(seeded_session):
    valid = _good_row(name_core="햇반")
    invalid = _good_row(name_core="신라면", brand="농심", pack_qty=120, category_id="missing")
    result = validate_lenient([valid, invalid], seeded_session)
    assert len(result.valid_rows) == 1
    assert result.valid_rows[0]["match_key"] == "cj|햇반|210.0|g"
    assert result.errors
