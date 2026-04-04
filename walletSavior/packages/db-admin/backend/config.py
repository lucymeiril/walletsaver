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

    # ── Connection Pool 설정 ──
    # pool_size: 동시 유지할 연결 수 (SQLite는 StaticPool 사용으로 무시됨)
    # max_overflow: pool_size 초과 시 허용할 추가 연결 수
    # pool_timeout: 풀에서 연결 대기 최대 초 (초과 시 TimeoutError)
    # pool_recycle: 연결 재활용 주기 (초) — MySQL/PG의 wait_timeout 대비
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))

settings = Settings()
