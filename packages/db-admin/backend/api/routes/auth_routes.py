"""Authentication endpoints: login, token refresh, current user info."""

import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, status

from api.auth import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_identity,
)
from services.base import get_session
from storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    """Authenticate with email + password, return JWT tokens."""
    session = get_session()
    try:
        user = session.query(User).filter(User.email == body.email).first()
        if not user or not user.hashed_password:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "비활성화된 계정입니다.")

        access = create_access_token(user.id, user.email, user.role.value)
        refresh = create_refresh_token(user.id)

        logger.info("[AUTH] login success: user=%s role=%s", user.email, user.role.value)
        return TokenResponse(access_token=access, refresh_token=refresh)
    finally:
        session.close()


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "리프레시 토큰이 아닙니다.")

    user_id = int(payload["sub"])
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 사용자입니다.")

        access = create_access_token(user.id, user.email, user.role.value)
        refresh = create_refresh_token(user.id)
        return TokenResponse(access_token=access, refresh_token=refresh)
    finally:
        session.close()


@router.get("/me")
def get_me(identity: dict = Depends(get_current_identity)):
    """Return the currently authenticated user's profile."""
    if identity["auth_type"] in ("api_key", "anonymous"):
        return {"id": identity["id"], "role": identity["role"], "auth_type": identity["auth_type"]}

    session = get_session()
    try:
        user = session.query(User).filter(User.id == identity["id"]).first()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
        return {
            "id": user.id,
            "email": user.email,
            "nickname": user.nickname,
            "role": user.role.value,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
    finally:
        session.close()
