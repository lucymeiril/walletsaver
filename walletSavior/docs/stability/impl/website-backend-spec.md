# Website Backend Stability — Implementation Spec

> **Scope:** Naver scraping resilience, SSE disconnect, circuit breaker, health check, unbounded queries, structured logging, graceful shutdown  
> **Target:** `packages/website/backend`  
> **Audit Refs:** S-01, S-02, S-03, S-05, S-06, S-09, S-19, S-27, S-28 (website-stability-audit.md)  
> **Estimated Effort:** 6–8 hours implementation + 2 hours testing

---

## Table of Contents

1. [Naver Scraping Recovery](#1-naver-scraping-recovery)
2. [SSE Disconnect Detection](#2-sse-disconnect-detection)
3. [Circuit Breaker for DB Admin API](#3-circuit-breaker-for-db-admin-api)
4. [Health Check Endpoint](#4-health-check-endpoint)
5. [Unbounded Query Limits](#5-unbounded-query-limits)
6. [In-Memory User Store (Tech Debt Flag)](#6-in-memory-user-store-tech-debt-flag)
7. [Structured Logging](#7-structured-logging)
8. [Graceful Shutdown](#8-graceful-shutdown)
9. [New Dependencies](#9-new-dependencies)
10. [Test Cases](#10-test-cases)
11. [Migration Checklist](#11-migration-checklist)

---

## 1. Naver Scraping Recovery

### Audit Findings

| ID | Issue | Severity |
|----|-------|----------|
| S-01 | No retry logic — single Playwright timeout → empty results, no backoff | 🔴 CRITICAL |
| S-02 | No circuit breaker on `naver_local.py` — repeated Naver blocks still trigger full browser automation | 🟠 HIGH |
| S-03 | `ThreadPoolExecutor(max_workers=4)` never `shutdown()` — thread leak on restart | 🟡 MEDIUM |

### 1.1 Circuit Breaker for Naver Scraping

**File:** `packages/website/backend/api/routes/naver_local.py`

The existing `CircuitBreaker` class in `api/utils/cache.py` (lines 95–136) is already thread-safe and proven in `flyer_service.py`. Reuse it.

**Current code (line 178–181):**
```python
_pool = _BrowserPool(idle_timeout=300)
_executor = ThreadPoolExecutor(max_workers=4)
```

**New code — add after line 181:**
```python
from api.utils.cache import CircuitBreaker

# Circuit breaker: 5 consecutive Playwright failures → 120s cooldown
# More generous than flyer_service (3/60s) because Naver scraping
# is the primary feature and we want to give it more chances
_naver_circuit = CircuitBreaker(failure_threshold=5, recovery_timeout=120)
```

### 1.2 Retry with Exponential Backoff

**File:** `packages/website/backend/api/routes/naver_local.py`

Add a retry wrapper for `_search_via_playwright_sync()`. This function (lines 208–276) currently catches all exceptions and returns `[]`. We need to distinguish retryable errors (timeout, browser crash) from permanent ones (blocked/CAPTCHA).

**New function — add before `_search_via_playwright_sync` (before line 208):**

```python
import random

_MAX_RETRIES = 3
_BASE_BACKOFF = 1.0  # seconds
_MAX_BACKOFF = 8.0


def _search_with_retry(
    query: str, lat: float, lng: float, max_items: int
) -> list[dict]:
    """Retry-wrapper around _search_via_playwright_sync with exponential backoff.

    Circuit breaker check → retry loop → record success/failure.
    Returns [] if circuit is open or all retries exhausted.
    """
    if not _naver_circuit.allow_request():
        logger.warning("[네이버 검색] 서킷브레이커 OPEN — 스크래핑 건너뜀")
        return []

    last_exc = None
    for attempt in range(_MAX_RETRIES):
        try:
            items = _search_via_playwright_sync(query, lat, lng, max_items)
            # Empty result on first attempt is OK (no results found);
            # but if it's a retry after failure, still counts as "recovered"
            _naver_circuit.record_success()
            return items
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "[네이버 검색] attempt %d/%d failed: %s",
                attempt + 1, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES - 1:
                backoff = min(
                    _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5),
                    _MAX_BACKOFF,
                )
                time.sleep(backoff)

    # All retries exhausted
    _naver_circuit.record_failure()
    logger.error(
        "[네이버 검색] %d회 재시도 모두 실패: %s", _MAX_RETRIES, last_exc
    )
    return []
```

**Modify `_search_via_playwright_sync` (line 262–264)** to **raise** instead of silently returning `[]`:

**Current code (lines 262–264):**
```python
    except Exception as exc:
        logger.warning(f"[네이버 검색] Playwright 크롤링 실패: {exc}")
        return items
```

**New code:**
```python
    except Exception as exc:
        logger.warning("[네이버 검색] Playwright 크롤링 실패: %s", exc)
        raise  # Let retry wrapper handle it
```

### 1.3 Update All Call Sites

Every call to `_search_via_playwright_sync` must go through `_search_with_retry` instead.

**Call site 1 — `/naver-search` endpoint (lines 348–352):**

Current:
```python
    async def _do_search():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor, _search_via_playwright_sync, query, lat, lng, max_items,
        )
```

New:
```python
    async def _do_search():
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            _executor, _search_with_retry, query, lat, lng, max_items,
        )
```

**Call site 2 — `_search_single_category_sync` (line 592):**

Current:
```python
    items = _search_via_playwright_sync(query, lat, lng, max_items)
```

New:
```python
    items = _search_with_retry(query, lat, lng, max_items)
```

**Call site 3 — `/subcategory-search` endpoint** (scan for any direct calls to `_search_via_playwright_sync` in the file and replace with `_search_with_retry`).

### 1.4 Browser Crash Recovery in `_BrowserPool`

**File:** `packages/website/backend/api/routes/naver_local.py`

The `get_browser()` method (line 135–149) already checks `is_connected()` and recreates if dead. However, if `chromium.launch()` itself throws (e.g., Playwright binary missing, system OOM), the exception propagates unhandled.

**Current code (lines 135–149):**
```python
    def get_browser(self):
        with self._lock:
            self._last_used = time.time()
            if self._browser and self._browser.is_connected():
                return self._browser
            self._cleanup()
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._schedule_cleanup()
            return self._browser
```

**New code:**
```python
    def get_browser(self):
        """Return a connected browser. Recreate on crash. Raise on launch failure."""
        with self._lock:
            self._last_used = time.time()
            if self._browser:
                try:
                    if self._browser.is_connected():
                        return self._browser
                except Exception:
                    pass  # is_connected() itself crashed → browser is dead
            # Browser is dead or missing — full restart
            self._cleanup()
            try:
                from playwright.sync_api import sync_playwright
                self._pw = sync_playwright().start()
                self._browser = self._pw.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
            except Exception as exc:
                logger.error("[BrowserPool] 브라우저 시작 실패: %s", exc)
                self._cleanup()
                raise
            self._schedule_cleanup()
            return self._browser

    def is_healthy(self) -> bool:
        """Check if the browser pool can serve requests (for health check)."""
        with self._lock:
            if self._browser is None:
                return True  # No browser running is OK (will lazy-start)
            try:
                return self._browser.is_connected()
            except Exception:
                return False
```

### 1.5 Replace Unbounded `_cache` Dict

**File:** `packages/website/backend/api/routes/naver_local.py`

**Current code (lines 186–205):**
```python
_cache: dict[str, tuple[float, object]] = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 300

def _cache_get(key: str):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < _CACHE_TTL:
            return entry[1]
        if entry:
            del _cache[key]
    return None

def _cache_set(key: str, value):
    with _cache_lock:
        _cache[key] = (time.time(), value)
```

**New code — replace entirely:**
```python
# Bounded cache for geocode + area-explore results (replaces raw dict)
_geo_area_cache = TTLCache(ttl_seconds=300, max_size=256)


def _cache_get(key: str):
    """TTL cache lookup — delegates to bounded TTLCache."""
    return _geo_area_cache.get(key)


def _cache_set(key: str, value):
    """TTL cache store — delegates to bounded TTLCache."""
    _geo_area_cache.set(key, value)
```

This removes the `_cache` dict, `_cache_lock`, and `_CACHE_TTL` variables. The `TTLCache` class (already imported on line 30) handles TTL, max size, and thread safety internally.

---

## 2. SSE Disconnect Detection

### Audit Findings

| ID | Issue | Severity |
|----|-------|----------|
| S-05 | Client disconnection not detected — all categories continue processing in executor after disconnect | 🔴 CRITICAL |
| S-06 | No per-category timeout wrapper — one hanging category blocks the entire SSE stream | 🟠 HIGH |

### 2.1 Detect Disconnect + Cancel Ongoing Work

**File:** `packages/website/backend/api/routes/naver_local.py`

The SSE endpoint uses `StreamingResponse` with an async generator. Starlette raises `asyncio.CancelledError` when the client disconnects. Additionally, we need `request.is_disconnected()` checks.

**Current SSE endpoint (lines 608–661):**
```python
@router.get("/area-explore-stream")
async def area_explore_stream(
    location_name: str = Query(None, description="장소명"),
    lat: float = Query(None, description="위도"),
    lng: float = Query(None, description="경도"),
    categories: str = Query(_DEFAULT_CATEGORIES, description="콤마 구분 카테고리"),
    max_items: int = Query(30, ge=1, le=50, description="카테고리당 최대 결과 수"),
):
    # ... geocoding logic (lines 617–633) remains unchanged ...

    cat_list = [c.strip() for c in categories.split(",") if c.strip()]

    async def event_generator():
        loop = asyncio.get_event_loop()
        for i, cat in enumerate(cat_list):
            try:
                result = await loop.run_in_executor(
                    _executor,
                    _search_single_category_sync,
                    location_name, lat, lng, cat, max_items,
                )
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
            except Exception as exc:
                logger.error(f"[SSE] 카테고리 '{cat}' 검색 실패: {exc}")
                yield f"data: ..."
            if i < len(cat_list) - 1:
                await asyncio.sleep(1)
        yield f"data: {json.dumps({'done': True, ...})}\n\n"

    return StreamingResponse(event_generator(), ...)
```

**New code — full replacement of the endpoint function body starting at line 637:**

```python
from starlette.requests import Request as StarletteRequest

@router.get("/area-explore-stream")
async def area_explore_stream(
    request: StarletteRequest,  # ← ADD request parameter for disconnect detection
    location_name: str = Query(None, description="장소명"),
    lat: float = Query(None, description="위도"),
    lng: float = Query(None, description="경도"),
    categories: str = Query(_DEFAULT_CATEGORIES, description="콤마 구분 카테고리"),
    max_items: int = Query(30, ge=1, le=50, description="카테고리당 최대 결과 수"),
):
    """SSE 스트리밍: 카테고리별 결과를 하나씩 반환하여 프론트엔드에서 점진적 로딩."""
    if not location_name and (lat is None or lng is None):
        async def error_gen():
            yield f"data: {json.dumps({'error': 'location_name 또는 lat/lng 좌표를 제공해야 합니다'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(error_gen(), media_type="text/event-stream")

    if location_name and (lat is None or lng is None):
        loop = asyncio.get_event_loop()
        geo = await loop.run_in_executor(_executor, _geocode_sync, location_name)
        if geo and geo.get("lat") and geo.get("lng"):
            lat = geo["lat"]
            lng = geo["lng"]
        else:
            lat = lat or 37.5665
            lng = lng or 126.9780

    if not location_name:
        location_name = ""

    cat_list = [c.strip() for c in categories.split(",") if c.strip()]

    async def event_generator():
        loop = asyncio.get_event_loop()
        for i, cat in enumerate(cat_list):
            # ── Disconnect check: stop sending if client is gone ──
            if await request.is_disconnected():
                logger.info("[SSE] 클라이언트 연결 끊김, 스트림 중단")
                return

            try:
                # ── Per-category timeout: 35s max per category ──
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        _executor,
                        _search_single_category_sync,
                        location_name, lat, lng, cat, max_items,
                    ),
                    timeout=35.0,
                )
                yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                logger.warning("[SSE] 카테고리 '%s' 타임아웃 (35s)", cat)
                yield f"data: {json.dumps({'name': cat, 'icon': '⏰', 'count': 0, 'items': [], 'error': 'timeout'}, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                logger.info("[SSE] 클라이언트 연결 끊김 (CancelledError), 스트림 중단")
                return
            except Exception as exc:
                logger.error("[SSE] 카테고리 '%s' 검색 실패: %s", cat, exc)
                yield f"data: {json.dumps({'name': cat, 'icon': '❌', 'count': 0, 'items': [], 'error': str(exc)}, ensure_ascii=False)}\n\n"

            # ban 방지: 카테고리 간 1초 간격
            if i < len(cat_list) - 1:
                await asyncio.sleep(1)

        yield f"data: {json.dumps({'done': True, 'location_name': location_name, 'lat': lat, 'lng': lng}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Key changes:**
1. Added `request: StarletteRequest` parameter to access `is_disconnected()`
2. Added `await request.is_disconnected()` check before each category
3. Wrapped executor call in `asyncio.wait_for(timeout=35.0)` — prevents indefinite hang
4. Added `asyncio.CancelledError` handler — Starlette raises this on client disconnect during `yield`
5. `TimeoutError` yields a structured error event so the frontend knows which category timed out

---

## 3. Circuit Breaker for DB Admin API

### Audit Finding

The website backend calls `storage.*` methods (backed by the db-admin `DBStorage` class) without any circuit-breaking. If the DB is down, every request still attempts a full query.

### 3.1 DB Admin Circuit Breaker

**File:** `packages/website/backend/api/utils/cache.py` (no changes needed — `CircuitBreaker` already exists)

**File:** `packages/website/backend/api/app.py`

Wrap the `storage` proxy with a circuit breaker at the app factory level. Rather than modifying every route, we create a lightweight wrapper that short-circuits when the DB is unreachable.

**New file:** `packages/website/backend/api/utils/storage_proxy.py`

```python
"""
Storage proxy with circuit breaker for db-admin API calls.

Wraps the DBStorage instance so that repeated DB failures
trigger fast-fail instead of hammering a dead database.
"""

import logging
from typing import Any
from api.utils.cache import CircuitBreaker

logger = logging.getLogger(__name__)

# 3 failures → 30s cooldown before retrying DB
_db_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=30)


class StorageProxy:
    """Transparent proxy around DBStorage with circuit breaker.

    All attribute access is forwarded to the underlying storage.
    Method calls are wrapped: if the circuit is open, they return
    a sensible default (empty list/dict) instead of attempting DB access.
    """

    def __init__(self, storage):
        self._storage = storage

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._storage, name)
        if not callable(attr):
            return attr

        def guarded(*args, **kwargs):
            if not _db_circuit.allow_request():
                logger.warning(
                    "[StorageProxy] 서킷 OPEN — %s() 호출 건너뜀", name
                )
                return []  # Safe default for list-returning methods
            try:
                result = attr(*args, **kwargs)
                _db_circuit.record_success()
                return result
            except Exception:
                _db_circuit.record_failure()
                logger.exception(
                    "[StorageProxy] %s() 실패 (failures=%d/%d)",
                    name,
                    _db_circuit._failure_count,
                    _db_circuit._failure_threshold,
                )
                raise

        return guarded

    @property
    def circuit_state(self) -> str:
        """Expose circuit state for health check."""
        return _db_circuit.state

    def __bool__(self):
        """Allow `if storage:` checks to work like the original."""
        return self._storage is not None
```

### 3.2 Wire Proxy into App Factory

**File:** `packages/website/backend/api/app.py`

**Current code (line 107–112):**
```python
            storage = DBStorage(f"sqlite:///{db_path}")
            storage.init_db()
            logging.info(f"✅ DB 연결 성공: {db_path}")
        except Exception as e:
            logging.warning(f"DB 연결 실패, mock 데이터 사용: {e}")
            storage = None
```

**New code:**
```python
            storage = DBStorage(f"sqlite:///{db_path}")
            storage.init_db()
            logging.info("✅ DB 연결 성공: %s", db_path)

            # Wrap with circuit breaker proxy
            from api.utils.storage_proxy import StorageProxy
            storage = StorageProxy(storage)
        except Exception as e:
            logging.warning("DB 연결 실패, mock 데이터 사용: %s", e)
            storage = None
```

**Why a proxy instead of decorators on each route:**
- Zero changes to existing route code — all `storage.search_products()`, `storage.get_hotdeals()` etc. calls work identically
- Circuit breaker state is shared across all DB calls
- Health check can query `storage.circuit_state`

---

## 4. Health Check Endpoint

### Audit Finding

Current `/api/health` (app.py line 178–181) returns a static `{"status": "ok"}` with no actual checks.

### 4.1 Enhanced Health Check

**File:** `packages/website/backend/api/app.py`

**Current code (lines 178–181):**
```python
    @app.get("/api/health")
    def health():
        """헬스체크 — 로드밸런서·모니터링용."""
        return {"status": "ok", "version": "0.1.0"}
```

**New code:**
```python
    import psutil

    @app.get("/api/health")
    async def health():
        """헬스체크 — DB, Playwright 브라우저, 메모리 상태 확인."""
        checks: dict = {}
        overall = "ok"

        # 1. DB connectivity
        storage = app.state.storage
        if storage is not None:
            try:
                # StorageProxy exposes circuit_state
                circuit = getattr(storage, "circuit_state", "unknown")
                if circuit == "open":
                    checks["db"] = {"status": "degraded", "circuit": "open"}
                    overall = "degraded"
                else:
                    # Quick probe: list 1 product
                    storage.search_products("", per_page=1)
                    checks["db"] = {"status": "ok", "circuit": circuit}
            except Exception as e:
                checks["db"] = {"status": "error", "error": str(e)}
                overall = "error"
        else:
            checks["db"] = {"status": "disconnected"}
            overall = "degraded"

        # 2. Playwright browser pool
        try:
            from api.routes.naver_local import _pool, _naver_circuit
            browser_ok = _pool.is_healthy()
            naver_circuit = _naver_circuit.state
            checks["playwright"] = {
                "status": "ok" if browser_ok else "error",
                "circuit": naver_circuit,
            }
            if not browser_ok or naver_circuit == "open":
                overall = "degraded" if overall == "ok" else overall
        except Exception as e:
            checks["playwright"] = {"status": "error", "error": str(e)}

        # 3. Memory usage
        try:
            process = psutil.Process()
            mem_info = process.memory_info()
            mem_mb = round(mem_info.rss / (1024 * 1024), 1)
            mem_status = "ok" if mem_mb < 512 else ("warning" if mem_mb < 1024 else "critical")
            checks["memory"] = {
                "status": mem_status,
                "rss_mb": mem_mb,
            }
            if mem_status != "ok":
                overall = "degraded" if overall == "ok" else overall
        except Exception:
            checks["memory"] = {"status": "unknown"}

        status_code = 200 if overall == "ok" else (200 if overall == "degraded" else 503)
        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall,
                "version": "0.1.0",
                "checks": checks,
            },
        )
```

### 4.2 New Dependency

Add `psutil` to `requirements.txt`:

```
psutil>=5.9.0
```

---

## 5. Unbounded Query Limits

### Audit Findings

| ID | Issue | Severity |
|----|-------|----------|
| S-27 | `restaurants.py` — `select(Restaurant)` loads ALL rows, no LIMIT | 🔴 CRITICAL |
| S-28 | `products.py` — `search_products("", per_page=500)` loads 500 into memory | 🟠 HIGH |
| S-09 | No timeout on SQLAlchemy queries | 🟠 HIGH |

### 5.1 Restaurants — Add LIMIT and Pagination

**File:** `packages/website/backend/api/routes/restaurants.py`

**Current code (lines 25–73):**
```python
@router.get("/restaurants/nearby")
async def nearby_restaurants(
    request: Request,
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    radius: int = Query(5000, ge=100, le=50000, description="반경 (미터)"),
    category: str = Query(None, description="카테고리 필터"),
    sort: str = Query("distance", description="정렬"),
):
    storage = request.app.state.storage
    if storage is not None:
        try:
            from sqlalchemy import select
            from storage.models import Restaurant
            with storage.SessionLocal() as session:
                stmt = select(Restaurant)
                rows = session.execute(stmt).scalars().all()
                # ... python-side filter/sort ...
```

**New code:**
```python
_MAX_RESTAURANT_RESULTS = 200  # Hard cap on results
_DEFAULT_RESTAURANT_LIMIT = 50

@router.get("/restaurants/nearby")
async def nearby_restaurants(
    request: Request,
    lat: float = Query(37.4979, description="위도"),
    lng: float = Query(127.0276, description="경도"),
    radius: int = Query(5000, ge=100, le=50000, description="반경 (미터)"),
    category: str = Query(None, description="카테고리 필터"),
    sort: str = Query("distance", description="정렬"),
    limit: int = Query(_DEFAULT_RESTAURANT_LIMIT, ge=1, le=_MAX_RESTAURANT_RESULTS, description="최대 결과 수"),
):
    storage = request.app.state.storage
    if storage is not None:
        try:
            from sqlalchemy import select
            from storage.models import Restaurant
            with storage.SessionLocal() as session:
                stmt = select(Restaurant).limit(1000)  # DB-level safety cap
                rows = session.execute(stmt).scalars().all()
                results = []
                for r in rows:
                    if r.lat and r.lng:
                        dist = _haversine(lat, lng, r.lat, r.lng)
                        if dist > radius:
                            continue
                    else:
                        dist = 0
                    entry = {
                        "id": r.id,
                        "name": r.name,
                        "category": r.category or "",
                        "address": r.address or "",
                        "lat": r.lat,
                        "lng": r.lng,
                        "avg_price": 0,
                        "rating": r.rating or 0,
                        "review_count": r.review_count or 0,
                        "distance": round(dist),
                    }
                    if category and entry["category"] != category:
                        continue
                    results.append(entry)
                if sort == "rating":
                    results.sort(key=lambda x: x.get("rating", 0), reverse=True)
                elif sort == "price_asc":
                    results.sort(key=lambda x: x.get("avg_price", float("inf")))
                else:
                    results.sort(key=lambda x: x["distance"])

                # Apply client-requested limit after sort
                results = results[:limit]
                return ApiResponse(data=results)
        except Exception:
            pass
    return ApiResponse(data=[])
```

**Key changes:**
1. `select(Restaurant).limit(1000)` — DB-level safety cap prevents OOM on huge tables
2. `limit` query parameter (default 50, max 200) — client controls result size
3. `results[:limit]` after sort — final truncation

### 5.2 Products — Reduce Category Summary Load

**File:** `packages/website/backend/api/routes/products.py`

**Current code (line 182):**
```python
        all_products = storage.search_products("", per_page=500)
```

**New code:**
```python
        # Cap at 100 products for aggregation — sufficient for category summary
        all_products = storage.search_products("", per_page=100)
```

**Rationale:** The category-summary endpoint computes min/avg/max per category. 100 products (vs 500) is sufficient for representative stats and reduces memory by 5×.

### 5.3 Dashboard — Add LIMIT to All Calls

**File:** `packages/website/backend/api/app.py`

All dashboard queries already use `per_page=10` or similar. Verify and leave unchanged. ✅

### 5.4 Hotdeals List — Already Bounded

**File:** `packages/website/backend/api/routes/hotdeals.py`

Line 49: `per_page: int = Query(20, ge=1, le=100)` — already bounded. ✅

### 5.5 Community Posts — Already Bounded

**File:** `packages/website/backend/api/routes/community.py`

Line 171: `posts = stmt.offset(offset).limit(per_page).all()` — already paginated. ✅

---

## 6. In-Memory User Store (Tech Debt Flag)

### Audit Finding

| ID | Issue | Severity |
|----|-------|----------|
| S-19 | `_users_db` is module-level dict with race conditions; `_next_id` incremented without locks | 🔴 CRITICAL |

### 6.1 Flag as Tech Debt

**File:** `packages/website/backend/api/routes/auth.py`

**Add comment block at lines 22–24 (where `_users_db` is defined):**

```python
# ═══════════════════════════════════════════════════════════════════
# ⚠️  TECH DEBT: In-memory user store
#
# Known issues (audit S-19):
#   - _users_db is a plain dict — data lost on restart
#   - _next_id has no lock — concurrent registrations can get same ID
#   - No duplicate email check is atomic (TOCTOU race)
#
# Proper fix requires:
#   1. SQLAlchemy User model (like community.py's UserModel)
#   2. DB migration via Alembic
#   3. Unique constraint on email column
#   4. Auto-increment PK replaces _next_id
#
# This is OUT OF SCOPE for the current stability sprint.
# Tracked as: WALLET-AUTH-DB-MIGRATION
# ═══════════════════════════════════════════════════════════════════
_users_db: dict[str, dict] = {}  # email → user object
_next_id = 1
```

### 6.2 Minimal Safety: Add Threading Lock

While the full DB migration is out of scope, add a lock to prevent the worst race condition:

**File:** `packages/website/backend/api/routes/auth.py`

**Add after line 24:**
```python
_users_lock = threading.Lock()
```

**Add import at top of file:**
```python
import threading
```

**Wrap register endpoint's critical section (lines 33–49) in lock:**

In the `register` function, wrap the check-and-insert logic:

```python
@router.post("/api/auth/register")
async def register(data: RegisterRequest):
    global _next_id
    with _users_lock:
        if data.email in _users_db:
            raise HTTPException(409, "이미 등록된 이메일입니다")
        # ... nickname uniqueness check ...
        user = {
            "id": _next_id,
            "email": data.email,
            # ...
        }
        _users_db[data.email] = user
        _next_id += 1
    # Token generation can be outside the lock
    return create_token_pair(user["id"], user["email"], user["role"])
```

---

## 7. Structured Logging

### Audit Finding

Multiple files use `print()` statements and f-string interpolation in log calls. Replace with structured `logging` using `%s` format (lazy evaluation) and consistent naming.

### 7.1 Logging Configuration

**New file:** `packages/website/backend/api/logging_config.py`

```python
"""
Structured logging configuration for the website backend.

JSON format in production, human-readable in development.
"""

import logging
import logging.config
import os
import json
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    """Configure logging based on environment."""
    env = os.getenv("ENV", "development").lower()
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    if env == "production":
        formatter_class = "api.logging_config.JSONFormatter"
        format_str = None
    else:
        formatter_class = None
        format_str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": formatter_class,
            } if formatter_class else {
                "format": format_str,
                "datefmt": "%H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.access": {"level": "WARNING"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "playwright": {"level": "WARNING"},
        },
    }

    logging.config.dictConfig(config)
```

### 7.2 Wire Logging into main.py

**File:** `packages/website/backend/main.py`

**Current code (lines 1–11):**
```python
from api.app import create_app
from config import API_HOST, API_PORT

app = create_app()
```

**New code:**
```python
from api.logging_config import setup_logging
setup_logging()

from api.app import create_app
from config import API_HOST, API_PORT

app = create_app()
```

### 7.3 Replace print() and f-string Logs

Scan all backend files for `print(` statements and `logger.xxx(f"..."` f-string patterns. Replace with `%s` lazy formatting.

**Files to update (representative examples):**

**`api/app.py` line 109:**
```python
# Current:
logging.info(f"✅ DB 연결 성공: {db_path}")
# New:
logging.info("DB 연결 성공: %s", db_path)
```

**`api/app.py` line 111:**
```python
# Current:
logging.warning(f"DB 연결 실패, mock 데이터 사용: {e}")
# New:
logging.warning("DB 연결 실패, mock 데이터 사용: %s", e)
```

**`api/routes/naver_local.py` — all `logger.xxx(f"...")` calls:**

Grep for `logger\.\w+\(f"` across all `.py` files and replace `f"..."` with `"...", args`.

**Full replacement list (apply mechanically):**

| File | Pattern | Replacement |
|------|---------|-------------|
| `naver_local.py` | `logger.warning(f"[네이버 검색] Playwright 크롤링 실패: {exc}")` | `logger.warning("[네이버 검색] Playwright 크롤링 실패: %s", exc)` |
| `naver_local.py` | `logger.error(f"[SSE] 카테고리 '{cat}' 검색 실패: {exc}")` | `logger.error("[SSE] 카테고리 '%s' 검색 실패: %s", cat, exc)` |
| `naver_local.py` | All other `f"` log calls | Same pattern: `%s` + args |
| `flyer_service.py` | Any `f"` log calls | Same pattern |
| `oauth_service.py` | Any `f"` log calls | Same pattern |

**Implementation approach:** Use a single grep + sed pass or IDE find-and-replace. The pattern is mechanical:

```
# Find:    logger.XXX(f"...{var}...")
# Replace: logger.XXX("...%s...", var)
```

---

## 8. Graceful Shutdown

### Audit Findings

| ID | Issue | Severity |
|----|-------|----------|
| S-03 | `ThreadPoolExecutor` never `shutdown()` | 🟡 MEDIUM |

### 8.1 Lifespan Context Manager

**File:** `packages/website/backend/api/app.py`

FastAPI supports `lifespan` async context managers for startup/shutdown. This replaces the need for `atexit`.

**Add to `app.py` — new `lifespan` function before `create_app`:**

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle."""
    logger.info("서버 시작 — 리소스 초기화")
    yield
    # ── Shutdown ──
    logger.info("서버 종료 — 리소스 정리 시작")

    # 1. Shutdown Playwright browser pool
    try:
        from api.routes.naver_local import _pool, _executor
        _pool._cleanup()
        logger.info("Playwright 브라우저 풀 정리 완료")
    except Exception:
        logger.exception("Playwright 정리 중 오류")

    # 2. Shutdown ThreadPoolExecutor
    try:
        _executor.shutdown(wait=True, cancel_futures=True)
        logger.info("ThreadPoolExecutor 종료 완료")
    except Exception:
        logger.exception("ThreadPoolExecutor 종료 중 오류")

    logger.info("서버 종료 — 리소스 정리 완료")
```

**Modify `create_app` (line 54) to use lifespan:**

```python
# Current:
    app = FastAPI(
        title="지갑 지키미 API",
        ...
    )

# New:
    app = FastAPI(
        title="지갑 지키미 API",
        description="물가 비교 서비스 백엔드 — 정부 공공데이터 + 마트 할인 + 커뮤니티 핫딜",
        version="0.1.0",
        docs_url="/docs" if is_debug else None,
        redoc_url="/redoc" if is_debug else None,
        openapi_url="/openapi.json" if is_debug else None,
        lifespan=lifespan,  # ← ADD
    )
```

### 8.2 BrowserPool `force_cleanup` Method

**File:** `packages/website/backend/api/routes/naver_local.py`

The existing `_cleanup` method is private. Add a public alias for the lifespan hook:

```python
    def force_cleanup(self):
        """Public cleanup for shutdown hook. Cancels timer + closes browser."""
        with self._lock:
            if self._cleanup_timer:
                self._cleanup_timer.cancel()
                self._cleanup_timer = None
            self._cleanup()
```

Update the lifespan to use `force_cleanup`:
```python
    _pool.force_cleanup()
```

---

## 9. New Dependencies

**File:** `packages/website/backend/requirements.txt`

**Add:**
```
psutil>=5.9.0
```

**No other new deps needed.** Retry logic is implemented manually (no `tenacity` needed for the simple 3-retry loop). Circuit breaker already exists in `api/utils/cache.py`.

---

## 10. Test Cases

### 10.1 Naver Scraping Recovery Tests

**File:** `packages/website/backend/tests/test_naver_scraping.py`

| Test | Description | Assertion |
|------|-------------|-----------|
| `test_retry_succeeds_on_second_attempt` | Mock `_search_via_playwright_sync` to fail once then succeed | Returns items, circuit stays CLOSED |
| `test_retry_exhausted_returns_empty` | Mock to fail 3 times | Returns `[]`, circuit records failure |
| `test_circuit_breaker_opens_after_threshold` | Trigger 5 consecutive failures | `_naver_circuit.state == "open"` |
| `test_circuit_breaker_rejects_when_open` | Set circuit to OPEN | `_search_with_retry` returns `[]` without calling Playwright |
| `test_circuit_breaker_recovers_after_timeout` | Set circuit OPEN, advance time 120s, then succeed | Circuit returns to CLOSED |
| `test_browser_pool_crash_recovery` | Mock `chromium.launch` to fail once then succeed | Second `get_browser()` call succeeds |
| `test_browser_pool_is_healthy` | Normal state vs crashed browser | `is_healthy()` returns correct boolean |

### 10.2 SSE Disconnect Tests

**File:** `packages/website/backend/tests/test_sse_disconnect.py`

| Test | Description | Assertion |
|------|-------------|-----------|
| `test_sse_stops_on_disconnect` | Mock `request.is_disconnected()` to return True after 1st category | Generator yields ≤1 result |
| `test_sse_per_category_timeout` | Mock `_search_single_category_sync` to hang 40s | Receives `'error': 'timeout'` event within 36s |
| `test_sse_normal_flow` | 3 categories, all succeed | 3 result events + 1 done event |
| `test_sse_partial_failure` | 2nd category raises exception | 1st and 3rd succeed, 2nd has error |

### 10.3 Circuit Breaker for DB Tests

**File:** `packages/website/backend/tests/test_storage_proxy.py`

| Test | Description | Assertion |
|------|-------------|-----------|
| `test_proxy_passes_through_on_success` | Call `search_products` | Returns same result as underlying storage |
| `test_proxy_records_failure_and_opens` | Storage raises 3 times | Circuit opens, 4th call returns `[]` |
| `test_proxy_recovers_after_timeout` | Open circuit → wait → succeed | Circuit returns to CLOSED |
| `test_proxy_bool_truthiness` | `if storage:` check | Returns True when underlying is not None |
| `test_circuit_state_exposed` | After failures | `storage.circuit_state == "open"` |

### 10.4 Health Check Tests

**File:** `packages/website/backend/tests/test_health.py`

| Test | Description | Assertion |
|------|-------------|-----------|
| `test_health_ok` | DB connected, browser healthy, memory OK | `status: "ok"`, HTTP 200 |
| `test_health_degraded_no_db` | `storage = None` | `status: "degraded"`, HTTP 200 |
| `test_health_degraded_circuit_open` | DB circuit breaker OPEN | `checks.db.circuit: "open"` |
| `test_health_memory_warning` | Mock `psutil` to report 600 MB | `checks.memory.status: "warning"` |

### 10.5 Unbounded Query Tests

| Test | Description | Assertion |
|------|-------------|-----------|
| `test_restaurants_respects_limit_param` | `?limit=5` | Returns ≤5 results |
| `test_restaurants_default_limit` | No limit param | Returns ≤50 results |
| `test_restaurants_max_limit` | `?limit=999` | Capped at 200 |
| `test_category_summary_bounded` | Call category-summary | `per_page=100` passed to `search_products` |

---

## 11. Migration Checklist

Implementation order (dependencies flow top→down):

```
Step  Task                                        File(s)                           Est.
────  ──────────────────────────────────────────  ──────────────────────────────    ────
 1    Add logging_config.py + wire into main.py   logging_config.py, main.py        30m
 2    Replace f-string logs with %s format        All .py files (grep + replace)    30m
 3    Add circuit breaker + retry to naver_local  naver_local.py                    60m
 4    Replace unbounded _cache with TTLCache      naver_local.py                    15m
 5    Add BrowserPool crash recovery + is_healthy  naver_local.py                   20m
 6    SSE disconnect detection + timeout          naver_local.py                    45m
 7    Add StorageProxy with circuit breaker       storage_proxy.py, app.py          30m
 8    Enhanced health check                       app.py                            30m
 9    Add LIMIT to restaurants query               restaurants.py                   15m
10    Reduce category-summary load                products.py                       5m
11    Flag in-memory user store + add lock        auth.py                           15m
12    Add lifespan (graceful shutdown)            app.py, naver_local.py            30m
13    Add psutil dependency                       requirements.txt                  5m
14    Write tests                                 tests/                            90m
────                                                                               ─────
                                                                     Total:       ~6 hrs
```

### Pre-Implementation Checklist

- [ ] `pip install psutil` in the backend virtualenv
- [ ] Run existing tests: `cd packages/website/backend && python -m pytest tests/`
- [ ] Verify Playwright is installed: `python -c "from playwright.sync_api import sync_playwright"`

### Post-Implementation Verification

- [ ] All existing tests pass (`pytest tests/`)
- [ ] New tests pass (`pytest tests/test_naver_scraping.py tests/test_sse_disconnect.py tests/test_storage_proxy.py tests/test_health.py`)
- [ ] `/api/health` returns correct status for each subsystem
- [ ] Manual SSE test: open `/api/local/area-explore-stream?location_name=강남`, close browser mid-stream, verify server logs show "클라이언트 연결 끊김"
- [ ] Kill DB, verify circuit breaker opens and subsequent requests fail fast
- [ ] `Ctrl+C` the server, verify "리소스 정리 완료" appears in logs
- [ ] No `print()` statements remain in backend code

### Files Created

| File | Purpose |
|------|---------|
| `api/utils/storage_proxy.py` | StorageProxy with circuit breaker |
| `api/logging_config.py` | Structured logging configuration |

### Files Modified

| File | Changes |
|------|---------|
| `main.py` | Add `setup_logging()` call |
| `api/app.py` | Add `lifespan`, wrap storage in proxy, enhance `/api/health` |
| `api/routes/naver_local.py` | Circuit breaker, retry, SSE disconnect, cache fix, `force_cleanup`, `is_healthy` |
| `api/routes/restaurants.py` | Add `.limit(1000)` + `limit` query param |
| `api/routes/products.py` | Reduce `per_page=500` → `per_page=100` |
| `api/routes/auth.py` | Tech debt comment + threading lock |
| `requirements.txt` | Add `psutil>=5.9.0` |
