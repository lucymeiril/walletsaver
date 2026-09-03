from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.db_admin_readonly import bulk_lookup_match_statuses, reset_db_admin_engine
from services.matching_enrichment import (
    _match_key_for_row, _source_package, enrich_items_with_matching_entries, lookup_row_match_statuses,
)


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
              public_variant_id TEXT PRIMARY KEY, public_product_id TEXT,
              package_quantity REAL, package_unit TEXT, bundle_count INTEGER,
              is_active BOOLEAN
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
            "INSERT INTO normalized_product_variants VALUES ('var-120', 'prod-choco', 120, 'ml', 1, 1)"
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


def _seed_source_scoped_match(engine, row, *, quantity=120, unit="ml", count=24, variant_product="prod-choco"):
    key, _ = _match_key_for_row(deepcopy(row))
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO normalized_canonical_products VALUES "
            "('prod-choco', '초코우유', 'CJ', 'food.dairy.milk.choco', 1)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_product_variants VALUES ('var-120', :product, :qty, :unit, :count, 1)"
        ), {"product": variant_product, "qty": quantity, "unit": unit, "count": count})
        connection.execute(text(
            "INSERT INTO matching_entries VALUES "
            "(1, :key, NULL, NULL, NULL, 0.95, 'external-ai', 'CJ', '초코우유', 120, 'ml', 'prod-choco', 'var-120')"
        ), {"key": key})
    return key


def _source_row(**changes):
    # Small deterministic shape of the persisted DiscountItem rows: the match
    # key uses the full raw name/unit, structured quantity is a separate field,
    # and old crawls retained ×N only in display_unit rather than bundle_count.
    row = {
        "name": "초코우유 120ml×24", "normalized_name": "초코우유 120ml×24",
        "brand": "__no_brand__", "unit": "120ml×24", "display_unit": "120ml×24",
        "package_quantity": 120, "package_unit": "ml", "source": "homeplus",
        "attributes": {"source_record_key": "123", "brand": "CJ"},
    }
    row.update(changes)
    return row


@pytest.mark.parametrize(("changes", "reason"), [
    ({}, None),
    ({"package_quantity": 140}, "normalized_variant_conflict"),
    ({"bundle_count": 12}, "normalized_variant_conflict"),
    ({"package_unit": "g"}, "normalized_variant_conflict"),
    ({"package_quantity": None}, "normalized_unit_unresolved"),
    ({"package_unit": None}, "normalized_unit_unresolved"),
    ({"package_quantity": float("nan")}, "normalized_unit_unresolved"),
    ({"package_quantity": "1e1000"}, "normalized_unit_unresolved"),
    ({"package_quantity": True}, "normalized_unit_unresolved"),
    ({"package_unit": "unknown"}, "normalized_unit_unresolved"),
    ({"bundle_count": 1.5}, "normalized_unit_unresolved"),
    ({"name": "새 초코우유 120ml×24"}, "normalized_source_name_conflict"),
    ({"source_title": "변경된 초코우유 120ml×24"}, "normalized_source_name_conflict"),
    ({"name": "새 초코우유 120ml×24", "normalized_name": "새 초코우유 120ml×24"}, "key_not_found"),
])
def test_runtime_and_export_revalidate_each_source_row(tmp_path, changes, reason):
    engine = _engine(tmp_path)
    original = _source_row()
    key = _seed_source_scoped_match(engine, original)
    reset_db_admin_engine(engine)
    try:
        candidate = _source_row(**changes)
        result = enrich_items_with_matching_entries([deepcopy(candidate)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == reason
        with Session(engine) as session:
            assert bulk_lookup_match_statuses(session, [key])[key] == "normalized_source_verification_required"
            statuses = lookup_row_match_statuses(session, [(candidate, result["match_key"])])
            assert statuses == [reason or "hit"]
    finally:
        reset_db_admin_engine()


def test_active_variant_cannot_belong_to_another_product(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row()
    key = _seed_source_scoped_match(engine, row, variant_product="different-product")
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == "miss"
        assert result["matching_miss_reason"] == "normalized_variant_product_conflict"
        with Session(engine) as session:
            assert bulk_lookup_match_statuses(session, [key])[key] == "normalized_variant_product_conflict"
            assert lookup_row_match_statuses(session, [(row, key)]) == ["normalized_variant_product_conflict"]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("quantity", "unit", "display"), [(1, "L", "1L"), (1000, "ml", "1000ml")])
def test_equivalent_explicit_volume_units_are_safe(tmp_path, quantity, unit, display):
    engine = _engine(tmp_path)
    row = _source_row(name="우유", normalized_name="우유", unit=display, display_unit=display, package_quantity=quantity, package_unit=unit)
    _seed_source_scoped_match(engine, row, quantity=1000, unit="ml", count=1)
    reset_db_admin_engine(engine)
    try:
        assert enrich_items_with_matching_entries([row])[0]["matching_status"] == "hit"
    finally:
        reset_db_admin_engine()


def test_mixed_refill_quantity_cannot_hide_behind_last_parsed_measure(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row(name="샴푸 본품500ml+리필450ml", normalized_name="샴푸 본품500ml+리필450ml", unit="450ml", display_unit="450ml", package_quantity=450)
    _seed_source_scoped_match(engine, row, quantity=450, count=1)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_miss_reason"] == "normalized_variant_conflict"
    finally:
        reset_db_admin_engine()


def test_key_only_rows_and_missing_variant_cannot_be_normalized_hits(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row()
    key = _seed_source_scoped_match(engine, row)
    reset_db_admin_engine(engine)
    try:
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [({"match_key": key}, key)]) == ["normalized_source_name_unresolved"]
        with engine.begin() as connection:
            connection.execute(text("UPDATE matching_entries SET public_variant_id=NULL"))
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_miss_reason"] == "normalized_variant_unavailable"
    finally:
        reset_db_admin_engine()


def test_lookup_failure_clears_stale_hit_metadata(tmp_path, monkeypatch):
    import services.matching_enrichment as module

    engine = _engine(tmp_path)
    reset_db_admin_engine(engine)
    def unavailable(*args):
        raise RuntimeError("isolated failure")
    monkeypatch.setattr(module, "_load_matching_entries", unavailable)
    row = _source_row(matching_status="hit", public_product_id="stale-product", public_variant_id="stale-variant")
    try:
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_status"] == "miss"
        assert result["matching_miss_reason"] == "matching_lookup_unavailable"
        assert "public_product_id" not in result
        assert "public_variant_id" not in result
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("changes", "active", "reason"), [
    ({}, 1, None),
    ({"name": "[밀키트] 변경된 상품 120ml×24"}, 1, "normalized_source_name_conflict"),
    ({"attributes": {"source_record_key": "new-listing"}}, 1, "normalized_source_listing_unavailable"),
    ({}, 0, "normalized_source_listing_unavailable"),
])
def test_original_listing_title_is_the_exact_name_contract(tmp_path, changes, active, reason):
    engine = _engine(tmp_path)
    original = _source_row(name="[밀키트] 초코우유 120ml×24")
    key = _seed_source_scoped_match(engine, original)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE normalized_source_listings (public_variant_id TEXT, source_name TEXT, source_record_key TEXT, source_title TEXT, is_active BOOLEAN)"
        ))
        connection.execute(text(
            "INSERT INTO normalized_source_listings VALUES ('var-120', 'homeplus', '123', :title, :active)"
        ), {"title": original["name"], "active": active})
    reset_db_admin_engine(engine)
    try:
        row = {**original, **changes}
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == reason
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [reason or "hit"]
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("quantity", "unit", "expected"), [
    (14, "T", (14.0, "t", 1)),
    (100, "t", (100.0, "t", 1)),
    (500, "mg", (0.5, "g", 1)),
    (1, "kg", (1000.0, "g", 1)),
])
def test_catalog_count_t_is_not_ton_and_mass_conversions_stay_valid(quantity, unit, expected):
    row = {"name": "동일 상품", "package_quantity": quantity, "package_unit": unit}
    package, reason = _source_package(row)
    assert package == expected
    assert reason is None


def test_count_t_cannot_match_an_equally_numbered_mass_variant(tmp_path):
    engine = _engine(tmp_path)
    row = _source_row(name="차 14T", normalized_name="차 14T", unit="14T", display_unit="14T", package_quantity=14, package_unit="T")
    _seed_source_scoped_match(engine, row, quantity=14000000, unit="g", count=1)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([row])[0]
        assert result["matching_miss_reason"] == "normalized_variant_conflict"
    finally:
        reset_db_admin_engine()


@pytest.mark.parametrize(("title", "quantity", "unit", "reason"), [
    ("캡슐커피 60개입", 60, "ea", None),
    ("팬 2개입", 2, "ea", None),
    ("찹쌀 김부각 세트(5개입) x 5", 5, "ea", "normalized_variant_conflict"),
    ("네일메드코세정제콤보(용기3개+세정용분말250포)", 3, "ea", "normalized_variant_conflict"),
    ("커클랜드 시그니춰 종이타월 160매 x 12롤", 160, "매", "normalized_variant_conflict"),
    ("맑은청 찰토마토 7~10입/팩", 10, "입", "normalized_unit_unresolved"),
])
def test_count_aliases_do_not_hide_ambiguous_package_compositions(tmp_path, title, quantity, unit, reason):
    engine = _engine(tmp_path)
    # Costco uses pack_qty/pack_unit without package_quantity or display_unit.
    row = {"name": title, "pack_qty": quantity, "pack_unit": unit, "source": "costco"}
    key = _seed_source_scoped_match(engine, row, quantity=quantity, unit=unit, count=1)
    reset_db_admin_engine(engine)
    try:
        result = enrich_items_with_matching_entries([deepcopy(row)])[0]
        assert result["matching_status"] == ("miss" if reason else "hit")
        assert result.get("matching_miss_reason") == reason
        with Session(engine) as session:
            assert lookup_row_match_statuses(session, [(row, key)]) == [reason or "hit"]
    finally:
        reset_db_admin_engine()


def test_runtime_keeps_explicit_weight_despite_variable_piece_count():
    package, reason = _source_package({
        "name": "토마토 1.5kg(5~6입)", "package_quantity": 1.5,
        "package_unit": "kg", "display_unit": "1.5kg",
    })
    assert package == (1500.0, "g", 1)
    assert reason is None


@pytest.mark.parametrize("count", [1, 2, 5])
def test_runtime_numeric_bundle_count_cannot_resolve_unparsed_multiplication(count):
    package, reason = _source_package({
        "name": "김부각 세트(5개입) x 5", "pack_qty": 5,
        "pack_unit": "ea", "bundle_count": count,
    })
    assert package is None
    assert reason == "normalized_variant_conflict"


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
