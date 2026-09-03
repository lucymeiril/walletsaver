"""Exercise the SQLite keyword migration, not only metadata.create_all()."""
from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_keyword_upgrade_downgrade_preserves_legacy_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.sqlite').as_posix()}")
    migration = import_module("storage.migrations.versions.capstone_keyword_ssot_v1")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE categories (id VARCHAR(100) PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE unified_categories (id VARCHAR(100) PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE keywords (id INTEGER PRIMARY KEY, word VARCHAR(100) NOT NULL UNIQUE, synonyms JSON, category_id VARCHAR(100) REFERENCES categories(id), search_count INTEGER, is_active BOOLEAN)")
        connection.exec_driver_sql("INSERT INTO categories VALUES ('legacy')")
        connection.exec_driver_sql("INSERT INTO unified_categories VALUES ('food.milk')")
        connection.exec_driver_sql("INSERT INTO keywords VALUES (7, '우유', '[]', 'legacy', 123, 1)")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        row = connection.execute(text("SELECT word, category_id, search_count, unified_category_id FROM keywords WHERE id=7")).one()
        assert tuple(row) == ("우유", "legacy", 123, None)
        connection.exec_driver_sql("UPDATE keywords SET unified_category_id='food.milk' WHERE id=7")
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert any(fk["referred_table"] == "unified_categories" for fk in inspect(connection).get_foreign_keys("keywords"))
        migration.downgrade()
        assert "unified_category_id" not in {col["name"] for col in inspect(connection).get_columns("keywords")}
        assert tuple(connection.exec_driver_sql("SELECT id, word, category_id, search_count FROM keywords").one()) == (7, "우유", "legacy", 123)
        migration.upgrade()
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    engine.dispose()
