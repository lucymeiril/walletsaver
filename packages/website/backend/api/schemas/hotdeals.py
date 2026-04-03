"""핫딜 관련 스키마"""
from pydantic import BaseModel
from typing import Optional


class HotdealResponse(BaseModel):
    id: int
    title: str
    source: str
    price: Optional[float] = None
    original_price: Optional[float] = None
    discount_rate: Optional[float] = None
    category: Optional[str] = None
    url: Optional[str] = None
    thumbnail: Optional[str] = None
    views: int = 0
    comments: int = 0
    posted_at: Optional[str] = None


class HotdealFilter(BaseModel):
    key: str
    label: str
