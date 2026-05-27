"""프로필 API — 웹 프론트의 회원정보 조회/수정/삭제 경로."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse, PaginationMeta

router = APIRouter(prefix="/api/profile", tags=["프로필"])


class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    bio: Optional[str] = None
    profile_image_url: Optional[str] = None
    preferences: Optional[dict] = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value):
        if value is not None and not (2 <= len(value) <= 20):
            raise ValueError("닉네임은 2~20자여야 합니다")
        return value

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, value):
        if value is not None and len(value) > 500:
            raise ValueError("바이오는 500자 이내여야 합니다")
        return value


def _user_store():
    from api.routes import auth as auth_module
    return auth_module._users_db


def _find_user_by_id(user_id: int) -> dict | None:
    for user in _user_store().values():
        if int(user.get("id", -1)) == int(user_id):
            return user
    return None


def _profile_payload(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "nickname": user.get("nickname") or user["email"].split("@")[0],
        "bio": user.get("bio"),
        "profile_image_url": user.get("profile_image_url") or user.get("profile_image"),
        "preferences": user.get("preferences"),
        "role": user.get("role", "user"),
        "created_at": user.get("created_at") or "",
        "updated_at": user.get("updated_at"),
    }


def _current_profile_user(identity: dict) -> dict:
    user = _find_user_by_id(identity["id"])
    if not user or user.get("is_deleted"):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if user.get("is_active") is False:
        raise HTTPException(status_code=403, detail="정지된 계정입니다")
    return user


@router.get("")
async def get_profile(identity: dict = Depends(require_auth)):
    return ApiResponse(data=_profile_payload(_current_profile_user(identity)))


@router.put("")
async def update_profile(body: ProfileUpdate, identity: dict = Depends(require_auth)):
    user = _current_profile_user(identity)
    users = _user_store()
    if body.nickname is not None and body.nickname != user.get("nickname"):
        if any(other.get("nickname") == body.nickname and other.get("id") != user.get("id") for other in users.values()):
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")
        user["nickname"] = body.nickname
    if body.bio is not None:
        user["bio"] = body.bio
    if body.profile_image_url is not None:
        user["profile_image_url"] = body.profile_image_url
    if body.preferences is not None:
        user["preferences"] = body.preferences
    user["updated_at"] = datetime.utcnow().isoformat()
    return ApiResponse(data=_profile_payload(user))


@router.delete("")
async def delete_profile(identity: dict = Depends(require_auth)):
    user = _current_profile_user(identity)
    user["is_deleted"] = True
    user["deleted_at"] = datetime.utcnow().isoformat()
    response = JSONResponse(content=ApiResponse(data={"message": "계정이 삭제되었습니다", "deleted_at": user["deleted_at"]}).model_dump())
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return response


@router.get("/activity")
async def get_activity(
    identity: dict = Depends(require_auth),
    page: int = 1,
    per_page: int = 20,
):
    _current_profile_user(identity)
    return ApiResponse(
        data=[],
        meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0),
    )
