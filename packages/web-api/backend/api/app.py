"""Public web API application factory.

Runtime storage is owned by web-api. Replaceable catalog/external-hotdeal
snapshots are read separately from server-owned account, interaction and
community SQLite databases. No db-admin source code is required on the server.
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    configured = os.getenv(
        "WALLETSAVIOR_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def _recent_dashboard_products(storage, limit: int = 8) -> list[dict]:
    """Return products ordered by their latest public price observation.

    Product search is intentionally alphabetical, so using it for a dashboard
    section called "recent" silently produced the first names in the catalog.
    Read the snapshot directly here and rank by the latest discount/baseline
    observation instead.
    """
    catalog = getattr(storage, "catalog", None)
    if catalog is None or not hasattr(catalog, "connection"):
        return []

    with catalog.connection() as connection:
        timestamp_parts: list[str] = []
        if catalog._table(connection, "discount_history"):
            timestamp_parts.append(
                "COALESCE((SELECT MAX(d.crawled_at) FROM discount_history d "
                "WHERE d.product_id=p.id), '')"
            )
        if catalog._table(connection, "baseline_prices"):
            timestamp_parts.append(
                "COALESCE((SELECT MAX(b.recorded_at) FROM baseline_prices b "
                "WHERE b.product_id=p.id), '')"
            )

        if len(timestamp_parts) >= 2:
            observed_sql = "MAX(" + ", ".join(timestamp_parts) + ")"
        elif timestamp_parts:
            observed_sql = timestamp_parts[0]
        else:
            observed_sql = "''"

        rows = connection.execute(
            "SELECT p.*, " + observed_sql + " AS _dashboard_observed_at "
            "FROM products p WHERE p.is_active=1 "
            "ORDER BY _dashboard_observed_at DESC, p.id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        products = []
        for row in rows:
            item = catalog._product(connection, row)
            item["observed_at"] = row["_dashboard_observed_at"] or ""
            products.append(item)
        return products


def create_app(storage=None, engine=None, event_bus=None) -> FastAPI:
    """Create web-api, using web-api-owned storage unless tests inject one."""
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

    owns_storage = storage is None
    if storage is None:
        try:
            from services.runtime_storage import RuntimeStorage

            storage = RuntimeStorage()
            storage.init_db()
            logger.info(
                "web-api storage initialized: catalog=%s accounts=%s interactions=%s",
                getattr(getattr(storage, "catalog", None), "path", None),
                getattr(getattr(storage, "accounts", None), "path", None),
                getattr(getattr(storage, "interactions", None), "path", None),
            )
        except Exception:
            logger.exception("web-api storage initialization failed")
            storage = None

    app.state.storage = storage
    app.state.account_storage = getattr(storage, "accounts", storage) if storage is not None else None
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
    from api.routes.admin_remote import router as admin_remote_router

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
    app.include_router(admin_remote_router)

    @app.get("/api/health")
    def health():
        current_storage = app.state.storage
        if current_storage is None:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "degraded",
                    "version": "0.1.0",
                    "catalog": "unavailable",
                    "accounts": "unavailable",
                    "external_hotdeals": "unavailable",
                },
            )

        catalog_health = None
        checker = getattr(current_storage, "catalog_health", None)
        if checker is not None:
            try:
                catalog_health = checker()
            except Exception as exc:
                return JSONResponse(
                    status_code=503,
                    content={
                        "status": "degraded",
                        "version": "0.1.0",
                        "catalog": "unavailable",
                        "accounts": "ok",
                        "external_hotdeals": "unknown",
                        "detail": str(exc),
                    },
                )

        external_hotdeal_health: dict | str = "injected"
        external_store = getattr(current_storage, "external_hotdeals", None)
        external_checker = getattr(external_store, "health", None)
        if callable(external_checker):
            try:
                external_hotdeal_health = external_checker()
            except Exception as exc:
                logger.exception("external hotdeal health check failed")
                external_hotdeal_health = {
                    "ok": False,
                    "available": False,
                    "reason": "health_check_failed",
                    "detail": str(exc),
                }

        optional_degraded = (
            isinstance(external_hotdeal_health, dict)
            and not bool(external_hotdeal_health.get("ok"))
        )
        return {
            "status": "degraded" if optional_degraded else "ok",
            "version": "0.1.0",
            "catalog": catalog_health or "injected",
            "accounts": "ok",
            # External hotdeals are an optional read replica. Report problems
            # without failing readiness for the catalog/account web service.
            "external_hotdeals": external_hotdeal_health,
        }

    @app.get("/api/dashboard")
    def dashboard():
        current_storage = app.state.storage
        if current_storage is None:
            raise HTTPException(status_code=503, detail="대시보드 저장소를 사용할 수 없습니다")
        try:
            hotdeals = current_storage.get_hotdeals(category="all", per_page=8)
            recent_products = _recent_dashboard_products(current_storage, limit=8)
            category_tree = current_storage.get_category_tree()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="대시보드 데이터를 불러올 수 없습니다") from exc

        category_summary = [
            {
                "category": node.get("name") or "기타",
                "name": node.get("name") or "기타",
                "count": int(node.get("count") or 0),
            }
            for node in category_tree
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

    if owns_storage:
        @app.on_event("shutdown")
        def _close_runtime_storage():
            current_storage = app.state.storage
            closer = getattr(current_storage, "close", None)
            if closer is not None:
                closer()

    return app
