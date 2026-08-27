"""Authenticated account features backed by the main users database."""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse, PaginationMeta
from services.account_feature_storage import AccountFeatureStore, AccountFeatureStoreError

router = APIRouter(tags=["Account features"])


class CartItemBody(BaseModel):
    product_id: int | None = Field(default=None, ge=1)
    item_name: str = Field(min_length=1, max_length=300)
    item_price: float = Field(ge=0)
    item_image_url: str | None = Field(default=None, max_length=500)
    store_name: str | None = Field(default=None, max_length=100)
    source_url: str | None = Field(default=None, max_length=500)
    original_price: float | None = Field(default=None, ge=0)
    discount_rate: float | None = None
    category: str | None = Field(default=None, max_length=100)
    quantity: int = Field(default=1, ge=1, le=999)


class CartUpdateBody(BaseModel):
    quantity: int = Field(ge=1, le=999)


class CartMergeBody(BaseModel):
    items: list[CartItemBody] = Field(default_factory=list, max_length=200)


class WishlistItemBody(BaseModel):
    product_id: int | None = Field(default=None, ge=1)
    item_name: str = Field(min_length=1, max_length=300)
    item_image_url: str | None = Field(default=None, max_length=500)
    store_name: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=100)
    price_at_add: float | None = Field(default=None, ge=0)
    current_price: float | None = Field(default=None, ge=0)
    target_price: float | None = Field(default=None, ge=0)
    notify_on_drop: bool = False


class WishlistUpdateBody(BaseModel):
    target_price: float | None = Field(default=None, ge=0)
    notify_on_drop: bool = False


class ActivityBody(BaseModel):
    activity_type: str = Field(min_length=1, max_length=30)
    target_type: str | None = Field(default=None, max_length=30)
    target_id: str | int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _store(request: Request) -> AccountFeatureStore:
    try:
        return AccountFeatureStore(request.app.state.storage)
    except AccountFeatureStoreError as exc:
        raise HTTPException(status_code=503, detail="회원 기능 저장소를 사용할 수 없습니다") from exc


def _handle_store_error(exc: AccountFeatureStoreError):
    if str(exc) == "product_not_found":
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다") from exc
    raise HTTPException(status_code=503, detail="회원 기능 저장에 실패했습니다") from exc


@router.get("/api/cart")
async def get_cart(request: Request, user: dict = Depends(require_auth)):
    return ApiResponse(data=_store(request).list_cart(int(user["id"])))


@router.post("/api/cart")
async def add_cart(request: Request, body: CartItemBody, user: dict = Depends(require_auth)):
    try:
        data = _store(request).add_cart(int(user["id"]), body.model_dump())
    except AccountFeatureStoreError as exc:
        _handle_store_error(exc)
    return ApiResponse(data=data)


@router.put("/api/cart/{cart_id}")
async def update_cart(
    request: Request,
    cart_id: int,
    body: CartUpdateBody,
    user: dict = Depends(require_auth),
):
    changed = _store(request).update_cart_quantity(int(user["id"]), cart_id, body.quantity)
    if not changed:
        raise HTTPException(status_code=404, detail="장바구니 항목을 찾을 수 없습니다")
    return ApiResponse(data={"id": cart_id, "quantity": body.quantity})


@router.delete("/api/cart/{cart_id}")
async def delete_cart_item(request: Request, cart_id: int, user: dict = Depends(require_auth)):
    changed = _store(request).delete_cart_item(int(user["id"]), cart_id)
    if not changed:
        raise HTTPException(status_code=404, detail="장바구니 항목을 찾을 수 없습니다")
    return ApiResponse(data={"id": cart_id, "deleted": True})


@router.delete("/api/cart")
async def clear_cart(request: Request, user: dict = Depends(require_auth)):
    deleted = _store(request).clear_cart(int(user["id"]))
    return ApiResponse(data={"deleted": deleted})


@router.post("/api/cart/merge")
async def merge_cart(request: Request, body: CartMergeBody, user: dict = Depends(require_auth)):
    try:
        data = _store(request).merge_cart(
            int(user["id"]),
            [item.model_dump() for item in body.items],
        )
    except AccountFeatureStoreError as exc:
        _handle_store_error(exc)
    return ApiResponse(data=data)


@router.get("/api/wishlist")
async def get_wishlist(
    request: Request,
    user: dict = Depends(require_auth),
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=1000),
):
    data = _store(request).list_wishlist(int(user["id"]))
    if per_page is None:
        return ApiResponse(data=data)

    total = len(data)
    start = (page - 1) * per_page
    page_data = data[start:start + per_page]
    total_pages = (total + per_page - 1) // per_page if total else 0
    return ApiResponse(
        data=page_data,
        meta=PaginationMeta(
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
        ),
    )


@router.post("/api/wishlist")
async def add_wishlist(request: Request, body: WishlistItemBody, user: dict = Depends(require_auth)):
    try:
        data = _store(request).add_wishlist(int(user["id"]), body.model_dump())
    except AccountFeatureStoreError as exc:
        _handle_store_error(exc)
    return ApiResponse(data=data)


@router.put("/api/wishlist/{wishlist_id}")
async def update_wishlist(
    request: Request,
    wishlist_id: int,
    body: WishlistUpdateBody,
    user: dict = Depends(require_auth),
):
    changed = _store(request).update_wishlist(
        int(user["id"]),
        wishlist_id,
        body.target_price,
        body.notify_on_drop,
    )
    if not changed:
        raise HTTPException(status_code=404, detail="찜 항목을 찾을 수 없습니다")
    return ApiResponse(data={
        "id": wishlist_id,
        "target_price": body.target_price,
        "notify_on_drop": body.notify_on_drop,
    })


@router.delete("/api/wishlist/{wishlist_id}")
async def delete_wishlist(request: Request, wishlist_id: int, user: dict = Depends(require_auth)):
    changed = _store(request).delete_wishlist(int(user["id"]), wishlist_id)
    if not changed:
        raise HTTPException(status_code=404, detail="찜 항목을 찾을 수 없습니다")
    return ApiResponse(data={"id": wishlist_id, "deleted": True})


@router.post("/api/activity/track")
async def track_activity(request: Request, body: ActivityBody, user: dict = Depends(require_auth)):
    allowed = {"view", "search", "cart_add", "wishlist_add", "vote"}
    if body.activity_type not in allowed:
        raise HTTPException(status_code=422, detail="지원하지 않는 활동 유형입니다")
    target_id = None if body.target_id is None else str(body.target_id)[:100]
    try:
        activity_id = _store(request).track_activity(
            int(user["id"]),
            body.activity_type,
            body.target_type,
            target_id,
            body.metadata,
        )
    except AccountFeatureStoreError as exc:
        _handle_store_error(exc)
    return ApiResponse(data={"id": activity_id, "saved": True})
