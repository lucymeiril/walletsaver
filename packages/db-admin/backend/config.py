"""DB 관리 백엔드 설정 — SQLite 기본, 환경변수로 PostgreSQL 전환 가능"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

LOCAL_ENV_PATHS = (
    BASE_DIR / ".env",
    BASE_DIR / ".env.local",
)


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_local_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = _strip_optional_quotes(value.strip())
    return values


def load_local_env_files(paths: tuple[Path, ...] = LOCAL_ENV_PATHS) -> None:
    """Load local gitignored env files before settings are initialized.

    Existing process env wins; otherwise later local files (for example
    ``.env.local``) may override earlier local files.
    """
    process_env_keys = set(os.environ)
    for path in paths:
        for key, value in _parse_local_env_file(path).items():
            if key not in process_env_keys:
                os.environ[key] = value


def _resolve_local_sqlite_url(url: str) -> str:
    """Resolve relative SQLite paths from this backend, not the caller's CWD.

    ``sqlite:///walletguardian.db`` is otherwise interpreted relative to the
    directory from which Python was launched. Keeping the resolution here makes
    a copied ``.env`` behave the same after cloning the repository anywhere.
    Absolute SQLite paths, in-memory databases, URI-style paths and non-SQLite
    URLs are left unchanged.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return url

    raw_path = url[len(prefix) :]
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        return url

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return f"sqlite:///{path.as_posix()}"


load_local_env_files()

# 기본: 로컬 SQLite (walletguardian.db)
# 운영: DATABASE_URL 환경변수로 PostgreSQL 지정
_default_db = f"sqlite:///{(BASE_DIR / 'walletguardian.db').as_posix()}"


class Settings:
    DATABASE_URL: str = _resolve_local_sqlite_url(os.getenv("DATABASE_URL", _default_db))
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    API_HOST: str = os.getenv("DB_ADMIN_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("DB_ADMIN_PORT", "8002"))

    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5175,http://127.0.0.1:5175",
        ).split(",")
    ]

    # ── Connection Pool 설정 ──
    # pool_size: 동시 유지할 연결 수 (SQLite는 NullPool 사용으로 무시됨)
    # max_overflow: pool_size 초과 시 허용할 추가 연결 수
    # pool_timeout: 풀에서 연결 대기 최대 초 (초과 시 TimeoutError)
    # pool_recycle: 연결 재활용 주기 (초) — MySQL/PG의 wait_timeout 대비
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    # ── Auth 설정 ──
    # 보안: 기본값 true — 관리 패널은 인증 필수 (개발 시 REQUIRE_AUTH=false 로 비활성화)
    REQUIRE_AUTH: bool = os.getenv("REQUIRE_AUTH", "true").lower() == "true"
    JWT_SECRET: str = os.getenv("JWT_SECRET", "CHANGE-ME-IN-PRODUCTION-32-chars!")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_EXPIRE_MIN", "60"))
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))

    # ── Logging 설정 ──
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text" if os.getenv("DEBUG", "false").lower() == "true" else "json")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # ── CORS 설정 ──
    CORS_ALLOWED_ORIGINS: list = []

    # ── Service API Keys ──
    # Format: "key1:role1,key2:role2"
    SERVICE_API_KEYS: dict = {}

    def __init__(self):
        self.CORS_ALLOWED_ORIGINS = [
            o.strip()
            for o in os.getenv(
                "CORS_ALLOWED_ORIGINS",
                "http://localhost:5175,http://127.0.0.1:5175,"
                "http://localhost:5173,http://127.0.0.1:5173,"
                "http://localhost:5174,http://127.0.0.1:5174",
            ).split(",")
            if o.strip()
        ]
        raw_keys = os.getenv("SERVICE_API_KEYS", "")
        if raw_keys:
            self.SERVICE_API_KEYS = {}
            for pair in raw_keys.split(","):
                pair = pair.strip()
                if ":" in pair:
                    key, role = pair.rsplit(":", 1)
                    self.SERVICE_API_KEYS[key.strip()] = role.strip()
        local_admin_key = os.getenv("DB_ADMIN_API_KEY", "").strip()
        if local_admin_key:
            local_admin_role = os.getenv("DB_ADMIN_API_KEY_ROLE", "admin").strip() or "admin"
            self.SERVICE_API_KEYS.setdefault(local_admin_key, local_admin_role)


settings = Settings()
