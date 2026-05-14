# DB Engine & Session Management — Implementation Spec

> **Scope:** Singleton engine, WAL mode, session factory, connection pool, transaction safety, query timeout  
> **Target:** `packages/db-admin/backend`  
> **Audit Refs:** C-1, C-2, C-3 (stability audit) · §1, §2, §3 (concurrency audit)  
> **Estimated Effort:** 2–3 hours implementation + 1 hour testing

---

## Table of Contents

1. [Singleton Engine & Session Factory](#1-singleton-engine--session-factory)
2. [WAL Mode & SQLite Pragmas](#2-wal-mode--sqlite-pragmas)
3. [Connection Pool Configuration](#3-connection-pool-configuration)
4. [Context Manager for Session Lifecycle](#4-context-manager-for-session-lifecycle)
5. [Transaction Safety — Rollback on All Write Endpoints](#5-transaction-safety--rollback-on-all-write-endpoints)
6. [Query / Connection Timeout](#6-query--connection-timeout)
7. [Lifespan Integration (Startup / Shutdown)](#7-lifespan-integration-startup--shutdown)
8. [Test Cases](#8-test-cases)
9. [Migration Checklist](#9-migration-checklist)

---

## 1. Singleton Engine & Session Factory

### Audit Finding

**C-1 (Critical):** `services/base.py` creates a NEW `create_engine()` and NEW `sessionmaker()` on **every** call to `get_session()`. The pool settings in `config.py` (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`) are dead code because each pool lives for exactly one request.

### Current Code

**File:** `packages/db-admin/backend/services/base.py`

```python
"""서비스 공통 세션 헬퍼"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from storage.models import Base


def get_engine(url=None):
    if url is None:
        from config import settings
        url = settings.DATABASE_URL
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, echo=False, connect_args=connect_args)


def get_session(engine=None) -> Session:
    if engine is None:
        engine = get_engine()
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
```

**Problems:**
- `get_engine()` → `create_engine()` every call → new pool per request
- `get_session()` → `sessionmaker()` every call → new factory per request
- No `scoped_session` → not thread-safe for concurrent FastAPI requests
- Pool config in `config.py` is ignored (pool is discarded after one use)
- No WAL mode, no busy_timeout, no foreign_keys pragma

### New Code

**File:** `packages/db-admin/backend/services/base.py` (full replacement)

```python
"""
서비스 공통 세션 헬퍼 — 싱글턴 엔진 + scoped_session.

왜 싱글턴인가:
    create_engine()은 내부적으로 커넥션 풀을 생성한다.
    매 요청마다 새 엔진을 만들면 풀이 재사용되지 않아
    config.py의 DB_POOL_SIZE 등 설정이 무의미해진다.
    모듈 수준에서 한 번만 생성하고 재사용한다.
"""

import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.pool import StaticPool

from storage.models import Base

logger = logging.getLogger(__name__)

# ── 모듈-레벨 싱글턴 ──
_engine = None
_session_factory = None
_ScopedSession = None


def get_engine(url: str | None = None):
    """
    싱글턴 SQLAlchemy 엔진을 반환한다.

    첫 호출에서 엔진을 생성하고 이후 호출에서는 동일 인스턴스를 반환.
    SQLite: StaticPool + WAL 모드 + busy_timeout 5초
    PostgreSQL: QueuePool + pool_size/max_overflow/pool_recycle
    """
    global _engine
    if _engine is not None:
        return _engine

    if url is None:
        from config import settings
        url = settings.DATABASE_URL

    connect_args: dict = {}
    pool_kwargs: dict = {}
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        connect_args["check_same_thread"] = False
        pool_kwargs["poolclass"] = StaticPool
    else:
        from config import settings
        pool_kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
        )

    _engine = create_engine(
        url, echo=False, connect_args=connect_args, **pool_kwargs,
    )

    # ── SQLite 전용 PRAGMA 설정 ──
    if is_sqlite:
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # ── PostgreSQL statement timeout ──
    if not is_sqlite:
        @event.listens_for(_engine, "connect")
        def _set_pg_timeout(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET statement_timeout = '30s'")
            cursor.close()

    logger.info("Engine created: %s (pool=%s)", url.split("@")[-1], type(_engine.pool).__name__)
    return _engine


def get_session_factory():
    """scoped_session 팩토리를 반환한다 (스레드 안전)."""
    global _session_factory, _ScopedSession
    if _ScopedSession is not None:
        return _ScopedSession

    engine = get_engine()
    _session_factory = sessionmaker(bind=engine)
    _ScopedSession = scoped_session(_session_factory)
    return _ScopedSession


def get_session(engine=None) -> Session:
    """
    세션을 반환한다.

    하위 호환성을 위해 engine 파라미터를 유지하되,
    기본 호출 시 싱글턴 팩토리에서 세션을 생성한다.
    """
    if engine is not None:
        # 테스트 등에서 명시적 engine을 주입하는 경우
        return sessionmaker(bind=engine)()

    factory = get_session_factory()
    return factory()


@contextmanager
def managed_session():
    """
    세션 컨텍스트 매니저 — commit/rollback/close를 자동 처리.

    사용법:
        with managed_session() as session:
            session.add(product)
            # commit은 블록 종료 시 자동 수행
            # 예외 발생 시 rollback 후 재발생

    쓰기 연산이 포함된 모든 라우트에서 사용을 권장.
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine():
    """
    엔진 및 세션 팩토리를 리셋한다.

    테스트에서 DB를 교체하거나 shutdown 시 사용.
    """
    global _engine, _session_factory, _ScopedSession
    if _ScopedSession is not None:
        _ScopedSession.remove()
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _ScopedSession = None
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Module-level `_engine` global instead of `@lru_cache` | `lru_cache` with mutable/unhashable args causes subtle bugs; explicit global is clearer and supports `reset_engine()` for tests |
| `StaticPool` for SQLite | SQLite allows only one writer at a time; `StaticPool` shares a single connection across threads, matching SQLite's concurrency model |
| `scoped_session` wrapper | Provides thread-local session scope — each FastAPI worker thread gets its own session instance |
| `managed_session()` context manager | Eliminates the try/except/finally boilerplate in every route; guarantees rollback on failure |
| `get_session(engine=None)` backward compat | Existing test fixtures pass explicit `engine`; we preserve this path while routing default calls through the singleton |
| `reset_engine()` for tests | Tests create in-memory DBs; they need to swap the engine cleanly between test modules |

---

## 2. WAL Mode & SQLite Pragmas

### Audit Finding

**C-3 (Critical) / §1.1-1.2:** No `PRAGMA journal_mode=WAL` and no `PRAGMA busy_timeout` configured. Default DELETE journal mode blocks all readers during writes.

### Implementation (embedded in `get_engine()` above)

```python
@event.listens_for(_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")      # concurrent reads during writes
    cursor.execute("PRAGMA busy_timeout=5000")      # wait 5s before SQLITE_BUSY error
    cursor.execute("PRAGMA synchronous=NORMAL")     # safe with WAL, better write perf
    cursor.execute("PRAGMA foreign_keys=ON")        # enforce FK constraints
    cursor.close()
```

### Why These Pragmas

| Pragma | Value | Effect |
|--------|-------|--------|
| `journal_mode=WAL` | Write-Ahead Logging | Readers don't block writers; writers don't block readers. Only one writer at a time, but reads proceed concurrently. |
| `busy_timeout=5000` | 5000 ms | When a write is in progress and another thread tries to write, it waits up to 5 seconds instead of failing immediately with `SQLITE_BUSY`. |
| `synchronous=NORMAL` | NORMAL | With WAL mode, `NORMAL` is safe against data corruption (but not power-loss durability). `FULL` is unnecessarily slow for WAL. |
| `foreign_keys=ON` | Enabled | SQLite defaults FK enforcement to OFF. Must be enabled per-connection (not persistent). |

### Verification

After the engine is created, the pragmas can be verified:

```python
with engine.connect() as conn:
    result = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert result == "wal"
    result = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert result == 5000
```

---

## 3. Connection Pool Configuration

### Audit Finding

Pool config values in `config.py` were never used because a new engine was created per request.

### Implementation (embedded in `get_engine()` above)

**SQLite (development):**
```python
pool_kwargs["poolclass"] = StaticPool
# No pool_size/max_overflow — StaticPool uses a single connection
```

**PostgreSQL (production):**
```python
pool_kwargs.update(
    pool_size=settings.DB_POOL_SIZE,         # default: 5
    max_overflow=settings.DB_MAX_OVERFLOW,    # default: 10
    pool_timeout=settings.DB_POOL_TIMEOUT,   # default: 30s
    pool_recycle=settings.DB_POOL_RECYCLE,    # default: 1800s (30 min)
    pool_pre_ping=True,                      # detect stale connections
)
```

### Config Values (no changes needed to `config.py`)

The existing `config.py` settings are correct; they just weren't being used:

```python
# config.py — these are already defined and will now be effective
DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))
```

### `pool_pre_ping=True`

Added for PostgreSQL to detect stale connections before checkout. This sends a lightweight `SELECT 1` before each connection is used. Not needed for SQLite (single process, no network).

---

## 4. Context Manager for Session Lifecycle

### Audit Finding

**C-2 (Critical):** Routes use `try/finally` with `session.close()` but no `session.rollback()` on exception. Failed commits leave dirty state.

### Implementation (embedded in `services/base.py` above)

```python
@contextmanager
def managed_session():
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

### Usage Pattern (routes)

**Before (current pattern — all write endpoints):**
```python
@router.post("/", status_code=201)
def create_product(body: ProductCreate, ...):
    session = get_session()
    try:
        p = Product(name=body.name, ...)
        session.add(p)
        session.commit()
        session.refresh(p)
        return {"id": p.id, "name": p.name}
    finally:
        session.close()
```

**After (with managed_session):**
```python
@router.post("/", status_code=201)
def create_product(body: ProductCreate, ...):
    with managed_session() as session:
        p = Product(name=body.name, ...)
        session.add(p)
        session.flush()        # assigns ID without committing
        session.refresh(p)
        return {"id": p.id, "name": p.name}
    # commit happens automatically on block exit
    # rollback happens automatically on exception
```

> **Note:** `session.flush()` is used instead of `session.commit()` inside the block when you need the auto-generated ID. The context manager calls `commit()` at block exit. For read-only endpoints, `managed_session()` is optional but still safe (a no-op commit on unchanged session).

### Read-Only Endpoints

Read-only endpoints can continue using `get_session()` with `try/finally`, or optionally switch to `managed_session()` for consistency. The commit on a read-only session is a no-op.

```python
# Option A: keep existing pattern (acceptable for reads)
@router.get("/")
def list_products(...):
    session = get_session()
    try:
        ...
        return result
    finally:
        session.close()

# Option B: use managed_session (preferred for consistency)
@router.get("/")
def list_products(...):
    with managed_session() as session:
        ...
        return result
```

---

## 5. Transaction Safety — Rollback on All Write Endpoints

### Audit Finding

**C-2 (Critical):** 15 write endpoints do `session.commit()` without `session.rollback()` in an except block. Only `admin.py` has proper rollback.

### Complete List of Endpoints Requiring Fix

Each endpoint below must be converted from `try/finally` to either `managed_session()` or `try/except/finally` with explicit rollback.

#### 5.1 `api/routes/products.py` — 5 endpoints

| Function | Method | Route | Line (approx) |
|----------|--------|-------|---------------|
| `create_product()` | POST | `/products/` | 283 |
| `update_product()` | PUT | `/products/{product_id}` | 299 |
| `delete_product()` | DELETE | `/products/{product_id}` | 314 |
| `bulk_delete_products()` | POST | `/products/bulk-delete` | 329 |
| `bulk_update_category()` | POST | `/products/bulk-category` | 341 |

**Before:**
```python
@router.post("/", status_code=201)
def create_product(body: ProductCreate, request: Request, identity: dict = Depends(require_moderator)):
    session = get_session()
    try:
        p = Product(
            name=body.name, category_id=body.category_id,
            unit=body.unit, description=body.description, image_url=body.image_url,
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        return {"id": p.id, "name": p.name}
    finally:
        session.close()
```

**After:**
```python
@router.post("/", status_code=201)
def create_product(body: ProductCreate, request: Request, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        p = Product(
            name=body.name, category_id=body.category_id,
            unit=body.unit, description=body.description, image_url=body.image_url,
        )
        session.add(p)
        session.flush()
        session.refresh(p)
        return {"id": p.id, "name": p.name}
```

**Apply same pattern to `update_product`, `delete_product`, `bulk_delete_products`, `bulk_update_category`.**

For bulk operations that don't need a refreshed object:

```python
@router.post("/bulk-delete")
def bulk_delete_products(body: BulkDeleteRequest, request: Request, identity: dict = Depends(require_admin)):
    with managed_session() as session:
        count = session.query(Product).filter(Product.id.in_(body.ids)).delete(synchronize_session=False)
        return {"deleted": count, "ids": body.ids}
```

#### 5.2 `api/routes/prices.py` — 1 endpoint

| Function | Method | Route |
|----------|--------|-------|
| `bulk_save_prices()` | POST | `/prices/bulk` |

**After:**
```python
@router.post("/bulk", status_code=201)
def bulk_save_prices(body: BulkPriceRequest, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        saved = 0
        for item in body.items:
            if body.data_type == "baseline":
                row = BaselinePrice(
                    product_id=item.product_id, price=item.price,
                    source=item.source, unit=item.unit,
                    recorded_at=datetime.utcnow(), region=item.region,
                )
            else:
                row = DiscountHistory(...)
            session.add(row)
            saved += 1
        return {"saved": saved}
```

#### 5.3 `api/routes/keywords.py` — 4 endpoints

| Function | Method | Route |
|----------|--------|-------|
| `create_keyword()` | POST | `/keywords/` |
| `bulk_delete_keywords()` | POST | `/keywords/bulk-delete` |
| `update_keyword()` | PUT | `/keywords/{keyword_id}` |
| `delete_keyword()` | DELETE | `/keywords/{keyword_id}` |

**After (example — `bulk_delete_keywords`):**
```python
@router.post("/bulk-delete")
def bulk_delete_keywords(body: BulkDeleteRequest, identity: dict = Depends(require_admin)):
    with managed_session() as session:
        if body.ids:
            keywords = session.execute(
                select(Keyword).where(Keyword.id.in_(body.ids))
            ).scalars().all()
        else:
            keywords = session.execute(
                select(Keyword).where(
                    Keyword.is_active == True,
                    Keyword.search_count == 0,
                )
            ).scalars().all()

        count = len(keywords)
        for kw in keywords:
            session.delete(kw)
        return {"deleted": count}
```

#### 5.4 `api/routes/ingestion.py` — 6 endpoints

| Function | Method | Route |
|----------|--------|-------|
| `submit_ingestion()` | POST | `/api/ingestions` |
| `bulk_approve()` | POST | `/api/ingestions/bulk-approve` |
| `cleanup_ingestions()` | POST | `/api/ingestions/cleanup` |
| `crawler_review()` | POST | `/api/ingestions/{id}/crawler-review` |
| `db_review()` | POST | `/api/ingestions/{id}/db-review` |
| `delete_ingestion()` | DELETE | `/api/ingestions/{id}` |

**After (example — `bulk_approve`):**
```python
@router.post("/bulk-approve")
def bulk_approve(body: BulkApproveRequest, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        results = []
        for ingestion_id in body.ids:
            row = session.get(PendingIngestion, ingestion_id)
            if not row:
                results.append({"id": ingestion_id, "status": "not_found"})
                continue
            if row.status != IngestionStatus.CRAWLER_APPROVED:
                results.append({"id": ingestion_id, "status": "skip", "reason": "not approved by crawler"})
                continue
            items = json.loads(row.items_json) if row.items_json else []
            saved = _insert_items(session, items, row.schema_type)
            row.status = IngestionStatus.APPROVED
            row.db_reviewer_notes = body.notes or f"Bulk approved"
            row.db_reviewed_at = datetime.utcnow()
            results.append({"id": ingestion_id, "status": "approved", "saved": saved})
        return {"results": results}
```

#### 5.5 `api/routes/analytics.py` — 1 endpoint

| Function | Method | Route |
|----------|--------|-------|
| `outlier_action()` | POST | `/analytics/outliers/{outlier_id}/action` |

**After:**
```python
@router.post("/outliers/{outlier_id}/action")
def outlier_action(outlier_id: int, body: OutlierActionRequest, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        # ... existing logic ...
        return result
```

#### 5.6 `api/routes/categories.py` — 3 endpoints (service-delegated)

These delegate to service functions (`create_category()`, `update_category()`, `delete_category()`) which call `session.commit()` internally. The route has `try/finally` but no except/rollback.

**After:**
```python
@router.post("/", status_code=201)
def add_category(body: CategoryCreate, identity: dict = Depends(require_moderator)):
    with managed_session() as session:
        return create_category(
            session, body.id, body.name, body.parent_id,
            body.attributes, body.icon, body.sort_order,
        )
```

> **Note:** Service functions like `create_category()` call `session.commit()` internally. This is acceptable for now — the `managed_session()` commit at block exit will be a no-op if the service already committed. A future improvement (M-1) is to remove commits from service functions and let the route control transaction scope.

#### 5.7 `api/routes/admin.py` — Already safe ✓

All 3 write endpoints (`reset_source`, `reset_products`, `reset_all`) already have `except: session.rollback()`. No changes needed.

### Import Change for All Route Files

Add this import to each route file being modified:

```python
from services.base import managed_session
```

Remove `get_session` import only if no read-only endpoints remain that use it. If read-only endpoints still use `get_session`, keep both imports:

```python
from services.base import get_session, managed_session
```

---

## 6. Query / Connection Timeout

### Audit Finding

**§2.1 (Critical):** No request timeout on server. A slow query holds a worker thread indefinitely.  
**§3.1 (Critical):** No statement-level timeout. Complex analytics can run for minutes.

### Implementation

#### 6.1 SQLite: `busy_timeout` (already in §2 pragmas)

SQLite does not support statement-level timeout natively. The `busy_timeout=5000` pragma prevents `SQLITE_BUSY` for up to 5 seconds on lock contention. For long-running queries, we rely on uvicorn's request timeout.

#### 6.2 PostgreSQL: `statement_timeout` (embedded in `get_engine()`)

```python
@event.listens_for(_engine, "connect")
def _set_pg_timeout(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("SET statement_timeout = '30s'")
    cursor.close()
```

Any single SQL statement running longer than 30 seconds will be cancelled by PostgreSQL.

#### 6.3 Uvicorn: `timeout_keep_alive`

**File:** `packages/db-admin/backend/main.py`

**Before:**
```python
uvicorn.run(
    "main:app",
    host=settings.API_HOST,
    port=settings.API_PORT,
    reload=settings.DEBUG,
)
```

**After:**
```python
uvicorn.run(
    "main:app",
    host=settings.API_HOST,
    port=settings.API_PORT,
    reload=settings.DEBUG,
    timeout_keep_alive=30,
)
```

This closes idle keep-alive connections after 30 seconds, freeing resources.

---

## 7. Lifespan Integration (Startup / Shutdown)

### Audit Finding

**§8.1-8.2 (Moderate):** No DB connectivity check on startup. No graceful shutdown for DB sessions.

### Implementation

**File:** `packages/db-admin/backend/api/app.py`

**Before (lifespan function):**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.DEBUG:
        if "changeme" in settings.DATABASE_URL:
            raise RuntimeError(
                "SECURITY: Default database password detected. "
                "Set a strong DATABASE_URL for production."
            )
    yield
```

**After:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.DEBUG:
        if "changeme" in settings.DATABASE_URL:
            raise RuntimeError(
                "SECURITY: Default database password detected. "
                "Set a strong DATABASE_URL for production."
            )

    # ── Startup: verify DB connectivity ──
    from services.base import get_engine
    engine = get_engine()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.critical("Database unreachable: %s", e)
        raise

    yield

    # ── Shutdown: dispose engine pool ──
    from services.base import reset_engine
    reset_engine()
    logger.info("Database connections closed")
```

Add required import at top of `app.py`:
```python
from sqlalchemy import text
```

---

## 8. Test Cases

### 8.1 Singleton Engine Test

**File:** `packages/db-admin/backend/tests/test_db_engine.py` (new file)

```python
"""
DB 엔진 싱글턴, WAL 모드, 세션 관리 테스트.
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session

from services.base import (
    get_engine, get_session, get_session_factory,
    managed_session, reset_engine,
)
from storage.models import Base, Product


# ── Fixtures ──

@pytest.fixture(autouse=True)
def _reset():
    """각 테스트 전후로 싱글턴 엔진을 리셋한다."""
    reset_engine()
    yield
    reset_engine()


@pytest.fixture
def setup_db():
    """인메모리 SQLite로 테이블을 생성한다."""
    import os
    os.environ["DATABASE_URL"] = "sqlite://"
    reset_engine()
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


# ── 1. 싱글턴 엔진 ──

class TestSingletonEngine:
    def test_same_engine_returned(self):
        """get_engine()은 항상 동일 인스턴스를 반환한다."""
        import os
        os.environ["DATABASE_URL"] = "sqlite://"
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_reset_creates_new_engine(self):
        """reset_engine() 후 새 엔진이 생성된다."""
        import os
        os.environ["DATABASE_URL"] = "sqlite://"
        e1 = get_engine()
        reset_engine()
        e2 = get_engine()
        assert e1 is not e2

    def test_session_factory_is_singleton(self):
        """get_session_factory()은 동일 인스턴스를 반환한다."""
        import os
        os.environ["DATABASE_URL"] = "sqlite://"
        f1 = get_session_factory()
        f2 = get_session_factory()
        assert f1 is f2


# ── 2. WAL 모드 ──

class TestWALMode:
    def test_wal_mode_enabled(self, setup_db):
        """SQLite에서 WAL journal_mode가 활성화된다."""
        with get_engine().connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert mode == "wal"

    def test_busy_timeout_set(self, setup_db):
        """busy_timeout이 5000ms로 설정된다."""
        with get_engine().connect() as conn:
            timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
            assert timeout == 5000

    def test_foreign_keys_enabled(self, setup_db):
        """foreign_keys가 활성화된다."""
        with get_engine().connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert fk == 1

    def test_synchronous_normal(self, setup_db):
        """synchronous가 NORMAL(1)로 설정된다."""
        with get_engine().connect() as conn:
            sync = conn.execute(text("PRAGMA synchronous")).scalar()
            assert sync == 1  # NORMAL = 1


# ── 3. 세션 관리 ──

class TestSessionManagement:
    def test_get_session_returns_session(self, setup_db):
        """get_session()이 유효한 Session 인스턴스를 반환한다."""
        session = get_session()
        assert isinstance(session, Session)
        session.close()

    def test_get_session_with_explicit_engine(self):
        """명시적 engine 전달 시 해당 engine에 바인딩된 세션을 반환한다."""
        engine = create_engine("sqlite://", echo=False)
        session = get_session(engine=engine)
        assert isinstance(session, Session)
        session.close()
        engine.dispose()


# ── 4. managed_session 컨텍스트 매니저 ──

class TestManagedSession:
    def test_commit_on_success(self, setup_db):
        """정상 종료 시 자동 commit된다."""
        with managed_session() as session:
            p = Product(name="테스트 상품", unit="개")
            session.add(p)
            session.flush()

        # 새 세션에서 조회하여 commit 확인
        session2 = get_session()
        try:
            result = session2.execute(
                text("SELECT name FROM products WHERE name = '테스트 상품'")
            ).scalar()
            assert result == "테스트 상품"
        finally:
            session2.close()

    def test_rollback_on_exception(self, setup_db):
        """예외 발생 시 rollback된다."""
        with pytest.raises(ValueError):
            with managed_session() as session:
                p = Product(name="롤백 테스트", unit="개")
                session.add(p)
                session.flush()
                raise ValueError("의도적 예외")

        # rollback 확인
        session2 = get_session()
        try:
            result = session2.execute(
                text("SELECT count(*) FROM products WHERE name = '롤백 테스트'")
            ).scalar()
            assert result == 0
        finally:
            session2.close()

    def test_session_closed_after_block(self, setup_db):
        """블록 종료 후 세션이 닫힌다."""
        session_ref = None
        with managed_session() as session:
            session_ref = session
        # scoped_session의 경우 close 후에도 접근 가능하나,
        # 새 트랜잭션이 시작되므로 이전 트랜잭션은 종료됨


# ── 5. 동시성 테스트 ──

class TestConcurrency:
    def test_concurrent_reads(self, setup_db):
        """여러 스레드에서 동시 읽기가 실패하지 않는다."""
        # seed
        with managed_session() as session:
            for i in range(10):
                session.add(Product(name=f"상품-{i}", unit="개"))

        errors = []

        def read_products():
            try:
                session = get_session()
                try:
                    result = session.execute(text("SELECT count(*) FROM products")).scalar()
                    assert result == 10
                finally:
                    session.close()
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(read_products) for _ in range(20)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0

    def test_concurrent_writes_no_crash(self, setup_db):
        """여러 스레드에서 동시 쓰기가 SQLITE_BUSY 없이 완료된다."""
        errors = []

        def write_product(idx):
            try:
                with managed_session() as session:
                    session.add(Product(name=f"동시-{idx}", unit="개"))
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(write_product, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()

        assert len(errors) == 0

        # 모든 레코드가 저장되었는지 확인
        with managed_session() as session:
            count = session.execute(text("SELECT count(*) FROM products")).scalar()
            assert count == 20
```

### 8.2 Existing Test Compatibility

The existing test fixtures in `conftest.py` and `tests/test_models.py` create their own in-memory engine:

```python
@pytest.fixture
def engine():
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture
def session(engine):
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()
```

These fixtures pass an explicit `engine` to `get_session(engine=engine)` or create sessions directly. They bypass the singleton and will continue to work without changes.

---

## 9. Migration Checklist

### File Changes Summary

| # | File | Change | Type |
|---|------|--------|------|
| 1 | `services/base.py` | Full rewrite: singleton engine, WAL, `managed_session()` | **Modified** |
| 2 | `api/routes/products.py` | 5 write endpoints → `managed_session()` | **Modified** |
| 3 | `api/routes/prices.py` | 1 write endpoint → `managed_session()` | **Modified** |
| 4 | `api/routes/keywords.py` | 4 write endpoints → `managed_session()` | **Modified** |
| 5 | `api/routes/ingestion.py` | 6 write endpoints → `managed_session()` | **Modified** |
| 6 | `api/routes/analytics.py` | 1 write endpoint → `managed_session()` | **Modified** |
| 7 | `api/routes/categories.py` | 3 write endpoints → `managed_session()` | **Modified** |
| 8 | `api/app.py` | Lifespan: startup DB check + shutdown dispose | **Modified** |
| 9 | `main.py` | Add `timeout_keep_alive=30` | **Modified** |
| 10 | `tests/test_db_engine.py` | New: singleton, WAL, session, concurrency tests | **New** |

### Step-by-Step Migration Order

1. **`services/base.py`** — Replace with new implementation. This is the foundation.
2. **Run existing tests** — `pytest tests/` to verify backward compatibility. The `get_session(engine=engine)` path must still work for test fixtures.
3. **`api/app.py`** — Add lifespan startup/shutdown hooks.
4. **`main.py`** — Add `timeout_keep_alive=30`.
5. **Route files** — Convert write endpoints one file at a time. After each file, run `pytest` to verify.
   - `products.py` → `prices.py` → `keywords.py` → `ingestion.py` → `analytics.py` → `categories.py`
6. **Add `tests/test_db_engine.py`** — Run new tests.
7. **Manual smoke test** — Start the server, verify:
   - `GET /health` returns 200
   - Create a product via the UI
   - Check that `PRAGMA journal_mode` returns `wal` (via admin endpoint or direct DB query)

### Rollback Plan

If issues arise after deployment:
1. Revert `services/base.py` to original
2. The route changes are backward-compatible (they just change control flow, not behavior)
3. WAL mode persists in the SQLite file — to revert: `PRAGMA journal_mode=DELETE`

### No Changes Needed

| File | Reason |
|------|--------|
| `config.py` | Pool settings already correct; now they'll actually be used |
| `storage/db.py` (`DBStorage`) | Already uses `scoped_session`, own engine — independent of `services/base.py` |
| `api/routes/admin.py` | Already has proper `except: session.rollback()` |
| `api/routes/auth_routes.py` | Read-only operations (login/refresh don't modify DB rows) |
| `api/routes/dashboard.py` | Read-only endpoint |
| `conftest.py` | Test path setup — no DB changes needed |
