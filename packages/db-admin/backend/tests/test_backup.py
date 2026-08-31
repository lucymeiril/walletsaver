import sqlite3

from services import backup


def test_create_backup_copies_sqlite_database(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE sample (value TEXT)")
        connection.execute("INSERT INTO sample VALUES ('kept')")

    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "backups")
    backup_path = backup.create_backup(f"sqlite:///{source.as_posix()}", reason="test")

    with sqlite3.connect(backup_path) as connection:
        assert connection.execute("SELECT value FROM sample").fetchone() == ("kept",)
    assert backup.list_backups()[0]["filename"].endswith(".db")
