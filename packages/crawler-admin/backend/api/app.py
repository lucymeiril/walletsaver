"""크롤러 관리 API."""

import logging
import os
import uuid

# .env 로드 — auth.py 등이 os.getenv() 호출 전에 환경변수가 준비되어야 함
import config  # noqa: F401  — config.py가 load_dotenv() 수행

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.gzip import GZipMiddleware

from api.error_codes import ErrorCode, safe_error_response
from logging_config import setup_logging

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


def create_app() -> FastAPI:
    is_debug = os.getenv("DEBUG", "").lower() in ("1", "true", "yes")

    setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))

    app = FastAPI(
        title="WalletSavior 크롤러 관리",
        description="크롤러 관리 및 모니터링 API",
        version="0.1.0",
        docs_url="/docs" if is_debug else None,
        redoc_url="/redoc" if is_debug else None,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(GZipMiddleware, minimum_size=500)
    from api.security.headers import SecurityHeadersMiddleware
    app.add_middleware(SecurityHeadersMiddleware)

    allowed_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return safe_error_response(
            422,
            ErrorCode.INVALID_INPUT,
            detail="요청 데이터가 유효하지 않습니다.",
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        error_id = uuid.uuid4().hex[:12]
        logger.exception(
            "[%s] Unhandled exception on %s %s",
            error_id,
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "error_id": error_id},
        )

    from error_middleware import ErrorLoggingMiddleware
    app.add_middleware(ErrorLoggingMiddleware, server_name="crawler-admin")

    from error_api import router as error_router
    app.include_router(error_router)

    from api.routes.crawlers import router as crawlers_router
    from api.routes.schedules import router as schedules_router
    from api.routes.logs import router as logs_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.operator_browser import router as operator_browser_router
    from api.routes.orchestrator import router as orchestrator_router
    from api.routes.weekly import router as weekly_router
    from api.routes.raw_batch_export import router as raw_batch_export_router

    from fastapi import Depends
    from api.security.auth import verify_api_key

    auth_dependencies = [Depends(verify_api_key)]

    app.include_router(crawlers_router, dependencies=auth_dependencies)
    app.include_router(schedules_router, dependencies=auth_dependencies)
    app.include_router(logs_router, dependencies=auth_dependencies)
    app.include_router(ingestion_router, dependencies=auth_dependencies)
    app.include_router(dashboard_router, dependencies=auth_dependencies)
    app.include_router(operator_browser_router, dependencies=auth_dependencies)
    app.include_router(orchestrator_router, dependencies=auth_dependencies)
    app.include_router(weekly_router, dependencies=auth_dependencies)
    app.include_router(raw_batch_export_router, dependencies=auth_dependencies)

    @app.on_event("startup")
    async def _register_plugins():
        for mod_name in ("emart", "homeplus", "lottemart", "costco"):
            try:
                mod = __import__(f"crawlers.marts.{mod_name}.plugin", fromlist=["register"])
                mod.register()
            except Exception as exc:
                logger.warning("[App] plugin %s registration failed: %s", mod_name, exc)

    @app.get("/health")
    async def health():
        import os as _os
        import time as _time

        result = {"status": "ok", "service": "crawler-admin"}

        try:
            from api.routes import schedules as schedule_routes
            from services.crawl_orchestrator import get_run_store

            store = get_run_store()
            active_schedules = store.list_schedules(enabled_only=True)
            recent_runs = store.list_runs(page=1, page_size=1).get("items", [])
            task = getattr(schedule_routes, "_schedule_task", None)
            schedule_loop_enabled = os.getenv(
                "WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", ""
            ).lower() not in {"1", "true", "yes"}
            result["scheduler_running"] = bool(
                schedule_loop_enabled and task is not None and not task.done()
            )
            result["scheduled_jobs"] = len(active_schedules)
            result["last_crawl"] = recent_runs[0] if recent_runs else None
            if schedule_loop_enabled and active_schedules and not result["scheduler_running"]:
                result["status"] = "degraded"
        except Exception:
            logger.exception("[health] orchestrator schedule status unavailable")
            result["scheduler_running"] = False
            result["scheduled_jobs"] = 0
            result["last_crawl"] = None

        try:
            from concurrency import active_count
            result["active_crawls"] = active_count()
        except Exception:
            result["active_crawls"] = 0

        try:
            from engine.browser_watchdog import get_browser_watchdog
            result["browser_processes"] = get_browser_watchdog().get_tracked_count()
        except Exception:
            result["browser_processes"] = 0

        try:
            import psutil
            proc = psutil.Process(_os.getpid())
            mem = proc.memory_info()
            result["memory_mb"] = round(mem.rss / (1024 * 1024), 1)
        except (ImportError, Exception):
            result["memory_mb"] = None

        try:
            result["uptime_seconds"] = round(_time.monotonic() - app.state.start_time, 1)
        except AttributeError:
            result["uptime_seconds"] = None

        return result

    @app.on_event("startup")
    async def _startup():
        import time as _time
        app.state.start_time = _time.monotonic()

        from engine.browser_watchdog import get_browser_watchdog
        get_browser_watchdog().start()
        logger.info("[App] browser watchdog started")

    @app.on_event("shutdown")
    async def _shutdown():
        import logging as _logging

        logger.info("[App] shutdown sequence started")

        try:
            from concurrency import clear_running_crawlers
            cleared = await clear_running_crawlers()
            if cleared:
                logger.info("[App] cleared %d running crawler slots", cleared)
        except Exception:
            logger.exception("[App] concurrency cleanup error")

        try:
            from engine.browser_watchdog import get_browser_watchdog
            watchdog = get_browser_watchdog()
            killed = watchdog.kill_all()
            watchdog.stop()
            if killed:
                logger.info("[App] killed %d browser processes", killed)
        except Exception:
            logger.exception("[App] browser cleanup error")

        for handler in _logging.root.handlers:
            try:
                handler.flush()
            except Exception:
                pass

        logger.info("[App] shutdown complete")

    import signal

    def _handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("[App] received %s, initiating graceful shutdown", sig_name)
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (OSError, ValueError):
        pass

    return app
