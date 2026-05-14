# DB Admin Sub-Project — Stability & Reliability Audit

**Date:** 2025-01-XX  
**Scope:** `packages/db-admin` (FastAPI backend + React frontend)  
**Auditor:** Automated stability analysis  

---

## Executive Summary

The DB Admin sub-project has a solid foundation with good security hardening (auth, rate limiting, input validation, audit logging). However, several **stability-critical issues** remain around database session management, transaction atomicity, crash recovery, and frontend error resilience. The most urgent problem is the **per-request engine/session factory creation pattern** which creates a new SQLAlchemy engine on every single API call, preventing connection reuse and making the pool configuration dead code.

**Finding Count:** 5 Critical · 7 High · 8 Medium · 5 Low

---

## CRITICAL Severity

### C-1: Engine Created Per Request — Connection Pool is Dead Code

**File:** `services/base.py`  
**Current State:**  
```python
def get_session(engine=None) -> Session:
    if engine is None:
        engine = get_engine()          # creates NEW engine every call
    SessionLocal = sessionmaker(bind=engine)  # creates NEW factory every call
    return SessionLocal()
```
Every API call creates a **new** `create_engine()` → new connection pool → new `sessionmaker` → new `Session`. The pool settings in `config.py` (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE`) are **completely ignored** because each pool lives for exactly one request.

**Risk:**  
- Under concurrency, hundreds of SQLite file handles open simultaneously → `database is locked` errors  
- Connection pool exhaustion is impossible to diagnose because there is no pooling  
- On PostgreSQL (stated as production target), this would open/close TCP connections per request — devastating for latency  

**Fix:**  
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_engine(url=None):
    if url is None:
        from config import settings
        url = settings.DATABASE_URL
    connect_args = {}
    pool_kwargs = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        from sqlalchemy.pool import StaticPool
        pool_kwargs["poolclass"] = StaticPool
    else:
        pool_kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
    return create_engine(url, echo=False, connect_args=connect_args, **pool_kwargs)

_SessionFactory = None

def get_session(engine=None) -> Session:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=engine or get_engine())
    return _SessionFactory()
```

---

### C-2: No Transaction Rollback on Failure in Most Routes

**Files:** All route files (`products.py`, `prices.py`, `categories.py`, `keywords.py`, `ingestion.py`)  
**Current State:**  
The `try/finally` pattern only calls `session.close()` — but **never** `session.rollback()` when an exception occurs during a write operation. Example:

```python
@router.post("/", status_code=201)
def create_product(body: ProductCreate, ...):
    session = get_session()
    try:
        p = Product(...)
        session.add(p)
        session.commit()           # if this fails halfway...
        session.refresh(p)
        return {"id": p.id}
    finally:
        session.close()            # session closes with dirty state
```

Only the admin routes (`admin.py`) have `except: session.rollback()`.

**Risk:**  
- If `session.commit()` fails (constraint violation, disk full, etc.), the session closes with pending changes → undefined behavior  
- SQLite can leave the database in an inconsistent state with partial writes  
- Service functions like `create_category()`, `add_keyword()` call `session.commit()` internally, so if they fail mid-way, the caller has no rollback  

**Fix:**  
Add `session.rollback()` in an `except` block for **every** write endpoint, or use a context manager:
```python
from contextlib import contextmanager

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

---

### C-3: SQLite WAL Mode Not Enabled — Concurrent Writes Will Lock

**File:** `services/base.py`  
**Current State:**  
No `PRAGMA journal_mode=WAL` is executed after connection creation. SQLite's default journal mode is `DELETE`, which locks the entire database for writes and blocks all concurrent readers.

**Risk:**  
- Any concurrent API requests (e.g., crawlers submitting data while admin browses dashboard) will encounter `database is locked` errors  
- The `check_same_thread=False` flag only allows multi-threaded access — it doesn't prevent locking  
- FastAPI uses async with thread pool, so multiple requests **will** run concurrently  

**Fix:**  
```python
from sqlalchemy import event

engine = get_engine()

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

---

### C-4: Bulk Operations Not Wrapped in Single Transaction

**Files:** `ingestion.py` (`bulk_approve`), `prices.py` (`bulk_save_prices`), `admin.py` (`reset-all`, `reset-products`)  
**Current State:**  
In `bulk_approve`, each ingestion is processed in a loop with `_insert_items()` inside a single session, but if it fails mid-loop, partial results are committed for earlier items. The `_insert_items` function adds rows one by one:

```python
for ingestion_id in body.ids:
    row = session.get(PendingIngestion, ingestion_id)
    ...
    saved = _insert_items(session, items, row.schema_type)
    row.status = IngestionStatus.APPROVED
    ...
session.commit()  # all or nothing — but errors mid-loop raise before commit
```

In `bulk_save_prices`, 5000 items are added one-by-one in a loop without batch insert:
```python
for item in body.items:
    session.add(row)
    saved += 1
session.commit()
```

**Risk:**  
- If the loop fails at item 3000 of 5000, the session rolls back (due to C-2, actually it doesn't roll back — it's even worse)  
- `cleanup_stale_data()` loads ALL stale rows into memory, deletes them one-by-one, then commits  
- `reset-all` deletes from 10 tables sequentially — if it fails mid-way, some tables are deleted and others aren't  

**Fix:**  
- Use `session.bulk_save_objects()` or `session.execute(insert(...).values([...]))` for batch operations  
- Wrap multi-table deletes in explicit `session.begin()` / savepoints  
- For stale data cleanup, use `DELETE WHERE` instead of loading all rows into memory  

---

### C-5: CSV/JSON Export Loads Entire Result Set into Memory

**Files:** `prices.py` (`export_csv`), `export.py` (`export_products_json`), `analytics.py` (`export_prices`, `export_products`)  
**Current State:**  
```python
rows = session.execute(...).all()  # loads ALL matching rows into memory
output = io.StringIO()
# ... write all rows to StringIO
return StreamingResponse(io.BytesIO(output.getvalue().encode("utf-8-sig")))
```
Despite the `StreamingResponse` wrapper, the **entire dataset is materialized in memory** twice (once as SQLAlchemy rows, once as the complete CSV string).

Also in `price_statistics()`:
```python
all_prices = session.execute(select(BaselinePrice.price)).scalars().all()
```
This loads **every price record** into Python memory to compute statistics.

**Risk:**  
- With 100K+ price records, this can consume hundreds of MB → OOM kill  
- The `export.py` has a `export_prices_csv_stream` function but it's **never used** — the routes call `export_prices_csv` instead  
- `price_statistics` computes median/stdev in Python instead of SQL  

**Fix:**  
- Use `yield_per()` / server-side cursors for streaming exports  
- Use the existing `export_prices_csv_stream` generator  
- Compute statistics (median, stdev) in SQL where possible; for SQLite, use windowed queries or `NTILE()`  

---

## HIGH Severity

### H-1: Health Check Doesn't Verify Database Connectivity

**File:** `api/app.py`  
**Current State:**  
```python
@app.get("/health")
async def health(request: Request):
    return {"status": "ok", "service": "db-admin"}
```
The health endpoint always returns "ok" regardless of whether the database is accessible.

**Risk:**  
- Load balancers / orchestrators (Docker, K8s) will route traffic to an instance that cannot reach its database  
- Silent database failures won't be detected by monitoring  

**Fix:**  
```python
@app.get("/health")
async def health(request: Request):
    try:
        session = get_session()
        session.execute(text("SELECT 1"))
        session.close()
        return {"status": "ok", "service": "db-admin", "db": "connected"}
    except Exception as e:
        return JSONResponse(status_code=503, content={
            "status": "unhealthy", "service": "db-admin", "db": str(e)
        })
```

---

### H-2: No Retry Logic on Database Operations

**Files:** All route files  
**Current State:**  
No retry mechanism exists for any database operation. SQLite's `SQLITE_BUSY` errors (which occur frequently with concurrent access) result in immediate 500 errors.

**Risk:**  
- Transient errors (locked database, network blip for PostgreSQL) cause user-visible failures  
- Crawlers submitting data will fail permanently on temporary contention  

**Fix:**  
Add `pool_pre_ping=True` to engine creation and implement retry decorator:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.1))
def execute_with_retry(session, stmt):
    return session.execute(stmt)
```
At minimum, set `PRAGMA busy_timeout=5000` for SQLite (see C-3).

---

### H-3: `tier_preview` Endpoint Runs N+1 Queries (One Per Product)

**File:** `prices.py`  
**Current State:**  
```python
products = session.execute(select(Product.id)).all()
for (pid,) in products:
    avg_baseline = session.execute(select(func.avg(BaselinePrice.price))...).scalar()
    avg_discount = session.execute(select(func.avg(DiscountHistory.price))...).scalar()
```
Two queries per product. With 10,000 products = 20,000 queries.

**Risk:**  
- API timeout for even moderate data sizes  
- SQLite lock contention under concurrent reads  
- Server thread blocked for minutes  

**Fix:**  
Rewrite as two aggregate queries grouped by `product_id`, then join in Python:
```python
baseline_avgs = session.execute(
    select(BaselinePrice.product_id, func.avg(BaselinePrice.price))
    .group_by(BaselinePrice.product_id)
).all()
```

---

### H-4: `global_outliers` Loads All Products' Price Data

**File:** `prices.py`  
**Current State:**  
```python
products = session.execute(select(Product.id, Product.name)).all()
for pid, pname in products:
    rows = session.execute(
        select(...).where(BaselinePrice.product_id == pid)
    ).all()
```
Individual query per product, all prices loaded into Python for IQR calculation.

**Risk:**  
- Same N+1 problem as H-3  
- Memory grows linearly with total price records  
- No pagination on the inner query — a product with 100K prices loads them all  

**Fix:**  
Use `data_quality.check_price_outliers_batch()` which already exists and does batch querying. Use it instead of the per-product loop.

---

### H-5: Frontend Has No Error Boundaries

**File:** `App.jsx`  
**Current State:**  
```jsx
export default function App() {
  return (
    <Suspense fallback={<Loader />}>
      <Routes>...</Routes>
    </Suspense>
  );
}
```
No React `ErrorBoundary` wraps any page or component. An unhandled JavaScript error in any component crashes the entire app.

**Risk:**  
- A single malformed API response or rendering error whites out the entire admin panel  
- Users lose all context and must refresh  

**Fix:**  
```jsx
import { ErrorBoundary } from 'react-error-boundary';

function ErrorFallback({ error, resetErrorBoundary }) {
  return (
    <div role="alert">
      <p>오류가 발생했습니다: {error.message}</p>
      <button onClick={resetErrorBoundary}>다시 시도</button>
    </div>
  );
}

// Wrap each route's element:
<ErrorBoundary FallbackComponent={ErrorFallback}>
  <Dashboard />
</ErrorBoundary>
```

---

### H-6: Frontend API Client Has No Timeout or Retry

**File:** `frontend/src/api/client.js`  
**Current State:**  
```javascript
const json = async (r) => {
  const data = await r.json();
  if (!r.ok) { throw new Error(msg); }
  return data;
};
```
- No `AbortController` timeout — requests hang indefinitely if server is unresponsive  
- No retry logic for network failures or 5xx responses  
- No request/response interceptors for token refresh  

**Risk:**  
- UI shows "loading" spinner forever on network issues  
- Expired JWT tokens cause hard 401 failures instead of auto-refreshing  

**Fix:**  
```javascript
const fetchWithTimeout = (url, options = {}, timeout = 30000) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  return fetch(url, { ...options, signal: controller.signal })
    .finally(() => clearTimeout(id));
};
```

---

### H-7: Alembic Migrations Directory Missing

**Files:** `alembic.ini` points to `storage/migrations` but no `alembic/` or `storage/migrations/` directory exists  
**Current State:**  
`alembic.ini` is configured but the migration scripts directory doesn't exist. Schema changes are likely done via `Base.metadata.create_all()` or manual SQL.

**Risk:**  
- Schema changes in production will cause data loss if tables are recreated  
- No rollback capability for failed schema migrations  
- No audit trail of schema evolution  

**Fix:**  
```bash
cd packages/db-admin/backend
alembic init storage/migrations
alembic revision --autogenerate -m "initial"
```

---

## MEDIUM Severity

### M-1: Service Functions Commit Internally — Caller Cannot Control Transaction Scope

**Files:** `category_mgmt.py`, `autocomplete.py`, `data_quality.py`  
**Current State:**  
```python
def create_category(session, ...):
    session.add(cat)
    session.commit()      # commits immediately
    session.refresh(cat)
```
The route creates the session, passes it to the service, but the service commits. If the route needs to do additional work after the service call (e.g., audit logging), it's in a **new implicit transaction**.

**Risk:**  
- Audit log entries and data changes can be in separate transactions — one commits and the other fails  
- Makes it impossible to implement "saga" patterns or multi-step operations  

**Fix:**  
Remove `session.commit()` from service functions; let the route control transaction boundaries.

---

### M-2: Stale Data Not Handled on Frontend

**File:** `stores/dbAdminStore.js`  
**Current State:**  
After mutations (create/update/delete), the store calls `fetchProducts()` etc. to refresh. But:
- No optimistic updates — UI shows old data until refetch completes  
- No cache invalidation across tabs  
- No polling or WebSocket for real-time updates  
- Dashboard data can be minutes stale  

**Risk:**  
- Two admins editing the same product see conflicting data  
- Dashboard shows stale alerts; recent failures aren't visible  

**Fix:**  
- Add `updatedAt` timestamp to store; show "last refreshed X minutes ago"  
- Implement periodic auto-refresh (e.g., every 60s for dashboard)  
- Add optimistic updates for delete/create operations  

---

### M-3: Whitelist Stored as JSON File — Race Condition on Concurrent Writes

**File:** `prices.py`  
**Current State:**  
```python
def _load_whitelist() -> set:
    data = json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
    return set(data)

def _save_whitelist(ids: set):
    WHITELIST_PATH.write_text(json.dumps(sorted(ids)), encoding="utf-8")
```
Read-modify-write without file locking. Two concurrent whitelist operations will lose data.

**Risk:**  
- Lost whitelist entries when two admins whitelist outliers simultaneously  
- Same issue with `tier_config.json`  

**Fix:**  
Move whitelist to the database (a simple `outlier_whitelist` table), or use `fcntl.flock()` / `portalocker`.

---

### M-4: Keyword Synonym Search Loads All Keywords

**File:** `autocomplete.py`  
**Current State:**  
```python
all_keywords = session.execute(
    select(Keyword).where(Keyword.is_active == True)
).scalars().all()
```
When prefix search results are insufficient, the fallback loads **every active keyword** into memory to scan synonyms.

**Risk:**  
- With thousands of keywords, this is a full-table scan plus Python iteration  
- Memory spike on every search miss  

**Fix:**  
Store synonyms in a separate `keyword_synonyms` table for SQL-level searching, or use SQLite FTS5 for full-text search on synonyms.

---

### M-5: No Request Timeout at Server Level

**File:** `main.py`  
**Current State:**  
```python
uvicorn.run("main:app", host=..., port=..., reload=...)
```
No `--timeout-keep-alive`, `--timeout-notify`, or middleware-level request timeouts configured.

**Risk:**  
- Slow queries (N+1 endpoints like `tier_preview`) can hold worker threads for minutes  
- With default uvicorn worker count, a few slow requests can exhaust all workers  

**Fix:**  
```python
uvicorn.run("main:app", ..., timeout_keep_alive=30, limit_concurrency=50)
```
Add a middleware timeout:
```python
from starlette.middleware import Middleware
from starlette_context.middleware import RawContextMiddleware
# Or use asyncio.timeout in async endpoints
```

---

### M-6: Audit Log Written But Never Read / Queried

**File:** `services/audit.py`  
**Current State:**  
`log_action()` is defined and imported in multiple routes, but **no API endpoint exists to query audit logs**. The function is called in some routes but the data is write-only.

**Risk:**  
- Audit trail exists in the database but admins cannot review it  
- No alerting on suspicious patterns (bulk deletes, frequent resets)  
- Compliance auditing requires direct database access  

**Fix:**  
Add `GET /api/admin/audit-logs` endpoint with filtering by action, entity, user, and date range.

---

### M-7: `sys.path.insert(0, ...)` for Shared Module Import — Fragile

**Files:** `services/price_calc.py`, `services/data_quality.py`  
**Current State:**  
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))
from core.statistics import compute_stats, determine_tier, ...
```
Runtime `sys.path` manipulation. Breaks if directory structure changes, makes IDE navigation fail, and causes import confusion.

**Risk:**  
- Moving or renaming the `shared` directory silently breaks imports at runtime  
- Multiple `sys.path.insert(0, ...)` calls can cause import shadowing  

**Fix:**  
Create `shared` as a proper installable package with `setup.py`/`pyproject.toml`:
```bash
pip install -e ../shared
```

---

### M-8: No Graceful Shutdown — In-Flight Requests May Be Interrupted

**File:** `main.py`  
**Current State:**  
No lifecycle shutdown handler. When the server stops (SIGTERM, Ctrl+C), in-flight database operations may be interrupted mid-transaction.

**Risk:**  
- `SIGTERM` during a `reset-all` or `bulk-approve` leaves the database partially modified  
- Backup operations interrupted mid-copy create corrupt backup files  

**Fix:**  
Add shutdown handler in `lifespan`:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    yield
    # shutdown: close engine pool
    engine = get_engine()
    engine.dispose()
```

---

## LOW Severity

### L-1: `datetime.utcnow()` Used Throughout — Deprecated in Python 3.12+

**Files:** All backend files  
**Current State:**  
```python
expire = datetime.utcnow() + timedelta(...)
```
`datetime.utcnow()` is deprecated since Python 3.12. It returns a naive datetime, which can cause timezone bugs.

**Fix:**  
```python
from datetime import datetime, timezone
expire = datetime.now(timezone.utc) + timedelta(...)
```

---

### L-2: Frontend Loader Has No Timeout

**File:** `App.jsx`  
**Current State:**  
```jsx
<Suspense fallback={<Loader />}>
```
If a lazy-loaded chunk fails to download, the loader shows indefinitely.

**Fix:**  
Add a timeout wrapper that shows an error message after 15 seconds, or use an error boundary around `Suspense`.

---

### L-3: Rate Limiter Uses In-Memory Storage — Resets on Restart

**File:** `api/middleware/rate_limit.py`  
**Current State:**  
```python
limiter = Limiter(
    key_func=_get_client_ip,
    storage_uri=os.getenv("RATE_LIMIT_STORAGE", "memory://"),
)
```
Rate limit counters are lost on restart. `REDIS_URL` is configured in settings but not wired to the rate limiter.

**Fix:**  
```python
storage_uri=os.getenv("RATE_LIMIT_STORAGE", settings.REDIS_URL)
```

---

### L-4: Logging Not Structured — Hard to Parse in Production

**Files:** All backend files  
**Current State:**  
```python
logger.warning("[ADMIN] reset-source: source=%s discount=%d", ...)
```
Free-form log messages with inconsistent formats. No JSON structured logging.

**Fix:**  
Use `python-json-logger` or `structlog` for machine-parseable log output:
```python
import structlog
logger = structlog.get_logger()
logger.warning("admin.reset_source", source=src, discount_count=discount_del)
```

---

### L-5: `_ANONYMOUS_IDENTITY` Grants Admin Role by Default

**File:** `api/auth.py`  
**Current State:**  
```python
_ANONYMOUS_IDENTITY = {
    "id": 0,
    "email": "anonymous",
    "role": "admin",        # anonymous user is admin!
    "auth_type": "anonymous",
}
```
When `REQUIRE_AUTH=false`, anonymous users are admin. This is intentional for development, but if accidentally deployed with auth disabled, the entire admin API is unprotected.

**Risk:**  
Low (development-only flag), but a defense-in-depth concern.

**Fix:**  
Log a startup warning if `REQUIRE_AUTH=false` in non-debug mode. The existing check only validates `DATABASE_URL`.

---

## Summary Matrix

| ID | Severity | Category | Effort | Impact |
|----|----------|----------|--------|--------|
| C-1 | Critical | Connection Management | 1h | Eliminates per-request engine creation |
| C-2 | Critical | Crash Recovery | 2h | Ensures transaction rollback on failure |
| C-3 | Critical | Data Consistency | 30m | Enables concurrent read/write |
| C-4 | Critical | Data Integrity | 3h | Makes bulk operations truly atomic |
| C-5 | Critical | Memory Management | 2h | Prevents OOM on large exports |
| H-1 | High | Health Checks | 30m | Enables proper health monitoring |
| H-2 | High | Retry Logic | 2h | Handles transient DB errors |
| H-3 | High | Performance | 1h | Fixes N+1 query pattern |
| H-4 | High | Performance | 1h | Uses existing batch function |
| H-5 | High | Error Boundaries | 1h | Prevents full-app crashes |
| H-6 | High | Error Handling | 1h | Adds timeout + retry to API client |
| H-7 | High | Database Migrations | 2h | Enables safe schema evolution |
| M-1 | Medium | Data Integrity | 3h | Enables proper transaction control |
| M-2 | Medium | State Management | 2h | Handles stale frontend data |
| M-3 | Medium | Data Consistency | 1h | Eliminates file-based race conditions |
| M-4 | Medium | Memory Management | 2h | Prevents full-table keyword scans |
| M-5 | Medium | Graceful Degradation | 30m | Prevents worker thread exhaustion |
| M-6 | Medium | Logging | 2h | Makes audit logs queryable |
| M-7 | Medium | Reliability | 1h | Fixes fragile shared imports |
| M-8 | Medium | Graceful Degradation | 30m | Ensures clean shutdown |
| L-1 | Low | Maintenance | 1h | Future-proofs for Python 3.12+ |
| L-2 | Low | Error Handling | 30m | Handles failed chunk loads |
| L-3 | Low | Rate Limiting | 15m | Persists rate limits across restarts |
| L-4 | Low | Logging | 2h | Enables log aggregation |
| L-5 | Low | Security | 15m | Adds defense-in-depth warning |

---

## Recommended Priority Order

1. **C-1 + C-3** — Fix engine singleton + WAL mode (foundational; everything else depends on stable connections)
2. **C-2** — Add transaction rollback (prevents data corruption)
3. **H-1** — Health check with DB ping (quick win for monitoring)
4. **C-5** — Streaming exports (prevents OOM)
5. **H-5 + H-6** — Frontend resilience (error boundaries + API timeout)
6. **C-4** — Atomic bulk operations
7. **H-3 + H-4** — Fix N+1 queries
8. **H-7** — Set up Alembic migrations
9. **M-1 through M-8** — Medium items in order of effort/impact
10. **L-1 through L-5** — Low items as time permits
