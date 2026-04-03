"""DB 관리 API 팩토리"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="WalletSavior DB 관리",
        description="데이터베이스 관리 API",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.routes.products import router as products_router
    from api.routes.prices import router as prices_router
    from api.routes.categories import router as categories_router
    from api.routes.keywords import router as keywords_router
    from api.routes.analytics import router as analytics_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.admin import router as admin_router

    # /api 접두어 — 프론트엔드 client.js가 /api/products 등으로 호출
    app.include_router(products_router, prefix="/api")
    app.include_router(prices_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(keywords_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    # ingestion 라우터는 이미 /api/ingestions 접두어가 있음
    app.include_router(ingestion_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "db-admin"}

    return app
