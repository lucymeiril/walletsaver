"""ai-admin 백엔드 설정 — 로컬 전용 스켈레톤."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_CONTROL_DB_PATH = BASE_DIR / "ai_control.db"
DEFAULT_DB_ADMIN_DB_PATH = BASE_DIR.parent.parent / "db-admin" / "backend" / "walletguardian.db"


class Settings:
    DEBUG: bool = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")
    API_HOST: str = os.getenv("AI_ADMIN_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("AI_ADMIN_PORT", "8003"))

    CORS_ALLOWED_ORIGINS: list[str] = []

    CONTROL_DATABASE_URL: str = ""
    DB_ADMIN_DATABASE_URL: str = ""

    def __init__(self) -> None:
        self.CORS_ALLOWED_ORIGINS = [
            o.strip()
            for o in os.getenv(
                "CORS_ALLOWED_ORIGINS",
                "http://localhost:5176,http://127.0.0.1:5176",
            ).split(",")
            if o.strip()
        ]
        self.CONTROL_DATABASE_URL = os.getenv(
            "AI_CONTROL_DATABASE_URL",
            f"sqlite:///{DEFAULT_CONTROL_DB_PATH.as_posix()}",
        )
        self.DB_ADMIN_DATABASE_URL = os.getenv(
            "DB_ADMIN_DATABASE_URL",
            f"sqlite:///{DEFAULT_DB_ADMIN_DB_PATH.as_posix()}",
        )


settings = Settings()
