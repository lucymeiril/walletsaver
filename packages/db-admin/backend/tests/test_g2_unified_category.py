from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from services.unified_categories import list_mappings, upsert_mapping
from storage.models import Base, MartCategoryMapping, Product, UnifiedCategory


def _session() -> Session:
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_model_crud_and_mapping_review_status() -> None:
    session = _session()
    try:
        category = UnifiedCategory(id="food", slug="food", name_ko="식품", level=0, sort_order=0, source_origin="lottemart")
        session.add(category)
        session.add(Product(name="테스트 우유", mart="homeplus", mart_native_category_id="hp-1", mart_native_category_path="우유"))
        session.commit()

        before = list_mappings(session, "homeplus")
        assert before[0]["review_status"] == "needs_review"

        mapping, action = upsert_mapping(
            session,
            mart="homeplus",
            mart_native_id="hp-1",
            mart_native_path="우유",
            unified_category_id="food",
            trust="human",
            confidence=1.0,
            decided_by="tester",
        )
        session.commit()

        assert action == "created"
        assert mapping.unified_category_id == "food"
        after = list_mappings(session, "homeplus")
        assert after[0]["review_status"] == "mapped"
        assert after[0]["trust"] == "human"
    finally:
        session.close()


def test_mapping_trust_hierarchy_blocks_lower_overwrite() -> None:
    session = _session()
    try:
        session.add_all([
            UnifiedCategory(id="food", slug="food", name_ko="식품", level=0, sort_order=0),
            UnifiedCategory(id="living", slug="living", name_ko="생활", level=0, sort_order=1),
        ])
        session.commit()

        upsert_mapping(
            session,
            mart="lottemart",
            mart_native_id="001",
            mart_native_path="식품",
            unified_category_id="food",
            trust="human",
            confidence=1.0,
            decided_by="operator",
        )
        session.commit()

        mapping, action = upsert_mapping(
            session,
            mart="lottemart",
            mart_native_id="001",
            mart_native_path="생활",
            unified_category_id="living",
            trust="auto-aggregate",
            confidence=0.7,
            decided_by="seed",
        )
        session.commit()

        assert action == "conflict"
        assert mapping.unified_category_id == "food"
        assert session.get(MartCategoryMapping, mapping.id).unified_category_id == "food"
    finally:
        session.close()


def test_seed_unified_tree_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import g2_seed_unified_tree as seed

    yaml_path = tmp_path / "g2-unified-tree.yaml"
    yaml_path.write_text(
        yaml.safe_dump(
            {
                "schema": "unified_category_tree.v1",
                "authoritative_mart": "lottemart",
                "nodes": [
                    {"id": "food", "name": "식품", "parent_id": None, "children": ["food.dairy"], "source_natives": {"lottemart": ["001"]}},
                    {"id": "food.dairy", "name": "우유/유제품", "parent_id": "food", "children": [], "source_natives": {"lottemart": ["008"]}},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    @contextmanager
    def managed_test_session():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    monkeypatch.setattr(seed, "managed_session", managed_test_session)

    first = seed.seed_from_yaml(yaml_path)
    second = seed.seed_from_yaml(yaml_path)

    assert first["categories_inserted"] == 2
    assert first["lottemart_mappings_inserted"] == 2
    assert second["categories_inserted"] == 0
    assert second["lottemart_mappings_inserted"] == 0
    with SessionLocal() as session:
        assert session.query(UnifiedCategory).count() == 2
        assert session.query(MartCategoryMapping).count() == 2


def test_g2_migration_up_down_smoke() -> None:
    migration_path = Path(__file__).resolve().parents[1] / "storage" / "migrations" / "versions" / "c3d4e5f6a7b8_round_r_g2_unified_category.py"
    spec = importlib.util.spec_from_file_location("g2_migration", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://", echo=False)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL)"))
        ctx = MigrationContext.configure(conn)
        op = Operations(ctx)
        migration.op = op

        migration.upgrade()
        inspector = inspect(conn)
        assert "unified_categories" in inspector.get_table_names()
        assert "mart_category_mappings" in inspector.get_table_names()
        assert "unified_category_id" in {col["name"] for col in inspector.get_columns("products")}

        migration.downgrade()
        inspector = inspect(conn)
        assert "unified_categories" not in inspector.get_table_names()
        assert "mart_category_mappings" not in inspector.get_table_names()
        assert "unified_category_id" not in {col["name"] for col in inspector.get_columns("products")}
