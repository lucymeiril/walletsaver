"""상품 관련 스키마"""
from pydantic import BaseModel
from typing import Optional


class ProductResponse(BaseModel):
    id: int
    name: str
    category: Optional[str] = None
    unit: str = "개"
    baseline_price: Optional[float] = None
    current_avg: Optional[float] = None
    price_tier: Optional[str] = None
    image_url: Optional[str] = None
    updated_at: Optional[str] = None


class PriceHistoryPoint(BaseModel):
    date: str
    price: float
    source: str


class PriceCompareItem(BaseModel):
    source: str
    price: float
    original_price: Optional[float] = None
    discount_rate: Optional[float] = None
    url: Optional[str] = None
