"""Structural integrity checks for the static category/keyword seed data.

These tests intentionally avoid product-planning assumptions such as minimum
category counts or required business domains. They only protect data that would
break lookup/seed behavior if malformed.
"""

from category_data.categories import (
    CATEGORIES,
    flatten_tree,
    get_all_ids,
    get_category_tree,
    validate_tree,
)
from category_data.keywords import KEYWORDS


def test_category_tree_has_unique_ids_and_valid_parent_depth_links():
    ids = [category["id"] for category in CATEGORIES]
    assert len(ids) == len(set(ids))

    by_id = {category["id"]: category for category in CATEGORIES}
    for category in CATEGORIES:
        assert {"id", "name", "parent_id", "depth", "sort_order", "is_active"} <= set(category)
        parent_id = category["parent_id"]
        if parent_id is None:
            assert category["depth"] == 0
            continue
        assert parent_id in by_id
        assert category["depth"] == by_id[parent_id]["depth"] + 1

    assert set(get_all_ids()) == set(ids)
    assert validate_tree() == []


def test_category_tree_flattening_preserves_all_rows():
    flat = flatten_tree(get_category_tree())
    assert len(flat) == len(CATEGORIES)
    assert {category["id"] for category in flat} == {category["id"] for category in CATEGORIES}


def test_keyword_seed_rows_have_well_formed_identity_and_synonyms():
    seen: set[tuple[str, object]] = set()
    for keyword in KEYWORDS:
        assert isinstance(keyword.get("word"), str)
        assert keyword["word"].strip()
        assert isinstance(keyword.get("synonyms"), list)
        assert isinstance(keyword.get("is_active"), bool)
        assert keyword.get("search_count", 0) >= 0

        identity = (keyword["word"], keyword.get("category_id"))
        assert identity not in seen
        seen.add(identity)

        for synonym in keyword["synonyms"]:
            assert isinstance(synonym, str)
            assert synonym.strip()
