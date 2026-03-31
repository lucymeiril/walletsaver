"""위치 기반 서비스 스키마 (주유소, 식당)"""
from pydantic import BaseModel
from typing import Optional


class GasStationResponse(BaseModel):
    id: int
    name: str
    brand: str
    address: str
    lat: float
    lng: float
    gasoline: Optional[float] = None
    diesel: Optional[float] = None
    lpg: Optional[float] = None
    distance: Optional[float] = None
    updated_at: Optional[str] = None


class RestaurantResponse(BaseModel):
    id: int
    name: str
    category: str
    address: str
    lat: float
    lng: float
    avg_price: Optional[float] = None
    rating: Optional[float] = None
    review_count: int = 0
    distance: Optional[float] = None


class RecipeCompareResponse(BaseModel):
    recipe_name: str
    servings: int
    cook_cost: float
    delivery_cost: float
    dine_out_cost: float
    savings_vs_delivery: float
    savings_vs_dine_out: float
    ingredients: list
