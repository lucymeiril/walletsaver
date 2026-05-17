"""WalletSavior Public Read API — Phase E1 + F2 (auth/board/admin) + F4 (fuels)."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    health,
    categories,
    products,
    autocomplete,
    auth,
    boards,
    moderation,
    fuels,
)


def create_app() -> FastAPI:
    app = FastAPI(title="WalletSavior Public API", version="1.1.0")

    origins = os.environ.get(
        "WALLETSAVIOR_CORS_ORIGINS", "http://localhost:5173"
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(categories.router, prefix="/api/v1")
    app.include_router(products.router, prefix="/api/v1")
    app.include_router(autocomplete.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(boards.router, prefix="/api/v1")
    app.include_router(moderation.router, prefix="/api/v1")
    app.include_router(fuels.router, prefix="/api/v1")

    return app


app = create_app()
