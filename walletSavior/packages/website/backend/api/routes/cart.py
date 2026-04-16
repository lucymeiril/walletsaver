"""장바구니 API — CRUD + 병합 (localStorage→DB 전환)

엔드포인트:
    GET    /api/cart           — 장바구니 목록
    POST   /api/cart           — 아이템 추가
    PUT    /api/cart/{item_id} — 수량 변경
    DELETE /api/cart/{item_id} — 아이템 삭제
    DELETE /api/cart           — 전체 비우기
    POST   /api/cart/merge     — localStorage 장바구니 병합
"""

import logging
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func

from api.schemas.common import ApiResponse
from api.middleware.auth import require_auth
from services.db import managed_session
from storage.models import CartItem, Product

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cart", tags=["장바구니"])

MAX_CART_ITEMS = 100


# ── Pydantic 스키마 ──

class CartItemCreate(BaseModel):
    product_id: Optional[int] = None
    item_name: Optional[str] = None
    item_price: Optional[float] = None
    item_image_url: Optional[str] = None
    store_name: Optional[str] = None
    source_url: Optional[str] = None
    original_price: Optional[float] = None
    discount_rate: Optional[float] = None
    category: Optional[str] = None
    quantity: int = 1
    expires_at: Optional[str] = None


class CartItemUpdate(BaseModel):
    quantity: int


class CartMergeItem(BaseModel):
    product_id: Optional[int] = None
    item_name: Optional[str] = None
    item_price: Optional[float] = None
    item_image_url: Optional[str] = None
    store_name: Optional[str] = None
    source_url: Optional[str] = None
    original_price: Optional[float] = None
    discount_rate: Optional[float] = None
    category: Optional[str] = None
    quantity: int = 1


class CartMergeRequest(BaseModel):
    items: List[CartMergeItem]


def _cart_item_to_dict(item: CartItem) -> dict:
    return {
        "id": item.id,
        "product_id": item.product_id,
        "item_name": item.item_name,
        "item_price": item.item_price,
        "item_image_url": item.item_image_url,
        "store_name": item.store_name,
        "source_url": item.source_url,
        "original_price": item.original_price,
        "discount_rate": item.discount_rate,
        "category": item.category,
        "quantity": item.quantity,
        "added_at": item.added_at.isoformat() if item.added_at else None,
        "expires_at": item.expires_at.isoformat() if item.expires_at else None,
    }


def _auto_fill_from_product(session, data: dict, product_id: int) -> dict:
    """product_id가 있으면 상품 정보로 자동 채움"""
    product = session.get(Product, product_id)
    if product:
        if not data.get("item_name"):
            data["item_name"] = product.name
        if not data.get("item_image_url"):
            data["item_image_url"] = product.image_url
        if not data.get("category"):
            data["category"] = product.category_id
        # 최신 가격 조회
        if not data.get("item_price") and product.baseline_prices:
            latest = max(product.baseline_prices, key=lambda bp: bp.recorded_at)
            data["item_price"] = latest.price
    return data


# ── 엔드포인트 ──

@router.get("")
async def list_cart(user: dict = Depends(require_auth)):
    """장바구니 목록 조회"""
    with managed_session() as session:
        items = session.execute(
            select(CartItem)
            .where(CartItem.user_id == user["id"])
            .order_by(CartItem.added_at.desc())
        ).scalars().all()
        return ApiResponse(data=[_cart_item_to_dict(i) for i in items])


@router.post("")
async def add_to_cart(body: CartItemCreate, user: dict = Depends(require_auth)):
    """장바구니에 아이템 추가 — 중복 시 수량 증가"""
    with managed_session() as session:
        # 아이템 수 제한
        count = session.execute(
            select(func.count(CartItem.id)).where(CartItem.user_id == user["id"])
        ).scalar() or 0
        if count >= MAX_CART_ITEMS:
            raise HTTPException(status_code=400, detail=f"장바구니는 최대 {MAX_CART_ITEMS}개까지 가능합니다")

        data = body.model_dump()

        # product_id가 있으면 상품 정보 자동 채움
        if body.product_id:
            data = _auto_fill_from_product(session, data, body.product_id)

        if not data.get("item_name"):
            raise HTTPException(status_code=400, detail="item_name은 필수입니다")
        if not data.get("item_price") or data["item_price"] <= 0:
            raise HTTPException(status_code=400, detail="item_price는 0보다 커야 합니다")

        # 중복 검사 (product_id + store_name)
        if body.product_id:
            existing = session.execute(
                select(CartItem).where(
                    CartItem.user_id == user["id"],
                    CartItem.product_id == body.product_id,
                    CartItem.store_name == (body.store_name or None),
                )
            ).scalar_one_or_none()
            if existing:
                existing.quantity += body.quantity
                existing.item_price = data["item_price"]
                return ApiResponse(data=_cart_item_to_dict(existing))

        expires_at = None
        if body.expires_at:
            try:
                expires_at = datetime.fromisoformat(body.expires_at)
            except ValueError:
                pass

        item = CartItem(
            user_id=user["id"],
            product_id=body.product_id,
            item_name=data["item_name"],
            item_price=data["item_price"],
            item_image_url=data.get("item_image_url"),
            store_name=data.get("store_name"),
            source_url=data.get("source_url"),
            original_price=data.get("original_price"),
            discount_rate=data.get("discount_rate"),
            category=data.get("category"),
            quantity=body.quantity,
            expires_at=expires_at,
        )
        session.add(item)
        session.flush()
        return ApiResponse(data=_cart_item_to_dict(item))


@router.put("/{item_id}")
async def update_cart_item(item_id: int, body: CartItemUpdate, user: dict = Depends(require_auth)):
    """수량 변경"""
    if body.quantity < 1:
        raise HTTPException(status_code=400, detail="수량은 1 이상이어야 합니다")
    with managed_session() as session:
        item = session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user["id"])
        ).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="장바구니 아이템을 찾을 수 없습니다")
        item.quantity = body.quantity
        return ApiResponse(data=_cart_item_to_dict(item))


@router.delete("/{item_id}")
async def remove_cart_item(item_id: int, user: dict = Depends(require_auth)):
    """아이템 삭제"""
    with managed_session() as session:
        item = session.execute(
            select(CartItem).where(CartItem.id == item_id, CartItem.user_id == user["id"])
        ).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="장바구니 아이템을 찾을 수 없습니다")
        session.delete(item)
        return ApiResponse(data={"message": "삭제되었습니다"})


@router.delete("")
async def clear_cart(user: dict = Depends(require_auth)):
    """장바구니 전체 비우기"""
    with managed_session() as session:
        items = session.execute(
            select(CartItem).where(CartItem.user_id == user["id"])
        ).scalars().all()
        for item in items:
            session.delete(item)
        return ApiResponse(data={"message": "장바구니가 비워졌습니다", "deleted_count": len(items)})


@router.post("/merge")
async def merge_cart(body: CartMergeRequest, user: dict = Depends(require_auth)):
    """localStorage 장바구니를 DB와 병합 — 로그인 전환 시 호출"""
    with managed_session() as session:
        current_count = session.execute(
            select(func.count(CartItem.id)).where(CartItem.user_id == user["id"])
        ).scalar() or 0

        merged = 0
        skipped = 0
        for merge_item in body.items:
            if current_count + merged >= MAX_CART_ITEMS:
                skipped += len(body.items) - merged - skipped
                break

            data = merge_item.model_dump()
            if merge_item.product_id:
                data = _auto_fill_from_product(session, data, merge_item.product_id)

            if not data.get("item_name") or not data.get("item_price"):
                skipped += 1
                continue

            # 중복 검사
            if merge_item.product_id:
                existing = session.execute(
                    select(CartItem).where(
                        CartItem.user_id == user["id"],
                        CartItem.product_id == merge_item.product_id,
                        CartItem.store_name == (merge_item.store_name or None),
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.quantity += merge_item.quantity
                    merged += 1
                    continue

            item = CartItem(
                user_id=user["id"],
                product_id=merge_item.product_id,
                item_name=data["item_name"],
                item_price=data["item_price"],
                item_image_url=data.get("item_image_url"),
                store_name=data.get("store_name"),
                source_url=data.get("source_url"),
                original_price=data.get("original_price"),
                discount_rate=data.get("discount_rate"),
                category=data.get("category"),
                quantity=merge_item.quantity,
            )
            session.add(item)
            merged += 1

        return ApiResponse(data={"merged": merged, "skipped": skipped})
