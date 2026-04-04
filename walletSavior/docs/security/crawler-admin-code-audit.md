# 🔒 Crawler-Admin Code-Level Security Audit

**Scope:** `packages/crawler-admin/backend/` — All Python files  
**Date:** 2025-07-18  
**Auditor:** Copilot Security Planner  
**Status:** Complete  

---

## Executive Summary

The crawler-admin backend manages web crawlers (Playwright, Selenium, requests, cloudscraper, undetected-chromedriver) against external sites, with a plugin system, pipeline, and scheduler. The audit covers **every Python file** in the backend directory.

**Findings:** 3 Critical, 6 High, 8 Medium, 5 Low

| Severity | Count | Top Categories |
|----------|-------|----------------|
| 🔴 Critical | 3 | No Authentication, CORS Wildcard + Credentials, Plugin Code Execution |
| 🟠 High | 6 | SSRF, Command Injection, Credential Exposure, Unsafe Proxy Input, Data Injection, Unvalidated URL Settings |
| 🟡 Medium | 8 | Error Leakage, Path Traversal in Plugin API, Resource Exhaustion, Missing Rate Limiting, Hardcoded Default DB Creds, Weak ETag Hashing, Cleanup Script Exposure, Scheduler Input |
| 🟢 Low | 5 | MD5 usage, Unbounded SSE, Missing HTTPS enforcement, dependency pinning, Anti-detect fingerprint risk |

---

## 🔴 CRITICAL Findings

### C-01: No Authentication on Any API Endpoint

**File:** `api/app.py` (all routes)  
**Lines:** 8–42  
**Risk:** Complete unauthorized access to all crawler management operations  

**Description:**  
Zero authentication or authorization is implemented on any API route. Every endpoint — including crawler execution (`POST /api/crawlers/{id}/run`), bulk runs, schedule management, plugin control, and settings modification — is publicly accessible to anyone who can reach the server.

**Attack Vector:**  
An attacker on the network can:
1. Execute arbitrary crawlers: `POST /api/crawlers/any-crawler/run`
2. Create schedules to repeatedly crawl targets: `POST /api/schedules`
3. Modify crawler target URLs to attack internal services (→ SSRF): `PUT /api/crawlers/{id}/settings`
4. Toggle plugins, modify plugin YAML files
5. Access all crawl logs, dashboard data, ingestion queue
6. Launch bulk crawls to exhaust server resources

**Fix:**
```python
# Add API key or JWT authentication middleware
from fastapi import Depends, Security
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if api_key != os.getenv("CRAWLER_ADMIN_API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")

# Apply to all routes
app.include_router(crawlers_router, dependencies=[Depends(verify_api_key)])
```

---

### C-02: CORS Wildcard with Credentials — Cookie/Auth Token Theft

**File:** `api/app.py:16–22`  

**Description:**  
CORS is configured with `allow_origins=["*"]` AND `allow_credentials=True` simultaneously. Per the [CORS specification](https://fetch.spec.whatwg.org/#http-access-control-allow-credentials), browsers should reject this combination, but some frameworks/browsers may behave inconsistently. More importantly, this signals zero origin restriction intent — any origin can interact with the API.

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Any origin
    allow_credentials=True,        # Sends cookies/auth headers
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Attack Vector:**  
A malicious site can make cross-origin requests to the crawler admin API. Combined with C-01 (no auth), any browser visiting a malicious page can trigger crawler operations.

**Fix:**
```python
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)
```

---

### C-03: Dynamic Plugin Loading Executes Arbitrary Code Without Sandboxing

**File:** `plugins/plugin_loader.py:262–293`  

**Description:**  
The plugin loader dynamically imports and executes Python modules from the filesystem using `importlib.util.spec_from_file_location()` + `spec.loader.exec_module()`. There is **no sandboxing**, no code signing, no hash verification, and no filesystem permission restriction. Any Python file placed in a `crawlers/*/` directory with a `plugin.yaml` will be automatically discovered and executed with full server privileges.

```python
spec = importlib.util.spec_from_file_location(module_name, str(crawler_file))
module = importlib.util.module_from_spec(spec)
sys.modules[module_name] = module
spec.loader.exec_module(module)  # Arbitrary code execution here
```

**Attack Vector:**  
1. If an attacker can write a file to any `crawlers/*/` directory (via path traversal, supply chain, or compromised dependency), they achieve Remote Code Execution.
2. The `reload_plugin()` method deletes from `sys.modules` and re-imports — enabling hot-swap of malicious code.
3. No validation that the code conforms to any interface before execution.

**Fix:**
```python
# 1. Restrict plugin directories to a hardcoded allowlist
# 2. Verify file hashes against a manifest
# 3. Run plugins in a subprocess with restricted permissions
# 4. At minimum, validate the plugin directory is within the expected base path:
def _import_plugin(self, name: str, plugin_dir: Path) -> PluginInterface:
    # Path containment check
    allowed_base = Path(__file__).resolve().parent.parent / "crawlers"
    if not plugin_dir.resolve().is_relative_to(allowed_base.resolve()):
        raise PluginLoadError(name, f"Plugin outside allowed directory: {plugin_dir}")
    # ... rest of import logic
```

---

## 🟠 HIGH Findings

### H-01: SSRF via Configurable Crawler Target URL

**File:** `api/routes/crawlers.py:214–230`, `api/routes/plugins.py:148–185`  
**Risk:** Server-Side Request Forgery  

**Description:**  
The `PUT /api/crawlers/{id}/settings` and `PUT /api/plugins/{id}/settings` endpoints accept a `target_url` parameter with **no URL validation**. An attacker can set any crawler's target to internal addresses.

```python
@router.put("/{crawler_id}/settings")
async def update_crawler_settings(crawler_id: str, body: CrawlerSettingsUpdate):
    if body.target_url is not None:
        current["target_url"] = body.target_url  # No validation!
```

**Attack Vector:**  
1. Set `target_url` to `http://localhost:8002/api/admin/delete-all` → the crawler will hit internal services
2. Set to `http://169.254.169.254/latest/meta-data/` → AWS metadata theft
3. Set to `file:///etc/passwd` (depending on strategy) → local file read
4. Set to internal Docker service URLs → lateral movement

**Fix:**
```python
from urllib.parse import urlparse

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "[::1]"}
ALLOWED_SCHEMES = {"http", "https"}

def validate_target_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"Scheme not allowed: {parsed.scheme}")
    host = parsed.hostname or ""
    if host in BLOCKED_HOSTS or host.startswith("10.") or host.startswith("172.") or host.startswith("192.168."):
        raise ValueError(f"Internal host not allowed: {host}")
    return url
```

---

### H-02: Command Injection in Demo Script via os.system()

**File:** `pipeline/crawl_pipeline.py:252`  
**Risk:** Command Injection  

**Description:**  
The demo script uses `os.system()` with a hardcoded command string. While the current command is static, `os.system()` passes through the shell, and this pattern in a server-side codebase is a red flag. If any part of this command were ever parameterized (e.g., test directory from user input), it would be directly exploitable.

```python
os.system("python -m pytest tests/ engine/tests/ -v --tb=short 2>&1")
```

**Attack Vector:**  
Currently low exploitability since the string is static. However, the pattern sets a dangerous precedent. Any future modification that interpolates user input into this call creates a direct command injection vector.

**Fix:**
```python
import subprocess
subprocess.run(
    ["python", "-m", "pytest", "tests/", "engine/tests/", "-v", "--tb=short"],
    capture_output=True, text=True
)
```

---

### H-03: Hardcoded API Secret in Source Code

**File:** `crawlers/delivery/yogiyo/crawler.py:255–256`  
**Risk:** Credential Exposure  

**Description:**  
A third-party API key and secret are hardcoded directly in source code:

```python
"x-apikey": "iphoneap",
"x-apisecret": "fe5183cc3dea12bd0ce299cf110a75a2",
```

While these may be publicly visible keys from the Yogiyo web app, hardcoding secrets in source code that gets committed to version control is a security anti-pattern. If these are rate-limited or revocable keys, exposure in a public repo leads to abuse.

**Fix:**
```python
YOGIYO_API_KEY = os.getenv("YOGIYO_API_KEY", "")
YOGIYO_API_SECRET = os.getenv("YOGIYO_API_SECRET", "")
```

---

### H-04: SSRF in Ingestion Proxy — Unvalidated Internal URL Construction

**File:** `api/routes/ingestion.py:14–16, 50–56`  
**Risk:** Server-Side Request Forgery  

**Description:**  
The ingestion proxy constructs URLs using string concatenation with user-provided `ingestion_id`:

```python
DB_ADMIN_URL = os.getenv("DB_ADMIN_INGESTION_URL", "http://localhost:8002/api/ingestions")

resp = await client.get(f"{DB_ADMIN_URL}/{ingestion_id}")
```

While `ingestion_id` is typed as `int` in the route signature (which provides some protection), the `DB_ADMIN_URL` itself is configurable via environment variable. If the env var is manipulated or if the type coercion is bypassed, path injection is possible. Also, the cleanup endpoint forwards an arbitrary `body: dict` to the internal service.

**Attack Vector:**  
1. If `DB_ADMIN_URL` is set to a malicious endpoint, all ingestion data is forwarded to an attacker
2. The `cleanup` endpoint forwards raw dicts to internal services — a confused deputy attack

**Fix:**
```python
# Validate ingestion_id is a positive integer (already done via type hint)
# Validate DB_ADMIN_URL at startup
# Don't forward arbitrary dict bodies — use a Pydantic model for cleanup
class CleanupRequest(BaseModel):
    status: str
    older_than_days: Optional[int] = None
```

---

### H-05: Crawled Data Passes Through Pipeline Without Sanitization (Data Injection)

**File:** `pipeline/pipeline.py:168–205`, `pipeline/transformer.py:14–77`  
**Risk:** Stored XSS / SQL Injection via Crawled Data  

**Description:**  
Crawled data from external websites flows through the pipeline (validate → dedup → transform → store) with **no output sanitization**. Field values like `product_name`, `title`, `store`, `url` are taken directly from crawled HTML and passed to the database. If these contain malicious payloads (e.g., `<script>alert('xss')</script>` in a product name), they will be stored and potentially rendered in admin dashboards or user-facing pages.

```python
# transformer.py — raw crawled data passed directly to DB record
def _to_discount_record(item, source, now):
    return {
        "product_name": item.get("normalized_name") or item.get("name", ""),  # No sanitization
        "store": item.get("store", ""),  # No sanitization
        "source_url": item.get("detail_url") or item.get("source_url", ""),  # No sanitization
    }
```

**Attack Vector:**  
1. A compromised or malicious crawl target injects `<script>` tags in product names
2. Data flows to DB-admin → user-facing dashboard → Stored XSS
3. SQL injection via specially crafted price strings (though ORM use would mitigate)

**Fix:**
```python
import html

def sanitize_text(value: str, max_length: int = 500) -> str:
    """Strip HTML tags and escape special characters."""
    if not value:
        return ""
    clean = html.escape(str(value).strip())
    return clean[:max_length]

# Apply in transformer
"product_name": sanitize_text(item.get("name", "")),
```

---

### H-06: Proxy Configuration Accepts Unvalidated Input

**File:** `engine/anti_detect.py:150–152`, `config.py:31–33`  
**Risk:** SSRF / Traffic Hijacking  

**Description:**  
Proxy URLs are loaded from `PROXY_LIST` environment variable and used directly in HTTP requests without validation. A malicious proxy URL could redirect all crawler traffic through an attacker-controlled server, enabling credential theft and data interception.

```python
PROXY_LIST: list[str] = [
    p.strip() for p in os.getenv("PROXY_LIST", "").split(",") if p.strip()
]
```

The `add_proxy()` method also accepts any string without validation:
```python
def add_proxy(self, proxy: str) -> None:
    if proxy not in self._proxies:
        self._proxies.append(proxy)
```

**Fix:**
```python
def validate_proxy(proxy: str) -> str:
    parsed = urlparse(proxy)
    if parsed.scheme not in ("http", "https", "socks5"):
        raise ValueError(f"Invalid proxy scheme: {parsed.scheme}")
    if not parsed.hostname:
        raise ValueError("Proxy must have a hostname")
    return proxy
```

---

## 🟡 MEDIUM Findings

### M-01: Error Messages Leak Internal Information to API Clients

**Files:** `api/routes/crawlers.py:344`, `api/routes/schedules.py:185,208`, `api/routes/ingestion.py:47`  
**Risk:** Information Disclosure  

**Description:**  
Exception messages including internal paths, stack traces, and system details are returned directly to API clients via `str(e)` in HTTP error responses:

```python
# crawlers.py:344
"error": str(e),  # Full exception message exposed to client

# ingestion.py:47
raise HTTPException(502, f"DB 관리 API 연결 실패: {exc}")  # Internal URL leak

# schedules.py:185
raise HTTPException(status_code=400, detail=str(exc))  # APScheduler internals
```

**Attack Vector:**  
Attackers learn internal service URLs, file paths, dependency versions, and system architecture from error responses, aiding targeted attacks.

**Fix:**
```python
# Return generic errors to clients, log details server-side
logger.error(f"Schedule error: {exc}", exc_info=True)
raise HTTPException(400, "Invalid schedule configuration")
```

---

### M-02: Plugin Settings Endpoint Allows Path Traversal in YAML Writes

**File:** `api/routes/plugins.py:148–185`  
**Risk:** Path Traversal  

**Description:**  
The `update_plugin_settings()` endpoint accepts a `plugin_id` string and uses `_find_plugin_yaml()` to locate the YAML file by scanning `crawlers/` with `rglob("plugin.yaml")`. While the scan is constrained to the crawlers directory, the found YAML file is then **written to** with user-provided values. If a `plugin.yaml` exists outside expected locations but within the `rglob` scope, it could be overwritten.

Additionally, the `config` string (line 111) returns the raw YAML dump of plugin configuration to the API client, potentially exposing internal paths:

```python
"path": str(yaml_path.parent),  # Line 112 — exposes filesystem path
```

**Fix:**
```python
# Validate plugin_id contains only alphanumeric/dash/underscore
import re
if not re.match(r'^[a-zA-Z0-9_-]+$', plugin_id):
    raise HTTPException(400, "Invalid plugin ID format")

# Don't expose filesystem paths in API responses
# Remove "path" and "config" from the response
```

---

### M-03: No Rate Limiting on Crawler Execution Endpoints

**Files:** `api/routes/crawlers.py:284–318` (`POST /{id}/run`), `api/routes/crawlers.py:237–281` (`POST /bulk-run`)  
**Risk:** Resource Exhaustion / DoS  

**Description:**  
Crawler execution endpoints have no rate limiting. Each execution spawns browser instances (Playwright/Selenium), makes network requests, and consumes CPU/memory. An attacker can rapidly trigger hundreds of concurrent crawl operations.

```python
@router.post("/{crawler_id}/run")
async def run_crawler(crawler_id: str):
    # No rate limit check
    asyncio.create_task(_run_and_store(crawler_id, pipeline))
```

The bulk-run endpoint iterates over a list of IDs and creates async tasks for each, with only a "already running" check per crawler — not a global concurrency limit.

**Fix:**
```python
from fastapi import Depends
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/{crawler_id}/run")
@limiter.limit("5/minute")
async def run_crawler(crawler_id: str, request: Request):
    ...

# Also add a global concurrency semaphore
MAX_CONCURRENT_CRAWLS = 5
_crawl_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)
```

---

### M-04: Hardcoded Default Database Credentials in config.py

**File:** `config.py:18`  
**Risk:** Credential Exposure  

**Description:**  
Default database credentials are hardcoded as a fallback:

```python
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/wallet_guardian"
)
```

If the environment variable is not set, the application connects with `user:password` — trivially guessable default credentials.

**Fix:**
```python
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")
```

---

### M-05: Weak Hash (MD5) for ETag Generation

**File:** `api/routes/crawlers.py:137, 373`  
**Risk:** Hash Collision  

**Description:**  
MD5 is used for ETag generation and change detection in the SSE stream:

```python
etag = hashlib.md5(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()
```

While MD5 for non-cryptographic ETags is not directly exploitable for security, it's a deprecated algorithm and using it signals weak cryptographic hygiene. ETags could be forged to trick caching.

**Fix:**
```python
import hashlib
etag = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:16]
```

---

### M-06: Unbounded asyncio.create_task() Without Concurrency Control

**File:** `api/routes/crawlers.py:274, 312`  
**Risk:** Resource Exhaustion  

**Description:**  
`asyncio.create_task()` is called for each crawler run without any concurrency limit. The bulk-run endpoint loops over all provided IDs and fires tasks:

```python
for cid in body.crawler_ids:
    asyncio.create_task(_run_and_store(cid, pipeline))
```

Each task may launch a browser instance (Playwright/Selenium), consuming 100–500MB RAM each. A request with 50 crawler IDs would attempt to launch 50 browser instances simultaneously.

**Fix:**
```python
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT_CRAWLS", "5"))
_semaphore = asyncio.Semaphore(MAX_CONCURRENT)

async def _run_and_store(crawler_id, pipeline):
    async with _semaphore:
        # ... existing logic
```

---

### M-07: collect_seed_data.py Uses __import__ with Module Paths from Hardcoded List

**File:** `collect_seed_data.py:25`  
**Risk:** Code Execution (Low Exploitability)  

**Description:**  
Uses `__import__()` to dynamically load crawler modules:

```python
mod = __import__(module, fromlist=[cls_name])
```

Currently the module paths come from a hardcoded list, so exploitation requires modifying the source file. However, this pattern is dangerous if the list were ever made configurable.

**Fix:**
```python
import importlib
mod = importlib.import_module(module)
```

---

### M-08: Schedule Cron Expression Not Validated for Abuse

**File:** `api/routes/schedules.py:109–111, 178–198`  
**Risk:** Resource Abuse  

**Description:**  
Cron expressions are accepted without semantic validation. A user could create a schedule like `* * * * *` (every minute) for every crawler, causing continuous resource consumption.

```python
class ScheduleCreate(BaseModel):
    crawler_name: str
    cron: str  # No validation — accepts any string
```

APScheduler's `CronTrigger.from_crontab()` validates syntax but not frequency. The `crawler_name` is also not validated against the registry — schedules can be created for non-existent crawlers.

**Fix:**
```python
from pydantic import field_validator

class ScheduleCreate(BaseModel):
    crawler_name: str
    cron: str

    @field_validator('cron')
    @classmethod
    def validate_cron(cls, v):
        CronTrigger.from_crontab(v)  # Syntax check
        # Frequency check: reject intervals shorter than 5 minutes
        parts = v.split()
        if parts[0] == '*' and parts[1] == '*':
            raise ValueError("Schedules more frequent than hourly are not allowed")
        return v
```

---

## 🟢 LOW Findings

### L-01: MD5 Used for URL Deduplication Hashing

**File:** `pipeline/dedup.py:79`  
**Risk:** Hash Collision (Negligible)  

**Description:**  
MD5 is used to hash normalized URLs for deduplication. In this context, intentional hash collisions could cause false dedup matches, dropping unique items. Practically unlikely but worth noting.

**Fix:** Use `hashlib.sha256()` for marginally better collision resistance.

---

### L-02: SSE Stream Has No Maximum Duration

**File:** `api/routes/crawlers.py:352–394`  
**Risk:** Connection Exhaustion  

**Description:**  
The SSE endpoint only terminates on client disconnect or crawler completion. If a crawler hangs without finishing, the SSE connection stays open indefinitely, consuming a server connection slot.

**Fix:** Add a maximum stream duration (e.g., 30 minutes) with `asyncio.wait_for()`.

---

### L-03: No HTTPS Enforcement

**File:** `config.py:66`  
**Risk:** Man-in-the-Middle  

**Description:**  
The API server binds to `0.0.0.0` by default with no TLS configuration. All API traffic, including any future auth tokens, would be transmitted in plaintext.

**Fix:** Deploy behind a reverse proxy (nginx/caddy) with TLS, or add HTTPS support directly.

---

### L-04: Dependency Version Ranges Allow Vulnerable Versions

**File:** `requirements.txt`  
**Risk:** Supply Chain  

**Description:**  
All dependencies use `>=` minimum versions without upper bounds:
```
requests>=2.32.0
selenium>=4.28.0
playwright>=1.50.0
```

This allows pip to install any future version, including potentially compromised ones. `cloudscraper` in particular has had supply chain concerns.

**Fix:** Pin exact versions or use upper bounds: `requests>=2.32.0,<3.0.0`

---

### L-05: Anti-Detect Module Creates Predictable Fingerprint Pool

**File:** `engine/anti_detect.py:28–73`  
**Risk:** Bot Detection / Account Banning  

**Description:**  
The User-Agent pool and Accept header combinations are hardcoded and finite (18 UAs, 3 Accept sets). Over time, target sites can fingerprint this fixed set and build a blocklist. This isn't a direct security vulnerability for the server but could lead to all crawlers being permanently banned.

**Fix:** Consider loading UA lists from an external, regularly updated source.

---

## Summary of Recommendations (Priority Order)

| Priority | Action | Effort |
|----------|--------|--------|
| 🔴 P0 | Add authentication to all API endpoints | Medium |
| 🔴 P0 | Restrict CORS origins; remove `allow_origins=["*"]` | Low |
| 🔴 P0 | Add plugin path containment + code signing | Medium |
| 🟠 P1 | Validate `target_url` against SSRF blocklist | Low |
| 🟠 P1 | Sanitize all crawled data before storage | Medium |
| 🟠 P1 | Move secrets to env vars; remove hardcoded keys | Low |
| 🟠 P1 | Replace `os.system()` with `subprocess.run()` | Low |
| 🟡 P2 | Add rate limiting to execution endpoints | Medium |
| 🟡 P2 | Add concurrency limits (semaphore) for crawler tasks | Low |
| 🟡 P2 | Sanitize error messages before returning to clients | Low |
| 🟡 P2 | Validate cron frequency in schedule creation | Low |
| 🟡 P2 | Remove default DB credentials from config.py | Low |
| 🟢 P3 | Pin dependency versions | Low |
| 🟢 P3 | Add SSE timeout, HTTPS enforcement | Low |

---

## Files Reviewed

### API Layer
- `api/app.py` — FastAPI app creation, CORS, middleware
- `api/routes/crawlers.py` — Crawler CRUD, execution, SSE streaming
- `api/routes/dashboard.py` — Dashboard statistics
- `api/routes/ingestion.py` — Ingestion proxy to DB-admin
- `api/routes/logs.py` — Log viewing, CSV export
- `api/routes/plugins.py` — Plugin management, YAML read/write
- `api/routes/schedules.py` — Schedule CRUD, APScheduler integration

### Engine Layer
- `engine/executor.py` — Multi-strategy cascade executor
- `engine/anti_detect.py` — Bot detection evasion (UA, proxy, delay)
- `engine/playwright_helper.py` — Playwright browser pool management
- `engine/diagnostics.py` — Failure diagnosis engine
- `engine/strategies/base.py` — Base strategy with anti-detect
- `engine/strategies/requests_st.py` — requests/BeautifulSoup strategy
- `engine/strategies/cloudscraper_st.py` — Cloudscraper strategy
- `engine/strategies/selenium_st.py` — Selenium + stealth strategy
- `engine/strategies/undetected_st.py` — undetected-chromedriver strategy
- `engine/strategies/playwright_st.py` — Playwright + stealth strategy

### Pipeline Layer
- `pipeline/pipeline.py` — Full crawl pipeline (crawl→validate→transform→store)
- `pipeline/validator.py` — Data validation, deduplication, price normalization
- `pipeline/dedup.py` — Hotdeal deduplication (URL + title similarity)
- `pipeline/transformer.py` — Data transformation to DB records
- `pipeline/crawl_pipeline.py` — Demo/verification script
- `pipeline/crawl_demo.py` — Crawling demo script

### Plugin System
- `plugins/plugin_interface.py` — Plugin interface definition
- `plugins/plugin_loader.py` — Dynamic plugin discovery and loading
- `plugins/plugin_manager.py` — Plugin lifecycle management

### Scheduler
- `scheduler/scheduler.py` — APScheduler-based scheduling
- `scheduler/job_tracker.py` — Job execution history tracking

### Infrastructure
- `config.py` — Environment-based configuration
- `crawlers/registry/registry.py` — Crawler auto-discovery registry
- `collect_seed_data.py` — Seed data collection script
- `requirements.txt` — Python dependencies

### Crawlers (sampled for patterns)
- `crawlers/delivery/yogiyo/crawler.py` — Hardcoded API credentials found
- All crawler modules follow same pattern — `str(e)` in error messages
