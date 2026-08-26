"""프로필 API — 메인 users 테이블의 회원정보 조회/수정/삭제."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse
from services.user_storage import PublicUserStore, PublicUserStoreError

router = APIRouter(prefix="/api/profile", tags=["프로필"])


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    bio: Optional[str] = None
    profile_image_url: Optional[str] = None
    preferences: Optional[dict] = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value):
        if value is not None and not (2 <= len(value.strip()) <= 20):
            raise ValueError("닉네임은 2~20자여야 합니다")
        return value

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, value):
        if value is not None and len(value) > 500:
            raise ValueError("바이오는 500자 이내여야 합니다")
        return value


def _store(request: Request) -> PublicUserStore:
    try:
        return PublicUserStore(request.app.state.storage)
    except PublicUserStoreError as exc:
        raise HTTPException(status_code=503, detail="회원 데이터 저장소를 사용할 수 없습니다") from exc


def _profile_payload(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "nickname": user["nickname"],
        "bio": user.get("bio"),
        "profile_image_url": user.get("profile_image_url"),
        "preferences": user.get("preferences"),
        "role": user.get("role") or "user",
        "created_at": user.get("created_at") or "",
        "updated_at": user.get("updated_at"),
    }


@router.get("")
async def get_profile(request: Request, identity: dict = Depends(require_auth)):
    user = _store(request).get_by_id(identity["id"])
    if not user or user.get("is_deleted"):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return ApiResponse(data=_profile_payload(user))


@router.put("")
async def update_profile(request: Request, body: ProfileUpdate, identity: dict = Depends(require_auth)):
    kwargs = {}
    fields = body.model_fields_set
    if "nickname" in fields:
        if body.nickname is None:
            raise HTTPException(status_code=422, detail="닉네임은 비울 수 없습니다")
        kwargs["nickname"] = body.nickname
    if "bio" in fields:
        kwargs["bio"] = body.bio
    if "profile_image_url" in fields:
        kwargs["profile_image_url"] = body.profile_image_url
    if "preferences" in fields:
        kwargs["preferences"] = body.preferences

    try:
        user = _store(request).update_profile(identity["id"], **kwargs)
    except PublicUserStoreError as exc:
        if str(exc) == "nickname_exists":
            raise HTTPException(status_code=409, detail="이미 사용 중인 닉네임입니다") from exc
        raise
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    return ApiResponse(data=_profile_payload(user))


@router.delete("")
async def delete_profile(request: Request, identity: dict = Depends(require_auth)):
    user = _store(request).soft_delete(identity["id"])
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

    response = JSONResponse(content=ApiResponse(data={
        "message": "계정이 삭제되었습니다",
        "deleted_at": user.get("deleted_at"),
    }).model_dump())
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return response


@router.get("/activity")
async def get_activity(identity: dict = Depends(require_auth)):
    """활동 이력 저장/조회 계약이 아직 연결되지 않았음을 명시한다."""
    raise HTTPException(status_code=501, detail="사용자 활동 이력 조회는 아직 구현되지 않았습니다")
