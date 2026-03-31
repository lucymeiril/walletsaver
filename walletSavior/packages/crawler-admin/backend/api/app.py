"""크롤러 관리 API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="WalletSavior 크롤러 관리",
        description="크롤러 관리 및 모니터링 API",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from api.routes.crawlers import router as crawlers_router
    from api.routes.schedules import router as schedules_router
    from api.routes.logs import router as logs_router

    app.include_router(crawlers_router)
    app.include_router(schedules_router)
    app.include_router(logs_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "crawler-admin"}

    return app
