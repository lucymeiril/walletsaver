"""프로필 API — 웹 프론트의 회원정보 조회/수정/삭제 경로."""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from api.middleware.auth import require_auth
from api.schemas.common import ApiResponse, PaginationMeta
from services.board_storage import User, get_board_session_factory

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


def _preferences(user: User):
    if not user.preferences_json:
        return None
    try:
        value = json.loads(user.preferences_json)
        return value if isinstance(value, dict) else None
    except (TypeError, json.JSONDecodeError):
        return None


def _profile_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "nickname": user.nickname or user.email.split("@")[0],
        "bio": user.bio,
        "profile_image_url": user.profile_image_url,
        "preferences": _preferences(user),
        "role": user.role or "user",
        "created_at": user.created_at.isoformat() if user.created_at else "",
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _current_profile_user(session, identity: dict) -> User:
    user = session.get(User, int(identity["id"]))
    if not user or user.is_deleted:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if user.is_active is False:
        raise HTTPException(status_code=403, detail="정지된 계정입니다")
    return user


@router.get("")
async def get_profile(identity: dict = Depends(require_auth)):
    factory = get_board_session_factory()
    with factory() as session:
        return ApiResponse(data=_profile_payload(_current_profile_user(session, identity)))


@router.put("")
async def update_profile(body: ProfileUpdate, identity: dict = Depends(require_auth)):
    factory = get_board_session_factory()
    with factory() as session:
        user = _current_profile_user(session, identity)

        if body.nickname is not None:
            nickname = body.nickname.strip()
            if nickname != user.nickname:
                duplicate = (
                    session.query(User)
                    .filter(
                        User.nickname == nickname,
                        User.id != user.id,
                        User.is_deleted.is_(False),
                    )
                    .first()
                )
                if duplicate:
                    raise HTTPException(status_code=409, detail="이미 사용 중인 닉네임입니다")
                user.nickname = nickname
        if body.bio is not None:
            user.bio = body.bio
        if body.profile_image_url is not None:
            user.profile_image_url = body.profile_image_url
        if body.preferences is not None:
            user.preferences_json = json.dumps(body.preferences, ensure_ascii=False)

        user.updated_at = datetime.utcnow()
        session.commit()
        session.refresh(user)
        return ApiResponse(data=_profile_payload(user))


@router.delete("")
async def delete_profile(identity: dict = Depends(require_auth)):
    factory = get_board_session_factory()
    with factory() as session:
        user = _current_profile_user(session, identity)
        deleted_at = datetime.utcnow()
        user.is_deleted = True
        user.is_active = False
        user.deleted_at = deleted_at
        user.updated_at = deleted_at
        session.commit()

    response = JSONResponse(
        content=ApiResponse(
            data={"message": "계정이 삭제되었습니다", "deleted_at": deleted_at.isoformat()}
        ).model_dump()
    )
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return response


@router.get("/activity")
async def get_activity(
    identity: dict = Depends(require_auth),
    page: int = 1,
    per_page: int = 20,
):
    factory = get_board_session_factory()
    with factory() as session:
        _current_profile_user(session, identity)
    return ApiResponse(
        data=[],
        meta=PaginationMeta(page=page, per_page=per_page, total=0, total_pages=0),
    )
