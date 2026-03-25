"""
전역 설정 관리.
.env 파일에서 환경변수를 읽어 설정값을 제공한다.
모든 모듈은 이 파일 대신 core/contracts를 통해 설정을 주입받아야 한다.
이 파일은 container.py에서만 사용된다.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# .env 로드
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# --- Database ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/wallet_guardian")

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
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))
