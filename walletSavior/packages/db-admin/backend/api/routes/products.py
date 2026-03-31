"""상품 CRUD + 가격 조회 라우트"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from services.base import get_session
from services.price_calc import (
    calculate_baseline_average,
    calculate_hotdeal_price,
    get_price_tier,
    get_price_history,
    get_price_comparison,
)
from storage.models import Product

router = APIRouter(prefix="/products", tags=["products"])


class ProductCreate(BaseModel):
    name: str
    category_id: Optional[str] = None
    unit: str = "개"
    description: Optional[str] = None
    image_url: Optional[str] = None


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/")
def list_products():
    session = get_session()
    try:
        products = session.query(Product).filter(Product.is_active == True).all()
        return [
            {"id": p.id, "name": p.name, "category_id": p.category_id, "unit": p.unit}
            for p in products
        ]
    finally:
        session.close()


@router.get("/{product_id}")
def get_product(product_id: int):
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        return {
            "id": p.id, "name": p.name, "category_id": p.category_id,
            "unit": p.unit, "description": p.description,
        }
    finally:
        session.close()


@router.post("/", status_code=201)
def create_product(body: ProductCreate):
    session = get_session()
    try:
        p = Product(
            name=body.name, category_id=body.category_id,
            unit=body.unit, description=body.description, image_url=body.image_url,
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        return {"id": p.id, "name": p.name}
    finally:
        session.close()


@router.put("/{product_id}")
def update_product(product_id: int, body: ProductUpdate):
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        for key, val in body.model_dump(exclude_unset=True).items():
            setattr(p, key, val)
        session.commit()
        return {"id": p.id, "name": p.name}
    finally:
        session.close()


@router.delete("/{product_id}")
def delete_product(product_id: int):
    """상품 삭제."""
    session = get_session()
    try:
        p = session.get(Product, product_id)
        if not p:
            raise HTTPException(404, "Product not found")
        session.delete(p)
        session.commit()
        return {"deleted": True, "id": product_id}
    finally:
        session.close()


@router.get("/{product_id}/baseline")
def product_baseline(product_id: int, days: int = 90):
    session = get_session()
    try:
        return calculate_baseline_average(session, product_id, days)
    finally:
        session.close()


@router.get("/{product_id}/hotdeal-price")
def product_hotdeal(product_id: int):
    session = get_session()
    try:
        return calculate_hotdeal_price(session, product_id)
    finally:
        session.close()


@router.get("/{product_id}/tier")
def product_tier(product_id: int, price: float):
    session = get_session()
    try:
        return get_price_tier(session, price, product_id)
    finally:
        session.close()


@router.get("/{product_id}/history")
def product_history(product_id: int, days: int = 30):
    session = get_session()
    try:
        return get_price_history(session, product_id, days)
    finally:
        session.close()


@router.get("/{product_id}/comparison")
def product_comparison(product_id: int):
    session = get_session()
    try:
        return get_price_comparison(session, product_id)
    finally:
        session.close()
