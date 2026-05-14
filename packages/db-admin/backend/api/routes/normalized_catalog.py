"""Normalized public catalog read routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import require_viewer
from services.base import get_session
from services.normalized_price_read import get_normalized_price_comparison

router = APIRouter(prefix="/normalized", tags=["normalized-catalog"])


@router.get("/price-comparison")
def normalized_price_comparison(
    category_id: str | None = Query(None, max_length=120),
    public_product_id: str | None = Query(None, max_length=120),
    public_variant_id: str | None = Query(None, max_length=120),
    limit: int = Query(50, ge=1, le=200),
    identity: dict = Depends(require_viewer),
):
    session = get_session()
    try:
        return get_normalized_price_comparison(
            session,
            category_id=category_id,
            public_product_id=public_product_id,
            public_variant_id=public_variant_id,
            limit=limit,
        )
    finally:
        session.close()
