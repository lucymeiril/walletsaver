from __future__ import annotations

import sqlite3
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services import public_snapshot_v2
from storage.models import Base, NormalizedCanonicalProduct, UnifiedCategory


def test_public_snapshot_contains_normalized_catalog_tables(tmp_path, monkeypatch):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    Base.metadata.create_all(source)
    with Session(source) as session:
        session.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
        session.add(NormalizedCanonicalProduct(
            public_product_id="prod-1",
            unified_category_id="food",
            canonical_name="테스트 상품",
            aliases=[], keywords=[], attributes={},
        ))
        session.commit()

    monkeypatch.setattr(public_snapshot_v2, "get_engine", lambda: source)
    target = tmp_path / "public.sqlite"
    result = public_snapshot_v2.build_public_snapshot(target)

    assert result["row_counts"]["normalized_canonical_products"] == 1
    with sqlite3.connect(target) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "normalized_product_variants" in tables
        assert connection.execute("SELECT unified_category_id FROM normalized_canonical_products").fetchone()[0] == "food"


def test_public_snapshot_keeps_one_validated_rollback_version(tmp_path, monkeypatch):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    Base.metadata.create_all(source)
    with Session(source) as session:
        session.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
        session.add(NormalizedCanonicalProduct(
            public_product_id="prod-1", unified_category_id="food",
            canonical_name="첫 버전", aliases=[], keywords=[], attributes={},
        ))
        session.commit()

    monkeypatch.setattr(public_snapshot_v2, "get_engine", lambda: source)
    target = tmp_path / "public.sqlite"
    public_snapshot_v2.build_public_snapshot(target)

    with Session(source) as session:
        session.get(NormalizedCanonicalProduct, "prod-1").canonical_name = "둘째 버전"
        session.commit()
    second = public_snapshot_v2.build_public_snapshot(target)

    assert second["previous_path"].endswith(".previous")
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT canonical_name FROM normalized_canonical_products"
        ).fetchone()[0] == "둘째 버전"
    connection.close()

    public_snapshot_v2.rollback_public_snapshot(target)
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT canonical_name FROM normalized_canonical_products"
        ).fetchone()[0] == "첫 버전"
    connection.close()


def test_snapshot_validation_rejects_missing_product_category(tmp_path, monkeypatch):
    source = create_engine(f"sqlite:///{(tmp_path / 'source.sqlite').as_posix()}")
    Base.metadata.create_all(source)
    with Session(source) as session:
        session.add(UnifiedCategory(id="leaf", slug="leaf", name_ko="리프", level=0))
        session.add(NormalizedCanonicalProduct(
            public_product_id="prod-1", unified_category_id="leaf",
            canonical_name="상품", aliases=[], keywords=[], attributes={},
        ))
        session.commit()
    monkeypatch.setattr(public_snapshot_v2, "get_engine", lambda: source)
    target = tmp_path / "public.sqlite"
    public_snapshot_v2.build_public_snapshot(target)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE normalized_canonical_products SET unified_category_id='missing'"
        )
        connection.commit()
    connection.close()

    with pytest.raises(ValueError, match="leaf category"):
        public_snapshot_v2.validate_public_snapshot(target)
