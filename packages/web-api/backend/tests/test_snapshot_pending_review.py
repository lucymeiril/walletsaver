"""Remote snapshot validation must not publish offers awaiting review."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.routes import admin_remote


def _catalog_snapshot(
    path: Path, offer_states: list[str], *, product_active: bool = False
) -> Path:
    """Create only the schema needed by the read-only validation boundary."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            "CREATE TABLE products (id INTEGER PRIMARY KEY);"
            "CREATE TABLE categories (id INTEGER PRIMARY KEY);"
            "CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT);"
            "CREATE TABLE snapshot_meta (id INTEGER PRIMARY KEY, revision TEXT, built_at TEXT);"
            "CREATE TABLE normalized_canonical_products ("
            "id INTEGER PRIMARY KEY, is_active BOOLEAN NOT NULL, unified_category_id TEXT);"
            "CREATE TABLE normalized_product_variants (id INTEGER PRIMARY KEY);"
            "CREATE TABLE normalized_source_listings (id INTEGER PRIMARY KEY);"
            "CREATE TABLE normalized_offer_events ("
            "id INTEGER PRIMARY KEY, offer_state VARCHAR(40) NOT NULL DEFAULT 'active');"
        )
        connection.execute("INSERT INTO unified_categories VALUES ('leaf', NULL)")
        connection.execute(
            "INSERT INTO normalized_canonical_products VALUES (1, ?, 'leaf')",
            (product_active,),
        )
        connection.execute(
            "INSERT INTO snapshot_meta VALUES (1, 'test-revision', '2026-09-03T00:00:00')"
        )
        connection.executemany(
            "INSERT INTO normalized_offer_events (offer_state) VALUES (?)",
            [(state,) for state in offer_states],
        )
        connection.commit()
    finally:
        connection.close()
    return path


@pytest.mark.parametrize(
    "offer_states",
    [
        [],
        ["active"],
        # Historical states are strings, not a closed enum or an allowlist.
        ["active", "expired", "withdrawn", "legacy_unknown"],
    ],
)
def test_snapshot_accepts_inactive_products_and_non_pending_states(tmp_path, offer_states):
    snapshot = _catalog_snapshot(tmp_path / "catalog.sqlite", offer_states)
    original_bytes = snapshot.read_bytes()

    validation = admin_remote._validate_sqlite(
        snapshot, admin_remote._SNAPSHOT_CONFIG["catalog"][2]
    )

    assert validation["revision"] == "test-revision"
    assert "normalized_offer_events" in validation["tables"]
    assert snapshot.read_bytes() == original_bytes


@pytest.mark.parametrize("product_active", [False, True])
@pytest.mark.parametrize(
    "offer_states",
    [
        ["pending_review"],
        ["active", "pending_review", "expired", "withdrawn", "pending_review"],
    ],
)
def test_snapshot_rejects_any_pending_review_without_mutating_file(
    tmp_path, product_active, offer_states
):
    snapshot = _catalog_snapshot(
        tmp_path / "catalog.sqlite", offer_states, product_active=product_active
    )
    original_bytes = snapshot.read_bytes()

    with pytest.raises(HTTPException) as error:
        admin_remote._validate_sqlite(
            snapshot, admin_remote._SNAPSHOT_CONFIG["catalog"][2]
        )

    assert error.value.status_code == 422
    assert (
        f"pending_review offers are not publishable: {offer_states.count('pending_review')}"
        in error.value.detail
    )
    assert snapshot.read_bytes() == original_bytes
