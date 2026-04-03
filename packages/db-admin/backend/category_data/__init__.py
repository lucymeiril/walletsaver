"""
WalletSavior 카테고리 & 키워드 데이터 모듈.

한국 핫딜 비교 서비스를 위한 포괄적 카테고리 트리,
자동완성 키워드, 상품-카테고리 매핑을 제공합니다.
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
from .mappings import (
    PRODUCT_MAPPINGS,
    get_categories_for_product,
    get_products_for_category,
)
from .data_io import (
    export_categories_json,
    export_keywords_json,
    import_categories_json,
    import_keywords_json,
    merge_categories,
    generate_seed_sql,
)
from .search_enhance import (
    extract_chosung,
    chosung_search,
    fuzzy_match,
    split_compound,
    search_with_ranking,
)

__all__ = [
    "CATEGORIES",
    "KEYWORDS",
    "SYNONYMS",
    "POPULAR_PATTERNS",
    "PRODUCT_MAPPINGS",
    "get_category_tree",
    "flatten_tree",
    "find_category",
    "get_children",
    "get_ancestors",
    "get_all_ids",
    "get_keywords_for_category",
    "resolve_synonym",
    "get_categories_for_product",
    "get_products_for_category",
    "export_categories_json",
    "export_keywords_json",
    "import_categories_json",
    "import_keywords_json",
    "merge_categories",
    "generate_seed_sql",
    "extract_chosung",
    "chosung_search",
    "fuzzy_match",
    "split_compound",
    "search_with_ranking",
]
