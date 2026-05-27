"""인증 미들웨어 — JWT 토큰 검증 및 사용자 추출"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.auth_service import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """현재 인증된 사용자 정보 추출 (선택적 인증)"""
    token = credentials.credentials if credentials else request.cookies.get("access_token")
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
    """인증 필수 — 미인증 시 401"""
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
    """관리자 권한 필수 — 비관리자 시 403"""
    if user["role"] not in ("admin", "moderator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user


def is_local_auth_user_blocked(user_id: int) -> bool:
    try:
        from api.routes import auth as auth_module
        for user in auth_module._users_db.values():
            if int(user.get("id", -1)) == int(user_id):
                return bool(user.get("is_deleted") or user.get("is_active") is False)
    except Exception:
        return False
    return False
