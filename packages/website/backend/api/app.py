"""
FastAPI 앱 팩토리 — container.py가 의존성을 주입하여 앱을 생성한다.

왜 팩토리 패턴인가:
    테스트 시 mock storage를 주입할 수 있고,
    main.py와 container.py가 각각 독립적으로 앱을 생성할 수 있다.
어디서 쓰이는가:
    container.py._init_api() → create_app(storage, engine, event_bus)
    main.py "server" 명령 → uvicorn으로 이 앱을 서빙.

라우터 구조:
    api/routes/ 디렉토리에 도메인별 라우터 파일을 배치한다.
    (routes/products.py, routes/hotdeals.py, routes/marts.py, routes/gas.py, routes/crawlers.py, routes/users.py)
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.middleware.security_headers import SecurityHeadersMiddleware
from api.middleware.request_size import RequestSizeLimitMiddleware
from api.middleware.error_handler import register_error_handlers
from api.middleware.rate_limit import limiter
from slowapi.errors import RateLimitExceeded

logger = logging.getLogger(__name__)


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            "detail": str(exc.detail),
        },
        headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    logger.info("서버 시작 — 리소스 초기화")
    yield
    # ── Shutdown ──
    logger.info("서버 종료 — 리소스 정리 시작")

    # 1. Shutdown Playwright browser pool
    try:
        from api.routes.naver_local import _pool, _executor
        _pool.force_cleanup()
        logger.info("Playwright 브라우저 풀 정리 완료")
    except Exception:
        logger.exception("Playwright 정리 중 오류")

    # 2. Shutdown ThreadPoolExecutor
    try:
        _executor.shutdown(wait=True, cancel_futures=True)
        logger.info("ThreadPoolExecutor 종료 완료")
    except Exception:
        logger.exception("ThreadPoolExecutor 종료 중 오류")

    logger.info("서버 종료 — 리소스 정리 완료")


def create_app(storage=None, engine=None, event_bus=None) -> FastAPI:
    """
    팩토리 패턴 — container.py가 의존성 주입하여 앱 생성.

    storage가 None이면 각 라우터가 mock 데이터를 반환하므로
    DB 없이도 즉시 프론트엔드 개발이 가능하다.
    """
    is_debug = os.getenv("DEBUG", "").lower() == "true"

    app = FastAPI(
        title="지갑 지키미 API",
        description="물가 비교 서비스 백엔드 — 정부 공공데이터 + 마트 할인 + 커뮤니티 핫딜",
        version="0.1.0",
        docs_url="/docs" if is_debug else None,
        redoc_url="/redoc" if is_debug else None,
        openapi_url="/openapi.json" if is_debug else None,
        lifespan=lifespan,
    )

    # ── 에러 핸들러 등록 ──
    register_error_handlers(app)

    # ── 레이트 리밋 ──
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

    # ── Error Logging (outermost — catches everything) ──
    from error_middleware import ErrorLoggingMiddleware
    app.add_middleware(ErrorLoggingMiddleware, server_name="website")

    # ── Error Log API ──
    from error_api import router as error_router
    app.include_router(error_router)

    # ── 미들웨어 (LIFO: 마지막 추가 = 먼저 실행) ──

    # 1. CORS — 프론트엔드 개발 서버 허용
    _DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
    allowed_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )

    # 2. GZip compression for responses > 500 bytes
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # 3. 보안 헤더
    app.add_middleware(SecurityHeadersMiddleware)

    # 4. 요청 크기 제한 (10 MB)
    app.add_middleware(RequestSizeLimitMiddleware, max_body_size=10 * 1024 * 1024)

    # storage가 없으면 db-admin의 DBStorage로 자동 연결 시도
    if storage is None:
        try:
            import sys
            db_admin_path = os.path.normpath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "db-admin", "backend"
            ))
            if db_admin_path not in sys.path:
                sys.path.insert(0, db_admin_path)

            from storage.db import DBStorage

            db_path = os.path.join(db_admin_path, "walletguardian.db")
            storage = DBStorage(f"sqlite:///{db_path}")
            storage.init_db()
            logging.info("DB 연결 성공: %s", db_path)

            # Wrap with circuit breaker proxy
            from api.utils.storage_proxy import StorageProxy
            storage = StorageProxy(storage)
        except Exception as e:
            logging.warning("DB 연결 실패, mock 데이터 사용: %s", e)
            storage = None

    # 의존성을 app.state에 저장 — 라우터에서 request.app.state.storage로 접근
    app.state.storage = storage
    app.state.engine = engine
    app.state.event_bus = event_bus

    # 라우터 등록 — 도메인별 분리
    from api.routes.products import router as products_router
    from api.routes.hotdeals import router as hotdeals_router
    from api.routes.marts import router as marts_router
    from api.routes.gas import router as gas_router
    from api.routes.crawlers import router as crawlers_router
    from api.routes.users import router as users_router
    from api.routes.auth import router as auth_router
    from api.routes.community import router as community_router
    from api.routes.search import router as search_router
    from api.routes.restaurants import router as restaurants_router
    from api.routes.naver_local import router as naver_local_router
    from api.routes.profile import router as profile_router
    from api.routes.cart import router as cart_router
    from api.routes.wishlist import router as wishlist_router
    from api.routes.activity import router as activity_router

    app.include_router(products_router, prefix="/api/products", tags=["Products"])
    app.include_router(hotdeals_router, prefix="/api/hotdeals", tags=["Hotdeals"])
    app.include_router(marts_router, prefix="/api/marts", tags=["Marts"])
    app.include_router(gas_router, prefix="/api/gas", tags=["Gas Stations"])
    app.include_router(crawlers_router, prefix="/api/crawlers", tags=["Crawlers"])
    app.include_router(users_router, prefix="/api/users", tags=["Users"])
    app.include_router(auth_router)
    app.include_router(community_router, prefix="/api/posts", tags=["Community"])
    app.include_router(search_router, prefix="/api/search", tags=["Search"])
    app.include_router(restaurants_router, prefix="/api", tags=["Restaurants"])
    app.include_router(naver_local_router, prefix="/api/local", tags=["Local / Naver"])
    app.include_router(profile_router)
    app.include_router(cart_router)
    app.include_router(wishlist_router)
    app.include_router(activity_router)

    # ── 편의 별칭 라우트 (테스트·호환성) ──
    from fastapi import Request as _Req, Query as _Q

    @app.get("/api/categories/", tags=["Categories"])
    async def categories_alias(request: _Req):
        """카테고리 독립 경로 — /api/products/categories 별칭."""
        from api.routes.products import get_categories
        return await get_categories(request)

    @app.get("/api/keywords/", tags=["Keywords"])
    async def keywords_alias(request: _Req):
        """키워드 독립 경로 — /api/products/trending 별칭."""
        from api.routes.products import get_trending_keywords
        return await get_trending_keywords(request)

    @app.get("/api/mart/discounts", tags=["Marts"])
    async def mart_discounts_alias(request: _Req):
        """마트 할인 — /api/marts 별칭."""
        from api.routes.marts import list_marts
        return await list_marts(request)

    @app.get("/api/prices/compare", tags=["Prices"])
    async def price_compare(request: _Req, product: str = ""):
        """상품명으로 가격 비교 — 이름 검색 후 출처별 비교."""
        s = request.app.state.storage
        if s is None:
            return {"success": True, "data": [], "error": None}
        products = s.search_products(product)
        if not products:
            return {"success": True, "data": [], "error": None}
        pid = products[0]["id"]
        compare = s.get_price_compare(pid)
        return {"success": True, "data": {"product": products[0], "prices": compare}, "error": None}

    @app.get("/api/health")
    async def health():
        """헬스체크 — DB, Playwright 브라우저, 메모리 상태 확인."""
        checks: dict = {}
        overall = "ok"

        # 1. DB connectivity
        storage = app.state.storage
        if storage is not None:
            try:
                circuit = getattr(storage, "circuit_state", "unknown")
                if circuit == "open":
                    checks["db"] = {"status": "degraded", "circuit": "open"}
                    overall = "degraded"
                else:
                    checks["db"] = {"status": "ok", "circuit": circuit}
            except Exception as e:
                checks["db"] = {"status": "error", "error": str(e)}
                overall = "error"
        else:
            checks["db"] = {"status": "disconnected"}
            overall = "degraded"

        # 2. Playwright browser pool
        try:
            from api.routes.naver_local import _pool, _naver_circuit
            browser_ok = _pool.is_healthy()
            naver_circuit = _naver_circuit.state
            checks["playwright"] = {
                "status": "ok" if browser_ok else "error",
                "circuit": naver_circuit,
            }
            if not browser_ok or naver_circuit == "open":
                overall = "degraded" if overall == "ok" else overall
        except Exception as e:
            checks["playwright"] = {"status": "error", "error": str(e)}

        # 3. Memory usage
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            mem_mb = round(mem_info.rss / (1024 * 1024), 1)
            mem_status = "ok" if mem_mb < 512 else ("warning" if mem_mb < 1024 else "critical")
            checks["memory"] = {
                "status": mem_status,
                "rss_mb": mem_mb,
            }
            if mem_status != "ok":
                overall = "degraded" if overall == "ok" else overall
        except Exception:
            checks["memory"] = {"status": "unknown"}

        status_code = 200 if overall in ("ok", "degraded") else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall,
                "version": "0.1.0",
                "checks": checks,
            },
        )

    # ── Dashboard: 홈페이지 데이터 통합 (8 calls → 1) ──
    from api.utils.cache import TTLCache as _TTLCache
    _dashboard_cache = _TTLCache(ttl_seconds=60, max_size=4)

    @app.get("/api/dashboard", tags=["Dashboard"])
    async def dashboard(request: _Req):
        """홈페이지 통합 데이터 — hotdeals, category-summary, trending, recent products를 한 번에 반환."""
        cached = _dashboard_cache.get("dashboard")
        if cached is not None:
            return cached

        s = request.app.state.storage
        result = {
            "hotdeals": [],
            "category_summary": [],
            "trending_keywords": [],
            "recent_products": [],
        }

        if s is not None:
            try:
                result["hotdeals"] = s.get_hotdeals(sort="recent", per_page=10)
            except Exception:
                logger.exception("Failed to load hotdeals for dashboard")
                result["hotdeals"] = []
            try:
                from api.routes.products import get_category_summary
                summary_resp = await get_category_summary(request)
                if hasattr(summary_resp, "data"):
                    result["category_summary"] = summary_resp.data
                elif isinstance(summary_resp, dict):
                    result["category_summary"] = summary_resp.get("data", [])
            except Exception:
                logger.exception("Failed to load category_summary for dashboard")
                result["category_summary"] = []
            try:
                from api.routes.products import get_trending_keywords
                trend_resp = await get_trending_keywords(request)
                if hasattr(trend_resp, "data"):
                    result["trending_keywords"] = trend_resp.data
                elif isinstance(trend_resp, dict):
                    result["trending_keywords"] = trend_resp.get("data", [])
            except Exception:
                logger.exception("Failed to load trending_keywords for dashboard")
                result["trending_keywords"] = []
            try:
                products = s.search_products("", per_page=10)
                if isinstance(products, list):
                    result["recent_products"] = products
                elif isinstance(products, dict) and "items" in products:
                    result["recent_products"] = products["items"][:10]
            except Exception:
                logger.exception("Failed to load recent_products for dashboard")
                result["recent_products"] = []

        resp = {"success": True, "data": result, "error": None}
        _dashboard_cache.set("dashboard", resp)
        return resp

    return app
