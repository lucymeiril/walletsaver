from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.artifact_db_adversarial_compare import compare_rows, normalize_public_row, _load_json_items, _sqlite_rows


def test_compare_rows_flags_source_owned_changes_and_duplicates() -> None:
    source_rows = [
        {
            "name": "상품 A 600g",
            "sale_price": 4110,
            "original_price": 5480,
            "discount_percent": 25,
            "detail_url": "https://example.invalid/a",
            "image_url": "https://example.invalid/a.jpg",
            "source": "emart",
            "package_quantity": 600,
            "package_unit": "g",
            "price_per_100g": 685,
            "category": "채소",
        },
        {
            "name": "상품 A 600g",
            "sale_price": 4110,
            "detail_url": "https://example.invalid/a",
            "source": "emart",
        },
    ]
    target_rows = [
        {
            "match_key": "emart|https://example.invalid/a|상품 A 600g",
            "row_kind": "proof_public_verification",
            "raw_title": "상품 A 600g",
            "current_price": 4990,
            "original_price": 5480,
            "discount_percent": 25,
            "detail_url": "https://example.invalid/a",
            "source_url": "https://example.invalid/a",
            "image_url": "https://example.invalid/a.jpg",
            "source": "emart",
            "package_quantity": 600,
            "package_unit": "g",
            "bundle_count": 1,
            "price_per_100g": 685,
            "standard_unit_price": 6850,
            "category": "채소",
        }
    ]

    comparison = compare_rows(source_rows, target_rows)

    assert comparison["counts"]["matched_rows"] == 2
    assert comparison["counts"]["changed_rows"] == 2
    assert comparison["counts"]["duplicate_key_groups"] == 1
    assert any(item["field"] == "current_price" for item in comparison["suspicious_changed_fields"])


def test_compare_rows_does_not_treat_package_enrichment_as_source_fact_change() -> None:
    source_rows = [
        {
            "raw_record_id": "emart:url:abc",
            "name": "성주 참외 5kg",
            "sale_price": 25890,
            "discount_percent": 0,
            "detail_url": "https://example.invalid/a",
            "image_url": "https://example.invalid/a.jpg",
            "source": "이마트",
            "unit": "100g",
        }
    ]
    target_rows = [
        {
            "match_key": "emart:url:abc",
            "row_kind": "proof_public_verification",
            "raw_title": "성주 참외 5kg",
            "current_price": 25890,
            "discount_percent": None,
            "detail_url": "https://example.invalid/a",
            "source_url": "https://example.invalid/a",
            "image_url": "https://example.invalid/a.jpg",
            "source": "emart",
            "unit": "5kg",
            "package_quantity": 5,
            "package_unit": "kg",
            "bundle_count": 1,
            "price_per_100g": 517.8,
            "standard_unit_price": 5178,
        }
    ]

    comparison = compare_rows(source_rows, target_rows)

    assert comparison["counts"]["matched_rows"] == 1
    assert comparison["counts"]["changed_rows"] == 1
    assert comparison["counts"]["suspicious_fields"] == 0


def test_compare_rows_does_not_treat_count_basis_unit_as_source_fact_change() -> None:
    source_rows = [
        {
            "raw_record_id": "emart:url:tissue",
            "name": "뽑아쓰는 키친타월 140매x4입",
            "sale_price": 10900,
            "detail_url": "https://example.invalid/tissue",
            "source": "이마트",
            "unit": "10매",
            "category": "크리넥스",
        }
    ]
    target_rows = [
        {
            "match_key": "emart:url:tissue",
            "row_kind": "proof_public_verification",
            "raw_title": "뽑아쓰는 키친타월 140매x4입",
            "current_price": 10900,
            "detail_url": "https://example.invalid/tissue",
            "source_url": "https://example.invalid/tissue",
            "source": "emart",
            "unit": "4입",
            "package_quantity": 4,
            "package_unit": "입",
            "bundle_count": 1,
            "category": "크리넥스",
        }
    ]

    comparison = compare_rows(source_rows, target_rows)

    assert comparison["counts"]["matched_rows"] == 1
    assert comparison["counts"]["changed_rows"] == 1
    assert comparison["counts"]["suspicious_fields"] == 0


def test_compare_rows_accepts_known_category_taxonomy_mapping() -> None:
    source_rows = [
        {
            "raw_record_id": "emart:url:rice",
            "name": "강화섬쌀밥 200g*4개",
            "sale_price": 4886,
            "detail_url": "https://example.invalid/rice",
            "source": "이마트",
            "unit": "100g",
            "category": "곡류 > 쌀",
        }
    ]
    target_rows = [
        {
            "match_key": "emart:url:rice",
            "row_kind": "proof_public_verification",
            "raw_title": "강화섬쌀밥 200g*4개",
            "current_price": 4886,
            "detail_url": "https://example.invalid/rice",
            "source_url": "https://example.invalid/rice",
            "source": "emart",
            "unit": "200g×4",
            "package_quantity": 200,
            "package_unit": "g",
            "bundle_count": 4,
            "price_per_100g": 610.75,
            "standard_unit_price": 6107.5,
            "category": "grain.rice",
        }
    ]

    comparison = compare_rows(source_rows, target_rows)

    assert comparison["counts"]["matched_rows"] == 1
    assert comparison["counts"]["suspicious_fields"] == 0
    assert not any(diff["field"] == "category" for diff in comparison["changed_rows"][0]["diffs"])


def test_compare_rows_does_not_treat_ai_category_enrichment_as_source_fact_change() -> None:
    source_rows = [
        {
            "raw_record_id": "emart-fixture:fixture-shrimp",
            "name": "흰다리 새우살 300g",
            "sale_price": 7980,
            "detail_url": "https://example.invalid/shrimp",
            "source": "emart",
            "category": None,
        }
    ]
    target_rows = [
        {
            "match_key": "emart-fixture:fixture-shrimp",
            "row_kind": "proof_public_verification",
            "raw_title": "흰다리 새우살 300g",
            "current_price": 7980,
            "detail_url": "https://example.invalid/shrimp",
            "source_url": "https://example.invalid/shrimp",
            "source": "emart",
            "unit": "300g",
            "package_quantity": 300,
            "package_unit": "g",
            "category": "seafood.frozen",
        }
    ]

    comparison = compare_rows(source_rows, target_rows)

    assert comparison["counts"]["matched_rows"] == 1
    assert comparison["counts"]["suspicious_fields"] == 0


def test_normalize_public_row_uses_nested_public_verification_fields() -> None:
    row = {
        "table": "discount_history",
        "id": 7,
        "price": 4110,
        "raw_data": {
            "normalized": {
                "source_listing": {
                    "source_name": "emart",
                    "source_title": "상품 A",
                    "source_url": "https://example.invalid/a",
                    "image_url": "https://example.invalid/a.jpg",
                },
                "product_variant": {"display_unit": "600g", "package_quantity": 600, "package_unit": "g", "bundle_count": 1},
                "offer_event": {"current_price": 4110, "original_price": 5480, "discount_percent": 25, "standard_unit_price": 6850},
                "canonical_product": {"category_name": "채소"},
            }
        },
    }

    normalized = normalize_public_row(row, raw_record_id="emart:url:abc")

    assert normalized["match_key"] == "emart:url:abc"
    assert normalized["raw_title"] == "상품 A"
    assert normalized["current_price"] == 4110
    assert normalized["standard_unit_price"] == 6850
    assert normalized["category"] == "채소"


def test_sqlite_rows_reads_normalized_projection(tmp_path: Path) -> None:
    db_path = tmp_path / "proof.sqlite"
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        create table products (id integer);
        create table discount_history (id integer);
        create table normalized_source_listings (
            public_source_listing_id text primary key, public_variant_id text, source_name text,
            source_record_key text, source_title text, source_url text, image_url text, source_unit_text text
        );
        create table normalized_offer_events (
            public_offer_event_id text primary key, public_source_listing_id text, price real,
            original_price real, discount_rate real, standard_unit_price real, price_per_100g real,
            raw_record_id text, raw_evidence text
        );
        create table normalized_product_variants (
            public_variant_id text primary key, public_product_id text, variant_name text,
            package_quantity real, package_unit text, display_unit text, bundle_count integer
        );
        create table normalized_canonical_products (
            public_product_id text primary key, category_id text, canonical_name text, primary_image_url text
        );
        """
    )
    con.execute("insert into products values (1)")
    con.execute("insert into discount_history values (1)")
    con.execute("insert into normalized_canonical_products values ('p1', '라면', '상품 A', null)")
    con.execute("insert into normalized_product_variants values ('v1', 'p1', '상품 A', 120, 'g', '120g×5', 5)")
    con.execute("insert into normalized_source_listings values ('s1', 'v1', 'homeplus', null, '상품 A', 'https://example.invalid/a', 'https://example.invalid/a.jpg', '120g×5')")
    con.execute(
        "insert into normalized_offer_events values ('o1', 's1', 4150, null, 0.1, 6916.67, 691.67, 'homeplus:url:abc', ?)",
        (json.dumps({"raw_payload": {"category": "라면"}}, ensure_ascii=False),),
    )
    con.commit()
    con.close()

    rows, counts = _sqlite_rows(db_path)

    assert counts["products"] == 1
    assert counts["discount_history"] == 1
    assert rows[0]["raw_record_id"] == "homeplus:url:abc"
    assert rows[0]["source"] == "homeplus"
    assert rows[0]["price_per_100g"] == 691.67


def test_load_json_items_prefers_raw_records_with_stable_ids(tmp_path: Path) -> None:
    artifact_path = tmp_path / "live-artifact.json"
    artifact_path.write_text(
        json.dumps(
            {
                "raw_selected_items": [{"name": "상품 A", "detail_url": "https://example.invalid/a"}],
                "raw_records": [
                    {
                        "raw_record_id": "emart:url:abc",
                        "raw_title": "상품 A",
                        "source_url": "https://example.invalid/a",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rows = _load_json_items(artifact_path)

    assert rows == [
        {
            "raw_record_id": "emart:url:abc",
            "raw_title": "상품 A",
            "source_url": "https://example.invalid/a",
        }
    ]
