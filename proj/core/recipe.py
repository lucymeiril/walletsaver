"""
레시피 비용 계산기 — "집에서 해먹으면 얼마?"

식당 가격 vs 재료비 비교로 절약 금액 산출.
"""

from __future__ import annotations
from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    """레시피 재료."""
    name: str             # "양파"
    amount: float         # 0.5
    unit: str             # "개"
    # 가격은 DB 조회로 채움
    price_per_unit: float = 0  # 단가 (원)

    @property
    def cost(self) -> float:
        return round(self.amount * self.price_per_unit, 0)


class Recipe(BaseModel):
    """레시피 정의."""
    name: str                     # "짜장면"
    servings: int = 1             # 기준 인분
    ingredients: list[Ingredient] = Field(default_factory=list)
    eating_out_price: int = 0     # 외식 평균가
    category: str = ""            # "중식", "한식" 등

    @property
    def total_cost(self) -> float:
        return sum(i.cost for i in self.ingredients)

    @property
    def savings(self) -> float:
        return self.eating_out_price - self.total_cost

    @property
    def savings_pct(self) -> float:
        if self.eating_out_price == 0:
            return 0
        return round((self.savings / self.eating_out_price) * 100, 1)

    def summary(self) -> dict:
        return {
            "recipe": self.name,
            "servings": self.servings,
            "eating_out": self.eating_out_price,
            "cook_at_home": int(self.total_cost),
            "savings": int(self.savings),
            "savings_pct": self.savings_pct,
            "ingredients": [
                {"name": i.name, "amount": f"{i.amount}{i.unit}", "cost": int(i.cost)}
                for i in self.ingredients
            ],
        }


def build_default_recipes() -> list[Recipe]:
    """기본 레시피 목록 (더미 데이터 + DB 연결 시 가격 자동 조회)."""
    return [
        Recipe(
            name="짜장면", servings=2, eating_out_price=6500, category="중식",
            ingredients=[
                Ingredient(name="중화면", amount=2, unit="인분", price_per_unit=600),
                Ingredient(name="춘장", amount=60, unit="g", price_per_unit=8),
                Ingredient(name="양파", amount=1, unit="개", price_per_unit=500),
                Ingredient(name="돼지고기 앞다리", amount=100, unit="g", price_per_unit=12),
                Ingredient(name="호박", amount=0.3, unit="개", price_per_unit=800),
                Ingredient(name="식용유", amount=15, unit="ml", price_per_unit=3),
            ]
        ),
        Recipe(
            name="김치찌개", servings=2, eating_out_price=8000, category="한식",
            ingredients=[
                Ingredient(name="김치", amount=200, unit="g", price_per_unit=11),
                Ingredient(name="돼지고기 앞다리", amount=150, unit="g", price_per_unit=12),
                Ingredient(name="두부", amount=0.5, unit="모", price_per_unit=1800),
                Ingredient(name="대파", amount=0.3, unit="단", price_per_unit=2800),
                Ingredient(name="고추장", amount=10, unit="g", price_per_unit=7),
            ]
        ),
        Recipe(
            name="된장찌개", servings=2, eating_out_price=7500, category="한식",
            ingredients=[
                Ingredient(name="된장", amount=30, unit="g", price_per_unit=10),
                Ingredient(name="두부", amount=0.5, unit="모", price_per_unit=1800),
                Ingredient(name="감자", amount=0.5, unit="개", price_per_unit=500),
                Ingredient(name="양파", amount=0.5, unit="개", price_per_unit=500),
                Ingredient(name="호박", amount=0.3, unit="개", price_per_unit=800),
                Ingredient(name="대파", amount=0.2, unit="단", price_per_unit=2800),
            ]
        ),
        Recipe(
            name="계란볶음밥", servings=1, eating_out_price=7000, category="한식",
            ingredients=[
                Ingredient(name="밥", amount=1, unit="공기", price_per_unit=500),
                Ingredient(name="계란", amount=2, unit="개", price_per_unit=200),
                Ingredient(name="대파", amount=0.1, unit="단", price_per_unit=2800),
                Ingredient(name="식용유", amount=10, unit="ml", price_per_unit=3),
                Ingredient(name="소금", amount=2, unit="g", price_per_unit=1),
            ]
        ),
        Recipe(
            name="삼겹살 구이", servings=1, eating_out_price=15000, category="한식",
            ingredients=[
                Ingredient(name="삼겹살", amount=200, unit="g", price_per_unit=19),
                Ingredient(name="쌈채소", amount=100, unit="g", price_per_unit=12),
                Ingredient(name="마늘", amount=20, unit="g", price_per_unit=15),
                Ingredient(name="쌈장", amount=20, unit="g", price_per_unit=8),
            ]
        ),
    ]
