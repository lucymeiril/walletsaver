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

    # ── Error Logging (outermost — catches everything) ──
    from error_middleware import ErrorLoggingMiddleware
    app.add_middleware(ErrorLoggingMiddleware, server_name="crawler-admin")

    # ── Error Log API ──
    from error_api import router as error_router
    app.include_router(error_router)

    # ── Routers ──────────────────────────────────────────────

    from api.routes.crawlers import router as crawlers_router
    from api.routes.schedules import router as schedules_router
    from api.routes.logs import router as logs_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.plugins import router as plugins_router
    from api.routes.source_workbench import router as source_workbench_router
    from api.routes.operator_browser import router as operator_browser_router
    from api.routes.orchestrator import router as orchestrator_router
    from api.routes.weekly import router as weekly_router
    # 외부 분류 export — 현재 db-admin PendingIngestion을 데이터 원본으로 사용
    from api.routes.raw_batch_export import router as raw_batch_export_router

    from fastapi import Depends
    from api.security.auth import verify_api_key

    _auth = [Depends(verify_api_key)]

    app.include_router(crawlers_router, dependencies=_auth)
    app.include_router(schedules_router, dependencies=_auth)
    app.include_router(logs_router, dependencies=_auth)
    app.include_router(ingestion_router, dependencies=_auth)
    app.include_router(dashboard_router, dependencies=_auth)
    app.include_router(plugins_router, dependencies=_auth)
    app.include_router(source_workbench_router, dependencies=_auth)
    app.include_router(operator_browser_router, dependencies=_auth)
    app.include_router(orchestrator_router, dependencies=_auth)
    app.include_router(weekly_router, dependencies=_auth)
    app.include_router(raw_batch_export_router, dependencies=_auth)

    @app.on_event("startup")
    async def _register_plugins():
        """F1 — 마트 플러그인 어댑터를 PluginRegistry에 등록."""
        for mod_name in ("emart", "homeplus", "lottemart", "costco"):
            try:
                mod = __import__(f"crawlers.marts.{mod_name}.plugin", fromlist=["register"])
                mod.register()
            except Exception as exc:
                logger.warning("[App] plugin %s registration failed: %s", mod_name, exc)

    # ── Health Check ─────────────────────────────────────────

    @app.get("/health")
    async def health():
        """HC-R1: enriched with scheduler, browser, memory, crawl status."""
        import time as _time
        import os as _os

        result = {
            "status": "ok",
            "service": "crawler-admin",
        }

        # Scheduler status
        try:
            scheduler = getattr(app.state, "scheduler", None)
            if scheduler:
                result["scheduler_running"] = scheduler.is_running
                result["scheduled_jobs"] = scheduler.get_pending_job_count()

                history = scheduler.tracker.get_history(limit=1)
                result["last_crawl"] = history[0] if history else None
            else:
                result["scheduler_running"] = False
                result["scheduled_jobs"] = 0
                result["last_crawl"] = None
        except Exception:
            result["scheduler_running"] = False

        # Active crawls from concurrency module
        try:
            from concurrency import active_count
            result["active_crawls"] = active_count()
        except Exception:
            result["active_crawls"] = 0

        # Browser process count from watchdog
        try:
            from engine.browser_watchdog import get_browser_watchdog
            result["browser_processes"] = get_browser_watchdog().get_tracked_count()
        except Exception:
            result["browser_processes"] = 0

        # Memory usage (RSS)
        try:
            import psutil
            proc = psutil.Process(_os.getpid())
            mem = proc.memory_info()
            result["memory_mb"] = round(mem.rss / (1024 * 1024), 1)
        except (ImportError, Exception):
            result["memory_mb"] = None

        # Uptime
        try:
            result["uptime_seconds"] = round(
                _time.monotonic() - app.state.start_time, 1
            )
        except AttributeError:
            result["uptime_seconds"] = None

        # Set degraded status if scheduler is down
        if result.get("scheduler_running") is False and result.get("scheduled_jobs", 0) > 0:
            result["status"] = "degraded"

        return result

    # ── Graceful Shutdown (GS-R1, GS-R2) ────────────────────

    @app.on_event("startup")
    async def _startup():
        """Initialize watchdog and track start time."""
        import time as _time
        app.state.start_time = _time.monotonic()

        from engine.browser_watchdog import get_browser_watchdog
        get_browser_watchdog().start()
        logger.info("[App] browser watchdog started")

    @app.on_event("shutdown")
    async def _shutdown():
        """Graceful shutdown: scheduler → plugins → browsers → logs.

        GS-R1: Proper shutdown sequence.
        GS-R2: Signal-safe browser cleanup.
        """
        import logging as _logging

        logger.info("[App] shutdown sequence started")

        # 1. Stop scheduler (wait for running jobs, max 30s)
        try:
            scheduler = getattr(app.state, "scheduler", None)
            if scheduler and scheduler.is_running:
                scheduler.stop(wait=True)
                logger.info("[App] scheduler stopped")
        except Exception:
            logger.exception("[App] scheduler shutdown error")

        # 2. Cancel all running crawl tasks
        try:
            from concurrency import clear_running_crawlers
            cleared = await clear_running_crawlers()
            if cleared:
                logger.info("[App] cleared %d running crawler slots", cleared)
        except Exception:
            logger.exception("[App] concurrency cleanup error")

        # 3. Shutdown plugins
        try:
            plugin_mgr = getattr(app.state, "plugin_manager", None)
            if plugin_mgr:
                await plugin_mgr.shutdown()
                logger.info("[App] plugins shut down")
        except Exception:
            logger.exception("[App] plugin shutdown error")

        # 4. Kill all browser processes via watchdog
        try:
            from engine.browser_watchdog import get_browser_watchdog
            watchdog = get_browser_watchdog()
            killed = watchdog.kill_all()
            watchdog.stop()
            if killed:
                logger.info("[App] killed %d browser processes", killed)
        except Exception:
            logger.exception("[App] browser cleanup error")

        # 5. Flush log handlers
        for handler in _logging.root.handlers:
            try:
                handler.flush()
            except Exception:
                pass

        logger.info("[App] shutdown complete")

    # ── Signal Handlers (GS-R2) ──────────────────────────────

    import signal

    def _handle_signal(signum, frame):
        """Handle SIGTERM/SIGINT — trigger FastAPI's graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("[App] received %s, initiating graceful shutdown", sig_name)
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (OSError, ValueError):
        pass  # Can't set signal handler in non-main thread

    return app
