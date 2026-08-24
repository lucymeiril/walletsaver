"""Build the current public product SQLite read replica.

Unlike the old Phase-D snapshot, this snapshot follows the product model that
current web routes actually use: Product + reviewed categories + price history.
Only public product-read tables are copied; users, admin queues, matching
knowledge, audit data and community data stay out of the file.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import MetaData, create_engine, insert, select, text
from sqlalchemy.engine import Connection

from services.base import get_engine
from services.public_snapshot_state import (
    get_snapshot_state,
    mark_public_snapshot_clean,
)
from storage.models import (
    BaselinePrice,
    Category,
    DiscountHistory,
    Keyword,
    PriceHistory,
    Product,
    ProductKeyword,
    UnifiedCategory,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PUBLIC_SNAPSHOT_PATH = _PROJECT_ROOT / ".walletsavior" / "public_snapshot.sqlite"

# Keep this intentionally narrow. These are sufficient for the current
# product/category/mart read paths backed by DBStorage. Write-heavy or private
# tables (pending_ingestions, matching_entries, users, audit_logs, etc.) are not
# copied to the public file.
_PUBLIC_MODELS = (
    Category,
    UnifiedCategory,
    Product,
    Keyword,
    ProductKeyword,
    BaselinePrice,
    DiscountHistory,
    PriceHistory,
)

_COPY_CHUNK_SIZE = 2_000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_metadata() -> tuple[MetaData, dict[str, object]]:
    metadata = MetaData()
    target_tables: dict[str, object] = {}
    for model in _PUBLIC_MODELS:
        source_table = model.__table__
        target_tables[source_table.name] = source_table.to_metadata(metadata)
    return metadata, target_tables


def _copy_table(
    source: Connection,
    target: Connection,
    source_table,
    target_table,
) -> int:
    result = source.execute(select(source_table))
    total = 0
    while True:
        rows = result.fetchmany(_COPY_CHUNK_SIZE)
        if not rows:
            break
        mappings = [dict(row._mapping) for row in rows]
        target.execute(insert(target_table), mappings)
        total += len(mappings)
    return total


def _write_snapshot_file(next_path: Path, source: Connection, revision: int) -> dict[str, int]:
    if next_path.exists():
        next_path.unlink()
    next_path.parent.mkdir(parents=True, exist_ok=True)

    target_engine = create_engine(f"sqlite:///{next_path.as_posix()}")
    metadata, target_tables = _public_metadata()
    row_counts: dict[str, int] = {}
    try:
        metadata.create_all(target_engine)
        with target_engine.begin() as target:
            for model in _PUBLIC_MODELS:
                source_table = model.__table__
                target_table = target_tables[source_table.name]
                row_counts[source_table.name] = _copy_table(
                    source,
                    target,
                    source_table,
                    target_table,
                )
            target.execute(
                text(
                    "CREATE TABLE snapshot_meta ("
                    "id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, "
                    "built_at TEXT NOT NULL)"
                )
            )
            target.execute(
                text(
                    "INSERT INTO snapshot_meta (id, revision, built_at) "
                    "VALUES (1, :revision, :built_at)"
                ),
                {"revision": revision, "built_at": _utc_iso()},
            )
    finally:
        target_engine.dispose()

    # Durability hint before the atomic replace.
    fd = os.open(str(next_path), os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return row_counts


def build_public_snapshot(
    target_path: Path | str = DEFAULT_PUBLIC_SNAPSHOT_PATH,
) -> dict:
    """Build and atomically publish a public product read replica.

    The source database is read under one transaction so all copied tables come
    from one coherent database view. The snapshot is marked clean only for the
    revision that was copied; if another writer changes public data during the
    build, the state remains dirty and a later rebuild is still required.
    """
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    next_path = target.with_suffix(target.suffix + ".next")

    source_engine = get_engine()
    with source_engine.connect() as source:
        transaction = source.begin()
        try:
            state = get_snapshot_state(source)
            revision = int(state["data_revision"])
            row_counts = _write_snapshot_file(next_path, source, revision)
            transaction.commit()
        except Exception:
            transaction.rollback()
            if next_path.exists():
                next_path.unlink()
            raise

    os.replace(next_path, target)

    # Update freshness state in a separate short write transaction. The CASE in
    # mark_public_snapshot_clean preserves dirty=1 if data_revision advanced
    # while the file was being built.
    with source_engine.begin() as connection:
        mark_public_snapshot_clean(connection, snapshot_revision=revision)
        final_state = get_snapshot_state(connection)

    return {
        "path": str(target),
        "revision": revision,
        "row_counts": row_counts,
        "dirty_after_build": bool(final_state["dirty"]),
        "data_revision_after_build": int(final_state["data_revision"]),
        "snapshot_revision": int(final_state["snapshot_revision"]),
    }
