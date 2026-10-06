"""사용자 API — 메인 사용자 원장 기반 프로필, 즐겨찾기, 가격 알림."""
from typing import Optional
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse
from services.user_storage import PublicUserStore, PublicUserStoreError
from services.catalog_storage import CatalogUnavailable

router = APIRouter()


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None


class FavoriteRequest(BaseModel):
    product_id: int


class AlertRequest(BaseModel):
    product_id: str | int
    target_price: int = Field(gt=0, strict=True)
    variant_id: str | None = Field(default=None, min_length=1, max_length=200)
    listing_id: str | None = Field(default=None, min_length=1, max_length=200)
    offer_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("product_id", mode="before")
    @classmethod
    def valid_product_id(cls, value):
        if (isinstance(value, bool) or not isinstance(value, (str, int))
                or (isinstance(value, int) and value <= 0)
                or (isinstance(value, str) and (not value.strip() or value != value.strip()))):
            raise ValueError("invalid product id")
        return value

    @model_validator(mode="after")
    def complete_selection(self):
        selected = (self.variant_id, self.listing_id, self.offer_id)
        if any(selected) and (not all(selected) or any(value != value.strip() for value in selected)):
            raise ValueError("complete catalog selection required")
        return self


def _require_storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        raise HTTPException(status_code=503, detail="사용자 데이터 저장소를 사용할 수 없습니다")
    return storage


def _user_store(request: Request) -> PublicUserStore:
    try:
        return PublicUserStore(_require_storage(request))
    except PublicUserStoreError as exc:
        raise HTTPException(status_code=503, detail="회원 데이터 저장소를 사용할 수 없습니다") from exc


@router.get("/me")
async def get_my_profile(user: dict = Depends(require_auth)):
    """내 프로필 — 인증 미들웨어가 메인 DB에서 읽은 최신 사용자 정보."""
    return ApiResponse(data={
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "nickname": user["nickname"],
        "created_at": user["created_at"],
    })


@router.put("/me")
async def update_my_profile(request: Request, body: ProfileUpdate, user: dict = Depends(require_auth)):
    """닉네임 수정 — 메인 users 테이블에 실제 반영."""
    nickname = (body.nickname or "").strip()
    if not nickname:
        raise HTTPException(status_code=422, detail="닉네임을 입력하세요")
    if len(nickname) < 2 or len(nickname) > 20:
        raise HTTPException(status_code=422, detail="닉네임은 2-20자여야 합니다")

    try:
        updated = _user_store(request).update_profile(user["id"], nickname=nickname)
    except PublicUserStoreError as exc:
        if str(exc) == "nickname_exists":
            raise HTTPException(status_code=409, detail="이미 사용 중인 닉네임입니다") from exc
        raise
    if not updated:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return ApiResponse(data={
        "id": updated["id"],
        "email": updated["email"],
        "role": updated["role"],
        "nickname": updated["nickname"],
        "created_at": updated["created_at"],
        "updated": True,
    })


@router.get("/me/favorites")
async def get_favorites(request: Request, user: dict = Depends(require_auth)):
    """즐겨찾기 목록 — Favorite.user_id는 같은 메인 users.id를 참조한다."""
    return ApiResponse(data=_require_storage(request).get_user_favorites(user["id"]))


@router.post("/me/favorites")
async def add_favorite(request: Request, body: FavoriteRequest, user: dict = Depends(require_auth)):
    """즐겨찾기 추가."""
    return ApiResponse(data=_require_storage(request).add_user_favorite(user["id"], body.product_id))


@router.delete("/me/favorites/{product_id}")
async def remove_favorite(request: Request, product_id: int, user: dict = Depends(require_auth)):
    """즐겨찾기 삭제 — 저장소 계약은 favorite row id가 아니라 product id를 받는다."""
    return ApiResponse(data=_require_storage(request).remove_user_favorite(user["id"], product_id))


@router.get("/me/alerts")
async def get_alerts(request: Request, user: dict = Depends(require_auth)):
    """가격 알림 목록."""
    return ApiResponse(data=_require_storage(request).get_user_alerts(user["id"]))


@router.post("/me/alerts")
async def create_alert(request: Request, body: AlertRequest, user: dict = Depends(require_auth)):
    """가격 알림 설정."""
    try:
        result = _require_storage(request).add_price_alert(
            user["id"], body.product_id, body.target_price,
            variant_id=body.variant_id, listing_id=body.listing_id, offer_id=body.offer_id,
        )
    except (CatalogUnavailable, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=503, detail="카탈로그를 확인할 수 없습니다") from exc
    except ValueError as exc:
        if str(exc) == "catalog_selection_invalid":
            raise HTTPException(status_code=422, detail="상품의 규격·판매처·거래 선택을 다시 확인해주세요") from exc
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다") from exc
    return ApiResponse(data=result)


@router.delete("/me/alerts/{alert_id}")
async def delete_alert(request: Request, alert_id: int, user: dict = Depends(require_auth)):
    """가격 알림 해제."""
    return ApiResponse(data=_require_storage(request).remove_price_alert(user["id"], alert_id))
