"""DB 관리 API 팩토리"""
import signal
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
import uuid
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from config import settings
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.middleware.rate_limit import limiter, rate_limit_exceeded_handler, GLOBAL_LIMIT

_lifecycle_logger = logging.getLogger("lifecycle")


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    sig_name = signal.Signals(signum).name
    _lifecycle_logger.info("Received %s — initiating graceful shutdown", sig_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──

    # 1. Security check
    if not settings.DEBUG:
        if "changeme" in settings.DATABASE_URL:
            raise RuntimeError(
                "SECURITY: Default database password detected. "
                "Set a strong DATABASE_URL for production."
            )

    # 2. Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass

    # 3. Verify DB connectivity (fail-fast)
    from services.base import get_engine
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _lifecycle_logger.info("Startup: database connection verified")
    except Exception as e:
        _lifecycle_logger.critical("Startup: database unreachable — %s", e)
        raise

    # 4. Seed reviewed catalog taxonomy without inserting sample product/price rows
    try:
        from services.catalog_seed import ensure_catalog_taxonomy_seeded
        result = ensure_catalog_taxonomy_seeded(engine)
        _lifecycle_logger.info(
            "Startup: catalog taxonomy seed complete — categories=%s keywords=%s",
            result.get("categories", 0),
            result.get("keywords", 0),
        )
    except Exception as e:
        _lifecycle_logger.warning("Startup: catalog taxonomy seed failed — %s", e)

    # 5. Seed default admin account if none exists
    try:
        from services.seed import seed_default_admin
        seed_default_admin()
    except Exception as e:
        _lifecycle_logger.warning("Startup: admin seed failed — %s", e)

    # 6. Log startup summary
    _lifecycle_logger.info(
        "Startup complete — host=%s port=%s debug=%s",
        settings.API_HOST, settings.API_PORT, settings.DEBUG,
    )

    yield

    # ── Shutdown ──
    _lifecycle_logger.info("Shutdown: closing database connections")

    # 6. Dispose engine via reset_engine (closes all pooled connections + clears singleton)
    try:
        from services.base import reset_engine
        reset_engine()
        _lifecycle_logger.info("Shutdown: engine disposed successfully")
    except Exception as e:
        _lifecycle_logger.error("Shutdown: engine disposal failed — %s", e)

    # 7. Flush all log handlers
    for handler in logging.root.handlers:
        try:
            handler.flush()
        except Exception:
            pass

    _lifecycle_logger.info("Shutdown: complete")


MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10MB

_api_logger = logging.getLogger("api")


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than MAX_REQUEST_BODY_BYTES."""

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"\uc694\uccad \ubcf8\ubb38\uc740 {MAX_REQUEST_BODY_BYTES // (1024*1024)}MB\ub97c \ucd08\uacfc\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.",
                        "request_id": "",
                    }
                },
            )
        return await call_next(request)


def create_app() -> FastAPI:
    app = FastAPI(
        title="WalletSavior DB 관리",
        description="데이터베이스 관리 API",
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
        lifespan=lifespan,
    )

    # ── Rate Limiting ──
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # ── Security Headers (CSP, X-Frame-Options, etc.) ──
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=not settings.DEBUG,
    )

    # ── Response Compression ──
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # ── CORS — restricted origins ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    # ── Error Logging (outermost — catches everything) ──
    from error_middleware import ErrorLoggingMiddleware
    app.add_middleware(ErrorLoggingMiddleware, server_name="db-admin")

    from api.routes.products import router as products_router
    from api.routes.prices import router as prices_router
    from api.routes.categories import router as categories_router
    from api.routes.keywords import router as keywords_router
    from api.routes.analytics import router as analytics_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.admin import router as admin_router
    from api.routes.auth_routes import router as auth_router
    from api.routes.integrity import router as integrity_router
    from api.routes.community import router as community_router

    # Payload size limit
    app.add_middleware(RequestSizeLimitMiddleware)

    # ── Error Log API ──
    from error_api import router as error_router
    app.include_router(error_router)

    # /api 접두어 — 프론트엔드 client.js가 /api/products 등으로 호출
    app.include_router(products_router, prefix="/api")
    app.include_router(prices_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(keywords_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(integrity_router, prefix="/api")
    app.include_router(community_router, prefix="/api")
    # ingestion 라우터는 이미 /api/ingestions 접두어가 있음
    app.include_router(ingestion_router)


    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = uuid.uuid4().hex[:12]
        _api_logger.warning(
            "Validation error [%s] %s %s: %s",
            request_id, request.method, request.url.path, exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "\uc785\ub825 \ub370\uc774\ud130\uac00 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.",
                    "request_id": request_id,
                    "details": [
                        {
                            "field": ".".join(str(loc) for loc in e["loc"]),
                            "message": e["msg"],
                        }
                        for e in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = uuid.uuid4().hex[:12]
        _api_logger.error(
            "Unhandled error [%s] %s %s: %s",
            request_id, request.method, request.url.path, exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "\uc11c\ubc84 \ub0b4\ubd80 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4.",
                    "request_id": request_id,
                }
            },
        )

    @app.get("/health")
    @limiter.limit(GLOBAL_LIMIT)
    async def health(request: Request):
        from api.health import run_health_check
        from services.base import get_session
        import os

        # Resolve DB file path for disk check
        db_url = settings.DATABASE_URL
        if db_url.startswith("sqlite"):
            db_path = os.path.dirname(db_url.replace("sqlite:///", ""))
            if not db_path:
                db_path = "."
        else:
            db_path = "."

        status_code, payload = run_health_check(get_session, db_path)
        if status_code != 200:
            return JSONResponse(status_code=status_code, content=payload)
        return payload

    return app
