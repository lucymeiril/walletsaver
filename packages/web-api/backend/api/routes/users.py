"""
사용자 API — 프로필, 즐겨찾기, 가격 알림.

저장소가 없을 때 mock 성공 응답을 만들지 않는다. 쓰기/읽기 저장소가 실제로
사용 불가능하면 503으로 명확히 실패시켜 사용자가 저장된 것으로 오해하지 않게 한다.
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from api.schemas.common import ApiResponse
from api.middleware.auth import require_auth
from services.board_storage import User, get_board_session_factory

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


@router.get("/me")
async def get_my_profile(user: dict = Depends(require_auth)):
    """내 프로필."""
    return ApiResponse(data={
        "id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "nickname": user["nickname"],
        "created_at": user["created_at"],
    })


@router.put("/me")
async def update_my_profile(body: ProfileUpdate, user: dict = Depends(require_auth)):
    """프로필 수정 — 영구 사용자 테이블에 실제 반영."""
    nickname = (body.nickname or "").strip()
    if not nickname:
        raise HTTPException(status_code=422, detail="닉네임을 입력하세요")
    if len(nickname) < 2 or len(nickname) > 20:
        raise HTTPException(status_code=422, detail="닉네임은 2-20자여야 합니다")

    factory = get_board_session_factory()
    with factory() as session:
        existing = (
            session.query(User)
            .filter(User.nickname == nickname, User.id != int(user["id"]), User.is_deleted.is_(False))
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="이미 사용 중인 닉네임입니다")

        db_user = session.get(User, int(user["id"]))
        if not db_user or db_user.is_deleted or db_user.is_active is False:
            raise HTTPException(status_code=401, detail="유효하지 않은 사용자입니다")
        db_user.nickname = nickname
        session.commit()
        session.refresh(db_user)
        return ApiResponse(data={
            "id": db_user.id,
            "email": db_user.email,
            "role": db_user.role or "user",
            "nickname": db_user.nickname,
            "created_at": db_user.created_at.isoformat() if db_user.created_at else "",
            "updated": True,
        })


@router.get("/me/favorites")
async def get_favorites(request: Request, user: dict = Depends(require_auth)):
    """즐겨찾기 목록."""
    storage = _require_storage(request)
    return ApiResponse(data=storage.get_user_favorites(user["id"]))


@router.post("/me/favorites")
async def add_favorite(request: Request, body: FavoriteRequest, user: dict = Depends(require_auth)):
    """즐겨찾기 추가."""
    storage = _require_storage(request)
    return ApiResponse(data=storage.add_user_favorite(user["id"], body.product_id))


@router.delete("/me/favorites/{favorite_id}")
async def remove_favorite(request: Request, favorite_id: int, user: dict = Depends(require_auth)):
    """즐겨찾기 삭제."""
    storage = _require_storage(request)
    return ApiResponse(data=storage.remove_user_favorite(user["id"], favorite_id))


@router.get("/me/alerts")
async def get_alerts(request: Request, user: dict = Depends(require_auth)):
    """가격 알림 목록."""
    storage = _require_storage(request)
    return ApiResponse(data=storage.get_user_alerts(user["id"]))


@router.post("/me/alerts")
async def create_alert(request: Request, body: AlertRequest, user: dict = Depends(require_auth)):
    """가격 알림 설정."""
    storage = _require_storage(request)
    return ApiResponse(data=storage.add_price_alert(user["id"], body.product_id, body.target_price))
