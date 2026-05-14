"""찜 목록 API — 관심 상품 관리, 가격 하락 알림

엔드포인트:
    GET    /api/wishlist           — 찜 목록 조회
    POST   /api/wishlist           — 찜 추가
    DELETE /api/wishlist/{item_id} — 찜 삭제
    PUT    /api/wishlist/{item_id} — 목표가/알림 설정 변경
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from api.schemas.common import ApiResponse
from api.middleware.auth import require_auth
from services.db import managed_session
from storage.models import WishlistItem, Product

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wishlist", tags=["찜 목록"])


# ── Pydantic 스키마 ──

class WishlistItemCreate(BaseModel):
    product_id: Optional[int] = None
    item_name: Optional[str] = None
    target_price: Optional[float] = None
    item_image_url: Optional[str] = None
    store_name: Optional[str] = None
    category: Optional[str] = None
    price_at_add: Optional[float] = None
    current_price: Optional[float] = None
    item_price: Optional[float] = None
    notify_on_drop: bool = False


class WishlistItemUpdate(BaseModel):
    target_price: Optional[float] = None
    notify_on_drop: Optional[bool] = None


def _wishlist_item_to_dict(item: WishlistItem) -> dict:
    return {
        "id": item.id,
        "product_id": item.product_id,
        "item_name": item.item_name,
        "target_price": item.target_price,
        "item_image_url": item.item_image_url,
        "store_name": item.store_name,
        "category": item.category,
        "price_at_add": item.price_at_add,
        "current_price": item.current_price,
        "added_at": item.added_at.isoformat() if item.added_at else None,
        "notify_on_drop": item.notify_on_drop,
    }


def _get_current_product_price(product: "Product") -> Optional[float]:
    """상품의 최신 가격 조회"""
    if product and product.baseline_prices:
        latest = max(product.baseline_prices, key=lambda bp: bp.recorded_at)
        return latest.price
    return None


# ── 엔드포인트 ──

@router.get("")
async def list_wishlist(user: dict = Depends(require_auth)):
    """찜 목록 조회 — 현재 가격 갱신"""
    with managed_session() as session:
        items = session.execute(
            select(WishlistItem)
            .where(WishlistItem.user_id == user["id"])
            .order_by(WishlistItem.added_at.desc())
        ).scalars().all()

        result = []
        for item in items:
            d = _wishlist_item_to_dict(item)
            # 상품 연결 시 최신 가격 갱신
            if item.product_id:
                product = session.get(Product, item.product_id)
                current = _get_current_product_price(product)
                if current is not None:
                    item.current_price = current
                    d["current_price"] = current
            result.append(d)

        return ApiResponse(data=result)


@router.post("")
async def add_to_wishlist(body: WishlistItemCreate, user: dict = Depends(require_auth)):
    """찜 추가 — product_id가 있으면 현재 가격 기록"""
    with managed_session() as session:
        item_name = body.item_name
        item_image_url = body.item_image_url
        category = body.category
        price_at_add = body.price_at_add if body.price_at_add is not None else body.item_price
        current_price = body.current_price if body.current_price is not None else price_at_add

        if body.product_id:
            # 중복 검사
            existing = session.execute(
                select(WishlistItem).where(
                    WishlistItem.user_id == user["id"],
                    WishlistItem.product_id == body.product_id,
                )
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=400, detail="이미 찜한 상품입니다")

            product = session.get(Product, body.product_id)
            if product:
                if not item_name:
                    item_name = product.name
                if not item_image_url:
                    item_image_url = product.image_url
                if not category:
                    category = product.category_id
                current = _get_current_product_price(product)
                if current is not None:
                    price_at_add = current
                    current_price = current
        else:
            existing = session.execute(
                select(WishlistItem).where(
                    WishlistItem.user_id == user["id"],
                    WishlistItem.product_id.is_(None),
                    WishlistItem.item_name == item_name,
                    WishlistItem.store_name == (body.store_name or None),
                )
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=400, detail="이미 찜한 상품입니다")

        if not item_name:
            raise HTTPException(status_code=400, detail="item_name은 필수입니다")

        item = WishlistItem(
            user_id=user["id"],
            product_id=body.product_id,
            item_name=item_name,
            target_price=body.target_price,
            item_image_url=item_image_url,
            store_name=body.store_name,
            category=category,
            price_at_add=price_at_add,
            current_price=current_price,
            notify_on_drop=body.notify_on_drop,
        )
        session.add(item)
        session.flush()
        return ApiResponse(data=_wishlist_item_to_dict(item))


@router.delete("/{item_id}")
async def remove_from_wishlist(item_id: int, user: dict = Depends(require_auth)):
    """찜 삭제"""
    with managed_session() as session:
        item = session.execute(
            select(WishlistItem).where(
                WishlistItem.id == item_id, WishlistItem.user_id == user["id"]
            )
        ).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="찜 아이템을 찾을 수 없습니다")
        session.delete(item)
        return ApiResponse(data={"message": "삭제되었습니다"})


@router.put("/{item_id}")
async def update_wishlist_item(item_id: int, body: WishlistItemUpdate, user: dict = Depends(require_auth)):
    """목표가/알림 설정 변경"""
    with managed_session() as session:
        item = session.execute(
            select(WishlistItem).where(
                WishlistItem.id == item_id, WishlistItem.user_id == user["id"]
            )
        ).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="찜 아이템을 찾을 수 없습니다")

        if body.target_price is not None:
            item.target_price = body.target_price
        if body.notify_on_drop is not None:
            item.notify_on_drop = body.notify_on_drop

        return ApiResponse(data=_wishlist_item_to_dict(item))
