"""Retired compatibility shim for the old regex/dictionary categorizer.

Automatic rule-based product categorization is no longer authoritative. Product
identity/category reuse is handled by persistent MatchingEntry knowledge, and
unresolved rows remain available for external classification or operator review.

The import is kept temporarily because older storage/ingestion code still calls
``auto_categorize``. Returning ``None`` makes those call sites a safe no-op until
their compatibility branches are removed without rewriting the large ingestion
module wholesale.
"""
from __future__ import annotations


def auto_categorize(product_name: str, source: str | None = None):
    """Do not guess a category for unresolved products."""
    return None


__all__ = ["auto_categorize"]
