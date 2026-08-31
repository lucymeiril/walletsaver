"""Build the current public product SQLite read replica.

Unlike the old Phase-D snapshot, this snapshot follows the product model that
current web routes actually use: Product + reviewed categories + price history.
Only public product-read tables are copied; users, admin queues, matching
knowledge, audit data and community data stay out of the file.
"""
from __future__ import annotations

import os
import sqlite3
import time
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
    MartCategoryMapping,
    NormalizedCanonicalProduct,
    NormalizedOfferEvent,
    NormalizedOfferWeekLink,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedWeekBucket,
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
    MartCategoryMapping,
    NormalizedCanonicalProduct,
    NormalizedProductVariant,
    NormalizedSourceListing,
    NormalizedOfferEvent,
    NormalizedWeekBucket,
    NormalizedOfferWeekLink,
)

_COPY_CHUNK_SIZE = 2_000


def _replace_with_retry(source: Path, target: Path, *, timeout: float = 5.0) -> None:
    """Handle short-lived read handles held by the Windows web process."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


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


def previous_snapshot_path(target_path: Path | str) -> Path:
    target = Path(target_path)
    return target.with_suffix(target.suffix + ".previous")


def validate_public_snapshot(path: Path | str) -> dict:
    """Validate a candidate before it can replace the approved snapshot."""
    candidate = Path(path)
    connection = sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro", uri=True)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()
        if not quick_check or quick_check[0] != "ok":
            raise ValueError(f"SQLite quick_check failed: {quick_check}")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {model.__tablename__ for model in _PUBLIC_MODELS} | {"snapshot_meta"}
        missing = sorted(required - tables)
        if missing:
            raise ValueError("required tables missing: " + ", ".join(missing))

        meta = connection.execute(
            "SELECT revision, built_at FROM snapshot_meta WHERE id=1"
        ).fetchone()
        if not meta:
            raise ValueError("snapshot metadata row is missing")

        category_rows = connection.execute(
            "SELECT id, parent_id FROM unified_categories"
        ).fetchall()
        parents = {str(row[0]): (str(row[1]) if row[1] is not None else None) for row in category_rows}
        for category_id in parents:
            seen: set[str] = set()
            cursor: str | None = category_id
            depth = 0
            while cursor is not None:
                if cursor not in parents:
                    raise ValueError(f"category parent not found: {cursor}")
                if cursor in seen:
                    raise ValueError(f"category cycle detected: {category_id}")
                seen.add(cursor)
                depth += 1
                if depth > 4:
                    raise ValueError(f"category depth exceeds four levels: {category_id}")
                cursor = parents[cursor]

        # Public products must be leaf-classified. Import validation already
        # enforces this, but the publication boundary independently verifies it.
        internal_assignments = int(connection.execute(
            "SELECT COUNT(*) FROM normalized_canonical_products p "
            "WHERE p.is_active=1 AND (p.unified_category_id IS NULL OR NOT EXISTS ("
            "SELECT 1 FROM unified_categories current "
            "WHERE current.id=p.unified_category_id) OR EXISTS ("
            "SELECT 1 FROM unified_categories child "
            "WHERE child.parent_id=p.unified_category_id))"
        ).fetchone()[0])
        if internal_assignments:
            raise ValueError(
                f"active products without a leaf category: {internal_assignments}"
            )

        counts = {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in sorted(required - {"snapshot_meta"})
        }
        return {
            "revision": int(meta[0]),
            "built_at": str(meta[1]),
            "row_counts": counts,
        }
    finally:
        connection.close()


def _publish_candidate(next_path: Path, target: Path) -> Path | None:
    """Atomically install a validated candidate and retain one rollback copy."""
    validate_public_snapshot(next_path)
    previous = previous_snapshot_path(target)
    had_target = target.exists()
    if had_target:
        try:
            validate_public_snapshot(target)
        except (OSError, sqlite3.Error, ValueError):
            # A pre-capstone or corrupt file must never block publication and
            # must not be advertised as a rollback candidate.
            rejected = target.with_suffix(target.suffix + ".rejected")
            if rejected.exists():
                rejected.unlink()
            _replace_with_retry(target, rejected)
            had_target = False
    if previous.exists():
        previous.unlink()
    if had_target:
        _replace_with_retry(target, previous)
    try:
        _replace_with_retry(next_path, target)
    except Exception:
        if had_target and previous.exists():
            _replace_with_retry(previous, target)
        raise
    return previous if had_target else None


def rollback_public_snapshot(target_path: Path | str = DEFAULT_PUBLIC_SNAPSHOT_PATH) -> dict:
    """Swap the approved snapshot with its immediately preceding version."""
    target = Path(target_path)
    previous = previous_snapshot_path(target)
    if not previous.is_file():
        raise FileNotFoundError(f"rollback snapshot not found: {previous}")
    validate_public_snapshot(previous)
    displaced = target.with_suffix(target.suffix + ".rollback")
    if displaced.exists():
        displaced.unlink()
    if target.exists():
        _replace_with_retry(target, displaced)
    try:
        _replace_with_retry(previous, target)
        if displaced.exists():
            _replace_with_retry(displaced, previous)
    except Exception:
        if displaced.exists() and not target.exists():
            _replace_with_retry(displaced, target)
        raise
    return {
        "path": str(target),
        "previous_path": str(previous),
        "validation": validate_public_snapshot(target),
    }


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

    previous_validation = None
    if target.exists():
        try:
            previous_validation = validate_public_snapshot(target)
        except (OSError, sqlite3.Error, ValueError):
            previous_validation = None
    previous = _publish_candidate(next_path, target)

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
        "previous_path": str(previous) if previous else None,
        "previous_row_counts": (
            previous_validation.get("row_counts") if previous_validation else None
        ),
    }
