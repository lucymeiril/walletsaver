"""
Per-IP rate limiting using slowapi.
Provides tiered limits: global, admin, destructive, export, ingestion.
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind reverse proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


GLOBAL_LIMIT = os.getenv("RATE_LIMIT_GLOBAL", "200/minute")
ADMIN_LIMIT = os.getenv("RATE_LIMIT_ADMIN", "10/minute")
DESTRUCTIVE_LIMIT = os.getenv("RATE_LIMIT_DESTRUCTIVE", "5/minute")
EXPORT_LIMIT = os.getenv("RATE_LIMIT_EXPORT", "10/minute")
INGESTION_LIMIT = os.getenv("RATE_LIMIT_INGESTION", "30/minute")

limiter = Limiter(
    key_func=_get_client_ip,
    default_limits=[GLOBAL_LIMIT],
    storage_uri=os.getenv("RATE_LIMIT_STORAGE", "memory://"),
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return JSON 429 instead of plain text."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "요청 횟수 제한을 초과했습니다. 잠시 후 다시 시도해주세요.",
            "retry_after": exc.detail,
        },
    )
