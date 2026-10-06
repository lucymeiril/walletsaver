"""Explicit reviewed catalog groups, preserving source and selection IDs.

Text similarity is deliberately not a group identity rule. Membership requires
the same reciprocal review on every named product and an existing leaf.
"""
from __future__ import annotations

import json
from functools import lru_cache
from collections.abc import Callable, Mapping
from pathlib import Path

GROUP_VERSION = "reviewed_catalog_groups_v1"


def attributes_of(product: Mapping) -> dict:
    value = product.get("attributes")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, Mapping) else {}


def validated_group_members(product: Mapping, lookup: Callable[[str], Mapping | None]) -> tuple[str, ...]:
    own = str(product.get("public_product_id") or "")
    fallback = (own,) if own else ()
    review = attributes_of(product).get("catalog_group")
    if not isinstance(review, Mapping) or review.get("review_version") != GROUP_VERSION:
        return fallback
    registered = next((row for row in reviewed_registry()["groups"] if row["key"] == review.get("key")), None)
    if not registered or any(review.get(key) != registered.get(key) for key in (
            "canonical_product_id", "member_product_ids", "canonical_name", "brand", "review_version")):
        return fallback
    members = review.get("member_product_ids")
    if (not isinstance(members, list) or not 2 <= len(members) <= 64
            or any(not isinstance(member, str) or not member for member in members)
            or len(set(members)) != len(members) or own not in members
            or review.get("canonical_product_id") not in members
            or not isinstance(review.get("key"), str) or not review["key"].strip()
            or not isinstance(review.get("canonical_name"), str) or not review["canonical_name"].strip()):
        return fallback
    category = product.get("unified_category_id")
    if not isinstance(category, str) or not category or category != registered.get("leaf"):
        return fallback
    for member in members:
        row = lookup(member)
        if (not isinstance(row, Mapping) or row.get("public_product_id") != member
                or row.get("unified_category_id") != category
                or attributes_of(row).get("catalog_group") != review):
            return fallback
    return tuple(members)


def reviewed_registry() -> dict:
    path = Path(__file__).with_name("reviewed_catalog_groups.json")
    return _read_registry(path.stat().st_mtime_ns)


@lru_cache(maxsize=1)
def _read_registry(_modified_ns: int) -> dict:
    return json.loads(Path(__file__).with_name("reviewed_catalog_groups.json").read_text(encoding="utf-8"))


def keyword_ids_for_category(category_id: str, categories: list[Mapping], keywords: list[Mapping]) -> list[int]:
    """Active keyword concepts inherit only down their assigned category tree."""
    parents = {row["id"]: row.get("parent_id") for row in categories}
    ancestry = set()
    current = category_id
    while current in parents and current not in ancestry:
        ancestry.add(current)
        current = parents[current]
    return sorted({row["id"] for row in keywords
                   if row.get("is_active") and type(row.get("id")) is int
                   and row.get("unified_category_id") in ancestry})


def keyword_words_for_category(category_id: str, categories: list[Mapping], keywords: list[Mapping]) -> list[str]:
    parents = {row["id"]: row.get("parent_id") for row in categories}
    ancestry = set()
    current = category_id
    while current in parents and current not in ancestry:
        ancestry.add(current)
        current = parents[current]
    return sorted({row["word"] for row in keywords
                   if row.get("is_active", True) and isinstance(row.get("word"), str)
                   and row.get("unified_category_id") in ancestry})


def reviewed_product_fields(product: Mapping, listings: list[Mapping]) -> dict:
    """Apply only registered exact source contexts; never infer a new member.

    The FK identity stays source-scoped. The separate reciprocal group mapping
    is the public browsing identity; old URLs and saved tuples keep their IDs.
    """
    result = dict(product)
    attrs = attributes_of(product)
    own = product.get("public_product_id")
    registry = reviewed_registry()
    for review in registry.get("leaf_reviews", []):
        if own != review["product_id"]:
            continue
        if (result.get("unified_category_id") in {review["old_leaf"], review["new_leaf"]}
                and listings and all(
                    row.get("source_name") == review["source_name"]
                    and row.get("source_record_key") == review["source_record_key"]
                    and row.get("source_title") in review["source_titles"]
                    and row.get("source_url") in review["source_urls"] for row in listings)):
            result["unified_category_id"] = review["new_leaf"]
            attrs["catalog_leaf_review"] = dict(review)
    for group in registry["groups"]:
        bindings = group["bindings"].get(own)
        if not bindings:
            continue
        expected = {(row["source_name"], row["source_record_key"]): row for row in bindings}
        if not listings or any(
                (row.get("source_name"), row.get("source_record_key")) not in expected
                or row.get("source_title") not in expected[(row["source_name"], row["source_record_key"])]["source_titles"]
                or row.get("source_url") not in expected[(row["source_name"], row["source_record_key"])]["source_urls"]
                for row in listings):
            attrs.pop("catalog_group", None)
            if own in group.get("derived_alias_member_ids", []):
                result["aliases"] = [alias for alias in (result.get("aliases") or [])
                                     if alias != group["canonical_name"]]
            break
        if result.get("unified_category_id") != group["leaf"]:
            attrs.pop("catalog_group", None)
            if own in group.get("derived_alias_member_ids", []):
                result["aliases"] = [alias for alias in (result.get("aliases") or [])
                                     if alias != group["canonical_name"]]
            break
        attrs["catalog_group"] = {key: group[key] for key in (
            "key", "canonical_product_id", "member_product_ids", "canonical_name", "brand", "review_version")}
        result["aliases"] = sorted(set(result.get("aliases") or []) | {group["canonical_name"]})
        break
    result["attributes"] = attrs
    return result


def with_category_keywords(product: Mapping, categories: list[Mapping], keywords: list[Mapping]) -> dict:
    result = dict(product)
    attrs = attributes_of(product)
    old_derived = attrs.get('catalog_keyword_words', [])
    old_derived = old_derived if isinstance(old_derived, list) else []
    derived = keyword_words_for_category(product.get('unified_category_id'), categories, keywords)
    original = set(product.get('keywords') or []) - set(old_derived)
    result['keywords'] = sorted(original | set(derived))
    if derived or old_derived:
        attrs['catalog_keyword_words'] = derived
    result['attributes'] = attrs
    return result


def reviewed_leaf_compatible(old_leaf: str, new_leaf: str, title: str, source_urls: list[str]) -> bool:
    """Retain a registered old quantity proof while correcting its display leaf."""
    return any(review["old_leaf"] == old_leaf and review["new_leaf"] == new_leaf
               and title in review["source_titles"] and source_urls
               and set(source_urls) <= set(review["source_urls"])
               for review in reviewed_registry().get("leaf_reviews", []))
