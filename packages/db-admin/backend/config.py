"""DB 관리 백엔드 설정 — SQLite 기본, 환경변수로 PostgreSQL 전환 가능"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 기본: 로컬 SQLite (walletguardian.db)
# 운영: DATABASE_URL 환경변수로 PostgreSQL 지정
_default_db = f"sqlite:///{BASE_DIR / 'walletguardian.db'}"

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    API_PORT: int = int(os.getenv("DB_ADMIN_PORT", "8002"))

settings = Settings()
