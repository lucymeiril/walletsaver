"""Tests for database backup service."""
import os
import sqlite3
import pytest
from pathlib import Path
from services.backup import (
    backup_sqlite,
    list_backups,
    restore_sqlite_backup,
)


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'hello')")
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture(autouse=True)
def set_backup_dir(tmp_path, monkeypatch):
    """Use temporary directory for backups during tests."""
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(backup_dir))
    import services.backup as bmod
    bmod.BACKUP_DIR = backup_dir
    return backup_dir


def test_sqlite_backup_creates_file(temp_db):
    path = backup_sqlite(temp_db, reason="test")
    assert os.path.exists(path)
    assert "test" in os.path.basename(path)


def test_sqlite_backup_is_valid(temp_db):
    path = backup_sqlite(temp_db, reason="test")
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT val FROM test WHERE id=1").fetchone()
    conn.close()
    assert rows[0] == "hello"


def test_list_backups_returns_metadata(temp_db):
    backup_sqlite(temp_db, reason="test")
    backups = list_backups()
    assert len(backups) == 1
    assert "filename" in backups[0]
    assert "size_bytes" in backups[0]
    assert "created_at" in backups[0]


def test_rotation_removes_old_backups(temp_db, monkeypatch):
    import services.backup as bmod
    monkeypatch.setattr(bmod, "RETENTION_COUNT", 2)
    backup_sqlite(temp_db, reason="old1")
    backup_sqlite(temp_db, reason="old2")
    backup_sqlite(temp_db, reason="new1")
    assert len(list_backups()) == 2


def test_restore_sqlite_backup_restores_temp_database(temp_db):
    backup_path = backup_sqlite(temp_db, reason="pre_mutation")
    conn = sqlite3.connect(temp_db)
    conn.execute("UPDATE test SET val='mutated' WHERE id=1")
    conn.commit()
    conn.close()

    restored = restore_sqlite_backup(backup_path, temp_db)

    assert restored == temp_db
    conn = sqlite3.connect(temp_db)
    rows = conn.execute("SELECT val FROM test WHERE id=1").fetchone()
    conn.close()
    assert rows[0] == "hello"
