"""API key authentication middleware for crawler-admin."""

import os
import hmac
import logging
from typing import Optional

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

PUBLIC_PATHS: set[str] = {"/health", "/docs", "/openapi.json", "/redoc"}


def _get_api_key() -> str:
    """Load API key from environment. Raise on missing."""
    key = os.getenv("CRAWLER_ADMIN_API_KEY", "")
    if not key:
        raise RuntimeError(
            "CRAWLER_ADMIN_API_KEY environment variable is required. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
        )
    return key


def _is_auth_required() -> bool:
    """Check if authentication is enabled via REQUIRE_AUTH env var.

    보안: 기본값 true — 관리 API는 인증 필수 (개발 시 REQUIRE_AUTH=false 로 비활성화)
    """
    return os.getenv("REQUIRE_AUTH", "true").lower() in ("true", "1", "yes")


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
) -> str:
    """
    Validate the X-API-Key header against the server-side secret.

    Uses hmac.compare_digest for constant-time comparison to prevent
    timing attacks. Auth is enabled by default (REQUIRE_AUTH=true).
    """
    if request.url.path in PUBLIC_PATHS:
        return "public"

    if not _is_auth_required():
        return "auth-disabled"

    if api_key is None:
        logger.warning(
            "Auth failure: missing X-API-Key header | ip=%s path=%s",
            request.client.host if request.client else "unknown",
            request.url.path,
        )
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    expected = _get_api_key()
    if not hmac.compare_digest(api_key, expected):
        logger.warning(
            "Auth failure: invalid API key | ip=%s path=%s",
            request.client.host if request.client else "unknown",
            request.url.path,
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    return api_key
