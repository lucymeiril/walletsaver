# DB-Admin: Error Recovery, Health Checks & Logging — Implementation Spec

> **Scope:** `packages/db-admin/backend`
> **Input Audits:** `db-admin-stability-audit.md` (H-1, H-2, L-4, M-5, M-8), `db-admin-concurrency-audit.md` (§7, §8)
> **Status:** Ready for implementation

---

## Table of Contents

1. [Health Check Endpoint](#1-health-check-endpoint)
2. [Structured Logging](#2-structured-logging)
3. [Background Task Error Handling](#3-background-task-error-handling)
4. [Graceful Shutdown](#4-graceful-shutdown)
5. [Retry Logic](#5-retry-logic-for-transient-db-errors)
6. [Disk Space Monitor](#6-disk-space-monitor)
7. [New Dependencies](#7-new-dependencies)
8. [File Change Summary](#8-file-change-summary)
9. [Testing Plan](#9-testing-plan)
10. [Rollout Checklist](#10-rollout-checklist)

---

## 1. Health Check Endpoint

### Audit Refs
- **H-1** (stability audit): Health endpoint always returns `"ok"` — never verifies DB connectivity.
- **§8.1** (concurrency audit): No DB connectivity check on startup or at runtime.

### Current State

**File:** `api/app.py`, lines ~140–143

```python
@app.get("/health")
@limiter.limit(GLOBAL_LIMIT)
async def health(request: Request):
    return {"status": "ok", "service": "db-admin"}
```

Returns `200 OK` unconditionally. Load balancers and orchestrators cannot detect a degraded instance.

### Target State

Replace with a multi-probe health check that reports:
- **DB connectivity** — execute `SELECT 1` against the live engine
- **Disk space** — free bytes on the DB file's partition
- **Memory usage** — current RSS of the Python process
- **Uptime** — seconds since process start

Return `200` when all probes pass, `503` when any critical probe fails.

### Implementation

**File:** `api/health.py` *(new file)*

```python
"""Health check probes for the db-admin backend."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import psutil
import shutil
from sqlalchemy import text

logger = logging.getLogger("health")

_START_TIME = time.monotonic()

# Thresholds (configurable via env)
DISK_WARN_MB = int(os.getenv("HEALTH_DISK_WARN_MB", "500"))
DISK_CRIT_MB = int(os.getenv("HEALTH_DISK_CRIT_MB", "100"))
MEMORY_WARN_MB = int(os.getenv("HEALTH_MEMORY_WARN_MB", "512"))


def _check_db(get_session_fn) -> dict[str, Any]:
    """Probe DB connectivity with a lightweight query."""
    try:
        session = get_session_fn()
        try:
            session.execute(text("SELECT 1"))
            return {"status": "ok"}
        finally:
            session.close()
    except Exception as e:
        logger.error("Health: DB probe failed: %s", e, exc_info=True)
        return {"status": "fail", "error": str(e)}


def _check_disk(path: str) -> dict[str, Any]:
    """Check free disk space on the partition containing *path*."""
    try:
        usage = shutil.disk_usage(path)
        free_mb = usage.free / (1024 * 1024)
        status = "ok"
        if free_mb < DISK_CRIT_MB:
            status = "fail"
        elif free_mb < DISK_WARN_MB:
            status = "warn"
        return {
            "status": status,
            "free_mb": round(free_mb, 1),
            "total_mb": round(usage.total / (1024 * 1024), 1),
            "used_percent": round(usage.used / usage.total * 100, 1),
        }
    except Exception as e:
        logger.error("Health: disk probe failed: %s", e)
        return {"status": "fail", "error": str(e)}


def _check_memory() -> dict[str, Any]:
    """Report process RSS memory usage."""
    try:
        proc = psutil.Process()
        mem = proc.memory_info()
        rss_mb = mem.rss / (1024 * 1024)
        status = "warn" if rss_mb > MEMORY_WARN_MB else "ok"
        return {
            "status": status,
            "rss_mb": round(rss_mb, 1),
            "vms_mb": round(mem.vms / (1024 * 1024), 1),
        }
    except Exception as e:
        logger.error("Health: memory probe failed: %s", e)
        return {"status": "unknown", "error": str(e)}


def run_health_check(get_session_fn, db_path: str) -> tuple[int, dict]:
    """
    Execute all probes and return (http_status_code, payload).

    Returns 200 if all critical probes pass, 503 otherwise.
    """
    db = _check_db(get_session_fn)
    disk = _check_disk(db_path)
    memory = _check_memory()

    uptime_s = round(time.monotonic() - _START_TIME, 1)

    # Overall status: fail if DB or disk is "fail"
    overall = "healthy"
    http_status = 200
    if db["status"] == "fail" or disk["status"] == "fail":
        overall = "unhealthy"
        http_status = 503
    elif db["status"] == "warn" or disk["status"] == "warn" or memory["status"] == "warn":
        overall = "degraded"
        # Still 200 — degraded is operational, just a warning
        http_status = 200

    payload = {
        "status": overall,
        "service": "db-admin",
        "uptime_seconds": uptime_s,
        "checks": {
            "database": db,
            "disk": disk,
            "memory": memory,
        },
    }
    return http_status, payload
```

**File:** `api/app.py` — replace the existing health endpoint:

```python
# At top of create_app(), add import
from api.health import run_health_check

# Replace the existing @app.get("/health") block with:
@app.get("/health")
@limiter.limit(GLOBAL_LIMIT)
async def health(request: Request):
    from services.base import get_session
    from config import settings
    import os

    # Resolve DB file path for disk check
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite"):
        db_path = os.path.dirname(db_url.replace("sqlite:///", ""))
        if not db_path:
            db_path = "."
    else:
        db_path = "."

    status_code, payload = run_health_check(get_session, db_path)
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=payload)
    return payload
```

### Response Format

**200 — Healthy:**
```json
{
  "status": "healthy",
  "service": "db-admin",
  "uptime_seconds": 3721.4,
  "checks": {
    "database": { "status": "ok" },
    "disk": { "status": "ok", "free_mb": 12480.3, "total_mb": 50000.0, "used_percent": 75.0 },
    "memory": { "status": "ok", "rss_mb": 87.2, "vms_mb": 312.5 }
  }
}
```

**503 — Unhealthy (DB down):**
```json
{
  "status": "unhealthy",
  "service": "db-admin",
  "uptime_seconds": 3721.4,
  "checks": {
    "database": { "status": "fail", "error": "OperationalError: unable to open database file" },
    "disk": { "status": "ok", "free_mb": 12480.3, "total_mb": 50000.0, "used_percent": 75.0 },
    "memory": { "status": "ok", "rss_mb": 87.2, "vms_mb": 312.5 }
  }
}
```

### Backward Compatibility

- The endpoint path `/health` does not change.
- The `"status"` field is still present (now `"healthy"` | `"degraded"` | `"unhealthy"` instead of `"ok"`).
- Clients checking `status == "ok"` must be updated to check `status == "healthy"`. Since this is an internal service, this is acceptable.
- Rate limiting remains identical (`GLOBAL_LIMIT`).

---

## 2. Structured Logging

### Audit Refs
- **L-4** (stability audit): Logs are free-form strings, hard to parse in production.
- All 8 files use `logging.getLogger()` but log unstructured messages.
- 2 files (`storage/seed.py`, `scripts/create_admin.py`) use bare `print()`.

### Current State

Logging uses Python's `logging` module with ad-hoc format strings:

```python
# api/app.py
_api_logger.warning("Validation error [%s] %s %s: %s", request_id, ...)

# services/audit.py
logger.info("AUDIT | action=%s entity=%s/%s user=%s ip=%s", ...)

# services/backup.py
logger.info("SQLite backup created: %s (%s)", backup_path, reason)
```

No root logger configuration exists — output goes to stderr with Python defaults.

### Target State

- Configure a **JSON formatter** at the root logger level so all loggers emit structured JSON.
- Each log line includes: `timestamp`, `level`, `logger`, `message`, `request_id` (when available), plus any extra fields.
- **`print()` statements** in `seed.py` and `create_admin.py` are replaced with `logger.info()`.
- Configurable via env var: `LOG_FORMAT=json` (production) or `LOG_FORMAT=text` (development).

### Implementation

**File:** `logging_config.py` *(new file)*

```python
"""Structured logging configuration for db-admin backend."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach extras that callers passed via `extra={...}`
        for key in ("request_id", "action", "entity_type", "entity_id",
                     "user_id", "ip", "method", "path", "status_code",
                     "duration_ms", "error", "component"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable formatter for development."""

    FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"

    def __init__(self):
        super().__init__(fmt=self.FORMAT, datefmt="%Y-%m-%d %H:%M:%S")


def setup_logging() -> None:
    """
    Configure root logger. Call once at application startup.

    Env vars:
      LOG_FORMAT: "json" (default in production) or "text" (default in debug)
      LOG_LEVEL: "DEBUG", "INFO" (default), "WARNING", "ERROR"
    """
    debug = os.getenv("DEBUG", "false").lower() == "true"
    log_format = os.getenv("LOG_FORMAT", "text" if debug else "json")
    log_level = os.getenv("LOG_LEVEL", "DEBUG" if debug else "INFO").upper()

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove any existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
```

**File:** `main.py` — call `setup_logging()` before app creation:

```python
"""DB 관리 백엔드 진입점"""
import uvicorn
from logging_config import setup_logging

setup_logging()

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

**File:** `storage/seed.py` — replace `print()` with `logger`:

```python
# Add at top:
import logging
logger = logging.getLogger("seed")

# Replace all print(...) calls:
#   print("시드 데이터 투입 완료!")  →  logger.info("시드 데이터 투입 완료")
#   print(f"...{count}건")          →  logger.info("...", extra={"count": count})
```

**File:** `scripts/create_admin.py` — same pattern:

```python
import logging
logger = logging.getLogger("scripts.create_admin")

# print(f"Created admin user: {email}")  →  logger.info("Created admin user", extra={"email": email})
```

### JSON Log Sample (Production)

```json
{"timestamp": "2025-07-18T14:32:01.123456+00:00", "level": "INFO", "logger": "audit", "message": "AUDIT | action=DELETE entity=product/42 user=admin@example.com ip=10.0.0.1", "action": "DELETE", "entity_type": "product", "entity_id": "42", "user_id": "admin@example.com", "ip": "10.0.0.1"}
{"timestamp": "2025-07-18T14:32:01.456789+00:00", "level": "ERROR", "logger": "api", "message": "Unhandled error [a1b2c3d4e5f6] POST /api/products: IntegrityError", "request_id": "a1b2c3d4e5f6", "method": "POST", "path": "/api/products", "exception": "Traceback ..."}
```

### Text Log Sample (Development)

```
2025-07-18 14:32:01 [INFO   ] audit: AUDIT | action=DELETE entity=product/42 user=admin@example.com ip=10.0.0.1
2025-07-18 14:32:01 [ERROR  ] api: Unhandled error [a1b2c3d4e5f6] POST /api/products: IntegrityError
```

### Config.py Addition

```python
# Add to Settings class:
LOG_FORMAT: str = os.getenv("LOG_FORMAT", "text" if os.getenv("DEBUG", "false").lower() == "true" else "json")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
```

### Env Var Documentation (`.env.example`)

```
# Logging
LOG_FORMAT=json        # "json" for production, "text" for development
LOG_LEVEL=INFO         # DEBUG, INFO, WARNING, ERROR
```

---

## 3. Background Task Error Handling

### Audit Refs
- **M-8** (stability audit): No lifecycle shutdown handler; in-flight operations interrupted.
- **§8.2** (concurrency audit): No graceful shutdown for DB sessions.
- Current codebase has **zero** `BackgroundTasks` usage — but several routes perform fire-and-forget work (backup rotation, stale data cleanup, audit logging) that should be offloaded.

### Current State

No `BackgroundTasks` are used anywhere. Long-running operations (backup, bulk approve, reset-all) run synchronously in the request handler, blocking the response.

### Target State

1. Create a **safe background task wrapper** that catches and logs all exceptions.
2. Offload non-critical post-response work (backup rotation, stale data cleanup) to background tasks.
3. Ensure background task failures are logged with full context, never silently swallowed.

### Implementation

**File:** `api/background.py` *(new file)*

```python
"""Safe background task utilities for FastAPI."""
from __future__ import annotations

import logging
import functools
from typing import Callable, Any

from fastapi import BackgroundTasks

logger = logging.getLogger("background")


def safe_task(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that wraps a background task function with try/except.
    Logs any exception with full traceback — never lets it propagate
    silently (FastAPI swallows background task exceptions).
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.error(
                "Background task '%s' failed",
                func.__name__,
                exc_info=True,
                extra={"component": "background_task", "task_name": func.__name__},
            )
    return wrapper


def add_safe_task(
    bg_tasks: BackgroundTasks,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Add a task to FastAPI's BackgroundTasks with automatic error wrapping.

    Usage:
        from api.background import add_safe_task

        @router.post("/admin/backup")
        def create_backup(..., background_tasks: BackgroundTasks):
            path = backup_sqlite(db_path, reason="manual")
            add_safe_task(background_tasks, rotate_backups)
            return {"path": path}
    """
    bg_tasks.add_task(safe_task(func), *args, **kwargs)
```

### Migration: Routes That Should Use Background Tasks

| Route | Current Work Done Synchronously | Offload to Background |
|-------|-------------------------------|----------------------|
| `POST /api/admin/backup` | `_rotate_backups()` after backup | Yes — rotation is non-critical |
| `POST /api/admin/reset-*` | Audit log write | No — must be transactional |
| `POST /api/ingestions/bulk-approve` | Categorization of approved items | Yes — can be async |
| `DELETE /api/admin/cleanup-stale` | Stale data deletion across tables | Keep sync — but wrap in retry |

### Example Migration (backup route)

```python
# api/routes/admin.py — backup endpoint

from fastapi import BackgroundTasks
from api.background import add_safe_task
from services.backup import backup_sqlite, _rotate_backups

@router.post("/backup")
@limiter.limit(ADMIN_LIMIT)
def create_backup_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    identity: dict = Depends(require_admin),
):
    path = backup_sqlite(db_path, reason="manual")
    add_safe_task(background_tasks, _rotate_backups)
    return {"path": path}
```

---

## 4. Graceful Shutdown

### Audit Refs
- **M-8** (stability audit): No lifecycle shutdown handler; SIGTERM during bulk operations leaves DB partially modified.
- **§8.2** (concurrency audit): `scoped_session` not explicitly disposed on shutdown.

### Current State

**File:** `api/app.py` — lifespan context manager:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.DEBUG:
        if "changeme" in settings.DATABASE_URL:
            raise RuntimeError("SECURITY: Default database password detected.")
    yield
    # ← No shutdown logic
```

No signal handlers. No engine disposal. No log flushing.

### Target State

1. **Startup:** Verify DB connectivity (fail-fast if unreachable).
2. **Shutdown (lifespan):** Dispose engine pool, flush log handlers.
3. **Signal handlers:** Register `SIGTERM` and `SIGINT` to trigger graceful shutdown flag.

### Implementation

**File:** `api/app.py` — updated lifespan:

```python
import signal
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from config import settings

logger = logging.getLogger("lifecycle")

# Shutdown coordination flag
_shutdown_event = asyncio.Event()


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — initiating graceful shutdown", sig_name)
    _shutdown_event.set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──

    # 1. Security check
    if not settings.DEBUG:
        if "changeme" in settings.DATABASE_URL:
            raise RuntimeError(
                "SECURITY: Default database password detected. "
                "Set a strong DATABASE_URL for production."
            )

    # 2. Register signal handlers
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            # ValueError on Windows when not in main thread
            pass

    # 3. Verify DB connectivity (fail-fast)
    from services.base import get_engine
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Startup: database connection verified")
    except Exception as e:
        logger.critical("Startup: database unreachable — %s", e)
        raise

    # 4. Log startup summary
    logger.info(
        "Startup complete — host=%s port=%s debug=%s",
        settings.API_HOST, settings.API_PORT, settings.DEBUG,
    )

    yield

    # ── Shutdown ──
    logger.info("Shutdown: closing database connections")

    # 5. Dispose engine (closes all pooled connections)
    try:
        engine.dispose()
        logger.info("Shutdown: engine disposed successfully")
    except Exception as e:
        logger.error("Shutdown: engine disposal failed — %s", e)

    # 6. Flush all log handlers
    for handler in logging.root.handlers:
        try:
            handler.flush()
        except Exception:
            pass

    logger.info("Shutdown: complete")
```

### Signal Handling Matrix

| Signal | Source | Behavior |
|--------|--------|----------|
| `SIGTERM` | Docker stop, K8s pod termination | Log + set shutdown flag + uvicorn graceful stop |
| `SIGINT` | Ctrl+C | Same as SIGTERM |
| `SIGKILL` | `kill -9`, OOM killer | Unhandleable — accepted data loss |

### Windows Compatibility Note

`signal.SIGTERM` is not available on Windows. The `try/except (OSError, ValueError)` guard handles this. On Windows, `SIGINT` (Ctrl+C) is the primary shutdown signal. Uvicorn's own signal handling covers the rest.

---

## 5. Retry Logic for Transient DB Errors

### Audit Refs
- **H-2** (stability audit): No retry mechanism. `SQLITE_BUSY` causes immediate 500.
- **§1.2** (concurrency audit): No `busy_timeout` — writers get `SQLITE_BUSY` immediately.
- **C-3** (stability audit): No WAL mode — concurrent writes lock.

### Current State

```python
# services/base.py — every route does:
session = get_session()
try:
    session.add(obj)
    session.commit()     # SQLITE_BUSY → unhandled OperationalError → 500
finally:
    session.close()
```

No retry. No busy_timeout. No WAL mode.

### Target State

1. **PRAGMA-level protection** (first line of defense): `busy_timeout=5000` + `journal_mode=WAL`.
2. **Application-level retry** (second line of defense): decorator for transient errors with exponential backoff.
3. **`pool_pre_ping=True`** on engine to detect stale connections.

### Implementation

**File:** `services/db_retry.py` *(new file)*

```python
"""Retry logic for transient database errors."""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable, Any, TypeVar, ParamSpec

from sqlalchemy.exc import OperationalError

logger = logging.getLogger("db.retry")

P = ParamSpec("P")
T = TypeVar("T")

# SQLite error messages that are transient and retryable
RETRYABLE_MESSAGES = (
    "database is locked",
    "database is busy",
    "disk I/O error",       # transient on NFS/network mounts
    "unable to open database",  # file briefly locked by backup
)

# Default retry config
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 0.1  # seconds
DEFAULT_MAX_DELAY = 2.0   # seconds


def is_retryable(exc: Exception) -> bool:
    """Check if an exception is a transient, retryable DB error."""
    if not isinstance(exc, OperationalError):
        return False
    msg = str(exc).lower()
    return any(pattern in msg for pattern in RETRYABLE_MESSAGES)


def retry_on_db_error(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> Callable:
    """
    Decorator: retry a function on transient DB errors with exponential backoff.

    Usage:
        @retry_on_db_error(max_retries=3)
        def save_product(session, product):
            session.add(product)
            session.commit()
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    if not is_retryable(e) or attempt == max_retries:
                        raise
                    last_exc = e
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        "Transient DB error on %s (attempt %d/%d), "
                        "retrying in %.2fs: %s",
                        func.__name__, attempt + 1, max_retries,
                        delay, e,
                        extra={
                            "component": "db_retry",
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "delay_seconds": delay,
                        },
                    )
                    time.sleep(delay)
            raise last_exc  # unreachable, but satisfies type checker
        return wrapper
    return decorator


def execute_with_retry(
    session,
    stmt,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
):
    """
    Execute a SQLAlchemy statement with retry on transient errors.

    Usage:
        result = execute_with_retry(session, select(Product).where(...))
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return session.execute(stmt)
        except OperationalError as e:
            if not is_retryable(e) or attempt == max_retries:
                raise
            last_exc = e
            delay = min(base_delay * (2 ** attempt), DEFAULT_MAX_DELAY)
            logger.warning(
                "Transient DB error on execute (attempt %d/%d), "
                "retrying in %.2fs: %s",
                attempt + 1, max_retries, delay, e,
            )
            time.sleep(delay)
    raise last_exc
```

**File:** `services/base.py` — add SQLite PRAGMAs + pool_pre_ping:

```python
"""서비스 공통 세션 헬퍼"""
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session

import logging

logger = logging.getLogger("db.session")


@lru_cache(maxsize=1)
def get_engine(url=None):
    if url is None:
        from config import settings
        url = settings.DATABASE_URL
    connect_args = {}
    pool_kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        from sqlalchemy.pool import StaticPool
        pool_kwargs["poolclass"] = StaticPool
    else:
        from config import settings
        pool_kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
    engine = create_engine(url, echo=False, connect_args=connect_args, **pool_kwargs)

    # Set SQLite PRAGMAs on every new connection
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            logger.debug("SQLite PRAGMAs set (WAL, busy_timeout=5000)")

    # Set PostgreSQL statement timeout on every new connection
    if not url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_pg_timeout(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET statement_timeout = '30s'")
            cursor.close()

    return engine


_SessionFactory = None


def get_session(engine=None) -> Session:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=engine or get_engine())
    return _SessionFactory()
```

### Retry Behavior Matrix

| Error | Retryable | Max Wait | After Exhaustion |
|-------|-----------|----------|-----------------|
| `database is locked` | ✅ Yes | 3 attempts, ~0.1s + 0.2s + 0.4s = 0.7s total | Raise `OperationalError` → 500 |
| `database is busy` | ✅ Yes | Same | Raise |
| `UNIQUE constraint failed` | ❌ No | — | Raise `IntegrityError` → 409/422 |
| `no such table` | ❌ No | — | Raise immediately |
| PostgreSQL `connection refused` | ✅ Yes | Same | Raise |
| PostgreSQL `statement timeout` | ❌ No | — | Raise immediately |

### Usage in Routes

```python
# api/routes/products.py — example
from services.db_retry import retry_on_db_error

@router.post("/products", status_code=201)
def create_product(body: ProductCreate, ...):
    session = get_session()
    try:
        @retry_on_db_error(max_retries=3)
        def _do_create():
            p = Product(name=body.name, ...)
            session.add(p)
            session.commit()
            session.refresh(p)
            return p
        p = _do_create()
        return {"id": p.id}
    except OperationalError:
        session.rollback()
        raise HTTPException(503, detail="Database temporarily unavailable. Retry later.")
    finally:
        session.close()
```

---

## 6. Disk Space Monitor

### Audit Refs
- **§7.1** (concurrency audit): No disk-space check before backup.
- **§7.1** (stability audit): If disk is full, `backup()` fails with obscure OS error.

### Current State

**File:** `services/backup.py` — no pre-flight disk check:

```python
def backup_sqlite(db_path: str, *, reason: str = "manual") -> str:
    _ensure_backup_dir()
    # ... directly starts backup without checking disk space
    src.backup(dst)
```

### Target State

1. **Pre-backup check** — refuse to start if free space < 2× DB file size.
2. **Periodic monitoring** — log warnings when disk space drops below thresholds.
3. **Expose in health check** — already covered in §1 (`_check_disk`).

### Implementation

**File:** `services/disk_monitor.py` *(new file)*

```python
"""Disk space monitoring for db-admin backend."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger("disk_monitor")

# Thresholds in MB (same as health.py — single source of truth)
WARN_THRESHOLD_MB = int(os.getenv("DISK_WARN_MB", "500"))
CRITICAL_THRESHOLD_MB = int(os.getenv("DISK_CRIT_MB", "100"))


class InsufficientDiskSpaceError(RuntimeError):
    """Raised when a disk-space pre-flight check fails."""
    def __init__(self, required_mb: float, available_mb: float, path: str):
        self.required_mb = required_mb
        self.available_mb = available_mb
        self.path = path
        super().__init__(
            f"Insufficient disk space at {path}: "
            f"need {required_mb:.1f} MB, have {available_mb:.1f} MB"
        )


def check_disk_space(path: str | Path) -> dict:
    """
    Check disk space at the given path.

    Returns:
        {
            "free_mb": float,
            "total_mb": float,
            "used_percent": float,
            "status": "ok" | "warn" | "critical"
        }
    """
    usage = shutil.disk_usage(str(path))
    free_mb = usage.free / (1024 * 1024)
    total_mb = usage.total / (1024 * 1024)
    used_pct = usage.used / usage.total * 100

    if free_mb < CRITICAL_THRESHOLD_MB:
        status = "critical"
        logger.critical(
            "Disk space CRITICAL: %.1f MB free at %s (threshold: %d MB)",
            free_mb, path, CRITICAL_THRESHOLD_MB,
            extra={"component": "disk_monitor", "free_mb": free_mb},
        )
    elif free_mb < WARN_THRESHOLD_MB:
        status = "warn"
        logger.warning(
            "Disk space LOW: %.1f MB free at %s (threshold: %d MB)",
            free_mb, path, WARN_THRESHOLD_MB,
            extra={"component": "disk_monitor", "free_mb": free_mb},
        )
    else:
        status = "ok"

    return {
        "free_mb": round(free_mb, 1),
        "total_mb": round(total_mb, 1),
        "used_percent": round(used_pct, 1),
        "status": status,
    }


def require_disk_space(path: str | Path, required_mb: float) -> None:
    """
    Pre-flight check: raise InsufficientDiskSpaceError if not enough space.

    Usage:
        require_disk_space(BACKUP_DIR, db_size_mb * 2)
    """
    usage = shutil.disk_usage(str(path))
    free_mb = usage.free / (1024 * 1024)
    if free_mb < required_mb:
        raise InsufficientDiskSpaceError(required_mb, free_mb, str(path))
    logger.debug(
        "Disk space OK: %.1f MB free, %.1f MB required at %s",
        free_mb, required_mb, path,
    )
```

**File:** `services/backup.py` — add pre-flight check:

```python
# Add imports at top:
from services.disk_monitor import require_disk_space, InsufficientDiskSpaceError

def backup_sqlite(db_path: str, *, reason: str = "manual") -> str:
    _ensure_backup_dir()

    # Pre-flight: require 2× the DB file size in free space
    db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    try:
        require_disk_space(BACKUP_DIR, db_size_mb * 2)
    except InsufficientDiskSpaceError:
        logger.error(
            "Backup aborted: insufficient disk space "
            "(need %.1f MB, DB size: %.1f MB)",
            db_size_mb * 2, db_size_mb,
        )
        raise

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
```

**Admin route error handling:**

```python
# api/routes/admin.py — backup endpoint
from services.disk_monitor import InsufficientDiskSpaceError

@router.post("/backup")
@limiter.limit(ADMIN_LIMIT)
def backup_endpoint(request: Request, identity: dict = Depends(require_admin)):
    try:
        path = create_backup(settings.DATABASE_URL, reason="manual")
        return {"backup_path": path}
    except InsufficientDiskSpaceError as e:
        raise HTTPException(
            status_code=507,
            detail=f"디스크 공간 부족: 필요 {e.required_mb:.0f}MB, 사용 가능 {e.available_mb:.0f}MB",
        )
```

---

## 7. New Dependencies

### `requirements.txt` Additions

```
# Existing
fastapi>=0.115.0
uvicorn>=0.34.0
sqlalchemy>=2.0.0
alembic>=1.14.0
psycopg2-binary>=2.9.0
pydantic>=2.0
redis>=5.0.0
slowapi>=0.1.9
limits>=3.0

# New — stability & monitoring
psutil>=5.9.0              # Process memory info for health check
```

### Why Only `psutil`?

| Need | Solution | Why Not External Lib? |
|------|----------|----------------------|
| JSON logging | Custom `JSONFormatter` (57 lines) | `python-json-logger` is 1 class — trivial to inline. No new dep. |
| Retry logic | Custom `retry_on_db_error` decorator | `tenacity` is powerful but overkill. Our retry needs are narrow (one error type, simple backoff). 40 lines vs adding a dependency. |
| Disk space | `shutil.disk_usage()` (stdlib) | No dependency needed |
| Memory info | `psutil.Process().memory_info()` | No stdlib alternative; `psutil` is the standard |
| Health checks | Custom `run_health_check()` | Framework-specific; no generic lib helps |

---

## 8. File Change Summary

### New Files (5)

| File | Purpose | Lines (est.) |
|------|---------|-------------|
| `api/health.py` | Health check probes (DB, disk, memory) | ~100 |
| `api/background.py` | Safe background task wrapper | ~50 |
| `logging_config.py` | JSON/text formatter + root logger setup | ~80 |
| `services/db_retry.py` | Retry decorator + retryable error detection | ~100 |
| `services/disk_monitor.py` | Disk space checks + pre-flight guard | ~80 |

### Modified Files (6)

| File | Change | Risk |
|------|--------|------|
| `main.py` | Add `setup_logging()` call before app import | Low — additive |
| `api/app.py` | Replace health endpoint; update lifespan with startup check + shutdown logic + signal handlers | Medium — lifespan is critical path |
| `services/base.py` | Singleton engine (`@lru_cache`), session factory caching, SQLite PRAGMAs, `pool_pre_ping` | Medium — changes session lifecycle |
| `services/backup.py` | Add disk space pre-flight check | Low — additive guard |
| `storage/seed.py` | Replace `print()` → `logger.info()` | Low — cosmetic |
| `scripts/create_admin.py` | Replace `print()` → `logger.info()` | Low — cosmetic |
| `config.py` | Add `LOG_FORMAT`, `LOG_LEVEL` settings | Low — additive |
| `requirements.txt` | Add `psutil>=5.9.0` | Low — well-known package |

### Untouched Files

All route files (`products.py`, `prices.py`, `categories.py`, etc.) are **not modified** in this spec. The retry decorator and background task wrapper are provided as utilities; route-level adoption is a separate follow-up task.

---

## 9. Testing Plan

### Unit Tests

**File:** `tests/test_health.py` *(new)*

```python
def test_health_db_ok(test_session):
    """Health check returns 200 when DB is reachable."""
    status, payload = run_health_check(lambda: test_session, ".")
    assert status == 200
    assert payload["status"] == "healthy"
    assert payload["checks"]["database"]["status"] == "ok"

def test_health_db_fail():
    """Health check returns 503 when DB is unreachable."""
    def bad_session():
        raise OperationalError("unable to open database", None, None)
    status, payload = run_health_check(bad_session, ".")
    assert status == 503
    assert payload["status"] == "unhealthy"
    assert payload["checks"]["database"]["status"] == "fail"

def test_health_disk_warn(tmp_path, monkeypatch):
    """Health check reports 'warn' when disk space is low."""
    monkeypatch.setenv("HEALTH_DISK_WARN_MB", "999999")
    status, payload = run_health_check(lambda: mock_session, str(tmp_path))
    assert payload["checks"]["disk"]["status"] == "warn"
```

**File:** `tests/test_db_retry.py` *(new)*

```python
def test_retry_succeeds_after_transient_error():
    """Retry decorator succeeds on second attempt after SQLITE_BUSY."""
    call_count = 0
    @retry_on_db_error(max_retries=3, base_delay=0.01)
    def flaky():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise OperationalError("database is locked", None, None)
        return "ok"
    assert flaky() == "ok"
    assert call_count == 2

def test_retry_raises_after_max_attempts():
    """Retry decorator raises after exhausting retries."""
    @retry_on_db_error(max_retries=2, base_delay=0.01)
    def always_fail():
        raise OperationalError("database is locked", None, None)
    with pytest.raises(OperationalError):
        always_fail()

def test_non_retryable_error_not_retried():
    """Non-transient errors raise immediately."""
    @retry_on_db_error(max_retries=3)
    def integrity_error():
        raise IntegrityError("UNIQUE constraint failed", None, None)
    with pytest.raises(IntegrityError):
        integrity_error()
```

**File:** `tests/test_disk_monitor.py` *(new)*

```python
def test_require_disk_space_sufficient():
    """No error when enough space."""
    require_disk_space(".", 1)  # 1 MB — should always pass

def test_require_disk_space_insufficient():
    """Raises InsufficientDiskSpaceError when space is low."""
    with pytest.raises(InsufficientDiskSpaceError):
        require_disk_space(".", 999_999_999)  # 999 TB

def test_check_disk_space_returns_dict():
    result = check_disk_space(".")
    assert "free_mb" in result
    assert "status" in result
    assert result["status"] in ("ok", "warn", "critical")
```

**File:** `tests/test_background.py` *(new)*

```python
def test_safe_task_catches_exception(caplog):
    """safe_task wraps exceptions and logs them."""
    @safe_task
    def exploding_task():
        raise ValueError("boom")

    exploding_task()  # should not raise
    assert "Background task 'exploding_task' failed" in caplog.text

def test_safe_task_passes_through_on_success():
    """safe_task returns result on success."""
    @safe_task
    def good_task():
        return 42
    assert good_task() == 42
```

**File:** `tests/test_logging_config.py` *(new)*

```python
def test_json_formatter_output():
    """JSONFormatter produces valid JSON with required fields."""
    import json as json_mod
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="hello", args=(), exc_info=None,
    )
    output = formatter.format(record)
    parsed = json_mod.loads(output)
    assert parsed["level"] == "INFO"
    assert parsed["message"] == "hello"
    assert "timestamp" in parsed

def test_setup_logging_json(monkeypatch):
    """setup_logging() configures JSON output when LOG_FORMAT=json."""
    monkeypatch.setenv("LOG_FORMAT", "json")
    setup_logging()
    handler = logging.root.handlers[0]
    assert isinstance(handler.formatter, JSONFormatter)
```

### Integration Tests

| Test | Validates |
|------|-----------|
| `test_health_endpoint_integration` | `GET /health` returns 200 with DB probes via TestClient |
| `test_health_503_on_bad_db` | Mock broken engine → 503 response |
| `test_backup_disk_full` | Mock `shutil.disk_usage` with 0 free → 507 from backup endpoint |
| `test_graceful_shutdown` | Send SIGTERM to test process → verify engine disposed, logs flushed |

---

## 10. Rollout Checklist

### Phase 1: Logging & Monitoring (No behavioral changes)

- [ ] Add `logging_config.py`
- [ ] Update `main.py` to call `setup_logging()`
- [ ] Add `LOG_FORMAT` / `LOG_LEVEL` to `config.py` and `.env.example`
- [ ] Replace `print()` in `seed.py` and `create_admin.py`
- [ ] Add `psutil` to `requirements.txt` and run `pip install -r requirements.txt`
- [ ] Run existing test suite — all tests must pass
- [ ] Deploy and verify JSON logs appear in log aggregator

### Phase 2: Health Check & Disk Monitor

- [ ] Add `api/health.py`
- [ ] Add `services/disk_monitor.py`
- [ ] Update health endpoint in `api/app.py`
- [ ] Update `services/backup.py` with pre-flight check
- [ ] Add `DISK_WARN_MB`, `DISK_CRIT_MB`, `HEALTH_MEMORY_WARN_MB` to `.env.example`
- [ ] Run new tests (`test_health.py`, `test_disk_monitor.py`)
- [ ] Deploy and verify `/health` returns detailed JSON

### Phase 3: Retry Logic & Engine Singleton

- [ ] Add `services/db_retry.py`
- [ ] Update `services/base.py` with singleton engine, session factory, PRAGMAs
- [ ] Run full test suite — verify no session leaks
- [ ] Load test: 50 concurrent requests to write endpoints — zero `database is locked` errors
- [ ] Run new tests (`test_db_retry.py`)

### Phase 4: Graceful Shutdown & Background Tasks

- [ ] Update `api/app.py` lifespan with startup check + shutdown disposal
- [ ] Add `api/background.py`
- [ ] Migrate backup rotation to background task
- [ ] Run new tests (`test_background.py`)
- [ ] Test: `docker stop` → verify "Shutdown: complete" in logs
- [ ] Test: Ctrl+C → verify clean shutdown message

### Phase 5: Route-Level Adoption (Follow-Up)

- [ ] Wrap write routes with `retry_on_db_error` decorator
- [ ] Add `session.rollback()` in `except` blocks for all write endpoints
- [ ] Offload non-critical post-response work to `add_safe_task()`
- [ ] Add concurrent write tests

---

## Appendix A: Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_FORMAT` | `text` (debug) / `json` (prod) | Log output format |
| `LOG_LEVEL` | `DEBUG` (debug) / `INFO` (prod) | Minimum log level |
| `HEALTH_DISK_WARN_MB` | `500` | Disk space warning threshold (MB) |
| `HEALTH_DISK_CRIT_MB` | `100` | Disk space critical threshold (MB) |
| `HEALTH_MEMORY_WARN_MB` | `512` | Process memory warning threshold (MB) |
| `DISK_WARN_MB` | `500` | Disk monitor warning threshold (MB) |
| `DISK_CRIT_MB` | `100` | Disk monitor critical threshold (MB) |

## Appendix B: Audit Finding Cross-Reference

| Spec Section | Audit Finding(s) | Severity | Status |
|-------------|-------------------|----------|--------|
| §1 Health Check | H-1, §8.1 | High / Moderate | Addressed |
| §2 Structured Logging | L-4 | Low | Addressed |
| §3 Background Tasks | M-8, §8.2 | Medium / Moderate | Addressed |
| §4 Graceful Shutdown | M-8, §8.2 | Medium / Moderate | Addressed |
| §5 Retry Logic | H-2, §1.2, C-3 | High / Critical | Addressed |
| §6 Disk Monitor | §7.1 (both audits) | Moderate | Addressed |
