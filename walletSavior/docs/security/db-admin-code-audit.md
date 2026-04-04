# DB Admin Security Audit — Code Level

> **Audit Date**: 2025-07-16  
> **Scope**: `packages/db-admin/backend/` (FastAPI + SQLAlchemy) and `packages/db-admin/frontend/src/` (React + Vite)  
> **Auditor**: Automated Code-Level Security Analysis

---

## Critical Issues (Must Fix)

### Issue 1: No Authentication or Authorization on Any Endpoint

- **File**: `backend/api/app.py` (all routes), `backend/api/routes/admin.py`, `backend/api/routes/ingestion.py`, `backend/api/routes/products.py`, `backend/api/routes/categories.py`, `backend/api/routes/keywords.py`, `backend/api/routes/prices.py`, `backend/api/routes/analytics.py`, `backend/api/routes/dashboard.py`
- **Risk**: CRITICAL
- **Description**: **Zero authentication or authorization** exists on any endpoint. Every route — including destructive admin operations like `POST /admin/reset-all`, `POST /admin/reset-products`, `POST /admin/reset-source`, bulk deletes, data ingestion, and data export — is publicly accessible to anyone who can reach the API. There is no login, no API key, no JWT, no session check, no role-based access control.
- **Attack Vector**: Any network-reachable attacker can:
  - Wipe the entire database via `POST /api/admin/reset-all` with body `{"confirm": "RESET_ALL_DATA"}`
  - Delete all products via `POST /api/admin/reset-products` with body `{"confirm": "DELETE_ALL_PRODUCTS"}`
  - Inject arbitrary product/price data via `POST /api/ingestions`
  - Delete individual products, categories, keywords via DELETE endpoints
  - Export all data via `/api/analytics/export/products` and `/api/prices/export`
  - Modify price tier configurations via `POST /api/prices/tier-config`
  - The "confirm" strings on admin endpoints are **not** a security mechanism — they are only accidental-click protection, as the expected strings are deterministic and disclosed in error messages.
- **Fix**:
  ```python
  # 1. Add authentication middleware (JWT or API key)
  from fastapi import Depends, Security
  from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
  
  security = HTTPBearer()
  
  async def verify_admin(credentials: HTTPAuthorizationCredentials = Security(security)):
      token = credentials.credentials
      # Validate JWT or API key
      payload = decode_jwt(token)
      if payload.get("role") != "admin":
          raise HTTPException(403, "Admin access required")
      return payload
  
  # 2. Apply to all admin routes
  @router.post("/reset-all")
  def reset_all(body: ResetAllRequest, user=Depends(verify_admin)):
      ...
  
  # 3. Apply to all state-changing routes at minimum
  ```

### Issue 2: Wildcard CORS Configuration with Credentials

- **File**: `backend/api/app.py:17-23`
- **Risk**: CRITICAL
- **Description**: CORS is configured with `allow_origins=["*"]`, `allow_credentials=True`, and `allow_methods=["*"]`. This is a dangerous combination. While browsers technically block `Access-Control-Allow-Origin: *` with `Access-Control-Allow-Credentials: true`, this configuration signals a complete lack of origin control. If the framework reflects the `Origin` header (as some CORS middleware implementations do when `allow_origins=["*"]` and `allow_credentials=True` are both set), it enables credential-theft attacks from any origin.
- **Attack Vector**: A malicious website can make cross-origin requests to the API. If origin reflection occurs, cookies/credentials would be attached, allowing the attacker to perform any API action on behalf of a visiting admin user.
- **Fix**:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=[
          "http://localhost:5175",
          "http://127.0.0.1:5175",
          # Add production frontend URL
      ],
      allow_credentials=True,
      allow_methods=["GET", "POST", "PUT", "DELETE"],
      allow_headers=["Content-Type", "Authorization"],
  )
  ```

### Issue 3: Destructive Admin Endpoints Protected Only by Guessable Confirmation Strings

- **File**: `backend/api/routes/admin.py:112-272`
- **Risk**: CRITICAL
- **Description**: The admin reset endpoints (`reset-source`, `reset-products`, `reset-all`) use simple confirmation strings as the sole protection mechanism. These strings are **deterministic** and **revealed in error messages**: `"DELETE_{SOURCE}"`, `"DELETE_ALL_PRODUCTS"`, `"RESET_ALL_DATA"`. This is a UI-level accidental-click guard, not a security measure.
- **Attack Vector**: An attacker (or automated script) knowing the API structure can call:
  ```bash
  curl -X POST http://host:8002/api/admin/reset-all \
    -H "Content-Type: application/json" \
    -d '{"confirm":"RESET_ALL_DATA"}'
  ```
  This would **delete all data** in the database with no authentication required.
- **Fix**: Add proper authentication (see Issue 1). Additionally, require a TOTP/2FA code for destructive operations, implement audit logging with user identity, and add rate limiting on admin endpoints.

---

## High Issues

### Issue 4: SQL LIKE Injection via Unescaped User Input in ORM Queries

- **File**: `backend/api/routes/keywords.py:58-59`, `backend/api/routes/prices.py:40,447,510`, `backend/api/routes/analytics.py:394`, `backend/services/autocomplete.py:59,202,213`
- **Risk**: HIGH
- **Description**: Multiple endpoints use f-string interpolation inside SQLAlchemy `.ilike()` and `.like()` operators. While SQLAlchemy parameterizes the value (preventing classic SQL injection), the **LIKE pattern characters** `%` and `_` in user input are not escaped. An attacker can craft input with `%` or `_` to alter query matching behavior.
  
  Examples:
  ```python
  # keywords.py:58 — user-controlled 'q' directly in LIKE pattern
  Keyword.word.ilike(f"%{q}%")
  
  # prices.py:40 — user-controlled 'source' in LIKE pattern
  BaselinePrice.source.ilike(f"%{source}%")
  
  # analytics.py:394 — user-controlled 'q' in LIKE pattern
  Product.name.ilike(f"%{q}%")
  ```
  
- **Attack Vector**: An attacker can input `%` as a search query to match **all records**, potentially causing a denial-of-service through result set explosion, or use `_` to brute-force single characters in sensitive fields. While this doesn't allow arbitrary SQL execution, it can leak data and cause performance issues.
- **Fix**:
  ```python
  def escape_like(value: str) -> str:
      """Escape LIKE special characters."""
      return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  
  # Usage:
  Keyword.word.ilike(f"%{escape_like(q)}%")
  ```

### Issue 5: Dynamic Column Access via User-Controlled `getattr()` — Attribute Enumeration

- **File**: `backend/api/routes/keywords.py:69`
- **Risk**: HIGH
- **Description**: The `sort_by` query parameter is used directly in `getattr(Keyword, sort_by, Keyword.search_count)` without validation against an allowlist. While the fallback default prevents a crash, an attacker can probe for model attribute names by observing sort behavior differences.
- **Attack Vector**: An attacker can enumerate Keyword model attributes (e.g., `sort_by=hashed_password`, `sort_by=synonyms`) by observing whether the result order changes, revealing internal model structure. If the model had sensitive fields, those could be used for sorting and thus for information inference.
- **Fix**:
  ```python
  ALLOWED_SORT_FIELDS = {"word", "search_count", "is_active", "id"}
  
  sort_col_name = sort_by if sort_by in ALLOWED_SORT_FIELDS else "search_count"
  sort_col = getattr(Keyword, sort_col_name)
  ```

### Issue 6: No Input Size Limits on Ingestion Payload — Denial of Service

- **File**: `backend/api/routes/ingestion.py:33-41,267-299`
- **Risk**: HIGH
- **Description**: The `POST /api/ingestions` endpoint accepts an unbounded `items: list[dict]` field in the `IngestionSubmit` model. There is no limit on:
  - Number of items in the list
  - Size of individual item dictionaries
  - Total payload size
  
  Similarly, the `items_json` is stored as raw JSON text without size constraints.
- **Attack Vector**: An attacker can submit a multi-gigabyte payload with millions of items, causing:
  - Memory exhaustion (OOM) during JSON parsing
  - Database bloat from storing massive JSON blobs
  - CPU exhaustion during quality score calculation
- **Fix**:
  ```python
  from pydantic import validator
  
  class IngestionSubmit(BaseModel):
      items: list[dict] = []
      
      @validator("items")
      def limit_items(cls, v):
          if len(v) > 10000:
              raise ValueError("Maximum 10,000 items per submission")
          return v
  ```
  Also set a global request body size limit in uvicorn or via middleware.

### Issue 7: Arbitrary File Write via Tier Config and Whitelist Endpoints

- **File**: `backend/api/routes/prices.py:89-90,101-117,250-257`
- **Risk**: HIGH
- **Description**: The tier config and outlier whitelist are stored as JSON files on the server filesystem. The paths (`TIER_CONFIG_PATH`, `WHITELIST_PATH`) are fixed relative paths, so direct path traversal is not possible. However, the `save_tier_config` endpoint writes **arbitrary user-supplied JSON** to a file, and the `whitelist_outlier` endpoint appends integers to a file. Without authentication, anyone can overwrite these configuration files.
- **Attack Vector**: 
  - An attacker can set arbitrary tier configuration that changes how prices are classified across the application.
  - Repeated whitelist additions can grow the file unboundedly.
  - Without authentication, any user can manipulate business-critical pricing logic.
- **Fix**: Add authentication (see Issue 1). Validate tier config structure strictly. Set a maximum whitelist size.

### Issue 8: No Rate Limiting on Any Endpoint

- **File**: All route files
- **Risk**: HIGH
- **Description**: No rate limiting is implemented on any endpoint. This includes:
  - Destructive admin endpoints (database wipes)
  - Data ingestion endpoints (unlimited data submission)
  - Search/autocomplete endpoints (expensive queries)
  - Bulk operations (mass delete/update)
- **Attack Vector**:
  - **DoS**: Flood expensive endpoints like `/api/prices/tier-preview` (which queries ALL products with nested loops), `/api/prices/outliers` (scans all products and prices), or `/api/analytics/summary`.
  - **Data flooding**: Repeatedly submit ingestion data to fill the database.
  - **Brute-force**: Enumerate product IDs, category IDs, or keyword IDs at high speed.
- **Fix**:
  ```python
  from slowapi import Limiter, _rate_limit_exceeded_handler
  from slowapi.util import get_remote_address
  
  limiter = Limiter(key_func=get_remote_address)
  app.state.limiter = limiter
  
  @router.post("/reset-all")
  @limiter.limit("1/minute")
  def reset_all(request: Request, body: ResetAllRequest):
      ...
  ```

---

## Medium Issues

### Issue 9: Unbounded Query Results — Memory Exhaustion Risk

- **File**: `backend/api/routes/prices.py:312-361` (`/outliers`), `backend/api/routes/prices.py:260-307` (`/tier-preview`), `backend/api/routes/products.py:381-427` (`/similar`), `backend/api/routes/analytics.py:220-294` (`/price-trends`)
- **Risk**: MEDIUM
- **Description**: Several endpoints load **all records** into memory before filtering:
  - `/prices/outliers`: Loads ALL products and ALL their prices, performs IQR calculations in Python.
  - `/prices/tier-preview`: Iterates ALL products, running 2 DB queries per product (N+1 pattern).
  - `/price-trends`: Can process up to 5 products with multiple queries each.
  
  These endpoints can consume excessive memory and CPU with large datasets.
- **Attack Vector**: With a database containing 100K+ products, a single request to `/api/prices/outliers` or `/api/prices/tier-preview` can exhaust server memory or block the event loop for minutes.
- **Fix**: Add pagination, limit result sets, use database-side aggregations. For `/tier-preview`, compute in SQL rather than iterating in Python.

### Issue 10: No CSRF Protection on State-Changing Endpoints

- **File**: All POST/PUT/DELETE endpoints
- **Risk**: MEDIUM
- **Description**: No CSRF tokens or protection mechanisms are in place. All state-changing operations use simple JSON POST/PUT/DELETE requests with no anti-CSRF tokens, no `SameSite` cookie policy, and no custom header requirements.
- **Attack Vector**: If an admin is logged in (future auth implementation) and visits a malicious site, that site can trigger destructive actions via cross-origin requests. Currently mitigated by the fact that there's no authentication at all (no session to hijack), but this will become critical once auth is added.
- **Fix**: When implementing authentication:
  1. Use `SameSite=Strict` or `SameSite=Lax` on session cookies
  2. Require a custom header (e.g., `X-Requested-With`) for state-changing operations
  3. Consider using the double-submit cookie pattern

### Issue 11: Error Handling Leaks Internal Information

- **File**: `backend/api/routes/admin.py:161-163`, `backend/api/app.py` (no global exception handler), all routes with bare `except Exception`
- **Risk**: MEDIUM
- **Description**: Several routes use bare `except Exception: raise` patterns without catching and sanitizing errors. FastAPI's default error handling will return stack traces in debug mode. The `admin.py:116-119` error response includes the expected confirmation string, revealing the exact string needed:
  ```python
  raise HTTPException(
      status_code=400,
      detail=f"확인 문자열이 올바르지 않습니다. '{expected}'를 입력하세요.",
  )
  ```
  Additionally, there is no global exception handler to prevent unhandled SQLAlchemy errors from leaking database schema information (table names, column names).
- **Attack Vector**: An attacker can:
  1. Trigger errors to discover database structure (table names, column names, relationships)
  2. Learn the exact confirmation string needed for destructive operations from the error message
  3. In debug mode (`DEBUG=true`), see full stack traces with file paths and code
- **Fix**:
  ```python
  # Add global exception handler
  @app.exception_handler(Exception)
  async def global_exception_handler(request, exc):
      logger.error(f"Unhandled error: {exc}", exc_info=True)
      return JSONResponse(
          status_code=500,
          content={"detail": "Internal server error"},
      )
  
  # Don't reveal expected confirmation strings in errors
  raise HTTPException(400, "확인 문자열이 올바르지 않습니다.")
  ```

### Issue 12: `find_duplicates()` Accepts Arbitrary Table/Field Names — Information Disclosure

- **File**: `backend/services/data_quality.py:110-139`, `backend/api/routes/analytics.py:73-79`
- **Risk**: MEDIUM
- **Description**: The `POST /api/analytics/duplicates` endpoint accepts `table_name` and `fields` from user input. While it validates against a whitelist of table names (`model_map`), the `fields` parameter allows querying **any column** on the allowed tables via `getattr(model, f)`. This enables an attacker to extract data from any column by constructing duplicate queries.
- **Attack Vector**: An attacker can discover column values by querying:
  ```json
  {"table_name": "products", "fields": ["description"]}
  {"table_name": "products", "fields": ["image_url"]}
  ```
  This reveals all duplicate values in any column, which may expose sensitive data patterns.
- **Fix**: Add an allowlist of permitted field combinations per table:
  ```python
  ALLOWED_FIELDS = {
      "products": ["name"],
      "baseline_prices": ["product_id", "source", "price"],
      "discount_history": ["product_id", "source", "price"],
  }
  ```

### Issue 13: Server Binds to `0.0.0.0` — Exposed to All Network Interfaces

- **File**: `backend/main.py:9`
- **Risk**: MEDIUM
- **Description**: The server binds to `0.0.0.0` (all interfaces), making it accessible from any network interface on the host machine. Combined with the lack of authentication, this means any device on the same network can access and destroy data.
- **Attack Vector**: On a shared network (university, office, public WiFi), any device can access `http://<host-ip>:8002/api/admin/reset-all` and wipe the database.
- **Fix**: Bind to `127.0.0.1` for local development:
  ```python
  uvicorn.run("main:app", host="127.0.0.1", port=settings.API_PORT, reload=settings.DEBUG)
  ```

### Issue 14: No Input Length Validation on String Fields

- **File**: `backend/api/routes/products.py:23-28` (`ProductCreate`), `backend/api/routes/categories.py:21-27` (`CategoryCreate`), `backend/api/routes/keywords.py:23-25` (`KeywordCreate`), `backend/api/routes/ingestion.py:33-41` (`IngestionSubmit`)
- **Risk**: MEDIUM
- **Description**: Pydantic models don't enforce string length limits. For example:
  - Product `name` has no max length (DB column is `String(255)` but Pydantic doesn't enforce)
  - Category `id` has no max length
  - Keyword `word` has no max length
  - `image_url` has no max length (DB column is `String(500)`)
  
  Oversized strings will either be silently truncated (data corruption) or cause database errors.
- **Attack Vector**: Submit a product with a 100MB name string to cause memory issues, or exploit truncation for data manipulation.
- **Fix**:
  ```python
  from pydantic import Field
  
  class ProductCreate(BaseModel):
      name: str = Field(..., min_length=1, max_length=255)
      category_id: Optional[str] = Field(None, max_length=100)
      unit: str = Field("개", max_length=50)
      description: Optional[str] = Field(None, max_length=5000)
      image_url: Optional[str] = Field(None, max_length=500)
  ```

### Issue 15: Debug Mode Configurable via Environment Variable Without Safeguards

- **File**: `backend/config.py:14`, `backend/main.py:9`
- **Risk**: MEDIUM
- **Description**: Debug mode is controlled by `DEBUG=true` environment variable, and when enabled, uvicorn runs with `reload=True`. In debug mode:
  - Stack traces may be exposed to clients
  - Hot reloading enables watching filesystem for changes
  - No warning or safeguard prevents running debug mode in production
- **Attack Vector**: If `DEBUG=true` is accidentally set in production, full stack traces (including file paths, code snippets, and variable values) are exposed to any client.
- **Fix**: Add safeguards:
  ```python
  if not settings.DEBUG:
      # Ensure production safety
      import logging
      logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
  ```
  Never expose FastAPI docs in production: `docs_url=None, redoc_url=None` when `DEBUG=False`.

---

## Low Issues

### Issue 16: API Documentation Exposed in Production

- **File**: `backend/api/app.py:8-12`
- **Risk**: LOW
- **Description**: FastAPI automatically serves OpenAPI docs at `/docs` (Swagger UI) and `/redoc`. These endpoints expose every API route, parameter, and schema — providing a complete attack surface map.
- **Attack Vector**: An attacker can visit `/docs` to discover all available endpoints, required parameters, and data structures, significantly reducing reconnaissance effort.
- **Fix**:
  ```python
  from config import settings
  
  app = FastAPI(
      title="WalletSavior DB 관리",
      docs_url="/docs" if settings.DEBUG else None,
      redoc_url="/redoc" if settings.DEBUG else None,
      openapi_url="/openapi.json" if settings.DEBUG else None,
  )
  ```

### Issue 17: Frontend API Client Has No Error Retry or Timeout

- **File**: `frontend/src/api/client.js:1-104`
- **Risk**: LOW
- **Description**: The API client uses bare `fetch()` with no timeout configuration, no retry logic, and no request cancellation. This can lead to hanging requests and poor user experience.
- **Attack Vector**: Not directly exploitable, but a slow or unresponsive backend can cause the frontend to hang indefinitely. Combined with the lack of rate limiting, an attacker could slow down the server enough to affect all connected clients.
- **Fix**: Add timeout and AbortController:
  ```javascript
  const fetchWithTimeout = (url, options = {}, timeout = 30000) => {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeout);
    return fetch(url, { ...options, signal: controller.signal }).finally(() => clearTimeout(id));
  };
  ```

### Issue 18: No Content Security Policy (CSP) Headers

- **File**: `backend/api/app.py` (no security headers middleware)
- **Risk**: LOW
- **Description**: No security headers are set: no `Content-Security-Policy`, no `X-Content-Type-Options`, no `X-Frame-Options`, no `Strict-Transport-Security`. While the React frontend handles most rendering safely, missing CSP headers reduce defense-in-depth.
- **Fix**:
  ```python
  from starlette.middleware.base import BaseHTTPMiddleware
  
  class SecurityHeadersMiddleware(BaseHTTPMiddleware):
      async def dispatch(self, request, call_next):
          response = await call_next(request)
          response.headers["X-Content-Type-Options"] = "nosniff"
          response.headers["X-Frame-Options"] = "DENY"
          response.headers["X-XSS-Protection"] = "1; mode=block"
          return response
  
  app.add_middleware(SecurityHeadersMiddleware)
  ```

### Issue 19: Session Management — Manual `session.close()` Pattern May Leak Connections

- **File**: `backend/services/base.py:17-21`, all route files
- **Risk**: LOW
- **Description**: Every endpoint creates a new `Session` via `get_session()` and manually closes it in a `finally` block. This pattern has two issues:
  1. A new `sessionmaker` is created on every `get_session()` call (slight overhead)
  2. If an exception occurs between `get_session()` and the `try` block (unlikely but possible), the session leaks
  
  FastAPI's standard pattern uses `Depends()` with generator functions for proper lifecycle management.
- **Fix**:
  ```python
  from fastapi import Depends
  
  def get_db():
      session = SessionLocal()
      try:
          yield session
      finally:
          session.close()
  
  @router.get("/")
  def list_products(session: Session = Depends(get_db)):
      ...
  ```

### Issue 20: Frontend Uses Unencoded Query Parameters in Some API Calls

- **File**: `frontend/src/api/client.js:51`
- **Risk**: LOW
- **Description**: Some API calls directly interpolate values without `encodeURIComponent()`:
  ```javascript
  searchKeywords: (q) => fetch(`${API_BASE}/keywords/search?q=${q}`).then(json),
  ```
  While `q` is from a text input (no XSS risk via URL), special characters like `&`, `=`, `#` in the search query will corrupt the URL.
- **Attack Vector**: Searching for terms containing `&` or `#` will produce incorrect API calls. Not directly a security vulnerability but a reliability issue that could mask attack detection.
- **Fix**:
  ```javascript
  searchKeywords: (q) => fetch(`${API_BASE}/keywords/search?q=${encodeURIComponent(q)}`).then(json),
  ```

### Issue 21: Insufficient Bulk Delete Validation — No Upper Bound on IDs

- **File**: `backend/api/routes/products.py:39-40` (`BulkDeleteRequest`), `backend/api/routes/keywords.py:36-37` (`BulkDeleteRequest`)
- **Risk**: LOW
- **Description**: Bulk delete operations accept an unbounded list of IDs with no maximum limit. An attacker could pass thousands of IDs in a single request.
- **Attack Vector**: Send a request with 100K+ IDs to cause excessive database load:
  ```json
  {"ids": [1, 2, 3, ..., 100000]}
  ```
- **Fix**:
  ```python
  class BulkDeleteRequest(BaseModel):
      ids: list[int] = Field(..., max_length=500)
  ```

### Issue 22: `keywords/bulk-delete` Without IDs Deletes All Unused Keywords

- **File**: `backend/api/routes/keywords.py:173-196`
- **Risk**: LOW
- **Description**: The `POST /api/keywords/bulk-delete` endpoint, when called with an empty body `{}`, deletes **all** keywords with `search_count=0`. This is by design but combined with no authentication, it means any caller can wipe keyword data.
- **Attack Vector**: `curl -X POST http://host:8002/api/keywords/bulk-delete -H 'Content-Type: application/json' -d '{}'` deletes all unused keywords.
- **Fix**: Require explicit IDs for bulk deletion, or require a confirmation parameter (and add authentication).

### Issue 23: XSS Low Risk — React Handles Rendering Safely

- **File**: All frontend JSX files
- **Risk**: LOW (Informational)
- **Description**: The frontend uses React's JSX rendering throughout, which automatically escapes user-provided content. No instances of `dangerouslySetInnerHTML`, `innerHTML`, `eval()`, or `document.write()` were found. Server-provided data (product names, category names, error messages) is rendered via JSX text interpolation (`{variable}`) which is XSS-safe.
- **Notes**: While the current codebase is safe, future changes should maintain this discipline. No sanitization library is used, so care must be taken if rendering HTML content is ever needed.

### Issue 24: Dependency Versions Are Minimum Bounds — No Pinning

- **File**: `backend/requirements.txt`, `frontend/package.json`
- **Risk**: LOW
- **Description**: Backend dependencies use `>=` version specifiers (e.g., `fastapi>=0.115.0`, `sqlalchemy>=2.0.0`) without upper bounds or pinning. This means `pip install` will install the **latest** version, which may introduce breaking changes or vulnerabilities. Frontend uses `^` (compatible) specifiers which is slightly better but still allows minor version bumps.
- **Fix**: Pin exact versions or use a lockfile:
  ```
  fastapi==0.115.6
  uvicorn==0.34.0
  sqlalchemy==2.0.36
  ```
  Run `pip freeze > requirements.lock` and use that for deployments.

---

## Summary

| Severity | Count | Issues |
|----------|-------|--------|
| **Critical** | 3 | No auth (Issue 1), Wildcard CORS (Issue 2), Unprotected destructive endpoints (Issue 3) |
| **High** | 5 | LIKE injection (Issue 4), Dynamic getattr (Issue 5), Unbounded ingestion payload (Issue 6), Arbitrary file write (Issue 7), No rate limiting (Issue 8) |
| **Medium** | 7 | Unbounded queries (Issue 9), No CSRF (Issue 10), Error info leak (Issue 11), find_duplicates info disclosure (Issue 12), 0.0.0.0 binding (Issue 13), No input length validation (Issue 14), Debug mode risk (Issue 15) |
| **Low** | 9 | API docs exposed (Issue 16), No fetch timeout (Issue 17), No CSP headers (Issue 18), Session management (Issue 19), Unencoded query params (Issue 20), Unbounded bulk delete (Issue 21), Keyword bulk-delete behavior (Issue 22), XSS informational (Issue 23), Unpinned deps (Issue 24) |
| **Total** | **24** | |

### Priority Remediation Roadmap

1. **Immediate** (Week 1): Implement authentication/authorization on ALL endpoints. This single fix addresses Issues 1, 3, 7, 8 (partially), and 22.
2. **Urgent** (Week 2): Fix CORS to allowlist specific origins (Issue 2). Add rate limiting (Issue 8). Bind to `127.0.0.1` (Issue 13).
3. **Important** (Week 3): Add input validation — string lengths (Issue 14), payload size limits (Issue 6), LIKE escaping (Issue 4), getattr allowlists (Issue 5, 12).
4. **Hardening** (Week 4): Add security headers (Issue 18), global error handler (Issue 11), disable docs in production (Issue 16), pin dependencies (Issue 24), CSRF protection (Issue 10).

### Architecture Notes

- The codebase uses **SQLAlchemy ORM** consistently — **no raw SQL strings** were found in the route/service layer. This is good practice and prevents classic SQL injection.
- React's **JSX auto-escaping** prevents XSS in the frontend — no `dangerouslySetInnerHTML` was found.
- The **fundamental issue** is the complete absence of an authentication/authorization layer, which makes every other security control moot. An attacker with network access has full control over the database.
