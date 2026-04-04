# DB-Admin Concurrency & Performance Stability Audit

> **Date**: 2025-07-18
> **Scope**: `packages/db-admin` (backend + frontend)
> **Focus**: Concurrency, performance under load, frontend resilience

---

## Executive Summary

The db-admin sub-project is a FastAPI + React admin dashboard for managing product/price data backed by SQLite (dev) / PostgreSQL (prod). The architecture is generally sound but has **critical gaps** in SQLite concurrency handling, request timeout/cancellation, and frontend network resilience that would cause failures under real-world concurrent load.

| Area | Rating | Key Risk |
|------|--------|----------|
| SQLite Concurrency | 🔴 Critical | No WAL mode, no busy timeout, write starvation |
| Request Queuing | 🟡 Moderate | Rate limiting exists but no back-pressure |
| Long-Running Queries | 🔴 Critical | No query timeout, no cancellation |
| Cache Invalidation | 🟡 Moderate | LRU cache unbounded lifetime, no cross-instance sync |
| Frontend Resilience | 🔴 Critical | No fetch timeout, no retry, no AbortController |
| API Contract | 🟢 Good | Consistent error format, pagination present |
| File System | 🟡 Moderate | Backup retention exists, no disk-space check |
| Startup/Shutdown | 🟡 Moderate | Lifespan hook exists but no DB health check |
| Hot Reload | 🟢 Good | Vite HMR + uvicorn reload functional |
| Test Coverage | 🟡 Moderate | 19 test files; no concurrency/load tests |

---

## 1. SQLite Concurrency

### Current State

**File**: `backend/storage/db.py`

```python
# Connection setup (simplified)
connect_args = {"check_same_thread": False}  # allows multi-thread access
engine = create_engine(url, connect_args=connect_args)
Session = scoped_session(sessionmaker(bind=engine))
```

- `check_same_thread=False` — allows SQLAlchemy's thread pool to share the connection.
- `scoped_session` — provides thread-local session isolation.
- **StaticPool** used for SQLite (single connection).

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 1.1 | **WAL mode not enabled** | 🔴 Critical | Default journal mode is DELETE. Under concurrent reads + writes, readers block writers and vice versa. WAL allows concurrent reads during writes. |
| 1.2 | **No busy_timeout** | 🔴 Critical | When a write is in progress, other writers get `SQLITE_BUSY` immediately instead of waiting. This causes `OperationalError: database is locked` under any concurrent write load. |
| 1.3 | **No write serialization** | 🟡 Moderate | Multiple FastAPI worker threads can attempt simultaneous writes. SQLite allows only one writer at a time; without a write queue, contention errors occur. |
| 1.4 | **StaticPool single connection** | 🟡 Moderate | All threads share one connection. Under 10+ concurrent requests, connection checkout contention becomes a bottleneck. |

### Recommendations

```python
# db.py — after engine creation, for SQLite only:
from sqlalchemy import event

@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")       # concurrent readers
    cursor.execute("PRAGMA busy_timeout=5000")       # wait 5s before BUSY error
    cursor.execute("PRAGMA synchronous=NORMAL")      # safe with WAL
    cursor.execute("PRAGMA foreign_keys=ON")         # enforce FK constraints
    cursor.close()
```

For write serialization, add an `asyncio.Lock` or `threading.Lock` around write operations, or switch to a `QueuePool` with `pool_size=1` to force serial writes:

```python
# Option: serialize writes via pool
engine = create_engine(
    url,
    connect_args={"check_same_thread": False},
    poolclass=QueuePool,
    pool_size=1,
    max_overflow=0,
    pool_timeout=10,
)
```

---

## 2. Request Queuing Under Load

### Current State

- **Rate Limiting** (`backend/api/rate_limit.py`): SlowAPI with configurable limits.
  - Global: `200/minute`
  - Admin ops: `10/minute`
  - Destructive: `5/minute`
  - Ingestion: `30/minute`
- **Storage**: In-memory by default (`memory://`), Redis in production.
- **Request Size Limit**: 10 MB (`RequestSizeLimitMiddleware`).
- **GZip Compression**: Responses > 500 bytes.

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 2.1 | **No request timeout on server** | 🔴 Critical | Uvicorn has no `timeout-keep-alive` or request-level timeout configured in `main.py`. A slow query can hold a worker thread indefinitely. |
| 2.2 | **In-memory rate limit state not shared** | 🟡 Moderate | If running multiple uvicorn workers, each has independent counters. A client can exceed the limit by distributing across workers. |
| 2.3 | **No back-pressure signal** | 🟡 Moderate | When all worker threads are busy, new requests queue in the OS socket buffer. No 503 is returned; requests just hang until timeout. |
| 2.4 | **Sync ORM in async framework** | 🟡 Moderate | FastAPI is async-capable but all DB operations use synchronous SQLAlchemy. Each DB call blocks a thread in the threadpool (default 40 threads). Under 40+ concurrent DB requests, new requests stall. |

### Recommendations

1. **Add uvicorn timeout**:
   ```python
   # main.py
   uvicorn.run(app, host=..., port=..., timeout_keep_alive=30)
   ```

2. **Use Redis for rate-limit storage in production** (already documented in `.env.example`; enforce it):
   ```
   RATE_LIMIT_STORAGE=redis://redis:6379/1
   ```

3. **Add a connection-limit middleware** or use uvicorn's `--limit-concurrency` flag to cap in-flight requests:
   ```bash
   uvicorn main:app --limit-concurrency 50
   ```

4. **Consider `run_in_executor`** for DB calls or migrate to async SQLAlchemy to avoid blocking the event loop.

---

## 3. Long-Running Queries

### Current State

- `MAX_RESULT_LIMIT = 1000` in `db.py` — prevents unbounded result sets.
- `joinedload()` used to prevent N+1 queries.
- Subquery-based aggregation reduces 8 queries → 2 for product detail.
- No query timeout or statement-level cancellation mechanism.

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 3.1 | **No query/statement timeout** | 🔴 Critical | A complex analytics query (e.g., quality report scanning full table) can run for minutes. No timeout kills it. Worker thread is occupied the entire time. |
| 3.2 | **No request cancellation propagation** | 🟡 Moderate | If the client disconnects (navigates away), the server-side query continues to completion. Wasted resources. |
| 3.3 | **Full table scans on analytics** | 🟡 Moderate | `quality-report`, `source-distribution`, `daily-trend` endpoints query all prices without date bounds. On a large dataset this is expensive. |

### Recommendations

1. **PostgreSQL statement timeout** (production):
   ```python
   @event.listens_for(engine, "connect")
   def set_pg_timeout(dbapi_conn, connection_record):
       cursor = dbapi_conn.cursor()
       cursor.execute("SET statement_timeout = '30s'")
       cursor.close()
   ```

2. **SQLite timeout** (development): Use `busy_timeout` pragma (see §1).

3. **Add date-range limits** on analytics endpoints. Default to last 90 days if no range specified.

4. **Detect client disconnect** in long operations:
   ```python
   from starlette.requests import Request
   if await request.is_disconnected():
       raise HTTPException(499, "Client disconnected")
   ```

---

## 4. Cache Invalidation

### Current State

- **Auto-categorization cache** (`backend/services/auto_categorize.py`):
  ```python
  @functools.lru_cache(maxsize=2048)
  def _auto_categorize_cached(product_name: str, source: str | None) -> tuple:
  ```
- **Frontend**: No explicit caching layer. Zustand store is ephemeral (lost on page refresh).

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 4.1 | **LRU cache has no TTL** | 🟡 Moderate | If keywords or categories are updated, cached categorization results remain stale until server restart or cache eviction. |
| 4.2 | **No cache invalidation on keyword/category CRUD** | 🟡 Moderate | Editing a keyword mapping doesn't clear the auto-categorize cache. Products could be mis-categorized until the cache entry is evicted. |
| 4.3 | **Multi-instance cache divergence** | 🟡 Moderate | If multiple server processes run (e.g., gunicorn workers), each has its own LRU cache. The same product name may get different categories on different workers after a keyword update. |
| 4.4 | **Frontend stale state** | 🟢 Low | Zustand store fetches fresh data on each page mount. Acceptable for admin tool usage patterns. |

### Recommendations

1. **Add TTL to LRU cache** using `cachetools.TTLCache` (already have `limits` in requirements):
   ```python
   from cachetools import TTLCache, cached
   _categorize_cache = TTLCache(maxsize=2048, ttl=300)  # 5 min TTL

   @cached(_categorize_cache)
   def _auto_categorize_cached(product_name, source):
       ...
   ```

2. **Invalidate on keyword/category mutation**:
   ```python
   def update_keyword(session, keyword_id, ...):
       # ... update logic ...
       _categorize_cache.clear()
   ```

3. **For multi-instance**: Use Redis-backed cache or accept 5-minute eventual consistency.

---

## 5. Frontend Resilience

### Current State

**File**: `frontend/src/api/client.js`

```javascript
const json = async (r) => {
  const data = await r.json();
  if (!r.ok) {
    const msg = data.detail || data.message || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return data;
};
```

- Centralized error extraction with status code.
- Error displayed in Zustand store: `set({ error: "..." })`.
- Loading states managed per-store-action.
- `Promise.allSettled()` used for analytics (graceful partial failure).

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 5.1 | **No request timeout** | 🔴 Critical | `fetch()` has no `AbortController` timeout. If backend hangs, the UI freezes with a loading spinner forever. |
| 5.2 | **No retry logic** | 🔴 Critical | Transient network errors (Wi-Fi glitch, backend restart) immediately fail. No retry with backoff. |
| 5.3 | **No request cancellation on navigation** | 🔴 Critical | When the user navigates away, pending `fetch()` calls continue. Responses arrive and update state for a page no longer displayed. Can cause React state-update-on-unmounted-component warnings. |
| 5.4 | **No React Error Boundary** | 🔴 Critical | A rendering error in any component crashes the entire app. No fallback UI, no recovery. |
| 5.5 | **No offline detection** | 🟡 Moderate | App shows loading spinner indefinitely if network is unavailable. No "you are offline" indicator. |
| 5.6 | **Error state overwrite** | 🟡 Moderate | Global `error` field in Zustand is a single string. Concurrent failures overwrite each other; user sees only the last error. |
| 5.7 | **Silent analytics failures** | 🟡 Moderate | `Promise.allSettled()` catches failures silently. Dashboard widgets show stale/empty data without indicating an error. |
| 5.8 | **No response schema validation** | 🟡 Moderate | No TypeScript or runtime validation. If the API returns an unexpected shape, the UI may crash with `Cannot read property of undefined`. |

### Recommendations

1. **Add timeout wrapper to fetch**:
   ```javascript
   function fetchWithTimeout(url, opts = {}, timeoutMs = 30000) {
     const controller = new AbortController();
     const timer = setTimeout(() => controller.abort(), timeoutMs);
     return fetch(url, { ...opts, signal: controller.signal })
       .finally(() => clearTimeout(timer));
   }
   ```

2. **Add retry with exponential backoff** (for GET requests only):
   ```javascript
   async function fetchWithRetry(url, opts = {}, retries = 3) {
     for (let i = 0; i < retries; i++) {
       try {
         return await fetchWithTimeout(url, opts);
       } catch (err) {
         if (i === retries - 1 || err.status >= 400) throw err;
         await new Promise(r => setTimeout(r, 1000 * 2 ** i));
       }
     }
   }
   ```

3. **Add React Error Boundary**:
   ```jsx
   class ErrorBoundary extends React.Component {
     state = { hasError: false };
     static getDerivedStateFromError() { return { hasError: true }; }
     componentDidCatch(err, info) { console.error(err, info); }
     render() {
       if (this.state.hasError) return <FallbackUI onRetry={...} />;
       return this.props.children;
     }
   }
   ```

4. **Add AbortController per page** (cancel on unmount):
   ```javascript
   useEffect(() => {
     const controller = new AbortController();
     fetchProducts(params, controller.signal);
     return () => controller.abort();
   }, [params]);
   ```

---

## 6. API Contract Consistency

### Current State

- **Error responses** follow `ErrorResponse` schema:
  ```json
  { "error": { "code": "VALIDATION_ERROR", "message": "...", "request_id": "abc123" } }
  ```
- **Validation errors** return 422 with field-level detail.
- **Pagination** uses `{ items: [], total, page, per_page, total_pages }`.
- **Rate limit errors** return 429 with `retry_after`.

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 6.1 | **Inconsistent error format between middleware and routes** | 🟡 Moderate | Rate limit middleware returns `{ "detail": "...", "retry_after": "..." }` while route errors return `{ "error": { "code": "...", ... } }`. Frontend must handle both shapes. |
| 6.2 | **Pagination off-by-one risk** | 🟢 Low | `total_pages` calculated server-side. If data changes between paginated requests, user may see duplicates or gaps. Acceptable for admin tool. |
| 6.3 | **No API versioning** | 🟡 Moderate | All routes under `/api/`. Breaking changes have no migration path. |

### Recommendations

1. **Standardize error envelope** — wrap rate-limit errors in the same `{ error: { code, message } }` format.
2. **Add `/api/v1/` prefix** as a future-proofing measure.

---

## 7. File System Risks

### Current State

- **Backup service** (`backend/services/backup.py`):
  - Uses SQLite hot-backup API (`src.backup(dst)`).
  - Retention: keeps 30 most recent, deletes oldest.
  - Naming: `walletguardian_{reason}_{timestamp}.db`.
- **DB file**: `walletguardian.db` in project root.
- **Seed data**: JSON files in `category_data/`, `price_data/`.

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 7.1 | **No disk-space check before backup** | 🟡 Moderate | If disk is full, `backup()` will fail with an obscure OS error. No pre-flight check or graceful error message. |
| 7.2 | **DB file in project root** | 🟢 Low | `walletguardian.db` sits in the code directory. Easy to accidentally `git add` or delete. Should be in a dedicated data directory. |
| 7.3 | **No file-locking conflict handling** | 🟡 Moderate | If an external tool (e.g., DB Browser for SQLite) locks the file, the app gets `SQLITE_BUSY` with no user-friendly error. |
| 7.4 | **Temp files during backup** | 🟢 Low | SQLite hot backup creates the destination file atomically. No temp-file leak risk. |

### Recommendations

1. **Pre-flight disk check**:
   ```python
   import shutil
   usage = shutil.disk_usage(backup_dir)
   if usage.free < db_size * 2:
       raise RuntimeError("Insufficient disk space for backup")
   ```

2. **Move DB to `data/` directory** outside the code tree with a `.gitignore`.

---

## 8. Startup / Shutdown

### Current State

**File**: `backend/api/app.py` — uses FastAPI `lifespan` context manager.

```python
@asynccontextmanager
async def lifespan(app):
    # Startup
    if not settings.DEBUG:
        if "changeme" in settings.DATABASE_URL:
            raise RuntimeError("SECURITY: Default database password detected.")
    yield
    # Shutdown (implicit)
```

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 8.1 | **No DB connectivity check on startup** | 🟡 Moderate | If the database file is missing or PostgreSQL is unreachable, the first request fails with an unhandled error instead of a clean startup failure. |
| 8.2 | **No graceful shutdown for DB sessions** | 🟡 Moderate | On SIGTERM, `scoped_session` is not explicitly disposed. Pending transactions may be lost. |
| 8.3 | **No startup order enforcement** | 🟢 Low | If Redis (for rate limiting) is unavailable, SlowAPI falls back silently. This is acceptable but should be logged. |

### Recommendations

1. **Add startup health check**:
   ```python
   @asynccontextmanager
   async def lifespan(app):
       # Verify DB
       try:
           db = DatabaseManager()
           with db.engine.connect() as conn:
               conn.execute(text("SELECT 1"))
           logger.info("Database connection verified")
       except Exception as e:
           logger.critical(f"Database unreachable: {e}")
           raise

       yield

       # Shutdown
       db.Session.remove()
       db.engine.dispose()
       logger.info("Database connections closed")
   ```

2. **Log Redis connectivity status** on startup for rate-limit storage.

---

## 9. Hot Reload (Development)

### Current State

- **Backend**: Uvicorn with `--reload` (inferred from `DEBUG` flag).
- **Frontend**: Vite with React Fast Refresh (HMR).
- **Proxy**: Vite proxies `/api` → `http://127.0.0.1:8002`.

### Issues Found

| # | Issue | Severity | Detail |
|---|-------|----------|--------|
| 9.1 | **SQLite lock during reload** | 🟢 Low | Uvicorn reload kills and restarts the process. SQLite WAL mode (if enabled) handles this gracefully. Without WAL, a reload during a write may corrupt the journal. |
| 9.2 | **Frontend proxy timeout** | 🟢 Low | During backend restart (~2s), frontend API calls return connection-refused. No retry means the user sees an error. Acceptable in dev. |

### Recommendations

- Enable WAL mode (see §1) to make hot-reload safe for SQLite writes.
- Consider adding a dev-mode retry wrapper in the frontend API client.

---

## 10. Test Coverage Gaps

### Current State — 19 Test Files

| Test File | Coverage Area |
|-----------|---------------|
| `test_models.py` (763 lines) | Full schema, relationships, cascades, constraints |
| `test_auth.py` | JWT, API keys, role hierarchy |
| `test_rate_limiting.py` | Rate limit enforcement |
| `test_security_headers.py` | HTTP security headers |
| `test_input_validation.py` | Input sanitization |
| `test_like_escape.py` | SQL LIKE escaping |
| `test_error_handling.py` | Error response format |
| `test_auto_categorize.py` | Categorization engine |
| `test_backup.py` | Backup/restore |
| `test_audit_log.py` | Audit trail |
| `test_config_security.py` | Configuration validation |
| `test_data_quality.py` | Data quality checks |
| Others | API docs, autocomplete, bind address, getattr safety, price calc |

### Critical Gaps

| # | Missing Test | Risk |
|---|-------------|------|
| 10.1 | **Concurrent write tests** | Cannot detect `database is locked` errors before production |
| 10.2 | **Load/stress tests** | No validation that 50+ concurrent requests don't crash the server |
| 10.3 | **Request timeout behavior** | Unknown behavior when queries exceed expected duration |
| 10.4 | **Pagination boundary tests** | Edge cases: page=0, page > total_pages, per_page=0, per_page=10000 |
| 10.5 | **Frontend component tests** | Vitest configured (`vitest` in package.json) but no test files found in `src/` |
| 10.6 | **API integration tests** | No end-to-end tests covering frontend → API → DB → response |
| 10.7 | **Cache invalidation tests** | No test verifying that keyword changes invalidate auto-categorize cache |
| 10.8 | **Backup under write-load** | No test for backup while concurrent writes are happening |

### Recommendations

1. **Add concurrency test** using `pytest` + `concurrent.futures`:
   ```python
   def test_concurrent_writes():
       with ThreadPoolExecutor(max_workers=10) as pool:
           futures = [pool.submit(create_product, f"prod-{i}") for i in range(50)]
           results = [f.result() for f in futures]
       assert all(r.status_code == 201 for r in results)
   ```

2. **Add frontend test stubs** for critical paths (product CRUD, error display, loading states).

3. **Add pagination boundary tests** for all list endpoints.

---

## Priority Action Items

### 🔴 P0 — Fix Before Any Load Testing

| # | Action | Effort | File(s) |
|---|--------|--------|---------|
| 1 | Enable SQLite WAL mode + busy_timeout | 15 min | `storage/db.py` |
| 2 | Add fetch timeout (AbortController) in frontend | 30 min | `api/client.js` |
| 3 | Add React Error Boundary | 20 min | `src/App.jsx` |
| 4 | Add uvicorn request timeout | 5 min | `main.py` |

### 🟡 P1 — Fix Before Production

| # | Action | Effort | File(s) |
|---|--------|--------|---------|
| 5 | Add query statement timeout (PostgreSQL) | 10 min | `storage/db.py` |
| 6 | Add retry logic to frontend API client | 1 hr | `api/client.js` |
| 7 | Add request cancellation on route change | 1 hr | Page components |
| 8 | Add TTL to auto-categorize cache | 20 min | `services/auto_categorize.py` |
| 9 | Invalidate cache on keyword/category mutation | 30 min | Route handlers |
| 10 | Add DB health check on startup | 15 min | `api/app.py` |
| 11 | Add graceful shutdown (dispose engine) | 10 min | `api/app.py` |
| 12 | Standardize error response envelope | 30 min | `api/rate_limit.py` |
| 13 | Add disk-space pre-check for backups | 10 min | `services/backup.py` |

### 🟢 P2 — Recommended Improvements

| # | Action | Effort | File(s) |
|---|--------|--------|---------|
| 14 | Add concurrent write tests | 2 hr | `tests/` |
| 15 | Add frontend component tests | 4 hr | `src/__tests__/` |
| 16 | Add API versioning prefix | 1 hr | All route files |
| 17 | Add offline detection in frontend | 30 min | `api/client.js` |
| 18 | Move DB file to `data/` directory | 15 min | `config.py`, `.gitignore` |
| 19 | Add load test script (locust/k6) | 4 hr | `tests/load/` |

---

## Appendix A: Configuration Checklist for Production

```
[ ] DATABASE_URL — unique password, not "changeme"
[ ] JWT_SECRET — random 32+ character string
[ ] REQUIRE_AUTH=true
[ ] DEBUG=false
[ ] CORS_ALLOWED_ORIGINS — production domain only
[ ] RATE_LIMIT_STORAGE=redis://... — not memory://
[ ] BACKUP_DIR — writable path with sufficient space
[ ] BACKUP_RETENTION_COUNT — set based on disk capacity
[ ] WAL mode enabled (SQLite) or statement_timeout set (PostgreSQL)
[ ] uvicorn --limit-concurrency set appropriately
[ ] Monitoring/alerting configured (errors, latency, disk usage)
```

## Appendix B: Concurrency Failure Scenario Matrix

| Scenario | Current Behavior | Expected Behavior |
|----------|-----------------|-------------------|
| 10 simultaneous product creates (SQLite) | Random `database is locked` errors | All succeed (serialized via WAL + busy_timeout) |
| Backend hangs for 60s | Frontend spinner forever | 30s timeout → error message → retry button |
| Backend restart during request | Frontend error, no recovery | Retry with backoff, success on second attempt |
| User navigates away during slow query | Query completes, state update on unmounted component | AbortController cancels request |
| Disk full during backup | Cryptic OS error, partial file | Pre-check fails gracefully, alerts admin |
| 100 concurrent analytics queries | Thread pool exhaustion, cascading timeouts | Rate limit at 200/min, query timeout at 30s |
| Redis down (prod rate limiting) | Fallback to memory (per-process) | Log warning, continue with memory fallback |
| Category renamed → auto-categorize | Stale cache returns old category | Cache invalidated, re-categorizes correctly |
