# Website Stability Audit

**Project:** WalletSavior — Website Sub-project  
**Date:** 2025-07-15  
**Scope:** Backend (FastAPI :8000) + Frontend (React/Vite :5173)  
**Auditor:** Copilot Stability Planner

---

## Executive Summary

| Severity | Count | Key Examples |
|----------|-------|-------------|
| 🔴 CRITICAL | 11 | Auth race conditions, XSS in community rendering, no Error Boundary, SSE disconnect leak, unbounded DB queries |
| 🟠 HIGH | 14 | Bare `except` clauses, cache stampede, rate-limiter memory leak, missing image fallbacks, polling leak |
| 🟡 MEDIUM | 16 | Toast auto-dismiss bug, stale localStorage hydration, missing retry logic, activeIndex desync |
| 🟢 LOW / ✅ | — | Strong sanitization (nh3 + DOMPurify), good hooks library, proper abort patterns, Zustand immutability |

The application has solid foundations (good sanitization, request deduplication, abort controllers) but lacks defensive layers: no error boundaries, no retry logic, no circuit breakers on scraping, and several race conditions in shared in-memory state.

---

## Table of Contents

1. [Naver Scraping Stability](#1-naver-scraping-stability)
2. [SSE Streaming](#2-sse-streaming)
3. [API Resilience](#3-api-resilience)
4. [Frontend Error Handling](#4-frontend-error-handling)
5. [State Management](#5-state-management)
6. [Authentication Stability](#6-authentication-stability)
7. [Navigation](#7-navigation)
8. [Large Data Sets](#8-large-data-sets)
9. [Image Loading](#9-image-loading)
10. [Offline Behavior](#10-offline-behavior)
11. [Cross-Browser](#11-cross-browser)
12. [Memory Leaks](#12-memory-leaks)
13. [Finding Registry](#13-finding-registry)
14. [Remediation Priorities](#14-remediation-priorities)

---

## 1. Naver Scraping Stability

**Files:** `backend/api/routes/naver_local.py`, `backend/services/flyer_service.py`

### 1.1 Browser Lifecycle

The scraping layer uses a custom `_BrowserPool` with a lock-protected singleton Chromium instance, idle-timeout cleanup (300 s), and per-request context creation.

**What works:**
- Context is closed in a `finally` block — pages are always cleaned up.
- Browser pool is thread-safe (`threading.Lock`).
- Idle-timeout auto-closes browser after 300 s inactivity.

**What doesn't:**

| ID | Issue | Severity |
|----|-------|----------|
| S-01 | **No retry logic.** A single Playwright timeout → empty results returned to user. No fallback, no exponential back-off. | 🔴 CRITICAL |
| S-02 | **No circuit breaker on Naver scraping.** Repeated Naver blocks or CAPTCHA challenges are not detected — every request still attempts full browser automation. `flyer_service.py` has a circuit breaker; `naver_local.py` does not. | 🟠 HIGH |
| S-03 | **ThreadPoolExecutor never shut down.** `_executor = ThreadPoolExecutor(max_workers=4)` is a module-level global; no `atexit` or shutdown hook. On app restart threads may leak. | 🟡 MEDIUM |
| S-04 | **Stealth is basic.** Only `navigator.webdriver` override + UA spoofing. No fingerprint randomization (canvas, WebGL, fonts), no mouse/scroll simulation, no proxy rotation. Naver detection likely to evolve. | 🟠 HIGH |

### 1.2 Timeouts

| Operation | Timeout | Assessment |
|-----------|---------|-----------|
| `page.goto()` | 20 s | ✅ Acceptable |
| API response poll | 10 s (100 ms intervals) | ✅ Acceptable |
| `context.new_page()` | None | ⚠️ Could hang |
| `page.add_init_script()` | None | ⚠️ Could hang |
| Overall per-request | ~30 s combined | ✅ Acceptable |

### 1.3 Cache

`naver_local.py` uses two caches:
- `_search_cache = TTLCache(ttl_seconds=300, max_size=128)` — ✅ bounded.
- `_cache: dict[str, tuple[float, object]] = {}` — ❌ **unbounded**; entries expire on access only; never-reaccessed keys persist forever.

**Recommendation:** Replace raw dict cache with `TTLCache` or add periodic eviction via background task.

---

## 2. SSE Streaming

**Files:** `backend/api/routes/naver_local.py` (`/area-explore-stream`), `frontend/src/services/localService.js`

### 2.1 Backend

| ID | Issue | Severity |
|----|-------|----------|
| S-05 | **Client disconnection not detected.** The `event_generator()` `async for` loop yields events but never checks if the client closed the connection. All categories continue processing in `ThreadPoolExecutor` even after disconnect. | 🔴 CRITICAL |
| S-06 | **No per-category timeout wrapper.** If one category hangs (e.g., Naver returns a CAPTCHA page), the SSE stream blocks for up to 30 s before continuing to the next category. No `asyncio.wait_for()`. | 🟠 HIGH |
| S-07 | **1-second inter-category delay is arbitrary.** No adaptive throttling based on Naver response codes. | 🟡 MEDIUM |

**Recommendation (S-05):** Wrap the generator in a try/except for `asyncio.CancelledError` or `starlette.requests.ClientDisconnect`:

```python
async def event_generator():
    for cat in cat_list:
        if await request.is_disconnected():
            logger.info("Client disconnected, stopping SSE")
            return
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(_executor, _search_single_category_sync, ...),
                timeout=35.0,
            )
            yield f"data: {json.dumps(result, ensure_ascii=False)}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'name': cat, 'error': 'timeout'})}\n\n"
```

### 2.2 Frontend (localService.js)

| Aspect | Status |
|--------|--------|
| AbortController cleanup | ✅ Returns abort function; callers can cancel |
| Incomplete message buffering | ✅ Buffers until `\n\n` delimiter |
| Malformed JSON | ✅ Silently skips with `try/catch` |
| Reconnection on drop | ❌ **No auto-reconnect.** If stream drops mid-way, user gets partial results with no indication. |
| Memory on huge streams | ⚠️ Buffers entire stream; could grow if categories return large payloads |

**Recommendation:** Add reconnect with exponential back-off (max 3 attempts); surface partial-failure state to user.

---

## 3. API Resilience

### 3.1 Timeout Handling

| File | External Call | Timeout |
|------|--------------|---------|
| `naver_local.py` | Playwright `page.goto()` | 20 s ✅ |
| `flyer_service.py` | `httpx.AsyncClient(timeout=20)` | 20 s ✅ |
| `oauth_service.py` | `httpx.AsyncClient().post(token_url)` | **None** ❌ |
| `app.py` | `storage.get_hotdeals()` (DB) | **None** ❌ |
| `community.py` | `session.query(PostModel)` (DB) | **None** ❌ |
| `restaurants.py` | `session.execute(select(Restaurant))` | **None** ❌ |

| ID | Issue | Severity |
|----|-------|----------|
| S-08 | **No timeout on OAuth token exchange.** `httpx.AsyncClient()` default timeout is 5 s for connect, no read limit. An unresponsive OAuth provider hangs the request indefinitely. | 🔴 CRITICAL |
| S-09 | **No timeout on SQLAlchemy queries.** Long-running DB scans (e.g., `restaurants.py` loads ALL rows) can block the event loop worker. | 🟠 HIGH |

### 3.2 Retry Logic

**None exists anywhere in the backend.** Every external call (Naver, OAuth, DB) fails on first error and returns empty/error.

| ID | Issue | Severity |
|----|-------|----------|
| S-10 | **No retry on transient failures.** Network blips, brief Naver throttling, or DB connection resets all return immediate errors. | 🟠 HIGH |

**Recommendation:** Add `tenacity` retry decorator for idempotent reads:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=0.5, max=4))
async def fetch_with_retry(url, **kwargs):
    ...
```

### 3.3 Circuit Breakers

- `flyer_service.py` — ✅ Has circuit breaker for Emart flyer scraping.
- `naver_local.py` — ❌ **No circuit breaker.** Repeated failures still trigger full browser automation.
- `oauth_service.py` — ❌ No circuit breaker on provider calls.

### 3.4 Error Handling Patterns

| ID | Issue | Severity |
|----|-------|----------|
| S-11 | **Bare `except Exception` clauses return partial data silently.** `app.py` dashboard, `products.py` category summary, `hotdeals.py` vote/report — all catch `Exception` and return fallback data. The client receives HTTP 200 with missing sections and no way to know which parts failed. | 🟠 HIGH |
| S-12 | **`hotdeals.py` vote/report endpoints accept raw `request.json()` without Pydantic validation.** Malformed JSON crashes with unhandled `json.JSONDecodeError`. | 🟠 HIGH |

### 3.5 Rate Limiting

| Layer | Status |
|-------|--------|
| Global (slowapi) | ✅ `100/minute` default via `rate_limit.py` middleware |
| Hotdeals custom | ❌ In-memory `dict[str, list[float]]`; **never garbage-collected**, race conditions on concurrent access |
| Naver scraping | ❌ No per-IP throttle; only 1 s inter-category delay |

| ID | Issue | Severity |
|----|-------|----------|
| S-13 | **Hotdeals rate-limiter memory leak.** `_rate_limit_store` keys are never deleted. Old IPs accumulate forever. | 🟠 HIGH |

---

## 4. Frontend Error Handling

**Files:** `App.jsx`, all page components, `services/api.js`

### 4.1 Error Boundaries

| ID | Issue | Severity |
|----|-------|----------|
| S-14 | **No React Error Boundary in the entire app.** If any component throws during render, the whole app crashes to a white screen. `Suspense` only catches lazy-load promises, not runtime errors. | 🔴 CRITICAL |

**Recommendation:**

```jsx
// Add to App.jsx
import { ErrorBoundary } from 'react-error-boundary';

function ErrorFallback({ error, resetErrorBoundary }) {
  return (
    <div role="alert">
      <h2>오류가 발생했습니다</h2>
      <button onClick={resetErrorBoundary}>다시 시도</button>
    </div>
  );
}

// Wrap routes
<ErrorBoundary FallbackComponent={ErrorFallback}>
  <Suspense fallback={<PageLoader />}>
    <Routes>...</Routes>
  </Suspense>
</ErrorBoundary>
```

### 4.2 Network Error UI

| Component | Error Handling | Loading State | Empty State |
|-----------|---------------|---------------|-------------|
| HotdealPage | ✅ try/catch + toast | ✅ Spinner | ✅ |
| SearchPage | ✅ ErrorFallback component | ✅ Spinner | ✅ EmptyState |
| CategoryComparePage | ✅ Error display | ✅ Spinner | ✅ |
| HomePage | ❌ No try/catch | ⚠️ Partial | ❌ |
| FavoritesDashboard | ❌ `catch(console.error)` only | ❌ None | ❌ |
| LocalPage | ⚠️ Partial | ✅ SkeletonLoader | ⚠️ |

| ID | Issue | Severity |
|----|-------|----------|
| S-15 | **HomePage references undeclared globals** (`PRODUCTS`, `HOTDEALS`, `MART_DATA`). Will throw `ReferenceError` if mock data not injected globally. | 🔴 CRITICAL |
| S-16 | **FavoritesDashboard silently swallows API errors.** `catch(console.error)` — user sees empty favorites with no explanation. | 🟠 HIGH |

### 4.3 API Client (services/api.js)

Strong implementation with good patterns:

| Feature | Status |
|---------|--------|
| Request timeout (AbortController + 15 s) | ✅ |
| In-flight GET deduplication | ✅ |
| Response cache (30 s TTL) | ✅ |
| Token refresh on 401 | ✅ |
| Custom `ApiError` with `retryable` flag | ✅ |
| JSON parse errors | ⚠️ Silently ignored (logged but not propagated) |

---

## 5. State Management

**Files:** `stores/appStore.js`, `stores/modalStore.js`

### 5.1 Zustand Store

| Aspect | Status |
|--------|--------|
| Immutable updates | ✅ Spread operator, no mutations |
| Selective subscriptions | ✅ Sliced selectors available |
| Persistence (localStorage) | ✅ Only theme, favorites, recentSearches, shoppingList, priceAlerts, filterPreferences |
| Sync updates (no race window) | ✅ Zustand's `set()` is synchronous |

| ID | Issue | Severity |
|----|-------|----------|
| S-17 | **No validation on hydrated localStorage data.** Corrupted or schema-mismatched data from a previous version silently loads and may crash components. | 🟡 MEDIUM |
| S-18 | **Shopping list uses `item.name` as fallback ID.** If a product name changes, duplicate entries appear. Always require `productId`. | 🟡 MEDIUM |

### 5.2 Race Conditions in Async Updates

| Component | Concern | Severity |
|-----------|---------|----------|
| HotdealPage votes | Optimistic local `votes` state desyncs from API-updated `allDeals` on navigation | 🟡 MEDIUM |
| SearchAutocomplete | `activeIndex` can exceed results array length if results change mid-keyboard-navigation | 🟡 MEDIUM |
| HomePage search | `setSelectedProduct(p)` then `navigate()` — product can change between calls | 🟡 MEDIUM |

---

## 6. Authentication Stability

**Files:** `backend/api/routes/auth.py`, `backend/services/auth_service.py`, `backend/services/oauth_service.py`, `backend/api/middleware/auth.py`, `frontend/src/services/authService.js`

### 6.1 Backend Auth

| ID | Issue | Severity |
|----|-------|----------|
| S-19 | **In-memory user database with TOCTOU race condition.** `_users_db` is a module-level dict; `_next_id` is a global int incremented without locks. Two concurrent register requests can get the same ID or create duplicate emails. | 🔴 CRITICAL |
| S-20 | **OAuth callback passes tokens in URL query string.** `RedirectResponse(url=f"http://localhost:5173/auth/callback?access_token=...")` — tokens logged by proxies, CDNs, browser history. Hardcoded to `localhost`. | 🔴 CRITICAL |
| S-21 | **`decode_token()` returns `None` for ALL JWT errors** — expiry, tampering, algorithm confusion all treated identically. No differentiation for logging or client feedback. | 🟡 MEDIUM |
| S-22 | **`get_current_user()` middleware: `int(payload["sub"])` crashes with `KeyError` if token payload missing `sub`, `email`, or `role` fields.** | 🟠 HIGH |
| S-23 | **OAuth state dict race condition.** `_cleanup_expired_states()` iterates then modifies `_oauth_states` dict; concurrent requests can cause `RuntimeError: dictionary changed size during iteration`. | 🟠 HIGH |
| S-24 | **Refresh token validity is 7 days.** A stolen refresh token provides week-long access with no revocation mechanism. | 🟡 MEDIUM |
| S-25 | **`/api/auth/me` returns 501.** Not implemented — clients calling this endpoint get an error rather than graceful fallback. | 🟡 MEDIUM |

### 6.2 Frontend Auth

| Aspect | Status |
|--------|--------|
| Token storage (sessionStorage) | ✅ Cleared on browser close |
| Token refresh on 401 | ✅ Auto-retry in `api.js` |
| Logout cleanup | ✅ Always clears tokens (finally block) |
| Redirect on auth failure | ⚠️ Not observed — no route guards |

---

## 7. Navigation

**Files:** `App.jsx`, `frontend/src/pages/*`

| Aspect | Status |
|--------|--------|
| Lazy-loaded routes | ✅ `React.lazy()` with `Suspense` fallback |
| Deep linking | ✅ SearchPage uses URL params (`useSearchParams`) |
| Back button | ✅ BrowserRouter handles natively |
| Route guards (auth) | ❌ **No protected routes.** Any page accessible without login. |
| 404 handling | ✅ `NotFound` page component present |
| Stale state on navigate | ⚠️ Zustand state persists across navigations — could show stale `selectedProduct` |

| ID | Issue | Severity |
|----|-------|----------|
| S-26 | **No protected routes.** User profile, favorites, alerts endpoints exist but routes don't redirect unauthenticated users. | 🟡 MEDIUM |

---

## 8. Large Data Sets

| Endpoint / Component | Data Volume | Pagination | Concern |
|---------------------|-------------|------------|---------|
| `GET /api/products/category-summary` | Fetches 500 products, groups in memory | ❌ None | 🟠 Memory spike |
| `GET /api/restaurants/nearby` | `select(Restaurant)` — **no LIMIT** | ❌ None | 🔴 Loads ALL rows |
| `GET /api/search` | Hotdeals: loads `per_page=50`, then client-side string filter | ❌ Server-side | 🟠 Inefficient |
| `GET /api/posts` | SQLAlchemy with `.limit(per_page)` | ✅ Paginated | ✅ |
| HotdealPage (frontend) | `useInfiniteScroll` | ✅ Intersection Observer | ✅ |
| SearchPage (frontend) | Results displayed as cards | ⚠️ No virtual scroll | 🟡 |
| CategoryComparePage | Proper pagination with prev/next | ✅ | ✅ |

| ID | Issue | Severity |
|----|-------|----------|
| S-27 | **`restaurants.py` loads ALL restaurant rows** with no LIMIT or pagination. With thousands of rows this causes OOM or extreme latency. | 🔴 CRITICAL |
| S-28 | **`products.py` category-summary loads 500 products into memory**, groups them by category with `defaultdict(list)`. No streaming or pagination. | 🟠 HIGH |
| S-29 | **`search.py` hotdeal search does client-side string filtering** over up to 50 items fetched from storage. Should use DB-level `LIKE` or full-text search. | 🟡 MEDIUM |

---

## 9. Image Loading

| Component | Lazy Loading | Error Fallback | Notes |
|-----------|-------------|----------------|-------|
| HotdealPage deal cards | ✅ `loading="lazy"` | ❌ No `onError` | Broken images show browser default icon |
| NaverPlaceDetailContent | ✅ `loading="lazy"` | ❌ No `onError` | Same |
| DetailModal (community) | ❌ Not observed | ❌ No `onError` | Image grid for community posts |
| FavoritesDashboard | ❌ Not observed | ❌ No `onError` | Product images |

| ID | Issue | Severity |
|----|-------|----------|
| S-30 | **No image error fallbacks anywhere.** Broken images (404, CORS, timeout) display browser's default broken-image icon. No placeholder or retry. | 🟠 HIGH |

**Recommendation:**

```jsx
function SafeImage({ src, alt, className, ...props }) {
  const [error, setError] = useState(false);
  return error ? (
    <div className="image-placeholder">{alt?.charAt(0) || '?'}</div>
  ) : (
    <img
      src={src}
      alt={alt}
      className={className}
      loading="lazy"
      onError={() => setError(true)}
      {...props}
    />
  );
}
```

---

## 10. Offline Behavior

| Scenario | Current Behavior |
|----------|-----------------|
| Network drops during page load | API calls timeout (15 s) → `ApiError` thrown → varies by component |
| Network drops during SSE stream | Stream fetch rejects → `onError` callback → partial results shown, no reconnect |
| Network drops during form submit | Unhandled — submit fails silently or shows generic error |
| Cached data available | ✅ API client 30 s cache; Zustand persists favorites/theme to localStorage |
| Service Worker | ❌ None — no offline support |

| ID | Issue | Severity |
|----|-------|----------|
| S-31 | **No offline detection or UI.** User sees loading spinners or empty states with no "you're offline" message. | 🟡 MEDIUM |
| S-32 | **No SSE reconnection.** Stream drops are permanent — user must manually refresh. | 🟠 HIGH |

---

## 11. Cross-Browser

| Feature | Compatibility Risk |
|---------|-------------------|
| `EventSource` / SSE | ❌ Not used — custom `fetch()` stream parsing. Works in all modern browsers. |
| `AbortController` | ✅ Supported in all modern browsers (Chrome 66+, Firefox 57+, Safari 12.1+) |
| `IntersectionObserver` | ✅ Supported (Chrome 58+, Firefox 55+, Safari 12.1+) |
| `navigator.clipboard` | ⚠️ Used in ShareButton; requires HTTPS in some browsers |
| CSS Modules | ✅ Vite handles; no runtime compatibility concern |
| `structuredClone` / modern JS | Not observed — safe |
| `Intl.NumberFormat` | Used via `fmt()` helper — ✅ well-supported |

| ID | Issue | Severity |
|----|-------|----------|
| S-33 | **`navigator.clipboard.writeText()` requires secure context (HTTPS).** On HTTP localhost it works, but on HTTP staging/production it will silently fail. | 🟡 MEDIUM |

---

## 12. Memory Leaks

### 12.1 Frontend

| Component | Subscription | Cleanup | Risk |
|-----------|-------------|---------|------|
| HotdealPage `setInterval` | 60 s polling | ✅ `clearInterval` in useEffect return | ⚠️ In-flight fetch not aborted on unmount |
| Header scroll listener | `window.addEventListener('scroll')` | ✅ Removed on unmount (passive) | ✅ |
| Modal keyboard listeners | `document.addEventListener('keydown')` | ✅ Removed on unmount | ✅ |
| ShoppingListPanel Escape key | `document.addEventListener('keydown')` | ✅ Removed on unmount | ✅ |
| SearchAutocomplete outside-click | `document.addEventListener('mousedown')` | ✅ Removed on unmount | ✅ |
| ToastContainer timer | `setTimeout` | ✅ Cleared on unmount | ⚠️ Only clears first toast's timer |
| LocalService SSE fetch | `AbortController` | ✅ Returns abort function | ✅ |

| ID | Issue | Severity |
|----|-------|----------|
| S-34 | **HotdealPage: in-flight API call from `setInterval` not aborted on unmount.** Timer is cleared, but if a fetch was already in-flight, its `.then()` updates state on an unmounted component (React warning). | 🟡 MEDIUM |

### 12.2 Backend

| Resource | Cleanup | Risk |
|----------|---------|------|
| `_BrowserPool` (Playwright) | Idle-timeout cleanup (300 s) | ✅ |
| Browser contexts/pages | `finally` block closes context | ✅ |
| `ThreadPoolExecutor(max_workers=4)` | ❌ Never `shutdown()` | 🟡 Thread leak on restart |
| `_rate_limit_store` (hotdeals.py) | ❌ Never garbage-collected | 🟠 Unbounded dict growth |
| `_cache` (naver_local.py) | ❌ No max size, manual TTL eviction | 🟡 Slow memory creep |
| `_oauth_states` (oauth_service.py) | Only cleaned when new state generated | 🟡 Slow growth |
| `_hotdeal_comments` (hotdeals.py) | ❌ Never evicted | 🟠 Unbounded growth |
| Audit log file (`audit.jsonl`) | ❌ No rotation configured | 🟡 Disk fill |

---

## 13. Finding Registry

Complete list of all findings for tracking.

| ID | Title | Severity | Category | File(s) |
|----|-------|----------|----------|---------|
| S-01 | No retry logic on Naver scraping | 🔴 CRITICAL | Scraping | `naver_local.py` |
| S-02 | No circuit breaker on Naver scraping | 🟠 HIGH | Scraping | `naver_local.py` |
| S-03 | ThreadPoolExecutor never shut down | 🟡 MEDIUM | Scraping | `naver_local.py` |
| S-04 | Basic stealth measures insufficient | 🟠 HIGH | Scraping | `naver_local.py` |
| S-05 | SSE client disconnection not detected | 🔴 CRITICAL | SSE | `naver_local.py` |
| S-06 | No per-category timeout wrapper in SSE | 🟠 HIGH | SSE | `naver_local.py` |
| S-07 | Arbitrary inter-category delay | 🟡 MEDIUM | SSE | `naver_local.py` |
| S-08 | No timeout on OAuth token exchange | 🔴 CRITICAL | API | `oauth_service.py` |
| S-09 | No timeout on SQLAlchemy queries | 🟠 HIGH | API | `community.py`, `restaurants.py` |
| S-10 | No retry on transient failures | 🟠 HIGH | API | All route files |
| S-11 | Bare `except` returns partial data as 200 | 🟠 HIGH | API | `app.py`, `products.py`, `hotdeals.py` |
| S-12 | Raw `request.json()` without Pydantic validation | 🟠 HIGH | API | `hotdeals.py` |
| S-13 | Hotdeals rate-limiter memory leak | 🟠 HIGH | API | `hotdeals.py` |
| S-14 | No React Error Boundary | 🔴 CRITICAL | Frontend | `App.jsx` |
| S-15 | HomePage references undeclared globals | 🔴 CRITICAL | Frontend | `HomePage.jsx` |
| S-16 | FavoritesDashboard swallows API errors | 🟠 HIGH | Frontend | `FavoritesDashboard.jsx` |
| S-17 | No validation on hydrated localStorage | 🟡 MEDIUM | State | `appStore.js` |
| S-18 | Shopping list uses name as fallback ID | 🟡 MEDIUM | State | `appStore.js` |
| S-19 | In-memory user DB with race conditions | 🔴 CRITICAL | Auth | `auth.py` (routes) |
| S-20 | OAuth tokens passed in URL query string | 🔴 CRITICAL | Auth | `auth.py` (routes) |
| S-21 | `decode_token()` hides all JWT error types | 🟡 MEDIUM | Auth | `auth_service.py` |
| S-22 | Missing key access crashes in auth middleware | 🟠 HIGH | Auth | `middleware/auth.py` |
| S-23 | OAuth state dict race condition | 🟠 HIGH | Auth | `oauth_service.py` |
| S-24 | 7-day refresh token with no revocation | 🟡 MEDIUM | Auth | `auth_service.py` |
| S-25 | `/api/auth/me` returns 501 | 🟡 MEDIUM | Auth | `auth.py` (routes) |
| S-26 | No protected routes | 🟡 MEDIUM | Navigation | `App.jsx` |
| S-27 | Restaurants loads ALL rows, no LIMIT | 🔴 CRITICAL | Data | `restaurants.py` |
| S-28 | Category summary loads 500 products in memory | 🟠 HIGH | Data | `products.py` |
| S-29 | Hotdeal search does client-side filtering | 🟡 MEDIUM | Data | `search.py` |
| S-30 | No image error fallbacks | 🟠 HIGH | Images | Multiple frontend components |
| S-31 | No offline detection UI | 🟡 MEDIUM | Offline | Frontend |
| S-32 | No SSE reconnection | 🟠 HIGH | SSE | `localService.js` |
| S-33 | Clipboard API needs HTTPS | 🟡 MEDIUM | Cross-browser | `ShareButton.jsx` |
| S-34 | In-flight fetch not aborted on unmount | 🟡 MEDIUM | Memory | `HotdealPage.jsx` |
| S-35 | Toast auto-dismiss only works for first toast | 🟡 MEDIUM | UI | `ToastContainer.jsx` |
| S-36 | View count lost-update race condition | 🟡 MEDIUM | Data | `community.py` |
| S-37 | `_hotdeal_comments` dict grows unbounded | 🟠 HIGH | Memory | `hotdeals.py` |
| S-38 | `_comment_id_seq` increment race condition | 🟡 MEDIUM | Data | `hotdeals.py` |
| S-39 | XSS risk in DetailModal rendering user content | 🔴 CRITICAL | Security | `DetailModal.jsx` |
| S-40 | Request size check relies on Content-Length header | 🟡 MEDIUM | Security | `request_size.py` |
| S-41 | No log rotation on audit log | 🟡 MEDIUM | Ops | `audit_logger.py` |

---

## 14. Remediation Priorities

### Phase 1 — Stop the Bleeding (Week 1)

| Priority | IDs | Action |
|----------|-----|--------|
| P0 | S-14 | Add `react-error-boundary` to `App.jsx` |
| P0 | S-15 | Fix `HomePage.jsx` — import mock data or wire to API |
| P0 | S-39 | Sanitize user content in `DetailModal.jsx` with `sanitizeHTML()` |
| P0 | S-19 | Move user storage from in-memory dict to SQLite/DB |
| P0 | S-20 | Pass OAuth tokens via HTTP-only cookie or POST body, not URL |
| P0 | S-27 | Add `.limit(100)` to restaurants query |
| P0 | S-05 | Check `request.is_disconnected()` in SSE generator |

### Phase 2 — Harden (Weeks 2–3)

| Priority | IDs | Action |
|----------|-----|--------|
| P1 | S-01, S-10 | Add `tenacity` retry decorator for scraping and external HTTP calls |
| P1 | S-02 | Add circuit breaker to `naver_local.py` (copy pattern from `flyer_service.py`) |
| P1 | S-08 | Add `timeout=httpx.Timeout(10, read=20)` to OAuth client |
| P1 | S-09 | Set SQLAlchemy `execution_options(timeout=10)` or wrap in `asyncio.wait_for` |
| P1 | S-11, S-12 | Replace bare excepts with typed error handling; add Pydantic schemas to hotdeal vote/report |
| P1 | S-22 | Add `.get()` with defaults in `get_current_user()` middleware |
| P1 | S-23 | Use `threading.Lock` around `_oauth_states` or switch to TTL dict |
| P1 | S-30 | Create `SafeImage` component with `onError` fallback |
| P1 | S-32 | Add SSE reconnect logic with exponential back-off in `localService.js` |
| P1 | S-13, S-37 | Replace in-memory rate-limiter and comments dicts with bounded `TTLCache` or Redis |

### Phase 3 — Polish (Weeks 4+)

| Priority | IDs | Action |
|----------|-----|--------|
| P2 | S-03 | Add `atexit.register(executor.shutdown)` |
| P2 | S-04 | Evaluate `playwright-stealth` or rotate proxies |
| P2 | S-06 | Wrap each SSE category search in `asyncio.wait_for(timeout=35)` |
| P2 | S-16 | Add error toast in FavoritesDashboard |
| P2 | S-17 | Add Zustand persist migration/validation |
| P2 | S-24 | Reduce refresh token TTL to 24 h; add token revocation table |
| P2 | S-26 | Add `<ProtectedRoute>` wrapper for auth-required pages |
| P2 | S-28 | Paginate category-summary endpoint; reduce from 500 to 50 per page |
| P2 | S-29 | Move hotdeal search filtering to DB `LIKE` query |
| P2 | S-31 | Add `navigator.onLine` listener + offline banner |
| P2 | S-34, S-35, S-36, S-38 | Fix minor race conditions and timer bugs |
| P2 | S-41 | Add `RotatingFileHandler` to audit logger |

---

## Appendix: What's Working Well

These patterns are solid and should be preserved/extended:

- **`api.js` request deduplication** — prevents duplicate GET requests in-flight
- **`useAbortController` hook** — clean abort pattern for async operations
- **`useInfiniteScroll` hook** — proper IntersectionObserver with cleanup
- **`sanitize.js` (frontend)** — DOMPurify with strict allowlist + hook-based enforcement
- **`sanitize.py` (backend)** — nh3 (Rust-based) with SVG blocking
- **`TTLCache` with threading.Lock** — thread-safe caching with bounded size
- **`RequestDeduplicator`** — asyncio.Future-based dedup prevents thundering herd
- **`flyer_service.py` circuit breaker** — good pattern to replicate elsewhere
- **Modal accessibility** — focus trapping, Escape key, aria attributes, scroll lock
- **Zustand persistence** — selective persistence of only essential slices
- **Security headers middleware** — comprehensive CSP, HSTS-ready, XSS protection
