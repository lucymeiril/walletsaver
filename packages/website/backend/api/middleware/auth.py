"""인증 미들웨어 — JWT 토큰 검증 및 사용자 추출 (Bearer header + httpOnly cookie)"""
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.auth_service import decode_token
from sqlalchemy import select
from services.db import managed_session
from storage.models import User

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """현재 인증된 사용자 정보 추출 (선택적 인증) — Bearer header 우선, cookie fallback"""
    token = None
    if credentials:
        token = credentials.credentials
    elif request.cookies.get("access_token"):
        token = request.cookies["access_token"]

    if not token:
        return None

    payload = decode_token(token)
    if not payload:
        return None

    if payload.get("type") != "access":
        return None

    return {
        "id": int(payload["sub"]),
        "email": payload["email"],
        "role": payload["role"],
    }


async def require_auth(
    user: Optional[dict] = Depends(get_current_user),
) -> dict:
    """인증 필수 — 미인증 시 401, 삭제된 계정 시 403"""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    with managed_session() as session:
        db_user = session.execute(
            select(User).where(User.id == user["id"])
        ).scalar_one_or_none()
        if db_user and db_user.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="계정이 삭제되었습니다",
            )
    return user


async def require_admin(
    user: dict = Depends(require_auth),
) -> dict:
    """관리자 권한 필수 — 비관리자 시 403"""
    if user["role"] not in ("admin", "moderator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user
