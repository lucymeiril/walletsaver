# DB Admin — Infrastructure Hardening Implementation Spec

> **Created**: 2025-07-18
> **Source Audits**: `db-admin-code-audit.md` (Issues 8, 13, 15, 16, 18), `db-admin-arch-audit.md` (Issues 4, 5, 10, 11, 12, 15)
> **Scope**: Security Headers, Rate Limiting, Bind Address, Config Security, API Docs Protection, Backup Strategy
> **Target Package**: `packages/db-admin/`

---

## Table of Contents

1. [Security Headers Middleware](#1-security-headers-middleware)
2. [Rate Limiting](#2-rate-limiting)
3. [Bind Address Restriction](#3-bind-address-restriction)
4. [Config Security — Secrets to Environment Variables](#4-config-security--secrets-to-environment-variables)
5. [API Docs Protection](#5-api-docs-protection)
6. [Backup Strategy](#6-backup-strategy)
7. [Integration & Startup Order](#7-integration--startup-order)
8. [Test Plan](#8-test-plan)
9. [Rollback Plan](#9-rollback-plan)

---

## 1. Security Headers Middleware

**Audit Refs**: Code Audit Issue 18, Arch Audit Issue 15
**Risk Addressed**: Missing CSP, HSTS, X-Frame-Options, X-Content-Type-Options

### 1.1 New File: `backend/api/middleware/security_headers.py`

```python
"""
Security response headers middleware.
Adds CSP, HSTS, X-Frame-Options, X-Content-Type-Options to every response.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject security headers into every HTTP response."""

    def __init__(self, app, *, enable_hsts: bool = False):
        super().__init__(app)
        # HSTS should only be enabled when TLS termination is in place
        self.enable_hsts = enable_hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Prevent MIME-type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevent clickjacking — admin panel must never be iframed
        response.headers["X-Frame-Options"] = "DENY"

        # Content Security Policy — restrict resource loading to same origin
        # 'unsafe-inline' for styles is needed by React dev tooling;
        # tighten to nonce-based in production builds
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )

        # Referrer leak prevention
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disable browser-side caching for API responses
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"

        # HSTS — only when served behind TLS-terminating reverse proxy
        if self.enable_hsts:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Remove Server header to avoid version fingerprinting
        response.headers.pop("server", None)

        return response
```

### 1.2 Register in `backend/api/app.py`

Add the middleware **before** CORSMiddleware (Starlette processes middleware in LIFO order, so the last-added middleware runs first on request but last on response — security headers must wrap the final response):

```python
# --- EXISTING (after app = FastAPI(...)) ---

from api.middleware.security_headers import SecurityHeadersMiddleware

app.add_middleware(
    SecurityHeadersMiddleware,
    enable_hsts=not settings.DEBUG,  # HSTS only when not in dev mode
)

# ... then CORS middleware (already exists)
```

### 1.3 Exact Diff for `backend/api/app.py`

```diff
 from fastapi import FastAPI
 from fastapi.middleware.cors import CORSMiddleware
 from fastapi.middleware.gzip import GZipMiddleware
+from api.middleware.security_headers import SecurityHeadersMiddleware
+from config import settings

 def create_app() -> FastAPI:
     app = FastAPI(
         title="WalletSavior DB 관리",
         description="데이터베이스 관리 API",
         version="0.1.0",
     )

+    # ── Security headers (CSP, X-Frame-Options, etc.) ──
+    app.add_middleware(
+        SecurityHeadersMiddleware,
+        enable_hsts=not settings.DEBUG,
+    )
+
     # 응답 압축: 500바이트 이상 응답에 gzip 적용
     app.add_middleware(GZipMiddleware, minimum_size=500)
```

### 1.4 Create Package Init

Create `backend/api/middleware/__init__.py` (empty file).

---

## 2. Rate Limiting

**Audit Refs**: Code Audit Issue 8, Arch Audit Issue 5
**Risk Addressed**: Unlimited requests on all 64 endpoints — DoS, brute-force, data flooding

### 2.1 Install Dependency

```diff
 # backend/requirements.txt — add:
+slowapi>=0.1.9
+limits>=3.0
```

Run: `pip install slowapi>=0.1.9`

### 2.2 New File: `backend/api/middleware/rate_limit.py`

```python
"""
Per-IP rate limiting using slowapi.
Provides tiered limits: global, standard, admin, export, destructive.
"""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


def _get_client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind reverse proxy."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


# Read limits from environment for production tuning
GLOBAL_LIMIT = os.getenv("RATE_LIMIT_GLOBAL", "200/minute")
ADMIN_LIMIT = os.getenv("RATE_LIMIT_ADMIN", "10/minute")
DESTRUCTIVE_LIMIT = os.getenv("RATE_LIMIT_DESTRUCTIVE", "3/hour")
EXPORT_LIMIT = os.getenv("RATE_LIMIT_EXPORT", "10/minute")
INGESTION_LIMIT = os.getenv("RATE_LIMIT_INGESTION", "30/minute")

limiter = Limiter(
    key_func=_get_client_ip,
    default_limits=[GLOBAL_LIMIT],
    storage_uri=os.getenv("RATE_LIMIT_STORAGE", "memory://"),
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return JSON 429 instead of plain text."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "요청 횟수 제한을 초과했습니다. 잠시 후 다시 시도해주세요.",
            "retry_after": exc.detail,
        },
    )
```

### 2.3 Register in `backend/api/app.py`

```diff
+from slowapi.errors import RateLimitExceeded
+from api.middleware.rate_limit import limiter, rate_limit_exceeded_handler

 def create_app() -> FastAPI:
     app = FastAPI(...)

+    # ── Rate Limiting ──
+    app.state.limiter = limiter
+    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

     # ... (existing middleware)
```

### 2.4 Apply Per-Route Limits

Decorate specific route handlers with tighter limits. The global `200/minute` default applies to all unlisted endpoints automatically.

#### `backend/api/routes/admin.py`

```diff
+from api.middleware.rate_limit import limiter, DESTRUCTIVE_LIMIT, ADMIN_LIMIT
+from starlette.requests import Request

 @router.post("/admin/reset-source")
+@limiter.limit(DESTRUCTIVE_LIMIT)
-def reset_source(body: ResetSourceRequest):
+def reset_source(request: Request, body: ResetSourceRequest):
     ...

 @router.post("/admin/reset-products")
+@limiter.limit(DESTRUCTIVE_LIMIT)
-def reset_products(body: ResetProductsRequest):
+def reset_products(request: Request, body: ResetProductsRequest):
     ...

 @router.post("/admin/reset-all")
+@limiter.limit(DESTRUCTIVE_LIMIT)
-def reset_all(body: ResetAllRequest):
+def reset_all(request: Request, body: ResetAllRequest):
     ...

 @router.get("/admin/data-summary")
+@limiter.limit(ADMIN_LIMIT)
-def data_summary():
+def data_summary(request: Request):
     ...
```

#### `backend/api/routes/prices.py` (export endpoint)

```diff
+from api.middleware.rate_limit import limiter, EXPORT_LIMIT
+from starlette.requests import Request

 @router.get("/prices/export")
+@limiter.limit(EXPORT_LIMIT)
-def export_prices():
+def export_prices(request: Request):
     ...
```

#### `backend/api/routes/analytics.py` (export endpoints)

```diff
+from api.middleware.rate_limit import limiter, EXPORT_LIMIT
+from starlette.requests import Request

 @router.get("/analytics/export/products")
+@limiter.limit(EXPORT_LIMIT)
-def export_products():
+def export_products(request: Request):
     ...

 @router.get("/analytics/export/prices/{product_id}")
+@limiter.limit(EXPORT_LIMIT)
-def export_product_prices(product_id: int):
+def export_product_prices(request: Request, product_id: int):
     ...
```

#### `backend/api/routes/ingestion.py`

```diff
+from api.middleware.rate_limit import limiter, INGESTION_LIMIT
+from starlette.requests import Request

 @router.post("/api/ingestions")
+@limiter.limit(INGESTION_LIMIT)
-def submit_ingestion(body: IngestionSubmit):
+def submit_ingestion(request: Request, body: IngestionSubmit):
     ...
```

### 2.5 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_GLOBAL` | `200/minute` | Default limit for all endpoints |
| `RATE_LIMIT_ADMIN` | `10/minute` | Admin read endpoints |
| `RATE_LIMIT_DESTRUCTIVE` | `3/hour` | Reset/wipe endpoints |
| `RATE_LIMIT_EXPORT` | `10/minute` | CSV/JSON export endpoints |
| `RATE_LIMIT_INGESTION` | `30/minute` | Crawler data submission |
| `RATE_LIMIT_STORAGE` | `memory://` | Backend for rate counters (`redis://host:6379/1` for production) |

---

## 3. Bind Address Restriction

**Audit Refs**: Code Audit Issue 13, Arch Audit Issue 4
**Risk Addressed**: Backend on `0.0.0.0` exposes admin panel to all network interfaces

### 3.1 Change `backend/main.py`

```diff
 if __name__ == "__main__":
     from config import settings
-    uvicorn.run("main:app", host="0.0.0.0", port=settings.API_PORT, reload=settings.DEBUG)
+    uvicorn.run(
+        "main:app",
+        host=settings.API_HOST,
+        port=settings.API_PORT,
+        reload=settings.DEBUG,
+    )
```

### 3.2 Add `API_HOST` to `backend/config.py`

```diff
 class Settings:
     DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db)
     REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
     DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
+    API_HOST: str = os.getenv("DB_ADMIN_HOST", "127.0.0.1")
     API_PORT: int = int(os.getenv("DB_ADMIN_PORT", "8002"))
```

### 3.3 Docker Override

When running inside Docker, the container needs to bind to `0.0.0.0` for Docker networking to work. Set the env var in `docker-compose.yml`:

```yaml
services:
  db-admin:
    environment:
      DB_ADMIN_HOST: "0.0.0.0"  # Required inside container
```

### 3.4 Frontend Vite Dev Server (optional hardening)

The Vite dev server also accepts all connections by default. For local-only development:

```diff
 // frontend/vite.config.js
 export default defineConfig({
   plugins: [react()],
   server: {
     port: 5175,
+    host: '127.0.0.1',
     proxy: {
```

### 3.5 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_ADMIN_HOST` | `127.0.0.1` | Bind address — `127.0.0.1` for local, `0.0.0.0` for Docker |

---

## 4. Config Security — Secrets to Environment Variables

**Audit Refs**: Arch Audit Issue 12
**Risk Addressed**: Hardcoded `changeme` password in `alembic.ini`, credentials in version control

### 4.1 Fix `backend/alembic.ini`

Remove the hardcoded connection string. Alembic's `env.py` already reads `DATABASE_URL` from the environment — the `alembic.ini` value is only the fallback.

```diff
 # alembic.ini — line ~89
-sqlalchemy.url = postgresql://walletsavior:changeme@localhost:5432/walletsavior
+# Connection URL is set dynamically in migrations/env.py from DATABASE_URL env var.
+# DO NOT hardcode credentials here.
+sqlalchemy.url =
```

### 4.2 Harden `backend/storage/migrations/env.py`

Ensure the env.py **requires** `DATABASE_URL` when not using SQLite:

```diff
 # env.py — around line 17
 database_url = os.getenv("DATABASE_URL")
 if database_url:
     config.set_main_option("sqlalchemy.url", database_url)
+else:
+    url = config.get_main_option("sqlalchemy.url")
+    if url and "changeme" in url:
+        raise RuntimeError(
+            "SECURITY: Default credentials detected in alembic.ini. "
+            "Set DATABASE_URL environment variable."
+        )
```

### 4.3 Add CORS Origins to Environment

```diff
 # backend/config.py
 class Settings:
+    CORS_ORIGINS: list[str] = [
+        o.strip()
+        for o in os.getenv(
+            "CORS_ALLOWED_ORIGINS",
+            "http://localhost:5175,http://127.0.0.1:5175",
+        ).split(",")
+    ]
```

Update `backend/api/app.py`:

```diff
     app.add_middleware(
         CORSMiddleware,
-        allow_origins=["*"],
+        allow_origins=settings.CORS_ORIGINS,
         allow_credentials=True,
-        allow_methods=["*"],
-        allow_headers=["*"],
+        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
+        allow_headers=["Content-Type", "Authorization"],
     )
```

### 4.4 Reject Default Credentials at Startup

Add a startup validation in `backend/main.py`:

```python
@app.on_event("startup")
async def _validate_config():
    """Block startup if insecure defaults are detected in production."""
    if not settings.DEBUG:
        db_url = settings.DATABASE_URL
        if "changeme" in db_url:
            raise RuntimeError(
                "SECURITY: Default database password detected. "
                "Set a strong DATABASE_URL for production."
            )
```

### 4.5 `.env.example` Template

Create `backend/.env.example` (committed to repo as documentation):

```bash
# ─── DB Admin Backend Environment Variables ───
# Copy to .env and fill in real values. NEVER commit .env to git.

# Database (required for production)
DATABASE_URL=postgresql://walletsavior:<STRONG_PASSWORD>@db:5432/walletsavior

# Application
DEBUG=false
DB_ADMIN_HOST=127.0.0.1
DB_ADMIN_PORT=8002

# CORS — comma-separated allowed origins
CORS_ALLOWED_ORIGINS=http://localhost:5175,http://127.0.0.1:5175

# Rate Limiting
RATE_LIMIT_GLOBAL=200/minute
RATE_LIMIT_ADMIN=10/minute
RATE_LIMIT_DESTRUCTIVE=3/hour
RATE_LIMIT_EXPORT=10/minute
RATE_LIMIT_INGESTION=30/minute
RATE_LIMIT_STORAGE=memory://
# For production with Redis: RATE_LIMIT_STORAGE=redis://redis:6379/1

# Redis (optional — used for rate limit storage)
REDIS_URL=redis://localhost:6379/0

# Connection Pool (PostgreSQL only)
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800

# Backup
BACKUP_DIR=./backups
BACKUP_RETENTION_COUNT=30
```

### 4.6 Add `.env` to `.gitignore`

```diff
 # .gitignore (project root or packages/db-admin/)
+.env
+*.db
```

### 4.7 Complete Environment Variable Registry

| Variable | Default | Where Used | Security Level |
|----------|---------|------------|----------------|
| `DATABASE_URL` | `sqlite:///walletguardian.db` | `config.py`, `migrations/env.py` | **CRITICAL** |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5175,...` | `config.py` → `app.py` | **HIGH** |
| `DB_ADMIN_HOST` | `127.0.0.1` | `config.py` → `main.py` | **HIGH** |
| `DB_ADMIN_PORT` | `8002` | `config.py` → `main.py` | LOW |
| `DEBUG` | `false` | `config.py` | **HIGH** |
| `REDIS_URL` | `redis://localhost:6379/0` | `config.py` | MEDIUM |
| `RATE_LIMIT_*` | (see §2.5) | `rate_limit.py` | LOW |
| `BACKUP_DIR` | `./backups` | `backup.py` | MEDIUM |
| `BACKUP_RETENTION_COUNT` | `30` | `backup.py` | LOW |

---

## 5. API Docs Protection

**Audit Refs**: Code Audit Issue 16, Arch Audit Issue 17
**Risk Addressed**: Swagger UI (`/docs`), ReDoc (`/redoc`), OpenAPI JSON (`/openapi.json`) expose full attack surface in production

### 5.1 Conditional Docs in `backend/api/app.py`

```diff
+from config import settings

 def create_app() -> FastAPI:
     app = FastAPI(
         title="WalletSavior DB 관리",
         description="데이터베이스 관리 API",
         version="0.1.0",
+        docs_url="/docs" if settings.DEBUG else None,
+        redoc_url="/redoc" if settings.DEBUG else None,
+        openapi_url="/openapi.json" if settings.DEBUG else None,
     )
```

### 5.2 Behavior

| Mode | `/docs` | `/redoc` | `/openapi.json` |
|------|---------|----------|-----------------|
| `DEBUG=true` | ✅ Swagger UI | ✅ ReDoc | ✅ Schema |
| `DEBUG=false` | 404 | 404 | 404 |

### 5.3 Production Verification

```bash
# With DEBUG=false:
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/docs
# Expected: 404

curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8002/openapi.json
# Expected: 404

# Health endpoint still works:
curl -s http://127.0.0.1:8002/health
# Expected: {"status":"ok","service":"db-admin"}
```

---

## 6. Backup Strategy

**Audit Refs**: Arch Audit Issue 11
**Risk Addressed**: No backup mechanism; destructive admin ops perform permanent hard deletes with no recovery path

### 6.1 New File: `backend/services/backup.py`

```python
"""
SQLite and PostgreSQL backup service.
Provides on-demand and pre-destructive-operation backups.
"""
import os
import shutil
import sqlite3
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
RETENTION_COUNT = int(os.getenv("BACKUP_RETENTION_COUNT", "30"))


def _ensure_backup_dir() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR


def _timestamp() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def backup_sqlite(db_path: str, *, reason: str = "manual") -> str:
    """
    Create a hot backup of a SQLite database using the backup API.
    Returns the path to the backup file.
    """
    _ensure_backup_dir()
    ts = _timestamp()
    backup_name = f"walletguardian_{reason}_{ts}.db"
    backup_path = BACKUP_DIR / backup_name

    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(str(backup_path))
    try:
        src.backup(dst)
        logger.info("SQLite backup created: %s (%s)", backup_path, reason)
    finally:
        dst.close()
        src.close()

    _rotate_backups()
    return str(backup_path)


def backup_postgresql(database_url: str, *, reason: str = "manual") -> str:
    """
    Create a pg_dump backup of a PostgreSQL database.
    Returns the path to the backup file.
    """
    _ensure_backup_dir()
    ts = _timestamp()
    backup_name = f"walletguardian_{reason}_{ts}.sql.gz"
    backup_path = BACKUP_DIR / backup_name

    parsed = urlparse(database_url)
    env = os.environ.copy()
    env["PGPASSWORD"] = parsed.password or ""

    cmd = [
        "pg_dump",
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "walletsavior",
        "-d", parsed.path.lstrip("/"),
        "--format=custom",
        "--compress=6",
        "-f", str(backup_path),
    ]

    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.error("pg_dump failed: %s", result.stderr)
        raise RuntimeError(f"pg_dump failed: {result.stderr}")

    logger.info("PostgreSQL backup created: %s (%s)", backup_path, reason)
    _rotate_backups()
    return str(backup_path)


def create_backup(database_url: str, *, reason: str = "manual") -> str:
    """
    Auto-detect database type and create appropriate backup.
    """
    if database_url.startswith("sqlite"):
        db_path = database_url.replace("sqlite:///", "")
        return backup_sqlite(db_path, reason=reason)
    elif database_url.startswith("postgresql"):
        return backup_postgresql(database_url, reason=reason)
    else:
        raise ValueError(f"Unsupported database type: {database_url}")


def _rotate_backups():
    """Remove oldest backups beyond RETENTION_COUNT."""
    _ensure_backup_dir()
    backups = sorted(BACKUP_DIR.glob("walletguardian_*"), key=os.path.getmtime)
    while len(backups) > RETENTION_COUNT:
        oldest = backups.pop(0)
        oldest.unlink()
        logger.info("Rotated old backup: %s", oldest)


def list_backups() -> list[dict]:
    """List all available backups with metadata."""
    _ensure_backup_dir()
    result = []
    for f in sorted(BACKUP_DIR.glob("walletguardian_*"), key=os.path.getmtime, reverse=True):
        stat = f.stat()
        result.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result
```

### 6.2 Integrate Pre-Destructive Backup into Admin Routes

**File**: `backend/api/routes/admin.py`

```diff
+from services.backup import create_backup
+from config import settings
+import logging
+
+logger = logging.getLogger(__name__)

 @router.post("/admin/reset-all")
 def reset_all(body: ResetAllRequest):
+    # Mandatory backup before destructive operation
+    try:
+        backup_path = create_backup(
+            settings.DATABASE_URL, reason="pre_reset_all"
+        )
+        logger.warning("Pre-reset backup created: %s", backup_path)
+    except Exception as e:
+        logger.error("Backup failed, aborting reset: %s", e)
+        raise HTTPException(
+            status_code=500,
+            detail="백업 실패로 리셋이 중단되었습니다.",
+        )
+
     # ... existing reset logic ...
```

Apply the same pattern to `reset-products` and `reset-source` endpoints.

### 6.3 Backup Management Endpoints

Add to `backend/api/routes/admin.py`:

```python
from services.backup import create_backup, list_backups


@router.post("/admin/backup")
def create_manual_backup(request: Request):
    """Create an on-demand database backup."""
    backup_path = create_backup(settings.DATABASE_URL, reason="manual")
    return {"status": "ok", "backup": backup_path}


@router.get("/admin/backups")
def get_backups(request: Request):
    """List all available backups."""
    return {"backups": list_backups()}
```

### 6.4 Backup Directory

- **Location**: `backend/backups/` (configurable via `BACKUP_DIR`)
- **Naming**: `walletguardian_{reason}_{YYYYMMDD_HHMMSS}.db` (SQLite) or `.sql.gz` (PostgreSQL)
- **Retention**: Last 30 backups (configurable via `BACKUP_RETENTION_COUNT`)

### 6.5 Add to `.gitignore`

```diff
+backups/
```

---

## 7. Integration & Startup Order

### 7.1 Final `backend/api/app.py` (Complete)

The middleware stack in the `create_app()` function should follow this order:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi.errors import RateLimitExceeded

from config import settings
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.middleware.rate_limit import limiter, rate_limit_exceeded_handler


def create_app() -> FastAPI:
    app = FastAPI(
        title="WalletSavior DB 관리",
        description="데이터베이스 관리 API",
        version="0.1.0",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        openapi_url="/openapi.json" if settings.DEBUG else None,
    )

    # ── Rate Limiting ──
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

    # ── Security Headers (CSP, X-Frame-Options, etc.) ──
    app.add_middleware(
        SecurityHeadersMiddleware,
        enable_hsts=not settings.DEBUG,
    )

    # ── Response Compression ──
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # ── CORS — restricted origins ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    # ── Routers ──
    from api.routes.products import router as products_router
    from api.routes.prices import router as prices_router
    from api.routes.categories import router as categories_router
    from api.routes.keywords import router as keywords_router
    from api.routes.analytics import router as analytics_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.admin import router as admin_router

    app.include_router(products_router, prefix="/api")
    app.include_router(prices_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(keywords_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(ingestion_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "db-admin"}

    # ── Startup validation ──
    @app.on_event("startup")
    async def _validate_config():
        if not settings.DEBUG:
            if "changeme" in settings.DATABASE_URL:
                raise RuntimeError(
                    "SECURITY: Default database password detected. "
                    "Set a strong DATABASE_URL for production."
                )

    return app
```

### 7.2 Final `backend/config.py` (Complete)

```python
"""DB 관리 백엔드 설정 — SQLite 기본, 환경변수로 PostgreSQL 전환 가능"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

_default_db = f"sqlite:///{BASE_DIR / 'walletguardian.db'}"


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db)
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
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))


settings = Settings()
```

### 7.3 Final `backend/main.py` (Complete)

```python
"""DB 관리 백엔드 진입점"""
import uvicorn
from api.app import create_app

app = create_app()

if __name__ == "__main__":
    from config import settings

    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=settings.DEBUG,
    )
```

### 7.4 New Files Checklist

| File | Purpose |
|------|---------|
| `backend/api/middleware/__init__.py` | Package init (empty) |
| `backend/api/middleware/security_headers.py` | CSP, HSTS, X-Frame-Options |
| `backend/api/middleware/rate_limit.py` | slowapi limiter config |
| `backend/services/backup.py` | SQLite/PostgreSQL backup service |
| `backend/.env.example` | Environment variable template |

### 7.5 Modified Files Checklist

| File | Changes |
|------|---------|
| `backend/api/app.py` | Add security headers, rate limiting, restricted CORS, conditional docs |
| `backend/config.py` | Add `API_HOST`, `CORS_ORIGINS` |
| `backend/main.py` | Use `settings.API_HOST` instead of `0.0.0.0` |
| `backend/alembic.ini` | Remove hardcoded password |
| `backend/storage/migrations/env.py` | Reject default credentials |
| `backend/requirements.txt` | Add `slowapi`, `limits` |
| `backend/api/routes/admin.py` | Pre-destructive backups, rate limits, backup endpoints |
| `backend/api/routes/prices.py` | Export rate limit |
| `backend/api/routes/analytics.py` | Export rate limit |
| `backend/api/routes/ingestion.py` | Ingestion rate limit |

---

## 8. Test Plan

### 8.1 Security Headers Tests

**File**: `backend/tests/test_security_headers.py`

```python
"""Tests for security headers middleware."""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_x_content_type_options(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_x_frame_options(client):
    r = client.get("/health")
    assert r.headers["X-Frame-Options"] == "DENY"


def test_content_security_policy(client):
    r = client.get("/health")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_referrer_policy(client):
    r = client.get("/health")
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_api_cache_control(client):
    r = client.get("/api/dashboard/stats")
    assert r.headers.get("Cache-Control") == "no-store"


def test_hsts_disabled_in_debug(client, monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    app = create_app()
    c = TestClient(app)
    r = c.get("/health")
    assert "Strict-Transport-Security" not in r.headers


def test_hsts_enabled_in_production(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    app = create_app()
    c = TestClient(app)
    r = c.get("/health")
    assert "Strict-Transport-Security" in r.headers
```

### 8.2 Rate Limiting Tests

**File**: `backend/tests/test_rate_limiting.py`

```python
"""Tests for rate limiting middleware."""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_GLOBAL", "5/minute")
    app = create_app()
    return TestClient(app)


def test_rate_limit_returns_429(client):
    """Exceed global rate limit and verify 429 response."""
    for _ in range(5):
        r = client.get("/health")
        assert r.status_code == 200

    r = client.get("/health")
    assert r.status_code == 429
    body = r.json()
    assert "요청 횟수 제한" in body["detail"]


def test_rate_limit_response_is_json(client):
    """429 response must be JSON, not plain text."""
    for _ in range(6):
        r = client.get("/health")
    assert r.headers["content-type"] == "application/json"


def test_destructive_endpoint_strict_limit(monkeypatch):
    """Admin reset endpoints have tighter limits."""
    monkeypatch.setenv("RATE_LIMIT_DESTRUCTIVE", "1/hour")
    app = create_app()
    c = TestClient(app)

    # First request should succeed (or 400 due to missing body — not 429)
    r = c.post("/api/admin/reset-all", json={"confirm": "wrong"})
    assert r.status_code != 429

    # Second request should be rate-limited
    r = c.post("/api/admin/reset-all", json={"confirm": "wrong"})
    assert r.status_code == 429
```

### 8.3 Bind Address Tests

**File**: `backend/tests/test_bind_address.py`

```python
"""Tests for bind address configuration."""
import os


def test_default_host_is_localhost():
    """Default bind address must be 127.0.0.1, not 0.0.0.0."""
    # Clear any override
    os.environ.pop("DB_ADMIN_HOST", None)
    # Re-import to get fresh defaults
    import importlib
    import config
    importlib.reload(config)
    assert config.settings.API_HOST == "127.0.0.1"


def test_host_override_from_env(monkeypatch):
    """DB_ADMIN_HOST env var overrides the default."""
    monkeypatch.setenv("DB_ADMIN_HOST", "0.0.0.0")
    import importlib
    import config
    importlib.reload(config)
    assert config.settings.API_HOST == "0.0.0.0"
```

### 8.4 API Docs Protection Tests

**File**: `backend/tests/test_api_docs.py`

```python
"""Tests for API docs protection in production."""
import pytest
from fastapi.testclient import TestClient


def test_docs_hidden_in_production(monkeypatch):
    monkeypatch.setenv("DEBUG", "false")
    from api.app import create_app
    app = create_app()
    c = TestClient(app)
    assert c.get("/docs").status_code == 404
    assert c.get("/redoc").status_code == 404
    assert c.get("/openapi.json").status_code == 404


def test_docs_available_in_debug(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    from api.app import create_app
    app = create_app()
    c = TestClient(app)
    assert c.get("/docs").status_code == 200
    assert c.get("/openapi.json").status_code == 200
```

### 8.5 Backup Service Tests

**File**: `backend/tests/test_backup.py`

```python
"""Tests for database backup service."""
import os
import sqlite3
import pytest
from pathlib import Path
from services.backup import (
    backup_sqlite,
    list_backups,
    _rotate_backups,
    BACKUP_DIR,
)


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, val TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'hello')")
    conn.commit()
    conn.close()
    return str(db_path)


@pytest.fixture(autouse=True)
def set_backup_dir(tmp_path, monkeypatch):
    """Use temporary directory for backups during tests."""
    backup_dir = tmp_path / "backups"
    monkeypatch.setenv("BACKUP_DIR", str(backup_dir))
    # Force module to re-read env
    import services.backup as bmod
    bmod.BACKUP_DIR = backup_dir
    return backup_dir


def test_sqlite_backup_creates_file(temp_db):
    path = backup_sqlite(temp_db, reason="test")
    assert os.path.exists(path)
    assert "test" in os.path.basename(path)


def test_sqlite_backup_is_valid(temp_db):
    path = backup_sqlite(temp_db, reason="test")
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT val FROM test WHERE id=1").fetchone()
    conn.close()
    assert rows[0] == "hello"


def test_list_backups_returns_metadata(temp_db):
    backup_sqlite(temp_db, reason="test")
    backups = list_backups()
    assert len(backups) == 1
    assert "filename" in backups[0]
    assert "size_bytes" in backups[0]
    assert "created_at" in backups[0]


def test_rotation_removes_old_backups(temp_db, monkeypatch):
    import services.backup as bmod
    monkeypatch.setattr(bmod, "RETENTION_COUNT", 2)
    backup_sqlite(temp_db, reason="old1")
    backup_sqlite(temp_db, reason="old2")
    backup_sqlite(temp_db, reason="new1")
    assert len(list_backups()) == 2
```

### 8.6 Config Security Tests

**File**: `backend/tests/test_config_security.py`

```python
"""Tests for configuration security."""
import os
import pytest


def test_cors_origins_not_wildcard():
    """CORS must not be configured with wildcard in default settings."""
    from config import settings
    assert "*" not in settings.CORS_ORIGINS


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://admin.example.com")
    import importlib
    import config
    importlib.reload(config)
    assert config.settings.CORS_ORIGINS == ["https://admin.example.com"]


def test_alembic_ini_no_hardcoded_password():
    """alembic.ini must not contain plaintext passwords."""
    ini_path = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    if os.path.exists(ini_path):
        content = open(ini_path).read()
        assert "changeme" not in content, "alembic.ini contains default password"


def test_production_rejects_default_password(monkeypatch):
    """Startup must fail if 'changeme' password detected in production."""
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:changeme@localhost/db",
    )
    from api.app import create_app
    app = create_app()

    from fastapi.testclient import TestClient
    with pytest.raises(RuntimeError, match="SECURITY"):
        with TestClient(app):
            pass
```

### 8.7 Manual Verification Checklist

```
□ Start server with DEBUG=false
  □ GET /docs → 404
  □ GET /redoc → 404
  □ GET /openapi.json → 404
  □ GET /health → 200 with security headers
  □ Response includes X-Content-Type-Options: nosniff
  □ Response includes X-Frame-Options: DENY
  □ Response includes Content-Security-Policy
  □ Response includes Strict-Transport-Security

□ Start server with DEBUG=true
  □ GET /docs → 200 (Swagger UI)
  □ No HSTS header (development mode)

□ Rate limiting
  □ Send 201 requests/minute to /health → last request returns 429
  □ Send 4 POST /api/admin/reset-all in 1 hour → 4th returns 429
  □ 429 response body is JSON with Korean error message

□ Bind address
  □ Default start → only accessible from 127.0.0.1
  □ DB_ADMIN_HOST=0.0.0.0 → accessible from LAN (Docker use case)

□ Backup
  □ POST /api/admin/backup → creates file in ./backups/
  □ GET /api/admin/backups → lists backup files
  □ POST /api/admin/reset-all → creates pre_reset_all backup before deletion
  □ Creating 31+ backups → oldest auto-rotated

□ Config
  □ alembic.ini has no 'changeme' string
  □ Server with DATABASE_URL=...changeme... and DEBUG=false → startup fails
  □ CORS_ALLOWED_ORIGINS=https://custom.com → only that origin accepted
```

---

## 9. Rollback Plan

Each change is independently revertible:

| Change | Rollback |
|--------|----------|
| Security headers middleware | Remove `SecurityHeadersMiddleware` from `app.py` |
| Rate limiting | Remove `slowapi` from requirements, remove limiter from `app.py` and route decorators |
| Bind address | Set `DB_ADMIN_HOST=0.0.0.0` in environment |
| CORS restriction | Set `CORS_ALLOWED_ORIGINS=*` (not recommended) |
| API docs protection | Set `DEBUG=true` or revert FastAPI constructor args |
| Backup service | Remove backup imports from `admin.py`; backup files are inert |
| alembic.ini cleanup | Restore the connection string (not recommended) |

---

> **Next Steps After This Spec**:
> - Authentication & Authorization (separate spec — most critical remaining gap)
> - Audit Logging middleware
> - Input validation hardening (LIKE escaping, payload size limits)
> - TLS/HTTPS setup with nginx reverse proxy
