"""
환경 변수 기반 전역 설정 — .env 파일 하나로 배포 환경별 설정을 전환한다.

왜 존재하는가:
    API 키·DB URL·프록시 목록 같은 환경별 설정을 코드에 하드코딩하면
    개발/스테이징/운영 환경 전환이 불가능하고, 시크릿이 Git에 노출된다.
    .env 파일에서 읽어오면 같은 코드로 환경만 바꿔가며 실행할 수 있다.
어디서 쓰이는가:
    container.py에서만 import한다 — 다른 모듈이 직접 import하면
    "설정을 어디서 읽는가"가 분산되어 추적이 어려워진다.
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
