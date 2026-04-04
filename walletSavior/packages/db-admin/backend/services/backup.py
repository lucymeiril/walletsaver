"""
SQLite backup service.
Provides on-demand and pre-destructive-operation backups.
"""
import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "30"))


def _ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def backup_sqlite(db_path: str, *, reason: str = "manual") -> str:
    """
    Create a hot backup of a SQLite database using the backup API.
    Returns the path to the backup file.
    """
    _ensure_backup_dir()
    ts = _timestamp()
    backup_name = f"walletguardian_{reason}_{ts}.db"
    backup_path = BACKUP_DIR / backup_name

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
        logger.info("SQLite backup created: %s (%s)", backup_path, reason)
    finally:
        dst.close()
        src.close()

    _rotate_backups()
    return str(backup_path)


def create_backup(database_url: str, *, reason: str = "manual") -> str:
    """Auto-detect database type and create appropriate backup."""
    if database_url.startswith("sqlite"):
        db_path = database_url.replace("sqlite:///", "")
        return backup_sqlite(db_path, reason=reason)
    else:
        raise ValueError(f"Unsupported database type for backup: {database_url}")


def _rotate_backups():
    """Remove oldest backups beyond RETENTION_COUNT."""
    _ensure_backup_dir()
    backups = sorted(BACKUP_DIR.glob("walletguardian_*"), key=os.path.getmtime)
    while len(backups) > RETENTION_COUNT:
        oldest = backups.pop(0)
        oldest.unlink()
        logger.info("Rotated old backup: %s", oldest)


def list_backups() -> list[dict]:
    """List all available backups with metadata."""
    _ensure_backup_dir()
    result = []
    for f in sorted(BACKUP_DIR.glob("walletguardian_*"), key=os.path.getmtime, reverse=True):
        stat = f.stat()
        result.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result
