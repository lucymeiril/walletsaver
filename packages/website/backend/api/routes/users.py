"""
사용자 API — 프로필, 즐겨찾기, 가격 알림.

엔드포인트:
    GET    /api/users/me                  — 내 프로필
    PUT    /api/users/me                  — 프로필 수정
    GET    /api/users/me/favorites        — 내 즐겨찾기
    POST   /api/users/me/favorites        — 즐겨찾기 추가
    DELETE /api/users/me/favorites/{id}   — 즐겨찾기 삭제
    GET    /api/users/me/alerts           — 내 가격 알림
    POST   /api/users/me/alerts           — 알림 설정
"""

import logging
from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select
from api.schemas.common import ApiResponse
from api.middleware.auth import require_auth, get_current_user
from services.db import managed_session
from storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None


class FavoriteRequest(BaseModel):
    product_id: int


class AlertRequest(BaseModel):
    product_id: int
    target_price: int


@router.get("/me")
async def get_my_profile(user: dict = Depends(require_auth)):
    """내 프로필 — DB에서 실제 사용자 데이터 조회."""
    try:
        with managed_session() as session:
            db_user = session.execute(
                select(User).where(User.id == user["id"])
            ).scalar_one_or_none()
            if db_user:
                return ApiResponse(data={
                    "id": db_user.id,
                    "email": db_user.email,
                    "role": db_user.role.value if hasattr(db_user.role, "value") else db_user.role,
                    "nickname": db_user.nickname,
                    "profile_image": db_user.profile_image,
                    "created_at": db_user.created_at.isoformat() if db_user.created_at else "",
                })
    except Exception:
        logger.exception("Error fetching user profile for user_id=%s", user["id"])

    return ApiResponse(data={
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "nickname": user.get("nickname", user["email"].split("@")[0]),
        "created_at": "",
    })


@router.put("/me")
async def update_my_profile(body: ProfileUpdate, user: dict = Depends(require_auth)):
    """프로필 수정 — DB에 영속화."""
    try:
        with managed_session() as session:
            db_user = session.execute(
                select(User).where(User.id == user["id"])
            ).scalar_one_or_none()
            if db_user:
                if body.nickname is not None:
                    db_user.nickname = body.nickname
                session.flush()
                return ApiResponse(data={
                    "id": db_user.id,
                    "email": db_user.email,
                    "role": db_user.role.value if hasattr(db_user.role, "value") else db_user.role,
                    "nickname": db_user.nickname,
                    "profile_image": db_user.profile_image,
                    "created_at": db_user.created_at.isoformat() if db_user.created_at else "",
                    "updated": True,
                })
    except Exception:
        logger.exception("Error updating user profile for user_id=%s", user["id"])

    return ApiResponse(data={
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "nickname": body.nickname or user["email"].split("@")[0],
        "created_at": "",
        "updated": False,
    })


@router.get("/me/favorites")
async def get_favorites(request: Request, user: dict = Depends(require_auth)):
    """즐겨찾기 목록 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])
    return ApiResponse(data=storage.get_user_favorites(user["id"]))


@router.post("/me/favorites")
async def add_favorite(request: Request, body: FavoriteRequest, user: dict = Depends(require_auth)):
    """즐겨찾기 추가 — DB에 저장."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data={"status": "error", "message": "DB 미연결"})
    return ApiResponse(data=storage.add_user_favorite(user["id"], body.product_id))


@router.delete("/me/favorites/{favorite_id}")
async def remove_favorite(request: Request, favorite_id: int, user: dict = Depends(require_auth)):
    """즐겨찾기 삭제 — DB에서 삭제."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data={"status": "error", "message": "DB 미연결"})
    return ApiResponse(data=storage.remove_user_favorite(user["id"], favorite_id))


@router.get("/me/alerts")
async def get_alerts(request: Request, user: dict = Depends(require_auth)):
    """가격 알림 목록 — DB에서 조회."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data=[])
    return ApiResponse(data=storage.get_user_alerts(user["id"]))


@router.post("/me/alerts")
async def create_alert(request: Request, body: AlertRequest, user: dict = Depends(require_auth)):
    """가격 알림 설정 — DB에 저장."""
    storage = request.app.state.storage
    if storage is None:
        return ApiResponse(data={"status": "error", "message": "DB 미연결"})
    return ApiResponse(data=storage.add_price_alert(user["id"], body.product_id, body.target_price))
