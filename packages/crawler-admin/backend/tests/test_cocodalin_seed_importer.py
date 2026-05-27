from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_ADMIN_BACKEND = BACKEND_DIR.parents[1] / "db-admin" / "backend"
for path in (DB_ADMIN_BACKEND, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
_SPEC = importlib.util.spec_from_file_location(
    "cocodalin_seed_importer",
    BACKEND_DIR / "services" / "cocodalin_seed_importer.py",
)
assert _SPEC and _SPEC.loader
_importer_module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _importer_module
_SPEC.loader.exec_module(_importer_module)
import_cocodalin_seed = _importer_module.import_cocodalin_seed
from storage.models import Base, PriceHistory, Product

FIXTURE_PATH = BACKEND_DIR / "tests" / "fixtures" / "cocodalin" / "seed_sample.json"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = Session()
    session.add_all(
        [
            Product(name="테스트 쌀 10kg", mart="costco", mart_native_code="686497", canon_hash="ricehash"),
            Product(
                name="Kirkland Signature Almonds 1kg",
                mart="costco",
                mart_native_code="123456",
                canon_hash="almondhash",
            ),
            Product(name="다른 마트 상품", mart="emart", mart_native_code="686497", canon_hash="emarthash"),
        ]
    )
    session.commit()
    return session


def test_import_report_counts_for_native_name_and_unmatched_records():
    session = _session()

    report = import_cocodalin_seed(session, FIXTURE_PATH)

    assert report.total_input == 3
    assert report.matched_by_native_code == 1
    assert report.matched_by_name == 1
    assert report.unmatched == 1
    assert report.inserted == 2
    assert report.skipped_duplicates == 0
    assert report.errors == 0
    rows = session.scalars(select(PriceHistory).order_by(PriceHistory.canon_key)).all()
    assert [row.canon_key for row in rows] == ["123456", "686497"]


def test_reimport_skips_duplicates_without_crashing():
    session = _session()
    first = import_cocodalin_seed(session, FIXTURE_PATH)
    second = import_cocodalin_seed(session, FIXTURE_PATH)

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.skipped_duplicates == 2
    assert second.unmatched == 1
    assert session.scalar(select(func.count()).select_from(PriceHistory)) == 2


def test_dry_run_reports_would_insert_but_does_not_write():
    session = _session()

    report = import_cocodalin_seed(session, FIXTURE_PATH, dry_run=True)

    assert report.inserted == 2
    assert report.matched_by_native_code == 1
    assert report.matched_by_name == 1
    assert session.scalar(select(func.count()).select_from(PriceHistory)) == 0
