"""Crawler-admin environment configuration.

Only settings used by the current crawler-admin runtime belong here. Historical
plugin, delivery, and broad government-API settings were intentionally removed
so configuration files do not advertise retired features.

Current crawlers persist remote ``image_url`` values with crawl records; there
is no local image-file download/resize/cache pipeline in the current runtime.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


# --- Current external data source ---
OPINET_API_KEY: str = os.getenv("OPINET_API_KEY", "")

# --- Proxy / crawler behaviour ---
PROXY_LIST: list[str] = [
    p.strip()
    for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()
]
CRAWL_DELAY_MIN: float = float(os.getenv("CRAWL_DELAY_MIN", "1.0"))
CRAWL_DELAY_MAX: float = float(os.getenv("CRAWL_DELAY_MAX", "5.0"))
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))

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

# --- db-admin working database (read-only from crawler-admin) ---
# Raw export and weekly diff read current db-admin data from here. Normal crawler
# ingestion writes through the db-admin HTTP API rather than opening this DB.
_DB_ADMIN_DB_DEFAULT = BASE_DIR.parent.parent / "db-admin" / "backend" / "walletguardian.db"
DB_ADMIN_DATABASE_URL: str = os.getenv(
    "DB_ADMIN_DATABASE_URL",
    f"sqlite:///{_DB_ADMIN_DB_DEFAULT.as_posix()}",
)

# --- crawler-owned weekly state ---
# Disappeared-SKU alerts are crawler UI/runtime state, not db-admin source data.
# Keep them in a separate SQLite file so weekly alert writes never touch the
# db-admin working database.
_WEEKLY_STATE_DB_DEFAULT = BASE_DIR / "state" / "weekly_state.db"
WEEKLY_STATE_DB_PATH: Path = Path(
    os.getenv("WALLETSAVIOR_WEEKLY_STATE_DB", str(_WEEKLY_STATE_DB_DEFAULT))
).expanduser().resolve()
