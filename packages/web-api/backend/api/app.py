"""Public web API application factory.

The API serves the current product, mart, gas, hotdeal, community, search and
Naver-local user features. Crawler control belongs to crawler-admin, not this
service.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def _cors_origins() -> list[str]:
    configured = os.getenv(
        "WALLETSAVIOR_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _enable_sqlite_foreign_keys(storage) -> None:
    """Make SQLite enforce the ForeignKey declarations used by account features."""
    storage_engine = getattr(storage, "engine", None)
    if storage_engine is None or getattr(storage_engine.dialect, "name", "") != "sqlite":
        return

    from sqlalchemy import event

    @event.listens_for(storage_engine, "connect")
    def _set_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_app(storage=None, engine=None, event_bus=None) -> FastAPI:
    """Create the web API with optionally injected storage for tests/runtime."""
    app = FastAPI(
        title="지갑 지키미 API",
        description="물가 비교 서비스 백엔드",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # storage가 없으면 db-admin의 DBStorage로 자동 연결 시도
    if storage is None:
        try:
            import logging
            import sys

            web_api_path = os.path.dirname(os.path.dirname(__file__))
            db_admin_path = os.path.normpath(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                "db-admin", "backend",
            ))
            if db_admin_path not in sys.path:
                sys.path.insert(0, db_admin_path)

            from storage.db import DBStorage

            configured_db = os.getenv("DATABASE_URL", "").strip()
            if configured_db:
                db_url = configured_db
                db_label = configured_db
            else:
                db_path = os.path.join(db_admin_path, "walletguardian.db")
                db_url = f"sqlite:///{db_path}"
                db_label = db_path

            storage = DBStorage(db_url)
            _enable_sqlite_foreign_keys(storage)
            storage.init_db()
            if web_api_path in sys.path:
                sys.path.remove(web_api_path)
            sys.path.insert(0, web_api_path)
            for module_name, module in list(sys.modules.items()):
                if module_name == "services" or module_name.startswith("services."):
                    module_file = str(getattr(module, "__file__", "") or "")
                    if module_file.startswith(os.path.join(db_admin_path, "services")):
                        del sys.modules[module_name]
            logging.info("DB 연결 성공: %s", db_label)
        except Exception as exc:
            import logging
            logging.warning("DB 연결 실패; storage 없이 시작합니다: %s", exc)
            storage = None

    app.state.storage = storage
    app.state.engine = engine
    app.state.event_bus = event_bus

    from api.routes.products import router as products_router
    from api.routes.hotdeals import router as hotdeals_router
    from api.routes.marts import router as marts_router
    from api.routes.gas import router as gas_router
    from api.routes.users import router as users_router
    from api.routes.auth import router as auth_router
    from api.routes.community import router as community_router
    from api.routes.search import router as search_router
    from api.routes.naver_local import router as naver_local_router
    from api.routes.profile import router as profile_router
    from api.routes.account_features import router as account_features_router

    app.include_router(products_router, prefix="/api/products", tags=["Products"])
    app.include_router(hotdeals_router, prefix="/api/hotdeals", tags=["Hotdeals"])
    app.include_router(marts_router, prefix="/api/marts", tags=["Marts"])
    app.include_router(gas_router, prefix="/api/gas", tags=["Gas Stations"])
    app.include_router(users_router, prefix="/api/users", tags=["Users"])
    app.include_router(auth_router)
    app.include_router(community_router, prefix="/api/posts", tags=["Community"])
    app.include_router(search_router, prefix="/api/search", tags=["Search"])
    app.include_router(naver_local_router, prefix="/api/local", tags=["Local / Naver"])
    app.include_router(profile_router)
    app.include_router(account_features_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/api/dashboard")
    def dashboard():
        """Home-screen aggregate from available storage; no fabricated rows."""
        current_storage = app.state.storage
        hotdeals = []
        recent_products = []
        if current_storage is not None:
            try:
                hotdeals = current_storage.get_hotdeals(category="all", per_page=8)
            except Exception:
                hotdeals = []
            try:
                recent_products = current_storage.search_products("", per_page=8)
            except Exception:
                recent_products = []

        category_counts = {}
        for product in recent_products:
            cat = product.get("cat") or product.get("category") or "기타"
            top = str(cat).split(" > ")[0] if cat else "기타"
            category_counts[top] = category_counts.get(top, 0) + 1
        category_summary = [
            {"category": name, "name": name, "count": count}
            for name, count in sorted(category_counts.items(), key=lambda item: item[0])
        ]
        return {
            "success": True,
            "data": {
                "hotdeals": hotdeals,
                "category_summary": category_summary,
                "recent_products": recent_products,
                "trending_keywords": [],
            },
            "error": None,
            "meta": None,
        }

    return app
