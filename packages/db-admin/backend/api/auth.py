"""Authentication & authorization dependencies for DB Admin API.

Dual-mode auth:
  - JWT bearer tokens for human users (frontend admin panel)
  - Static API keys for service-to-service calls (crawler → db-admin)

Auth is OPTIONAL by default (REQUIRE_AUTH=false). When disabled, all
endpoints pass through without authentication. Enable for production
with REQUIRE_AUTH=true.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

from config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


_optional_bearer = HTTPBearer(auto_error=False)

_ANONYMOUS_IDENTITY = {
    "id": 0,
    "email": "anonymous",
    "role": "admin",
    "auth_type": "anonymous",
}


async def get_current_identity(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Resolve the caller from JWT, service API key, or dev anonymous mode."""
    if credentials and credentials.credentials:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "액세스 토큰이 아닙니다.")
        return {
            "id": int(payload["sub"]),
            "email": payload.get("email", ""),
            "role": payload.get("role", "user"),
            "auth_type": "jwt",
        }

    if x_api_key:
        role = settings.SERVICE_API_KEYS.get(x_api_key)
        if role:
            return {
                "id": f"service:{x_api_key[:8]}",
                "email": "service-account",
                "role": role,
                "auth_type": "api_key",
            }
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 API 키입니다.")

    if not settings.REQUIRE_AUTH:
        return _ANONYMOUS_IDENTITY

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다. Authorization 헤더 또는 X-API-Key를 제공하세요.",
        headers={"WWW-Authenticate": "Bearer"},
    )


ROLE_HIERARCHY = {
    "user": 0,
    "viewer": 0,
    "service": 1,
    "moderator": 2,
    "admin": 3,
}


def _require_min_role(min_role: str):
    """Factory returning a FastAPI dependency for the minimum role level."""
    min_level = ROLE_HIERARCHY.get(min_role, 0)

    async def _checker(identity: dict = Depends(get_current_identity)) -> dict:
        caller_level = ROLE_HIERARCHY.get(identity["role"], 0)
        if caller_level < min_level:
            logger.warning(
                "Access denied: user=%s role=%s required=%s",
                identity.get("email"),
                identity["role"],
                min_role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"'{min_role}' 이상의 권한이 필요합니다. 현재 권한: '{identity['role']}'",
            )
        return identity

    return _checker


require_viewer = _require_min_role("viewer")
require_service = _require_min_role("service")
require_moderator = _require_min_role("moderator")
require_admin = _require_min_role("admin")

# Ordinary moderator/admin operation. Kept under the existing dependency name
# so route code does not need a compatibility-only commit.
require_backup_snapshot_reader = require_moderator

# Temporary import compatibility only: ingestion_core still imports this name,
# while ingestion.py removes the retired ai-safe route before the router is used.
# No ai_publisher/one_shot_publisher role exists anymore.
require_ai_publisher = require_moderator
