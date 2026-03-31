"""가격 대량 저장 + 통계 라우트"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from services.base import get_session
from services.price_calc import calculate_baseline_average
from services.export import get_statistics_summary
from storage.models import BaselinePrice, DiscountHistory

router = APIRouter(prefix="/prices", tags=["prices"])


class PriceItem(BaseModel):
    product_id: int
    price: float
    source: str
    unit: str = "개"
    region: Optional[str] = None


class BulkPriceRequest(BaseModel):
    items: list[PriceItem]
    data_type: str = "baseline"  # "baseline" or "discount"


@router.post("/bulk", status_code=201)
def bulk_save_prices(body: BulkPriceRequest):
    session = get_session()
    try:
        saved = 0
        for item in body.items:
            if body.data_type == "baseline":
                row = BaselinePrice(
                    product_id=item.product_id,
                    price=item.price,
                    source=item.source,
                    unit=item.unit,
                    recorded_at=datetime.utcnow(),
                    region=item.region,
                )
            else:
                row = DiscountHistory(
                    product_id=item.product_id,
                    price=item.price,
                    source=item.source,
                    crawled_at=datetime.utcnow(),
                )
            session.add(row)
            saved += 1
        session.commit()
        return {"saved": saved}
    finally:
        session.close()


@router.get("/stats")
def price_statistics():
    session = get_session()
    try:
        return get_statistics_summary(session)
    finally:
        session.close()


@router.get("/product/{product_id}")
def product_prices(product_id: int, days: int = 90):
    session = get_session()
    try:
        return calculate_baseline_average(session, product_id, days)
    finally:
        session.close()
