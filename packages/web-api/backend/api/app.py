"""WalletSavior Public Read API — Phase E1."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health, categories, products, autocomplete


def create_app() -> FastAPI:
    app = FastAPI(title="WalletSavior Public API", version="1.0.0")

    origins = os.environ.get(
        "WALLETSAVIOR_CORS_ORIGINS", "http://localhost:5173"
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(categories.router, prefix="/api/v1")
    app.include_router(products.router, prefix="/api/v1")
    app.include_router(autocomplete.router, prefix="/api/v1")

    return app


app = create_app()
