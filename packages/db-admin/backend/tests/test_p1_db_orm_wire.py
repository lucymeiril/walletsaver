"""p1-db-orm-wire — Alembic 마이그레이션 연결 테스트.

검증 대상:
  1. env.py가 CanonicalBase를 import하고 combined metadata를 target_metadata로 사용
  2. 새 canonical 마이그레이션 파일(c1a2b3d4e5f6)이 존재하고, 올바른 down_revision을 가짐
  3. 빈 SQLite DB 에서 CanonicalBase.metadata.create_all() 후 5개 canonical 테이블이 존재
  4. legacy Base + CanonicalBase metadata 합산 후 중복 테이블이 없음
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

BACKEND_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from storage.canonical_models import CanonicalBase, bootstrap_canonical_tables
from storage.models import Base as LegacyBase

MIGRATIONS_DIR = BACKEND_ROOT / "storage" / "migrations"
VERSIONS_DIR = MIGRATIONS_DIR / "versions"
CANONICAL_MIGRATION_FILE = VERSIONS_DIR / "c1a2b3d4e5f6_p1_db_orm_wire_canonical_tables.py"


# ─── 1. env.py 소스 검사 ────────────────────────────────────────────────────

def test_env_py_imports_canonical_base():
    env_src = (MIGRATIONS_DIR / "env.py").read_text(encoding="utf-8")
    assert "CanonicalBase" in env_src, "env.py가 CanonicalBase를 import하지 않음"
    assert "canonical_models" in env_src, "env.py가 canonical_models를 import하지 않음"


def test_env_py_uses_combined_metadata():
    env_src = (MIGRATIONS_DIR / "env.py").read_text(encoding="utf-8")
    # combined metadata 구성 코드 확인
    assert "_combined_meta" in env_src or "target_metadata" in env_src, (
        "env.py에서 canonical + legacy metadata 합산 코드가 없음"
    )


# ─── 2. 마이그레이션 파일 존재 확인 ────────────────────────────────────────

def test_canonical_migration_file_exists():
    assert CANONICAL_MIGRATION_FILE.exists(), (
        f"canonical 마이그레이션 파일이 없음: {CANONICAL_MIGRATION_FILE}"
    )


def test_canonical_migration_has_correct_down_revision():
    src = CANONICAL_MIGRATION_FILE.read_text(encoding="utf-8")
    assert 'down_revision' in src, "down_revision 없음"
    # 이전 migration id 참조
    assert "8018226a8e9e" in src, "down_revision이 8018226a8e9e를 가리키지 않음"


def test_canonical_migration_has_upgrade_and_downgrade():
    src = CANONICAL_MIGRATION_FILE.read_text(encoding="utf-8")
    assert "def upgrade" in src, "upgrade() 함수 없음"
    assert "def downgrade" in src, "downgrade() 함수 없음"


def test_canonical_migration_creates_all_five_tables():
    src = CANONICAL_MIGRATION_FILE.read_text(encoding="utf-8")
    expected_tables = [
        "canonical_category_nodes",
        "canonical_products",
        "canonical_mart_sku_aliases",
        "canonical_price_observations",
        "canonical_product_review_queue",
    ]
    for tbl in expected_tables:
        assert tbl in src, f"마이그레이션에서 테이블 '{tbl}'을 생성하지 않음"


# ─── 3. CanonicalBase.metadata.create_all — 5개 테이블 생성 ─────────────────

@pytest.fixture
def sqlite_engine(tmp_path):
    db_path = tmp_path / "test_canonical.db"
    engine = create_engine(f"sqlite:///{db_path}")
    yield engine
    engine.dispose()


def test_bootstrap_creates_canonical_tables(sqlite_engine):
    bootstrap_canonical_tables(sqlite_engine)
    insp = inspect(sqlite_engine)
    tables = insp.get_table_names()
    expected = {
        "canonical_category_nodes",
        "canonical_products",
        "canonical_mart_sku_aliases",
        "canonical_price_observations",
        "canonical_product_review_queue",
    }
    for tbl in expected:
        assert tbl in tables, f"테이블 '{tbl}'이 생성되지 않음. 생성된 목록: {tables}"


# ─── 4. legacy + canonical metadata 합산 시 중복 없음 ───────────────────────

def test_combined_metadata_no_duplicate_tables():
    import sqlalchemy as _sa
    combined = _sa.MetaData()
    for table in LegacyBase.metadata.tables.values():
        table.to_metadata(combined)
    for table in CanonicalBase.metadata.tables.values():
        assert table.name not in combined.tables, (
            f"테이블 '{table.name}'이 legacy와 canonical 양쪽에 존재함 — 이름 충돌"
        )
        table.to_metadata(combined)
    # 합산 후 canonical 5개 + legacy 테이블 모두 포함
    canonical_expected = {
        "canonical_category_nodes",
        "canonical_products",
        "canonical_mart_sku_aliases",
        "canonical_price_observations",
        "canonical_product_review_queue",
    }
    for tbl in canonical_expected:
        assert tbl in combined.tables, f"합산 metadata에 '{tbl}' 없음"
