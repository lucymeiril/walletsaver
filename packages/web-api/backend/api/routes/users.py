"""사용자 API — 메인 사용자 원장 기반 프로필, 즐겨찾기, 가격 알림."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse
from services.user_storage import PublicUserStore, PublicUserStoreError

router = APIRouter()


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None


class FavoriteRequest(BaseModel):
    product_id: int


class AlertRequest(BaseModel):
    product_id: int
    target_price: int


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
    return ApiResponse(data=_require_storage(request).add_price_alert(
        user["id"], body.product_id, body.target_price
    ))
