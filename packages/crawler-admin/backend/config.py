"""
환경 변수 기반 전역 설정 — .env 파일 하나로 배포 환경별 설정을 전환한다.

crawler-admin 패키지용 설정 모듈.
원본: proj/config.py
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env 로드
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# --- Database ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    import warnings
    warnings.warn(
        "DATABASE_URL not set — database features will be unavailable",
        RuntimeWarning,
        stacklevel=2,
    )

# --- 공공데이터 API Keys ---
KAMIS_API_KEY: str = os.getenv("KAMIS_API_KEY", "")
KAMIS_API_ID: str = os.getenv("KAMIS_API_ID", "")
OPINET_API_KEY: str = os.getenv("OPINET_API_KEY", "")
KOSIS_API_KEY: str = os.getenv("KOSIS_API_KEY", "")

# --- Naver API ---
NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")

# --- Proxy ---
PROXY_LIST: list[str] = [
    p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()
]

# --- Crawler ---
CRAWL_DELAY_MIN: float = float(os.getenv("CRAWL_DELAY_MIN", "1.0"))
CRAWL_DELAY_MAX: float = float(os.getenv("CRAWL_DELAY_MAX", "5.0"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))

# --- Image Storage ---
IMAGE_STORAGE_PATH: str = os.getenv("IMAGE_STORAGE_PATH", str(BASE_DIR / "storage" / "images"))
IMAGE_MAX_SIZE: int = int(os.getenv("IMAGE_MAX_SIZE", "1920"))
THUMBNAIL_SIZE: int = int(os.getenv("THUMBNAIL_SIZE", "300"))

# --- API Server ---
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
API_PORT: int = int(os.getenv("API_PORT", "8000"))

# --- Resource Limits ---
MAX_CONCURRENT_CRAWLS: int = int(os.getenv("MAX_CONCURRENT_CRAWLS", "5"))
CRAWL_CUMULATIVE_TIMEOUT: int = int(os.getenv("CRAWL_CUMULATIVE_TIMEOUT", "180"))
SSE_MAX_DURATION: int = int(os.getenv("SSE_MAX_DURATION", "1800"))

# --- Audit ---
AUDIT_LOG_MAX_BYTES: int = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(50 * 1024 * 1024)))
AUDIT_LOG_BACKUP_COUNT: int = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", "10"))

# --- 외부 DB 읽기 전용 접근 (export 컨텍스트 파일용) ---
# ai-admin control DB (raw_crawl_records 원본) — ai-admin 폐기로 _archived 로 이전됨.
# 레거시 raw-batch/workbench 읽기 경로가 호출될 때만 사용(보존된 DB 참조).
_AI_ADMIN_DB_DEFAULT = BASE_DIR.parents[2] / "_archived" / "packages" / "ai-admin" / "backend" / "ai_control.db"
AI_ADMIN_DATABASE_URL: str = os.getenv(
    "AI_ADMIN_DATABASE_URL",
    f"sqlite:///{_AI_ADMIN_DB_DEFAULT.as_posix()}",
)
# db-admin DB (matching_entries / categories / keywords)
_DB_ADMIN_DB_DEFAULT = BASE_DIR.parent.parent / "db-admin" / "backend" / "walletguardian.db"
DB_ADMIN_DATABASE_URL: str = os.getenv(
    "DB_ADMIN_DATABASE_URL",
    f"sqlite:///{_DB_ADMIN_DB_DEFAULT.as_posix()}",
)
