"""Test fixtures — mini in-memory SQLite snapshot for isolated tests."""
import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure backend/ and packages/ are on sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PACKAGES_DIR = _BACKEND_DIR.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))


def _create_mini_snapshot(db_path: str):
    """Create a minimal snapshot SQLite for tests."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS canonical_product (
        id TEXT PRIMARY KEY,
        brand TEXT,
        name_core TEXT,
        pack_quantity REAL,
        pack_unit TEXT,
        category_id TEXT,
        representative_image_url TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS price_grade (
        canonical_id TEXT PRIMARY KEY,
        window_months INTEGER,
        sample_size INTEGER,
        p10 REAL,
        p25 REAL,
        p50 REAL,
        p75 REAL,
        computed_at TEXT,
        sufficient INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS category_node (
        id TEXT PRIMARY KEY,
        parent_id TEXT,
        name_kr TEXT,
        name_slug TEXT,
        level INTEGER,
        path TEXT
    );
    CREATE TABLE IF NOT EXISTS mart_sku_alias (
        id TEXT PRIMARY KEY,
        canonical_id TEXT,
        mart TEXT,
        mart_item_id TEXT,
        mart_item_name_raw TEXT,
        source_url TEXT,
        last_seen_at TEXT
    );
    """)

    cur.executemany("INSERT OR REPLACE INTO category_node VALUES (?,?,?,?,?,?)", [
        ("fresh_food", None, "신선식품", "fresh_food", 1, "신선식품"),
        ("vegetable", "fresh_food", "채소", "vegetable", 2, "신선식품 > 채소"),
        ("processed_food", None, "가공식품", "processed_food", 1, "가공식품"),
        ("tofu_cat", "processed_food", "두부", "tofu", 2, "가공식품 > 두부"),
        ("dairy", None, "유제품", "dairy", 1, "유제품"),
        ("egg_cat", "fresh_food", "란류", "egg", 2, "신선식품 > 란류"),
    ])

    cur.executemany("INSERT OR REPLACE INTO canonical_product VALUES (?,?,?,?,?,?,?,?)", [
        ("prod_tofu_001", "풀무원", "국산 부침두부", 300.0, "g", "tofu_cat", None, "2024-01-01"),
        ("prod_egg_001", None, "행복생생란", 30.0, "개", "egg_cat", None, "2024-01-01"),
        ("prod_kimchi_001", "종가집", "배추김치", 1.0, "kg", None, None, "2024-01-01"),
        ("prod_milk_001", "서울우유", "흰우유", 1.0, "L", "dairy", None, "2024-01-01"),
        ("prod_rice_001", None, "철원 오대쌀", 10.0, "kg", None, None, "2024-01-01"),
    ])

    cur.executemany("INSERT OR REPLACE INTO price_grade VALUES (?,?,?,?,?,?,?,?,?)", [
        ("prod_tofu_001", 6, 10, 1500.0, 1800.0, 2200.0, 2800.0, "2024-01-01", 1),
        ("prod_egg_001", 6, 3, None, None, 4500.0, None, "2024-01-01", 0),
        ("prod_kimchi_001", 6, 8, 8000.0, 9500.0, 12000.0, 15000.0, "2024-01-01", 1),
        ("prod_milk_001", 6, 6, 1200.0, 1400.0, 1600.0, 1900.0, "2024-01-01", 1),
        ("prod_rice_001", 6, 2, None, None, 28000.0, None, "2024-01-01", 0),
    ])

    cur.executemany("INSERT OR REPLACE INTO mart_sku_alias VALUES (?,?,?,?,?,?,?)", [
        ("alias_001", "prod_tofu_001", "LOTTEMART", "tofu_001", "풀무원 국산 부침두부 300g", "http://lotte.com/1", "2024-01-01"),
        ("alias_002", "prod_tofu_001", "HOMEPLUS", "tofu_002", "풀무원 부침두부", "http://home.com/1", "2024-01-01"),
        ("alias_003", "prod_egg_001", "LOTTEMART", "egg_001", "행복생생란 30구", "http://lotte.com/2", "2024-01-01"),
        ("alias_004", "prod_kimchi_001", "EMART", "kimchi_001", "종가집 배추김치 1kg", "http://emart.com/1", "2024-01-01"),
        ("alias_005", "prod_milk_001", "EMART", "milk_001", "서울우유 흰우유 1L", "http://emart.com/2", "2024-01-01"),
    ])

    conn.commit()
    conn.close()


@pytest.fixture(scope="session")
def mini_snapshot_path(tmp_path_factory):
    db = tmp_path_factory.mktemp("snapshot") / "test_snapshot.sqlite"
    _create_mini_snapshot(str(db))
    return str(db)


@pytest.fixture
def test_client(mini_snapshot_path, monkeypatch):
    monkeypatch.setenv("WALLETSAVIOR_PUBLIC_DB", mini_snapshot_path)
    # Re-import app fresh so any cached module state picks up env
    import importlib
    import api.app as app_module
    importlib.reload(app_module)
    from fastapi.testclient import TestClient
    return TestClient(app_module.create_app())
