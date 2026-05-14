"""사용자 프로필 API — 프로필 조회/수정/삭제, 활동 내역

엔드포인트:
    GET    /api/profile          — 현재 사용자 프로필 조회
    PUT    /api/profile          — 프로필 수정 (닉네임, 바이오, 선호 설정)
    DELETE /api/profile          — 계정 소프트 삭제
    GET    /api/profile/activity — 활동 내역 (페이지네이션)
"""

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select, desc

from api.schemas.common import ApiResponse, PaginationMeta
from api.middleware.auth import require_auth
from services.db import managed_session
from storage.models import User, UserActivity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/profile", tags=["프로필"])

_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


# ── Pydantic 스키마 ──

class ProfileUpdate(BaseModel):
    nickname: Optional[str] = None
    bio: Optional[str] = None
    profile_image_url: Optional[str] = None
    preferences: Optional[dict] = None

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v):
        if v is not None:
            if len(v) < 2 or len(v) > 20:
                raise ValueError("닉네임은 2~20자여야 합니다")
        return v

    @field_validator("bio")
    @classmethod
    def validate_bio(cls, v):
        if v is not None and len(v) > 500:
            raise ValueError("바이오는 500자 이내여야 합니다")
        return v


# ── 엔드포인트 ──

@router.get("")
async def get_profile(user: dict = Depends(require_auth)):
    """현재 사용자 프로필 조회"""
    with managed_session() as session:
        db_user = session.execute(
            select(User).where(User.id == user["id"])
        ).scalar_one_or_none()
        if not db_user or db_user.is_deleted:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
        return ApiResponse(data={
            "id": db_user.id,
            "email": db_user.email,
            "nickname": db_user.nickname,
            "bio": getattr(db_user, "bio", None),
            "profile_image_url": db_user.profile_image,
            "preferences": getattr(db_user, "preferences", None),
            "role": db_user.role.value,
            "created_at": db_user.created_at.isoformat() if db_user.created_at else None,
            "updated_at": db_user.updated_at.isoformat() if db_user.updated_at else None,
        })


@router.put("")
async def update_profile(body: ProfileUpdate, user: dict = Depends(require_auth)):
    """프로필 수정"""
    with managed_session() as session:
        db_user = session.execute(
            select(User).where(User.id == user["id"])
        ).scalar_one_or_none()
        if not db_user or db_user.is_deleted:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

        # 닉네임 변경 시 중복 검사
        if body.nickname is not None and body.nickname != db_user.nickname:
            existing = session.execute(
                select(User).where(User.nickname == body.nickname, User.id != user["id"])
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")
            db_user.nickname = body.nickname

        if body.bio is not None:
            db_user.bio = body.bio
        if body.profile_image_url is not None:
            db_user.profile_image = body.profile_image_url
        if body.preferences is not None:
            db_user.preferences = body.preferences

        db_user.updated_at = datetime.utcnow()

        return ApiResponse(data={
            "id": db_user.id,
            "email": db_user.email,
            "nickname": db_user.nickname,
            "bio": getattr(db_user, "bio", None),
            "profile_image_url": db_user.profile_image,
            "preferences": getattr(db_user, "preferences", None),
            "role": db_user.role.value,
            "updated_at": db_user.updated_at.isoformat() if db_user.updated_at else None,
        })


@router.delete("")
async def delete_profile(user: dict = Depends(require_auth)):
    """계정 소프트 삭제 — is_deleted=True, deleted_at=now, auth cookies 정리"""
    with managed_session() as session:
        db_user = session.execute(
            select(User).where(User.id == user["id"])
        ).scalar_one_or_none()
        if not db_user or db_user.is_deleted:
            raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")

        db_user.is_deleted = True
        db_user.deleted_at = datetime.utcnow()

        data = ApiResponse(data={"message": "계정이 삭제되었습니다", "deleted_at": db_user.deleted_at.isoformat()})

    response = JSONResponse(content=data.model_dump())
    response.delete_cookie(key="access_token", path="/")
    response.delete_cookie(key="refresh_token", path="/api/auth")
    return response


@router.get("/activity")
async def get_activity(
    user: dict = Depends(require_auth),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """사용자 활동 내역 (페이지네이션)"""
    with managed_session() as session:
        stmt = (
            select(UserActivity)
            .where(UserActivity.user_id == user["id"])
            .order_by(desc(UserActivity.created_at))
        )
        total_stmt = select(UserActivity).where(UserActivity.user_id == user["id"])
        all_activities = session.execute(total_stmt).scalars().all()
        total = len(all_activities)

        offset = (page - 1) * per_page
        activities = session.execute(stmt.offset(offset).limit(per_page)).scalars().all()

        import math
        data = [
            {
                "id": a.id,
                "activity_type": a.activity_type,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "metadata": a.metadata_,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in activities
        ]
        return ApiResponse(
            data=data,
            meta=PaginationMeta(
                page=page,
                per_page=per_page,
                total=total,
                total_pages=math.ceil(total / per_page) if total > 0 else 0,
            ),
        )
