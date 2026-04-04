"""크롤러 관리 API."""

import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.gzip import GZipMiddleware

from api.error_codes import ErrorCode, safe_error_response

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


def create_app() -> FastAPI:
    is_debug = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

    app = FastAPI(
        title="WalletSavior 크롤러 관리",
        description="크롤러 관리 및 모니터링 API",
        version="0.1.0",
        docs_url="/docs" if is_debug else None,
        redoc_url="/redoc" if is_debug else None,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # GZip 압축: JSON 응답 전송 크기 50-80% 감소 (500바이트 이상만 압축)
    app.add_middleware(GZipMiddleware, minimum_size=500)
    # Security headers
    from api.security.headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — restricted origins
    ALLOWED_ORIGINS = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    # ── Global Exception Handlers ────────────────────────────

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        """Pydantic 검증 실패 — 안전한 메시지만 반환."""
        return safe_error_response(
            422,
            ErrorCode.INVALID_INPUT,
            detail="요청 데이터가 유효하지 않습니다.",
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """미처리 예외 — 스택 트레이스 노출 방지, 서버 로그에만 기록."""
        error_id = uuid.uuid4().hex[:12]
        logger.exception(
            "[%s] Unhandled exception on %s %s",
            error_id, request.method, request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "error_id": error_id,
            },
        )

    # ── Routers ──────────────────────────────────────────────

    from api.routes.crawlers import router as crawlers_router
    from api.routes.schedules import router as schedules_router
    from api.routes.logs import router as logs_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.plugins import router as plugins_router

    from fastapi import Depends
    from api.security.auth import verify_api_key

    _auth = [Depends(verify_api_key)]

    app.include_router(crawlers_router, dependencies=_auth)
    app.include_router(schedules_router, dependencies=_auth)
    app.include_router(logs_router, dependencies=_auth)
    app.include_router(ingestion_router, dependencies=_auth)
    app.include_router(dashboard_router, dependencies=_auth)
    app.include_router(plugins_router, dependencies=_auth)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "crawler-admin"}

    return app
