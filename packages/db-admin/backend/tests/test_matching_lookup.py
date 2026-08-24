"""High-value MatchingEntry lookup tests for the current identity contract."""
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

from core.match_key import NO_BRAND_SENTINEL, build_match_key
from services import matching_lookup
from storage.models import Base, MatchingEntry


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        yield db
    engine.dispose()


@pytest.fixture(autouse=True)
def clear_matching_cache():
    matching_lookup.invalidate()
    yield
    matching_lookup.invalidate()


def _entry(session: Session, *, brand: str | None, name: str, qty: float, unit: str) -> MatchingEntry:
    key = build_match_key(brand, name, qty, unit)
    entry = MatchingEntry(
        match_key=key,
        brand=brand or NO_BRAND_SENTINEL,
        name_core=name,
        pack_qty=qty,
        pack_unit=unit,
        confidence=0.95,
        source="external-ai",
        hit_count=0,
    )
    session.add(entry)
    session.flush()
    return entry


def test_match_key_uses_brandless_sentinel():
    key = build_match_key(None, "신라면", 120, "g")
    assert key == f"{NO_BRAND_SENTINEL}|신라면|120.0|g"


def test_match_key_canonicalizes_equivalent_weight_and_volume_units():
    assert build_match_key("Brand", "쌀", 1, "kg") == build_match_key("brand", "쌀", 1000, "g")
    assert build_match_key("Brand", "우유", 1, "L") == build_match_key("brand", "우유", 1000, "ml")


def test_lookup_one_and_bulk_return_only_existing_keys(session: Session):
    first = _entry(session, brand="CJ", name="햇반", qty=210, unit="g")
    second = _entry(session, brand=None, name="두부", qty=300, unit="g")
    missing = build_match_key("없는브랜드", "없는상품", 1, "ea")

    assert matching_lookup.lookup_one(session, first.match_key).id == first.id
    assert matching_lookup.lookup_one(session, missing) is None

    result = matching_lookup.lookup_bulk(session, [first.match_key, second.match_key, missing])
    assert set(result) == {first.match_key, second.match_key}


def test_classify_brandless_row_reuses_matching_entry_and_records_hit(session: Session):
    entry = _entry(session, brand=None, name="무브랜드 두부", qty=300, unit="g")

    resolved, reason = matching_lookup.classify_raw_record(
        session,
        {
            "name": "무브랜드 두부",
            "pack_qty": 0.3,
            "pack_unit": "kg",
        },
    )

    assert reason is None
    assert resolved is not None
    assert resolved.id == entry.id
    session.flush()
    session.refresh(entry)
    assert entry.hit_count == 1
    assert entry.last_used_at is not None


def test_classify_missing_name_is_not_keyed(session: Session):
    resolved, reason = matching_lookup.classify_raw_record(
        session,
        {"brand": "CJ", "pack_qty": 210, "pack_unit": "g"},
    )
    assert resolved is None
    assert reason == "no_name"


def test_classify_unknown_identity_returns_key_not_found(session: Session):
    resolved, reason = matching_lookup.classify_raw_record(
        session,
        {"brand": "CJ", "name": "미등록상품", "pack_qty": 210, "pack_unit": "g"},
    )
    assert resolved is None
    assert reason == "key_not_found"


def test_record_hits_batch_updates_each_entry_once(session: Session):
    first = _entry(session, brand="A", name="상품1", qty=1, unit="ea")
    second = _entry(session, brand="B", name="상품2", qty=2, unit="ea")

    matching_lookup.record_hits_batch(session, [first.id, second.id])
    session.flush()
    session.refresh(first)
    session.refresh(second)

    assert first.hit_count == 1
    assert second.hit_count == 1
    assert first.last_used_at is not None
    assert second.last_used_at is not None
