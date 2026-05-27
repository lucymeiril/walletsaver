from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from db_admin.backend.scripts import g2_category_aggregator as agg


def _make_db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE products (mart TEXT, mart_native_category_id TEXT, mart_native_category_path TEXT)"
    )
    conn.executemany(
        "INSERT INTO products (mart, mart_native_category_id, mart_native_category_path) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def test_aggregator_finds_all_marts_in_db(tmp_path: Path) -> None:
    db_path = tmp_path / "walletguardian.db"
    _make_db(
        db_path,
        [
            ("emart", "6000095494", "과일/채소"),
            ("homeplus", "1", "정육"),
            ("lottemart", "008001", "우유ㆍ유제품 > 우유"),
            ("costco", "cos_10.1", "식품 > 쌀/잡곡"),
        ],
    )

    records = agg.read_db_categories(db_path)

    assert {record.mart for record in records} == set(agg.MARTS)


def test_tree_yaml_validates_against_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "walletguardian.db"
    _make_db(
        db_path,
        [
            ("emart", "6000095494", "과일/채소"),
            ("homeplus", "1", "정육"),
            ("lottemart", "008001", "우유ㆍ유제품 > 우유"),
            ("costco", "cos_10.1", "식품 > 쌀/잡곡"),
        ],
    )
    output = tmp_path / "g2-unified-tree.yaml"

    tree = agg.generate(output, db_path, write_report_file=False)
    loaded = yaml.safe_load(output.read_text(encoding="utf-8"))

    assert loaded == tree
    assert loaded["schema"] == "unified_category_tree.v1"
    assert loaded["authoritative_mart"] in agg.MARTS
    assert isinstance(loaded["nodes"], list) and loaded["nodes"]
    food = next(node for node in loaded["nodes"] if node["id"] == "food")
    dairy = next(node for node in loaded["nodes"] if node["id"] == "food.dairy")
    milk = next(node for node in loaded["nodes"] if node["id"] == "food.dairy.milk")
    assert dairy["id"] in food["children"]
    assert milk["id"] in dairy["children"]
    for node in loaded["nodes"]:
        assert {"id", "name", "parent_id", "children", "source_natives"}.issubset(node)
        assert set(node["source_natives"]) == set(agg.MARTS)


def test_unmapped_natives_go_to_review_queue() -> None:
    native = agg.NativeCategory("emart", "unknown-1", "계절특설 > 한정행사", "test")

    tree = agg.build_tree([native], [], {mart: [] for mart in agg.MARTS})

    assert any(
        item["native_id"] == "unknown-1" and item["status"] == "needs_review"
        for item in tree["review_queue"]
    )
