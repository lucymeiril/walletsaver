"""Legacy RD8 seed knowledge must remain backup-safe and lower-trust than AI."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.matching_sync import import_from_file
from storage.models import Base, MatchingEntry


def _record(source: str, *, updated_at: datetime, notes: str) -> dict:
    return {
        "match_key": "legacy-seed|상품|100.000000|g",
        "brand": "legacy-seed",
        "name_core": "상품",
        "pack_qty": 100.0,
        "pack_unit": "g",
        "canonical_product_id": None,
        "category_id": None,
        "keyword_ids": [],
        "confidence": 0.9,
        "source": source,
        "created_at": updated_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "last_used_at": None,
        "hit_count": 0,
        "notes": notes,
    }


def _write(path: Path, row: dict) -> Path:
    path.write_text(yaml.safe_dump([row], allow_unicode=True), encoding="utf-8")
    return path


def test_seed_roundtrip_and_trust_order(tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    now = datetime.now(timezone.utc)

    with Session() as session:
        seed_diff = import_from_file(
            session,
            _write(tmp_path / "seed.yaml", _record("rd8_c3_seed", updated_at=now, notes="seed")),
            dry_run=False,
        )
        assert len(seed_diff.to_add) == 1
        session.flush()
        assert session.query(MatchingEntry).one().source == "rd8_c3_seed"

        ai_diff = import_from_file(
            session,
            _write(
                tmp_path / "ai.yaml",
                _record("external-ai", updated_at=now + timedelta(seconds=1), notes="ai"),
            ),
            dry_run=False,
        )
        assert len(ai_diff.to_update) == 1
        session.flush()
        assert session.query(MatchingEntry).one().source == "external-ai"

        seed_again = import_from_file(
            session,
            _write(
                tmp_path / "seed-again.yaml",
                _record("rd8_c3_seed", updated_at=now + timedelta(seconds=2), notes="seed-again"),
            ),
            dry_run=False,
        )
        assert len(seed_again.conflicts) == 1
        session.flush()
        assert session.query(MatchingEntry).one().source == "external-ai"
        assert session.query(MatchingEntry).one().notes == "ai"

    engine.dispose()
