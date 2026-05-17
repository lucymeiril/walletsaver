"""Search service: loads snapshot, builds autocomplete index, filters/sorts products."""
import sys
from pathlib import Path
from typing import Optional

# Add packages/ to path so we can import shared.core.X
_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_PACKAGES = _REPO_ROOT / "packages"
if str(_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_PACKAGES))

from shared.core.autocomplete import (  # noqa: E402
    build_from_canonical_products,
    load_synonyms,
    normalize_token,
    AutocompleteIndex,
)

from services.snapshot_repo import SnapshotRepo, CanonicalProductRow  # noqa: E402
from services.grading_view import get_grade_label  # noqa: E402


def _build_index(repo: SnapshotRepo) -> AutocompleteIndex:
    """Build in-memory autocomplete index from snapshot data."""
    products = repo.all_products()

    class _FakeCanonical:
        def __init__(self, row: CanonicalProductRow):
            self.id = row.id
            self.brand = row.brand or ""
            self.name_core = row.name_core or ""

    canonicals = [_FakeCanonical(p) for p in products]

    class _FakeCategoryTree:
        def __init__(self, nodes):
            self._nodes = {n.id: n for n in nodes}

        def all_ids(self):
            return list(self._nodes.keys())

        def get(self, node_id):
            n = self._nodes.get(node_id)
            if not n:
                return None

            class _FakeNode:
                pass

            obj = _FakeNode()
            obj.name_kr = n.name_kr
            return obj

    categories = repo.all_categories()
    tree = _FakeCategoryTree(categories)

    brand_set = set(p.brand for p in products if p.brand)
    synonyms = load_synonyms()

    return build_from_canonical_products(canonicals, tree, brand_set, synonyms)


def autocomplete_suggest(repo: SnapshotRepo, prefix: str, limit: int = 10) -> list[dict]:
    index = _build_index(repo)
    entries = index.suggest(prefix, limit=limit)
    return [
        {
            "token": e.token,
            "display": e.display,
            "source": e.source,
            "weight": e.weight,
            "canonical_id": e.canonical_id,
            "category_node_id": e.category_node_id,
        }
        for e in entries
    ]


def search_products(
    repo: SnapshotRepo,
    q: Optional[str],
    category: Optional[str],
    page: int,
    page_size: int,
    sort: str,
) -> dict:
    """Search products with optional text query and category filter."""
    products = repo.all_products()
    grades = {g.canonical_id: g for g in repo.all_grades()}
    aliases: dict[str, list] = {}
    for a in repo.all_aliases():
        aliases.setdefault(a.canonical_id, []).append(a)

    if q:
        norm_q = normalize_token(q)
        synonyms = load_synonyms()
        query_terms = {norm_q} if norm_q else set()
        for canonical_term, alts in synonyms.items():
            norm_canonical = normalize_token(canonical_term)
            norm_alts = [normalize_token(a) for a in alts]
            if norm_q in norm_alts or norm_q == norm_canonical:
                query_terms.add(norm_canonical)
                query_terms.update(norm_alts)

        def _matches(p: CanonicalProductRow) -> bool:
            name_norm = normalize_token(p.name_core or "")
            brand_norm = normalize_token(p.brand or "")
            for term in query_terms:
                if not term:
                    continue
                if term in name_norm or term in brand_norm:
                    return True
            for alias in aliases.get(p.id, []):
                alias_norm = normalize_token(alias.mart_item_name_raw or "")
                for term in query_terms:
                    if term and term in alias_norm:
                        return True
            return False

        products = [p for p in products if _matches(p)]

    if category:
        products = [p for p in products if p.category_id == category]

    def _sort_key_hot(p: CanonicalProductRow):
        g = grades.get(p.id)
        if g and g.p50 and g.p10:
            return (g.p50 - g.p10) / g.p50
        return -1.0

    def _sort_key_price(p: CanonicalProductRow):
        g = grades.get(p.id)
        if g and g.p50:
            return g.p50
        return float("inf")

    def _sort_key_recent(p: CanonicalProductRow):
        return -(hash(p.created_at or p.id) % 1000000)

    if sort == "hot_deal":
        products = sorted(products, key=_sort_key_hot, reverse=True)
    elif sort == "price_asc":
        products = sorted(products, key=_sort_key_price)
    elif sort == "price_desc":
        products = sorted(products, key=_sort_key_price, reverse=True)
    else:
        products = sorted(products, key=_sort_key_recent)

    total = len(products)
    start = (page - 1) * page_size
    page_items = products[start:start + page_size]

    items = []
    for p in page_items:
        g = grades.get(p.id)
        grade_label = get_grade_label(
            g.p50 if g else None,
            g.p10 if g else None,
            g.p25 if g else None,
            g.p75 if g else None,
            g.sufficient if g else False,
        )
        items.append({
            "canonical_id": p.id,
            "name_core": p.name_core,
            "brand": p.brand,
            "pack_quantity": p.pack_quantity,
            "pack_unit": p.pack_unit,
            "category_id": p.category_id,
            "image_url": p.representative_image_url,
            "p10": g.p10 if g else None,
            "p25": g.p25 if g else None,
            "p50": g.p50 if g else None,
            "p75": g.p75 if g else None,
            "sufficient": g.sufficient if g else False,
            "grade_label": grade_label,
            "marts": [a.mart for a in aliases.get(p.id, [])],
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        "items": items,
    }
