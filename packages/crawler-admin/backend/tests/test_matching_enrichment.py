from __future__ import annotations

from sqlalchemy import create_engine, text

from services.db_admin_readonly import reset_db_admin_engine
from services.matching_enrichment import enrich_items_with_matching_entries


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE matching_entries (
              id INTEGER PRIMARY KEY, match_key TEXT UNIQUE, canonical_product_id TEXT,
              category_id TEXT, keyword_ids JSON, confidence REAL, source TEXT,
              brand TEXT, name_core TEXT, pack_qty REAL, pack_unit TEXT,
              public_product_id TEXT, public_variant_id TEXT
            )
        """))
        connection.execute(text("""
            CREATE TABLE products (
              id INTEGER PRIMARY KEY, name TEXT, display_name TEXT, brand TEXT,
              name_core TEXT, pack_qty REAL, pack_unit TEXT, category_id TEXT,
              unified_category_id TEXT, is_active BOOLEAN
            )
        """))
        connection.execute(text("""
            CREATE TABLE normalized_canonical_products (
              public_product_id TEXT PRIMARY KEY, canonical_name TEXT, brand TEXT,
              unified_category_id TEXT, is_active BOOLEAN
            )
        """))
        connection.execute(text("""
            CREATE TABLE normalized_product_variants (
              public_variant_id TEXT PRIMARY KEY, is_active BOOLEAN
            )
        """))
    return engine


def test_normalized_match_hit_preserves_source_title_and_adds_ssot_refs(tmp_path):
    from core.match_key import build_match_key

    engine = _engine(tmp_path)
    key = build_match_key("남양", "초코에몽", 120, "ml")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO normalized_canonical_products VALUES "
            "('prod-choco', '초코에몽', '남양', 'food.dairy.milk.choco', 1)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_product_variants VALUES ('var-120', 1)"
        ))
        connection.execute(text(
            "INSERT INTO matching_entries VALUES "
            "(1, :key, NULL, NULL, NULL, 0.95, 'human', '남양', '초코에몽', 120, 'ml', 'prod-choco', 'var-120')"
        ), {"key": key})
    reset_db_admin_engine(engine)
    try:
        row = {"brand": "남양", "name": "초코에몽", "pack_qty": 120, "pack_unit": "ml"}
        enriched = enrich_items_with_matching_entries([row])[0]
        assert enriched["matching_status"] == "hit"
        assert enriched["source_title"] == "초코에몽"
        assert enriched["public_product_id"] == "prod-choco"
        assert enriched["public_variant_id"] == "var-120"
        assert enriched["unified_category_id"] == "food.dairy.milk.choco"
    finally:
        reset_db_admin_engine()


def test_low_confidence_matching_entry_remains_a_miss(tmp_path):
    from core.match_key import build_match_key

    engine = _engine(tmp_path)
    key = build_match_key("남양", "초코에몽", 120, "ml")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO normalized_canonical_products VALUES "
            "('prod-choco', '초코에몽', '남양', 'food.dairy.milk.choco', 1)"
        ))
        connection.execute(text(
            "INSERT INTO matching_entries VALUES "
            "(1, :key, NULL, NULL, NULL, 0.79, 'external-ai', '남양', '초코에몽', 120, 'ml', 'prod-choco', NULL)"
        ), {"key": key})
    reset_db_admin_engine(engine)
    try:
        enriched = enrich_items_with_matching_entries([
            {"brand": "남양", "name": "초코에몽", "pack_qty": 120, "pack_unit": "ml"}
        ])[0]
        assert enriched["matching_status"] == "miss"
        assert enriched["matching_miss_reason"] == "low_confidence"
        assert "public_product_id" not in enriched
    finally:
        reset_db_admin_engine()
