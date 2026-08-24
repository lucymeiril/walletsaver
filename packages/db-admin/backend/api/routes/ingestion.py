"""PendingIngestion API facade with canonical Product-ID reuse.

The route implementation lives in :mod:`api.routes.ingestion_core`.  Keeping the
large route body unchanged here makes the product-resolution boundary explicit:
rows already resolved by the crawler MatchingEntry knowledge base carry an
immutable ``canonical_product_id`` and must bind price observations to that
Product before the older name-based fallback is considered.

At the end of import this module aliases itself to ``ingestion_core`` so existing
imports and monkeypatches keep targeting the same module globals as before.
"""
from __future__ import annotations

import sys
from contextvars import ContextVar

from . import ingestion_core as _core
from storage.models import Product

_CANONICAL_PRODUCT_ID: ContextVar[int | str | None] = ContextVar(
    "ingestion_canonical_product_id",
    default=None,
)

if not getattr(_core, "_canonical_product_resolution_installed", False):
    _original_ensure_product = _core._ensure_product
    _original_insert_items = _core._insert_items

    def _ensure_product(
        session,
        name: str,
        crawler_source: str | None = None,
        *,
        category_id: str | None = None,
        image_url: str | None = None,
        unit: str | None = None,
        attributes: dict | None = None,
        promo_label: str | None = None,
        promo_type: str | None = None,
    ) -> int:
        """Reuse a trusted canonical Product ID before legacy name lookup."""
        canonical_id = _CANONICAL_PRODUCT_ID.get()
        product = None
        if canonical_id not in (None, ""):
            try:
                canonical_id_int = int(canonical_id)
            except (TypeError, ValueError):
                _core.logger.warning(
                    "_ensure_product: invalid canonical_product_id=%r; falling back to name",
                    canonical_id,
                )
            else:
                with session.no_autoflush:
                    candidate = session.get(Product, canonical_id_int)
                if candidate is not None and candidate.is_active:
                    product = candidate
                elif candidate is not None:
                    _core.logger.warning(
                        "_ensure_product: canonical Product id=%s is inactive; falling back to name",
                        canonical_id_int,
                    )
                else:
                    _core.logger.warning(
                        "_ensure_product: canonical Product id=%s not found; falling back to name",
                        canonical_id_int,
                    )

        if product is None:
            return _original_ensure_product(
                session,
                name,
                crawler_source,
                category_id=category_id,
                image_url=image_url,
                unit=unit,
                attributes=attributes,
                promo_label=promo_label,
                promo_type=promo_type,
            )

        source_type = (
            _core._SOURCE_TYPE_MAP.get(crawler_source, "unknown")
            if crawler_source
            else "unknown"
        )
        if source_type != "unknown" and product.source_type in (None, "", "unknown"):
            product.source_type = source_type
        _core._apply_approved_product_metadata(
            session,
            product,
            category_id=category_id,
            image_url=image_url,
            unit=unit,
            attributes=attributes,
        )
        if promo_label:
            product.promo_label = str(promo_label)
        if promo_type:
            product.promo_type = str(promo_type)
        return product.id

    def _insert_items(session, items: list[dict], schema_type: str) -> int:
        """Set canonical Product context per row, preserving legacy insert semantics."""
        saved = 0
        for item in items:
            canonical_id = (
                item.get("canonical_product_id")
                if schema_type != "HotdealPost"
                else None
            )
            token = _CANONICAL_PRODUCT_ID.set(canonical_id)
            try:
                saved += _original_insert_items(session, [item], schema_type)
            finally:
                _CANONICAL_PRODUCT_ID.reset(token)
        return saved

    _core._ensure_product = _ensure_product
    _core._insert_items = _insert_items
    _core._canonical_product_resolution_installed = True

# Preserve the historical module identity for callers/tests: importing
# ``api.routes.ingestion`` returns the implementation module whose globals are
# patched above, not a second facade namespace.
sys.modules[__name__] = _core
