"""인증 미들웨어 — JWT 토큰 검증 후 영구 사용자 상태를 확인한다."""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.auth_service import decode_token
from services.board_storage import User, get_board_session_factory

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """현재 인증된 사용자 정보 추출 (선택적 인증)."""
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        return None

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None

    factory = get_board_session_factory()
    with factory() as session:
        user = session.get(User, user_id)
        if not user or user.is_deleted or user.is_active is False:
            return None
        return {
            "id": user.id,
            "email": user.email,
            "role": user.role or "user",
            "nickname": user.nickname,
            "created_at": user.created_at.isoformat() if user.created_at else "",
        }


async def require_auth(
    user: Optional[dict] = Depends(get_current_user),
) -> dict:
    """인증 필수 — 미인증 시 401."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: dict = Depends(require_auth),
) -> dict:
    """관리자 권한 필수 — 비관리자 시 403."""
    if user["role"] not in ("admin", "moderator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user


def is_local_auth_user_blocked(user_id: int) -> bool:
    """게시판/관리 기능에서 동일한 영구 사용자 상태를 확인한다."""
    try:
        factory = get_board_session_factory()
        with factory() as session:
            user = session.get(User, int(user_id))
            return bool(user and (user.is_deleted or user.is_active is False))
    except Exception:
        return False
