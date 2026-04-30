"""ai-admin FastAPI 앱 팩토리 (로컬 전용 스켈레톤).

추후 단계에서 인증/rate limit/security headers/error logging을 다른 admin
패키지처럼 추가한다. 지금은 의존성을 최소로 유지한다.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings

logger = logging.getLogger("ai-admin")


def create_app() -> FastAPI:
    app = FastAPI(
        title="WalletSavior AI 관리",
        description="AI 워커 관리 (스켈레톤)",
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    from api.routes.capabilities import router as capabilities_router

    app.include_router(capabilities_router)

    @app.get("/health")
    async def health():
        from api.health import run_health_check

        status_code, payload = run_health_check()
        if status_code != 200:
            return JSONResponse(status_code=status_code, content=payload)
        return payload

    return app
