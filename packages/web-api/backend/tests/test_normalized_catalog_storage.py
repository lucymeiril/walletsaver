from __future__ import annotations

import json
import sqlite3

from services.catalog_storage import PublicCatalogStore


def test_empty_normalized_schema_does_not_resurrect_legacy_categories(tmp_path):
    path = tmp_path / "empty-capstone.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE categories (id TEXT PRIMARY KEY, parent_id TEXT, name TEXT, sort_order INTEGER);
        INSERT INTO categories VALUES ('legacy', NULL, '레거시', 0);
        CREATE TABLE products (id INTEGER PRIMARY KEY, category_id TEXT, unified_category_id TEXT, name TEXT, is_active INTEGER);
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT, name_ko TEXT, sort_order INTEGER DEFAULT 0);
        CREATE TABLE normalized_canonical_products (
          public_product_id TEXT PRIMARY KEY, unified_category_id TEXT,
          canonical_name TEXT, brand TEXT, aliases TEXT, keywords TEXT,
          attributes TEXT, primary_image_url TEXT, is_active INTEGER
        );
        """)
    store = PublicCatalogStore(path)

    assert store.get_category_tree() == []
    assert store.get_category_products("legacy", 1, 20) == ([], 0)


def test_normalized_catalog_exposes_total_bundle_and_unit_prices(tmp_path):
    path = tmp_path / "catalog.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE unified_categories (id TEXT PRIMARY KEY, parent_id TEXT, name_ko TEXT, sort_order INTEGER DEFAULT 0);
        CREATE TABLE normalized_canonical_products (
          public_product_id TEXT PRIMARY KEY, unified_category_id TEXT,
          canonical_name TEXT, brand TEXT, aliases TEXT, keywords TEXT,
          attributes TEXT, primary_image_url TEXT, is_active INTEGER
        );
        CREATE TABLE normalized_product_variants (
          public_variant_id TEXT PRIMARY KEY, public_product_id TEXT, variant_name TEXT,
          package_quantity REAL, package_unit TEXT, display_unit TEXT,
          bundle_count INTEGER, standard_unit TEXT, attributes TEXT, is_active INTEGER
        );
        CREATE TABLE normalized_source_listings (
          public_source_listing_id TEXT PRIMARY KEY, public_variant_id TEXT,
          source_name TEXT, source_record_key TEXT, source_title TEXT, source_url TEXT,
          image_url TEXT, source_unit_text TEXT, is_active INTEGER
        );
        CREATE TABLE normalized_offer_events (
          public_offer_event_id TEXT PRIMARY KEY, public_source_listing_id TEXT,
          price_state TEXT, promotion_type TEXT, price REAL, original_price REAL,
          discount_rate REAL, event_name TEXT, raw_evidence TEXT,
          crawled_at TEXT, offer_state TEXT
        );
        """)
        db.executemany("INSERT INTO unified_categories VALUES (?,?,?,?)", [
            ("food", None, "식품", 0),
            ("food.dairy", "food", "유제품", 0),
            ("food.dairy.milk", "food.dairy", "우유", 0),
            ("food.dairy.milk.choco", "food.dairy.milk", "초코우유", 0),
        ])
        db.execute(
            "INSERT INTO normalized_canonical_products VALUES (?,?,?,?,?,?,?,?,?)",
            ("prod-choco", "food.dairy.milk.choco", "초코에몽", "남양", "[]", "[]", json.dumps({"classification_warning": True}), None, 1),
        )
        db.execute(
            "INSERT INTO normalized_product_variants VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("var-120-24", "prod-choco", "120ml 24개", 120, "ml", "120ml×24", 24, "100ml", "{}", 1),
        )
        db.execute(
            "INSERT INTO normalized_source_listings VALUES (?,?,?,?,?,?,?,?,?)",
            ("list-emart", "var-120-24", "emart", "123", "초코에몽 120ml 24개", "https://example.test", None, "120ml×24", 1),
        )
        db.execute(
            "INSERT INTO normalized_offer_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("offer-1", "list-emart", "normal", "was_now_price", 24000, 28800, 0.1667, "회원가", json.dumps({"condition_text": "회원 1인 1개"}), "2026-08-30", "active"),
        )
        db.commit()

    store = PublicCatalogStore(path)
    rows, total = store.search_normalized_products_page("초코", page=1, per_page=10)

    assert total == 1
    assert rows[0]["classification_label"] == "분류 확인 필요"
    detail = store.get_normalized_product_detail("prod-choco")
    offer = detail["variants"][0]["listings"][0]["offers"][0]
    assert offer["total_price"] == 24000
    assert offer["total_quantity"] == 2880
    assert offer["per_item"] == 1000
    assert offer["per_100ml"] == 833
    assert offer["promotion_condition"] == "회원 1인 1개"

    tree = store.get_category_tree()
    assert tree[0]["name"] == "식품"
    assert tree[0]["count"] == 1
    children, total, path_text = store.get_category_children("food.dairy.milk")
    assert total == 1
    assert children == [{"id": "food.dairy.milk.choco", "name": "초코우유", "count": 1}]
    assert path_text == "식품 > 유제품 > 우유"
    category_rows, category_total = store.get_category_products(
        "food.dairy", page=1, per_page=10
    )
    assert category_total == 1
    assert category_rows[0]["public_product_id"] == "prod-choco"

    mart = store.get_mart_deals("emart")
    deal = mart["emart"]["items"][0]
    assert deal["sale"] == 24000
    assert deal["per_100ml"] == 833
    assert deal["promotion_condition"] == "회원 1인 1개"
