"""ai-admin 백엔드 설정 — 로컬 전용 스켈레톤."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Settings:
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")
    API_HOST: str = os.getenv("AI_ADMIN_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("AI_ADMIN_PORT", "8003"))

    CORS_ALLOWED_ORIGINS: list[str] = []

    def __init__(self) -> None:
        self.CORS_ALLOWED_ORIGINS = [
            o.strip()
            for o in os.getenv(
                "CORS_ALLOWED_ORIGINS",
                "http://localhost:5176,http://127.0.0.1:5176",
            ).split(",")
            if o.strip()
        ]


settings = Settings()
