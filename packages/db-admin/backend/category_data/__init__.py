"""Reviewed catalog category and keyword seed data.

Only the static category tree and autocomplete keyword dictionaries are kept
here. Runtime product classification uses persistent matching knowledge and DB
services rather than the retired in-memory rule/mapping engine.
"""

from .categories import (
    CATEGORIES,
    get_category_tree,
    flatten_tree,
    find_category,
    get_children,
    get_ancestors,
    get_all_ids,
)
from .keywords import (
    KEYWORDS,
    SYNONYMS,
    POPULAR_PATTERNS,
    get_keywords_for_category,
    resolve_synonym,
)

__all__ = [
    "CATEGORIES",
    "KEYWORDS",
    "SYNONYMS",
    "POPULAR_PATTERNS",
    "get_category_tree",
    "flatten_tree",
    "find_category",
    "get_children",
    "get_ancestors",
    "get_all_ids",
    "get_keywords_for_category",
    "resolve_synonym",
]
