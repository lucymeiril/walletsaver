"""Build the replaceable external-hotdeal SQLite read replica.

Only HotdealPost is published. User votes/reports belong to web-api's
interactions.sqlite and are deliberately excluded so replacing this file can
never erase server-side interaction data.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import MetaData, create_engine, insert, select, text

from services.base import get_engine
from storage.models import HotdealPost

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_EXTERNAL_HOTDEAL_SNAPSHOT_PATH = (
    _PROJECT_ROOT / ".walletsavior" / "external_hotdeals.sqlite"
)
_COPY_CHUNK_SIZE = 2_000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def external_hotdeal_snapshot_path() -> Path:
    configured = os.getenv("WALLETSAVIOR_EXTERNAL_HOTDEAL_DB", "").strip()
    return (
        Path(configured).expanduser()
        if configured
        else DEFAULT_EXTERNAL_HOTDEAL_SNAPSHOT_PATH
    ).resolve()


def source_fingerprint() -> str:
    """Return a stable content fingerprint for the local HotdealPost table."""
    table = HotdealPost.__table__
    digest = hashlib.sha256()
    engine = get_engine()
    with engine.connect() as connection:
        rows = connection.execute(select(table).order_by(table.c.id))
        for row in rows:
            # repr(tuple(...)) is sufficient here because all SQLAlchemy values
            # are deterministic scalar/JSON values from one local DB row.
            digest.update(repr(tuple(row)).encode("utf-8", errors="replace"))
            digest.update(b"\n")
    return digest.hexdigest()


def _write_snapshot(next_path: Path, revision: int) -> int:
    if next_path.exists():
        next_path.unlink()
    next_path.parent.mkdir(parents=True, exist_ok=True)

    source_table = HotdealPost.__table__
    metadata = MetaData()
    target_table = source_table.to_metadata(metadata)
    target_engine = create_engine(f"sqlite:///{next_path.as_posix()}")
    source_engine = get_engine()
    copied = 0

    try:
        metadata.create_all(target_engine)
        with source_engine.connect() as source:
            source_tx = source.begin()
            try:
                result = source.execute(select(source_table).order_by(source_table.c.id))
                with target_engine.begin() as target:
                    while True:
                        rows = result.fetchmany(_COPY_CHUNK_SIZE)
                        if not rows:
                            break
                        mappings = [dict(row._mapping) for row in rows]
                        target.execute(insert(target_table), mappings)
                        copied += len(mappings)
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
                source_tx.commit()
            except Exception:
                source_tx.rollback()
                raise
    finally:
        target_engine.dispose()

    fd = os.open(str(next_path), os.O_RDWR)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return copied


def build_external_hotdeal_snapshot(
    target_path: Path | str | None = None,
) -> dict:
    """Atomically replace the external-hotdeal read replica."""
    target = (
        Path(target_path).expanduser().resolve()
        if target_path is not None
        else external_hotdeal_snapshot_path()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    next_path = target.with_suffix(target.suffix + ".next")
    # Timestamp microseconds are only publication metadata; source identity is
    # tracked separately with source_fingerprint().
    revision = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

    try:
        copied = _write_snapshot(next_path, revision)
        os.replace(next_path, target)
    except Exception:
        if next_path.exists():
            next_path.unlink()
        raise

    return {
        "path": str(target),
        "revision": revision,
        "row_count": copied,
        "fingerprint": source_fingerprint(),
    }
