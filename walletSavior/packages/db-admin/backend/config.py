"""DB 관리 백엔드 설정"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://walletsavior:changeme@localhost:5432/walletsavior")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    API_PORT: int = int(os.getenv("DB_ADMIN_PORT", "8002"))

settings = Settings()
