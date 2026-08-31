"""DB 관리 API 팩토리."""
import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from api.middleware.rate_limit import GLOBAL_LIMIT, limiter, rate_limit_exceeded_handler
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.security import MAX_REQUEST_BODY_BYTES
from config import settings

_ROOT = Path(__file__).resolve().parents[4]
_SHARED = _ROOT / "packages" / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

_lifecycle_logger = logging.getLogger("lifecycle")
_api_logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.DEBUG and "changeme" in settings.DATABASE_URL:
        raise RuntimeError(
            "SECURITY: Default database password detected. "
            "Set a strong DATABASE_URL for production."
        )

    from services.base import get_engine
    from storage.models import Base

    engine = get_engine()
    try:
        # A clean local checkout does not ship walletguardian.db. Create the
        # current SQLAlchemy schema before seeds and route traffic touch it.
        # Existing databases still require explicit migrations for column
        # changes; create_all() only fills in missing tables.
        Base.metadata.create_all(bind=engine)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        _lifecycle_logger.info("Startup: database schema/connection verified")
    except Exception as exc:
        _lifecycle_logger.critical("Startup: database initialization failed — %s", exc)
        raise

    try:
        from services.catalog_seed import ensure_catalog_taxonomy_seeded

        result = ensure_catalog_taxonomy_seeded(engine)
        _lifecycle_logger.info(
            "Startup: catalog taxonomy seed complete — categories=%s keywords=%s",
            result.get("categories", 0),
            result.get("keywords", 0),
        )
    except Exception as exc:
        _lifecycle_logger.warning("Startup: catalog taxonomy seed failed — %s", exc)

    try:
        from services.seed import seed_default_admin

        seed_default_admin()
    except Exception as exc:
        _lifecycle_logger.warning("Startup: admin seed failed — %s", exc)

    snapshot_stop = asyncio.Event()
    snapshot_task = None
    auto_publisher = os.getenv(
        "WALLETSAVIOR_AUTO_SNAPSHOT_PUBLISHER", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if auto_publisher:
        from services.public_snapshot_publisher import run_public_snapshot_publisher

        snapshot_task = asyncio.create_task(
            run_public_snapshot_publisher(snapshot_stop),
            name="public-snapshot-publisher",
        )
    else:
        _lifecycle_logger.info(
            "Automatic snapshot publisher disabled; moderator approval is required"
        )

    _lifecycle_logger.info(
        "Startup complete — host=%s port=%s debug=%s",
        settings.API_HOST,
        settings.API_PORT,
        settings.DEBUG,
    )

    yield

    if snapshot_task is not None:
        _lifecycle_logger.info("Shutdown: stopping public snapshot publisher")
        snapshot_stop.set()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _lifecycle_logger.error("Shutdown: public snapshot publisher failed — %s", exc)

    _lifecycle_logger.info("Shutdown: closing database connections")
    try:
        from services.base import reset_engine

        reset_engine()
        _lifecycle_logger.info("Shutdown: engine disposed successfully")
    except Exception as exc:
        _lifecycle_logger.error("Shutdown: engine disposal failed — %s", exc)

    for handler in logging.root.handlers:
        try:
            handler.flush()
        except Exception:
            pass

    _lifecycle_logger.info("Shutdown: complete")


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
                        "message": f"요청 본문은 {MAX_REQUEST_BODY_BYTES // (1024 * 1024)}MB를 초과할 수 없습니다.",
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

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=not settings.DEBUG,
    )
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

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
    from api.routes.normalized_catalog import router as normalized_catalog_router
    from api.routes.maintenance import router as maintenance_router
    from api.routes.matching_import import router as matching_import_router
    from api.routes.matching_rules import router as matching_rules_router
    from api.routes.catalog_bundles import router as catalog_bundles_router

    app.add_middleware(RequestSizeLimitMiddleware)

    from error_api import router as error_router

    app.include_router(error_router)
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
    app.include_router(normalized_catalog_router, prefix="/api")
    app.include_router(maintenance_router, prefix="/api")
    app.include_router(matching_import_router, prefix="/api")
    app.include_router(matching_rules_router, prefix="/api")
    app.include_router(catalog_bundles_router, prefix="/api")
    # ingestion router already owns the /api/ingestions prefix.
    app.include_router(ingestion_router)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = uuid.uuid4().hex[:12]
        _api_logger.warning(
            "Validation error [%s] %s %s: %s",
            request_id,
            request.method,
            request.url.path,
            exc.errors(),
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "입력 데이터가 올바르지 않습니다.",
                    "request_id": request_id,
                    "details": [
                        {
                            "field": ".".join(str(loc) for loc in error["loc"]),
                            "message": error["msg"],
                        }
                        for error in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = uuid.uuid4().hex[:12]
        _api_logger.error(
            "Unhandled error [%s] %s %s: %s",
            request_id,
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "서버 내부 오류가 발생했습니다.",
                    "request_id": request_id,
                }
            },
        )

    @app.get("/health")
    @limiter.limit(GLOBAL_LIMIT)
    async def health(request: Request):
        import os

        from api.health import run_health_check
        from services.base import get_session

        db_url = settings.DATABASE_URL
        if db_url.startswith("sqlite"):
            db_path = os.path.dirname(db_url.replace("sqlite:///", "")) or "."
        else:
            db_path = "."

        status_code, payload = run_health_check(get_session, db_path)
        if status_code != 200:
            return JSONResponse(status_code=status_code, content=payload)
        return payload

    return app
