"""Route public product reads to a derived SQLite snapshot.

The current web API still has low-volume private/write features (favorites,
alerts, hotdeal voting, etc.) that belong to the main application store. Product
catalog, category, mart-price and price-history reads are safe to serve from the
public snapshot instead. This proxy keeps the existing route surface intact
while enforcing that split at the storage boundary.
"""
from __future__ import annotations

from typing import Any


class SplitStorage:
    """Delegate selected public reads to ``public`` and everything else to main."""

    PUBLIC_READ_METHODS = frozenset(
        {
            "get_products",
            "get_product_detail",
            "search_products",
            "get_mart_deals",
            "get_price_history",
            "get_price_compare",
        }
    )

    def __init__(self, *, main: Any, public: Any | None) -> None:
        self.main = main
        self.public = public

    @property
    def SessionLocal(self):
        """Direct category/product ORM reads in products.py use the public DB."""
        target = self.public or self.main
        return getattr(target, "SessionLocal", None)

    @property
    def public_enabled(self) -> bool:
        return self.public is not None

    def __getattr__(self, name: str):
        if name in self.PUBLIC_READ_METHODS and self.public is not None:
            public_attr = getattr(self.public, name, None)
            if public_attr is not None:
                return public_attr
        return getattr(self.main, name)
