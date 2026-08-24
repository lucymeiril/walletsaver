"""External-classification bundle service facade.

The implementation remains in :mod:`services.bundle_import_core`. This boundary
normalizes legacy no-brand aliases before *every* product application, including
one-off tools and direct service callers, so product identity cannot fall back
to a mart name and split the same brandless product across marts.
"""
from __future__ import annotations

import sys

from core.match_key import NO_BRAND_SENTINEL
from . import bundle_import_core as _core

_NO_BRAND_ALIASES = {
    "",
    "no_brand",
    "no-brand",
    "none",
    "null",
    "브랜드없음",
    "브랜드 없음",
    NO_BRAND_SENTINEL,
}

if not getattr(_core, "_brandless_product_policy_installed", False):
    _original_apply_products = _core.apply_products

    def apply_products(session, rows: list[dict], mode: str) -> dict:
        """Apply products after promoting all no-brand aliases to one sentinel."""
        match_keys = {
            str(row.get("match_key") or "").strip()
            for row in rows
            if str(row.get("match_key") or "").strip()
        }
        if match_keys:
            entries = (
                session.query(_core.MatchingEntry)
                .filter(_core.MatchingEntry.match_key.in_(match_keys))
                .all()
            )
            for entry in entries:
                raw_brand = (entry.brand or "").strip()
                if raw_brand.lower() in _NO_BRAND_ALIASES:
                    entry.brand = NO_BRAND_SENTINEL

        return _original_apply_products(session, rows, mode)

    _core.apply_products = apply_products
    _core._brandless_product_policy_installed = True

# Return one shared module object so apply_bundle() and callers/tests see the
# patched apply_products global rather than separate facade state.
sys.modules[__name__] = _core
