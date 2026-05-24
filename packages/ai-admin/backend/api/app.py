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
from runtime import configure_utf8_runtime

logger = logging.getLogger("ai-admin")


def create_app() -> FastAPI:
    configure_utf8_runtime()
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
    from api.routes.providers import router as providers_router
    from api.routes.ingest import router as ingest_router
    from api.routes.jobs import router as jobs_router
    from api.routes.prompts import router as prompts_router
    from api.routes.review import router as review_router
    from api.routes.workers import router as workers_router
    from api.routes.match_monitor import router as match_monitor_router
    # pending_db_review 자동 escalation 큐 라우트
    from api.routes.escalation import router as escalation_router

    app.include_router(capabilities_router)
    app.include_router(providers_router)
    app.include_router(ingest_router)
    app.include_router(jobs_router)
    app.include_router(prompts_router)
    app.include_router(review_router)
    app.include_router(workers_router)
    app.include_router(match_monitor_router)
    app.include_router(escalation_router)

    @app.get("/health")
    async def health():
        from api.health import run_health_check

        status_code, payload = run_health_check()
        if status_code != 200:
            return JSONResponse(status_code=status_code, content=payload)
        return payload

    return app
