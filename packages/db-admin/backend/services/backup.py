"""SQLite backups used to guard destructive DB-admin operations."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import shutil
import sqlite3

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
RETENTION_COUNT = max(1, int(os.getenv("BACKUP_RETENTION_COUNT", "30")))


def create_backup(database_url: str, *, reason: str = "manual") -> str:
    """Create a consistent hot backup for a file-backed SQLite database."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError(f"Unsupported database type for backup: {url.get_backend_name()}")
    if not url.database or url.database == ":memory:":
        raise ValueError("A file-backed SQLite database is required for backup")
    return backup_sqlite(url.database, reason=reason)


def backup_sqlite(db_path: str | Path, *, reason: str = "manual") -> str:
    source_path = Path(db_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Database file not found: {source_path}")

    backup_dir = _ensure_backup_dir()
    required_bytes = max(source_path.stat().st_size * 2, 1)
    available_bytes = shutil.disk_usage(backup_dir).free
    if available_bytes < required_bytes:
        raise OSError(
            f"Insufficient disk space for backup: need {required_bytes} bytes, "
            f"have {available_bytes} bytes"
        )

    safe_reason = "".join(
        char if char.isalnum() or char in "-_" else "-" for char in reason
    ).strip("-") or "manual"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"walletguardian_{safe_reason}_{timestamp}.db"

    source = sqlite3.connect(str(source_path))
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    _rotate_backups()
    logger.info("SQLite backup created: %s (%s)", backup_path, safe_reason)
    return str(backup_path)


def list_backups() -> list[dict]:
    """List managed backup files, newest first."""
    backup_dir = _ensure_backup_dir()
    backups = sorted(
        backup_dir.glob("walletguardian_*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return [
        {
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(
                path.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(),
        }
        for path in backups
    ]


def _ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _rotate_backups() -> None:
    backups = sorted(
        _ensure_backup_dir().glob("walletguardian_*.db"),
        key=lambda path: path.stat().st_mtime,
    )
    for obsolete in backups[:-RETENTION_COUNT]:
        obsolete.unlink()
        logger.info("Rotated old backup: %s", obsolete)
