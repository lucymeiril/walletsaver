"""Authentication middleware backed by the authoritative main users table."""
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth_service import decode_token
from services.user_storage import PublicUserStore, PublicUserStoreError

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """Return the active persistent user for a valid access token."""
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

    try:
        user = PublicUserStore(request.app.state.storage).get_by_id(user_id)
    except PublicUserStoreError:
        return None
    if not user or user.get("is_deleted") or not user.get("is_active"):
        return None
    return user


async def require_auth(user: Optional[dict] = Depends(get_current_user)) -> dict:
    """Require an authenticated active user."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(user: dict = Depends(require_auth)) -> dict:
    """Require admin or moderator role."""
    if user.get("role") not in ("admin", "moderator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user
