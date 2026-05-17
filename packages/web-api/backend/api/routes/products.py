from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from services.snapshot_repo import SnapshotRepo, get_conn
from services.search import search_products
from services.grading_view import get_grade_label

router = APIRouter()


@router.get("/products/search")
def search(
    q: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort: str = Query(default="recent", pattern="^(hot_deal|price_asc|price_desc|recent)$"),
):
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return search_products(repo, q, category, page, page_size, sort)


@router.get("/products/{canonical_id}")
def get_product(canonical_id: str):
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    product = repo.product_by_id(canonical_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    grade = repo.grade_by_id(canonical_id)
    aliases = repo.aliases_by_canonical(canonical_id)

    grade_label = get_grade_label(
        grade.p50 if grade else None,
        grade.p10 if grade else None,
        grade.p25 if grade else None,
        grade.p75 if grade else None,
        grade.sufficient if grade else False,
    )

    return {
        "canonical_id": product.id,
        "name_core": product.name_core,
        "brand": product.brand,
        "pack_quantity": product.pack_quantity,
        "pack_unit": product.pack_unit,
        "category_id": product.category_id,
        "image_url": product.representative_image_url,
        "price_grade": {
            "p10": grade.p10 if grade else None,
            "p25": grade.p25 if grade else None,
            "p50": grade.p50 if grade else None,
            "p75": grade.p75 if grade else None,
            "sufficient": grade.sufficient if grade else False,
            "sample_size": grade.sample_size if grade else 0,
            "grade_label": grade_label,
        },
        "mart_aliases": [
            {
                "mart": a.mart,
                "mart_item_id": a.mart_item_id,
                "mart_item_name_raw": a.mart_item_name_raw,
                "source_url": a.source_url,
                "last_seen_at": a.last_seen_at,
            }
            for a in aliases
        ],
    }
