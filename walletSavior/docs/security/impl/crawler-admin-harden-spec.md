# Crawler-Admin Hardening Implementation Spec

> **Scope:** Resource Limits, Rate Limiting, Data Sanitization, Error Handling, Audit Trail, Bind Address, Concurrency Safety  
> **Base Path:** `packages/crawler-admin/backend/`  
> **Audit Sources:** `crawler-admin-code-audit.md` (C-01–L-05), `crawler-admin-arch-audit.md` (CRIT-01–LOW-04)  
> **Date:** 2025-07-18

---

## Table of Contents

1. [Bind Address — 127.0.0.1](#1-bind-address)
2. [Concurrency Safety](#2-concurrency-safety)
3. [Resource Limits](#3-resource-limits)
4. [Rate Limiting](#4-rate-limiting)
5. [Data Sanitization](#5-data-sanitization)
6. [Error Handling](#6-error-handling)
7. [Audit Trail](#7-audit-trail)
8. [New Dependencies](#8-new-dependencies)
9. [Docker Hardening](#9-docker-hardening)
10. [Test Cases](#10-test-cases)
11. [Rollout Checklist](#11-rollout-checklist)

---

## 1. Bind Address

**Audit refs:** CRIT-06, L-03  
**Risk:** API exposed on all network interfaces — any host on the LAN/VPC can control crawlers.

### 1.1 Change: `config.py` line 66

```python
# BEFORE
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")

# AFTER
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
```

Single-line change. Docker/production deployments that need external access must set `API_HOST=0.0.0.0` explicitly via env var and should place a reverse proxy (nginx with TLS) in front.

### 1.2 Docker Compose guard

In `docker-compose.yml`, bind the published port to localhost only:

```yaml
# BEFORE
ports:
  - "8001:8000"

# AFTER
ports:
  - "127.0.0.1:8001:8000"
```

---

## 2. Concurrency Safety

**Audit refs:** M-06, HIGH-04, arch "Crawler Isolation"  
**Risk:** Duplicate crawler runs via race condition; unbounded `asyncio.create_task()`.

### 2.1 New file: `backend/concurrency.py`

```python
"""
Concurrency primitives for crawler execution.

Provides:
- A global semaphore limiting total concurrent crawler tasks.
- A per-crawler lock set preventing duplicate runs of the same crawler.
"""

import asyncio
import os
import logging

logger = logging.getLogger(__name__)

MAX_CONCURRENT_CRAWLS: int = int(os.getenv("MAX_CONCURRENT_CRAWLS", "5"))

# Global semaphore — caps total browser/crawler processes
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)

# Per-crawler lock set — prevents the same crawler from running twice
_running_crawlers: set[str] = set()
_lock = asyncio.Lock()


async def acquire_crawler_slot(crawler_id: str) -> bool:
    """Try to mark a crawler as running. Returns False if already running."""
    async with _lock:
        if crawler_id in _running_crawlers:
            return False
        _running_crawlers.add(crawler_id)
    return True


async def release_crawler_slot(crawler_id: str) -> None:
    """Mark a crawler as no longer running."""
    async with _lock:
        _running_crawlers.discard(crawler_id)


def get_semaphore() -> asyncio.Semaphore:
    return _semaphore


def active_count() -> int:
    return len(_running_crawlers)
```

### 2.2 Changes: `api/routes/crawlers.py`

#### 2.2.1 Import the module (add near line 1)

```python
from concurrency import (
    acquire_crawler_slot,
    release_crawler_slot,
    get_semaphore,
    MAX_CONCURRENT_CRAWLS,
)
```

#### 2.2.2 Replace the `_run_and_store` function (lines 321–349)

```python
async def _run_and_store(crawler_id: str, pipeline: CrawlPipeline):
    """Background: execute crawler under global semaphore + per-crawler guard."""
    try:
        async with get_semaphore():
            result = await pipeline.run_crawler(crawler_id)

        _crawl_results[crawler_id] = {
            "crawler_id": crawler_id,
            "status": result.status,
            "items_found": result.items_found,
            "items_valid": result.items_valid,
            "items_saved": result.items_saved,
            "duration": result.duration,
            "errors": result.errors,
            "finished_at": datetime.now().isoformat(),
        }
        _append_run_history(crawler_id, result.status, result.duration)
        logger.info(
            f"Crawler '{crawler_id}' completed: {result.status} "
            f"(found={result.items_found}, saved={result.items_saved})"
        )
    except Exception as e:
        _crawl_results[crawler_id] = {
            "crawler_id": crawler_id,
            "status": "failed",
            "error": "Crawler execution failed",      # safe message
            "finished_at": datetime.now().isoformat(),
            "errors": ["internal error"],
        }
        _append_run_history(crawler_id, "failed")
        logger.error(f"Crawler '{crawler_id}' failed: {e}", exc_info=True)
    finally:
        await release_crawler_slot(crawler_id)
```

#### 2.2.3 Replace the duplicate-check in `run_crawler` (lines 293–299)

```python
# BEFORE — dict-based check (race-prone)
current = _crawl_results.get(crawler_id)
if current and current.get("status") == "running":
    return { ... }

# AFTER — atomic lock-based check
if not await acquire_crawler_slot(crawler_id):
    return {
        "crawler_id": crawler_id,
        "status": "running",
        "message": f"Crawler '{crawler_id}' is already running",
    }
```

Apply the same pattern inside `bulk_run_crawlers` (lines 256–262).

#### 2.2.4 Cap `bulk-run` input size (line 237 area)

```python
class BulkRunRequest(BaseModel):
    crawler_ids: list[str]

    @field_validator("crawler_ids")
    @classmethod
    def cap_size(cls, v):
        if len(v) > MAX_CONCURRENT_CRAWLS:
            raise ValueError(
                f"Maximum {MAX_CONCURRENT_CRAWLS} crawlers per bulk-run request"
            )
        return v
```

---

## 3. Resource Limits

**Audit refs:** HIGH-04, M-06, arch "Crawler Isolation"  
**Risk:** Browser subprocesses consume unbounded RAM/CPU; no cumulative timeout.

### 3.1 Cumulative timeout: `engine/executor.py`

Add a total execution timeout across all strategies:

```python
# Add at module level (near line 45)
_DEFAULT_STRATEGY_TIMEOUT = 60
_MAX_CUMULATIVE_TIMEOUT = int(os.getenv("CRAWL_CUMULATIVE_TIMEOUT", "180"))

# In execute() — wrap the entire strategy cascade
async def execute(self, url: str, **options) -> CrawlResult:
    try:
        return await asyncio.wait_for(
            self._execute_cascade(url, **options),
            timeout=self._cumulative_timeout,
        )
    except asyncio.TimeoutError:
        logger.error(f"Cumulative timeout ({self._cumulative_timeout}s) exceeded for {url}")
        return CrawlResult(
            status=CrawlStatus.FAILED,
            errors=[f"Cumulative timeout ({self._cumulative_timeout}s) exceeded"],
        )
```

Move the current cascade logic into `_execute_cascade()`.

### 3.2 Constructor change: `engine/executor.py`

```python
def __init__(
    self,
    strategies: list,
    event_bus: Optional[EventBus] = None,
    strategy_timeout: Optional[int] = None,
    cumulative_timeout: Optional[int] = None,
) -> None:
    self._strategies = sorted(strategies, key=lambda s: s.difficulty)
    self._event_bus = event_bus or EventBus()
    self._strategy_timeout = strategy_timeout or _DEFAULT_STRATEGY_TIMEOUT
    self._cumulative_timeout = cumulative_timeout or _MAX_CUMULATIVE_TIMEOUT
```

### 3.3 Browser resource flags

**File:** Each browser strategy that spawns Chrome/Chromium.

#### `engine/strategies/selenium_st.py` — Selenium Chrome options

```python
# Add to Chrome options construction
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--js-flags=--max-old-space-size=256")
options.add_argument("--single-process")
options.add_argument("--disable-extensions")
options.add_argument("--disable-gpu")
```

#### `engine/strategies/playwright_st.py` — Playwright launch args

```python
browser = await playwright.chromium.launch(
    headless=True,
    args=[
        "--disable-dev-shm-usage",
        "--js-flags=--max-old-space-size=256",
        "--disable-extensions",
        "--disable-gpu",
    ],
)
```

#### `engine/strategies/undetected_st.py` — undetected-chromedriver

```python
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--js-flags=--max-old-space-size=256")
```

### 3.4 SSE stream timeout: `api/routes/crawlers.py` (lines 352–394)

```python
_SSE_MAX_DURATION = int(os.getenv("SSE_MAX_DURATION", "1800"))  # 30 min

async def event_generator():
    last_hash = None
    stream_start = time.monotonic()
    while True:
        if await request.is_disconnected():
            break
        if time.monotonic() - stream_start > _SSE_MAX_DURATION:
            yield f'data: {{"status":"timeout","message":"Stream max duration reached"}}\n\n'
            break
        # ... rest unchanged
```

### 3.5 Config additions: `config.py`

```python
# --- Resource Limits ---
MAX_CONCURRENT_CRAWLS: int = int(os.getenv("MAX_CONCURRENT_CRAWLS", "5"))
CRAWL_CUMULATIVE_TIMEOUT: int = int(os.getenv("CRAWL_CUMULATIVE_TIMEOUT", "180"))
SSE_MAX_DURATION: int = int(os.getenv("SSE_MAX_DURATION", "1800"))
```

---

## 4. Rate Limiting

**Audit refs:** HIGH-02, M-03  
**Risk:** No inbound API rate limiting; no outbound crawl rate limiting.

### 4.1 Inbound API rate limiting (slowapi)

#### 4.1.1 New dependency

```
slowapi>=0.1.9
```

#### 4.1.2 Changes: `api/app.py`

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

def create_app() -> FastAPI:
    app = FastAPI(...)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    # ... rest unchanged
    return app
```

#### 4.1.3 Rate limit decorators: `api/routes/crawlers.py`

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/{crawler_id}/run")
@limiter.limit("5/minute")
async def run_crawler(crawler_id: str, request: Request):
    ...

@router.post("/bulk-run")
@limiter.limit("2/minute")
async def bulk_run_crawlers(body: BulkRunRequest, request: Request):
    ...

@router.get("")
@limiter.limit("60/minute")
async def list_crawlers(request: Request):
    ...
```

#### 4.1.4 Rate limits per route group

| Route Pattern | Limit | Rationale |
|---|---|---|
| `POST /*/run`, `POST /bulk-run` | 5/min, 2/min | Each spawns browser processes |
| `PUT /*/settings` | 10/min | Config changes should be rare |
| `GET /*/status`, `GET /` | 60/min | Read-heavy but bounded |
| `POST /schedules`, `PUT /schedules/*` | 10/min | Schedule mutations |
| `GET /logs/*`, `GET /dashboard/*` | 30/min | Report queries |
| `POST /ingestion/*` | 20/min | Data submission |

### 4.2 Outbound crawl rate limiting

#### 4.2.1 New file: `backend/engine/rate_limiter.py`

```python
"""
Per-domain outbound rate limiter.

Ensures crawlers respect a minimum interval between requests to the same domain.
Prevents IP bans and legal issues from aggressive crawling.
"""

import asyncio
import time
import os
from urllib.parse import urlparse
from collections import defaultdict

_DEFAULT_MIN_INTERVAL = float(os.getenv("CRAWL_MIN_DOMAIN_INTERVAL", "2.0"))


class DomainRateLimiter:
    """Enforces a per-domain minimum interval between outbound requests."""

    def __init__(self, min_interval: float = _DEFAULT_MIN_INTERVAL):
        self._min_interval = min_interval
        self._last_request: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def wait(self, url: str) -> None:
        """Block until the domain is available for a new request."""
        domain = urlparse(url).netloc.lower()
        if not domain:
            return

        async with self._locks[domain]:
            elapsed = time.monotonic() - self._last_request[domain]
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request[domain] = time.monotonic()

    def set_interval(self, domain: str, interval: float) -> None:
        """Override interval for a specific domain (e.g., from robots.txt Crawl-delay)."""
        # Stored per-domain; wait() uses the global default if no override exists
        pass  # future enhancement


# Module-level singleton
_limiter = DomainRateLimiter()


def get_domain_limiter() -> DomainRateLimiter:
    return _limiter
```

#### 4.2.2 Integration: `engine/executor.py`

Before calling `strategy.fetch(url)`:

```python
from engine.rate_limiter import get_domain_limiter

# Inside _execute_cascade(), before each strategy attempt:
await get_domain_limiter().wait(url)
raw_data = await asyncio.wait_for(
    strategy.fetch(url, **options),
    timeout=self._strategy_timeout,
)
```

---

## 5. Data Sanitization

**Audit refs:** H-05, arch "Pipeline Integrity"  
**Risk:** Crawled HTML data stored unsanitized → Stored XSS, SQL injection via product names.

### 5.1 New file: `backend/pipeline/sanitizer.py`

```python
"""
Data sanitization for crawled content.

All text fields from external sources MUST pass through these functions
before entering the pipeline's transform stage.
"""

import html
import re
from typing import Any, Optional

# Strip HTML tags
_TAG_RE = re.compile(r"<[^>]+>")

# Allow only safe characters (letters, digits, common punctuation, Korean)
_UNSAFE_CHARS_RE = re.compile(r"[^\w\s가-힣ㄱ-ㅎㅏ-ㅣ.,;:!?%()\-/&#+@₩$€¥·•–—''""\"' ]")

# Null bytes and control characters (except newline/tab)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Collapse whitespace
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def sanitize_text(value: Any, max_length: int = 500) -> str:
    """
    Sanitize a text field from crawled data.

    1. Coerce to string
    2. Remove null bytes and control characters
    3. Strip HTML tags
    4. HTML-escape special characters (prevents XSS)
    5. Remove remaining unsafe characters
    6. Collapse whitespace
    7. Truncate to max_length
    """
    if value is None:
        return ""
    text = str(value)

    text = _CONTROL_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    text = html.escape(text, quote=True)
    text = _MULTI_SPACE_RE.sub(" ", text).strip()
    return text[:max_length]


def sanitize_url(value: Any, max_length: int = 2048) -> str:
    """
    Sanitize a URL field.

    1. Coerce to string
    2. Strip whitespace
    3. Reject javascript: / data: / vbscript: schemes
    4. Truncate to max_length
    """
    if value is None:
        return ""
    url = str(value).strip()

    lower = url.lower()
    if any(lower.startswith(s) for s in ("javascript:", "data:", "vbscript:")):
        return ""

    url = _CONTROL_RE.sub("", url)
    return url[:max_length]


def sanitize_number(value: Any, min_val: float = 0, max_val: float = 100_000_000) -> Optional[float]:
    """
    Validate and coerce a numeric value.

    Returns None if the value is not a valid number or out of range.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num < min_val or num > max_val:
        return None
    return num


def sanitize_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Apply field-level sanitization to a pipeline record.

    Text fields → sanitize_text()
    URL fields  → sanitize_url()
    Price fields → sanitize_number()
    """
    text_fields = [
        "product_name", "title", "store", "category",
        "event_name", "source", "source_community",
    ]
    url_fields = ["source_url", "url", "detail_url", "image_url"]
    price_fields = [
        "original_price", "sale_price", "price", "discount_percent",
    ]

    sanitized = dict(record)

    for field in text_fields:
        if field in sanitized:
            sanitized[field] = sanitize_text(sanitized[field])

    for field in url_fields:
        if field in sanitized:
            sanitized[field] = sanitize_url(sanitized[field])

    for field in price_fields:
        if field in sanitized:
            sanitized[field] = sanitize_number(sanitized[field])

    return sanitized
```

### 5.2 Integration: `pipeline/transformer.py`

Apply `sanitize_record()` to every output record:

```python
from pipeline.sanitizer import sanitize_record

# In to_discount_history() (around line 17)
def to_discount_history(items, source="mart_discount"):
    now = datetime.now().isoformat()
    records = [_to_discount_record(item, source, now) for item in items]
    return [sanitize_record(r) for r in records]

# In to_hotdeal_prices() (around line 54)
def to_hotdeal_prices(items, source="hotdeal"):
    now = datetime.now().isoformat()
    records = [_to_hotdeal_record(item, source, now) for item in items]
    return [sanitize_record(r) for r in records]
```

### 5.3 Pre-pipeline input sanitization: `pipeline/pipeline.py`

Add an early sanitization pass on raw crawled items before validation:

```python
from pipeline.sanitizer import sanitize_text, sanitize_url

# In run_crawler(), after crawl completes and before validation (around line 177)
# Sanitize raw items before they enter the pipeline
for item in items:
    for key, val in list(item.items()):
        if isinstance(val, str) and len(val) > 5000:
            item[key] = val[:5000]  # Prevent memory abuse via huge strings
```

---

## 6. Error Handling

**Audit refs:** M-01  
**Risk:** `str(e)` in HTTP responses leaks internal paths, stack traces, dependency versions.

### 6.1 New file: `backend/api/error_handler.py`

```python
"""
Safe error handling for API responses.

Never expose internal details (paths, stack traces, SQL, URLs) to API clients.
Log full details server-side for debugging.
"""

import logging
import traceback
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("security.errors")


# Map known exception types to safe user-facing messages
_SAFE_MESSAGES = {
    KeyError: "Resource not found",
    ValueError: "Invalid input provided",
    FileNotFoundError: "Resource not found",
    PermissionError: "Operation not permitted",
    TimeoutError: "Operation timed out",
    ConnectionError: "Service temporarily unavailable",
}


def safe_error_detail(exc: Exception) -> str:
    """Return a generic, safe error message for the given exception."""
    for exc_type, message in _SAFE_MESSAGES.items():
        if isinstance(exc, exc_type):
            return message
    return "An internal error occurred"


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler — logs full details, returns safe response.

    Attaches a correlation ID so operators can match user-reported errors
    to server-side log entries.
    """
    error_id = uuid.uuid4().hex[:12]

    logger.error(
        f"[{error_id}] Unhandled exception on {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}",
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "error_id": error_id,
        },
    )
```

### 6.2 Register handler: `api/app.py`

```python
from api.error_handler import global_exception_handler

def create_app() -> FastAPI:
    app = FastAPI(...)
    app.add_exception_handler(Exception, global_exception_handler)
    # ... rest unchanged
```

### 6.3 Replace `str(e)` in route handlers

All HTTPException `detail` strings that use `str(e)` or `str(exc)` must be replaced with safe messages. These are the exact locations:

| File | Line(s) | Current | Replacement |
|---|---|---|---|
| `routes/crawlers.py` | 344 | `"error": str(e)` | `"error": "Crawler execution failed"` |
| `routes/schedules.py` | 185 | `detail=str(exc)` | `detail="Invalid schedule configuration"` |
| `routes/schedules.py` | 208 | `detail=str(exc)` | `detail="Failed to update schedule"` |
| `routes/ingestion.py` | 47 | `f"DB 관리 API 연결 실패: {exc}"` | `"Upstream service unavailable"` |
| `routes/plugins.py` | varies | `str(e)` in HTTPException | `"Plugin operation failed"` |

Each replacement must be accompanied by a `logger.error(...)` call with `exc_info=True` to preserve the diagnostic information server-side.

Pattern for each replacement:

```python
# BEFORE
except Exception as exc:
    raise HTTPException(status_code=400, detail=str(exc))

# AFTER
except Exception as exc:
    logger.error(f"Schedule creation failed: {exc}", exc_info=True)
    raise HTTPException(status_code=400, detail="Invalid schedule configuration")
```

---

## 7. Audit Trail

**Audit refs:** MED-01, arch "Audit Trail"  
**Risk:** No structured logging of who triggered crawls, what data was submitted, or when configs changed.

### 7.1 New file: `backend/audit.py`

```python
"""
Structured audit logger for security-relevant events.

Emits JSON-formatted log records to a dedicated audit log file.
Each record includes: timestamp, event type, actor (IP), target resource,
action, result, and a request hash for non-repudiation.

Log file: logs/audit.jsonl (append-only)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Request

_AUDIT_LOG_DIR = Path(os.getenv(
    "AUDIT_LOG_DIR",
    str(Path(__file__).resolve().parent / "logs")
))
_AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

_audit_logger = logging.getLogger("audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

if not _audit_logger.handlers:
    handler = logging.FileHandler(
        _AUDIT_LOG_DIR / "audit.jsonl",
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(handler)


class AuditEventType:
    CRAWLER_RUN = "crawler.run"
    CRAWLER_BULK_RUN = "crawler.bulk_run"
    CRAWLER_SETTINGS_UPDATE = "crawler.settings_update"
    SCHEDULE_CREATE = "schedule.create"
    SCHEDULE_DELETE = "schedule.delete"
    SCHEDULE_TOGGLE = "schedule.toggle"
    PLUGIN_TOGGLE = "plugin.toggle"
    PLUGIN_SETTINGS_UPDATE = "plugin.settings_update"
    DATA_SUBMISSION = "data.submission"
    DATA_INGESTION = "data.ingestion"
    CRAWL_COMPLETED = "crawler.completed"
    CRAWL_FAILED = "crawler.failed"


def audit_log(
    event_type: str,
    *,
    request: Optional[Request] = None,
    actor_ip: Optional[str] = None,
    resource: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    result: str = "success",
) -> None:
    """
    Emit a structured audit log entry.

    Args:
        event_type: One of AuditEventType constants.
        request: The incoming FastAPI Request (extracts IP, method, path).
        actor_ip: Override IP if request is not available.
        resource: The target resource identifier (e.g., crawler_id).
        detail: Additional context (will be JSON-serialized).
        result: "success", "failure", "denied", or "error".
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "result": result,
        "resource": resource,
    }

    if request:
        entry["actor_ip"] = request.client.host if request.client else "unknown"
        entry["method"] = request.method
        entry["path"] = str(request.url.path)
    elif actor_ip:
        entry["actor_ip"] = actor_ip

    if detail:
        entry["detail"] = detail

    _audit_logger.info(json.dumps(entry, ensure_ascii=False, default=str))
```

### 7.2 Instrument each route handler

Below are the exact audit points to add in each route file.

#### `routes/crawlers.py`

```python
from audit import audit_log, AuditEventType

# In run_crawler() — after acquiring the slot, before creating the task:
audit_log(
    AuditEventType.CRAWLER_RUN,
    request=request,
    resource=crawler_id,
)

# In _run_and_store() — on completion:
audit_log(
    AuditEventType.CRAWL_COMPLETED,
    resource=crawler_id,
    detail={
        "items_found": result.items_found,
        "items_saved": result.items_saved,
        "duration": result.duration,
        "strategy": getattr(result, "strategy_used", None),
    },
)

# In _run_and_store() — on failure:
audit_log(
    AuditEventType.CRAWL_FAILED,
    resource=crawler_id,
    result="error",
)

# In bulk_run_crawlers():
audit_log(
    AuditEventType.CRAWLER_BULK_RUN,
    request=request,
    detail={"crawler_ids": body.crawler_ids},
)

# In update_crawler_settings():
audit_log(
    AuditEventType.CRAWLER_SETTINGS_UPDATE,
    request=request,
    resource=crawler_id,
    detail={"fields_changed": list(body.dict(exclude_unset=True).keys())},
)
```

#### `routes/schedules.py`

```python
from audit import audit_log, AuditEventType

# In create_schedule():
audit_log(
    AuditEventType.SCHEDULE_CREATE,
    request=request,
    resource=body.crawler_name,
    detail={"cron": body.cron},
)

# In delete_schedule():
audit_log(
    AuditEventType.SCHEDULE_DELETE,
    request=request,
    resource=crawler_name,
)

# In toggle_schedule():
audit_log(
    AuditEventType.SCHEDULE_TOGGLE,
    request=request,
    resource=crawler_name,
    detail={"enabled": body.enabled},
)
```

#### `routes/plugins.py`

```python
from audit import audit_log, AuditEventType

# In toggle_plugin():
audit_log(
    AuditEventType.PLUGIN_TOGGLE,
    request=request,
    resource=plugin_id,
    detail={"enabled": body.enabled},
)

# In update_plugin_settings():
audit_log(
    AuditEventType.PLUGIN_SETTINGS_UPDATE,
    request=request,
    resource=plugin_id,
)
```

#### `routes/ingestion.py`

```python
from audit import audit_log, AuditEventType

# In submit_ingestion():
audit_log(
    AuditEventType.DATA_INGESTION,
    request=request,
    detail={"item_count": len(body.items) if hasattr(body, 'items') else 0},
)
```

#### `pipeline/pipeline.py`

```python
from audit import audit_log, AuditEventType

# In _store_to_ingestion() — on successful submission:
audit_log(
    AuditEventType.DATA_SUBMISSION,
    resource=crawler_name,
    detail={
        "item_count": len(items),
        "schema_type": schema_type,
        "strategy": strategy_used,
    },
)
```

### 7.3 Audit log format (sample entry)

```json
{
  "timestamp": "2025-07-18T14:32:01.123456+00:00",
  "event": "crawler.run",
  "result": "success",
  "resource": "emart-discount",
  "actor_ip": "127.0.0.1",
  "method": "POST",
  "path": "/api/crawlers/emart-discount/run"
}
```

### 7.4 Log rotation

Add to `config.py`:

```python
AUDIT_LOG_MAX_BYTES: int = int(os.getenv("AUDIT_LOG_MAX_BYTES", str(50 * 1024 * 1024)))  # 50MB
AUDIT_LOG_BACKUP_COUNT: int = int(os.getenv("AUDIT_LOG_BACKUP_COUNT", "10"))
```

Optionally use `RotatingFileHandler` in `audit.py`:

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    _AUDIT_LOG_DIR / "audit.jsonl",
    maxBytes=50 * 1024 * 1024,   # 50 MB
    backupCount=10,
    encoding="utf-8",
)
```

---

## 8. New Dependencies

Add to `requirements.txt`:

```
slowapi>=0.1.9
```

No other new runtime dependencies required. All sanitization, audit, concurrency, and error handling code uses Python stdlib.

---

## 9. Docker Hardening

**Audit refs:** HIGH-04  

### 9.1 `docker-compose.yml` resource limits

```yaml
services:
  crawler-admin:
    # ... existing config ...
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"
        reservations:
          memory: 512M
          cpus: "0.5"
    # Limit child processes (prevents fork bombs from crawlers)
    pids_limit: 100
    ports:
      - "127.0.0.1:8001:8000"
    environment:
      - API_HOST=0.0.0.0           # Inside container, bind all interfaces
      - MAX_CONCURRENT_CRAWLS=5
      - CRAWL_CUMULATIVE_TIMEOUT=180
```

### 9.2 `docker-compose.dev.yml` overrides

```yaml
services:
  crawler-admin:
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "4.0"
    pids_limit: 200
    environment:
      - MAX_CONCURRENT_CRAWLS=3
```

---

## 10. Test Cases

### 10.1 Concurrency tests: `tests/test_concurrency.py`

```python
"""Tests for concurrency control primitives."""

import asyncio
import pytest
from concurrency import (
    acquire_crawler_slot,
    release_crawler_slot,
    get_semaphore,
    active_count,
    MAX_CONCURRENT_CRAWLS,
)


@pytest.mark.asyncio
async def test_duplicate_crawler_rejected():
    """Same crawler cannot run twice concurrently."""
    assert await acquire_crawler_slot("test-crawler") is True
    assert await acquire_crawler_slot("test-crawler") is False
    await release_crawler_slot("test-crawler")


@pytest.mark.asyncio
async def test_different_crawlers_allowed():
    """Different crawlers can run concurrently."""
    assert await acquire_crawler_slot("crawler-a") is True
    assert await acquire_crawler_slot("crawler-b") is True
    await release_crawler_slot("crawler-a")
    await release_crawler_slot("crawler-b")


@pytest.mark.asyncio
async def test_release_allows_reacquire():
    """After release, the same crawler can be acquired again."""
    assert await acquire_crawler_slot("test-crawler") is True
    await release_crawler_slot("test-crawler")
    assert await acquire_crawler_slot("test-crawler") is True
    await release_crawler_slot("test-crawler")


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """Global semaphore enforces MAX_CONCURRENT_CRAWLS."""
    sem = get_semaphore()
    acquired = 0

    async def try_acquire():
        nonlocal acquired
        async with sem:
            acquired += 1
            await asyncio.sleep(0.5)

    tasks = [asyncio.create_task(try_acquire()) for _ in range(MAX_CONCURRENT_CRAWLS + 3)]
    await asyncio.sleep(0.1)
    assert acquired <= MAX_CONCURRENT_CRAWLS
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_active_count():
    """active_count reflects running crawlers."""
    assert active_count() == 0
    await acquire_crawler_slot("c1")
    assert active_count() == 1
    await acquire_crawler_slot("c2")
    assert active_count() == 2
    await release_crawler_slot("c1")
    assert active_count() == 1
    await release_crawler_slot("c2")
    assert active_count() == 0
```

### 10.2 Sanitization tests: `tests/test_sanitizer.py`

```python
"""Tests for data sanitization functions."""

import pytest
from pipeline.sanitizer import sanitize_text, sanitize_url, sanitize_number, sanitize_record


class TestSanitizeText:
    def test_strips_html_tags(self):
        assert "<script>" not in sanitize_text('<script>alert("xss")</script>Hello')
        assert "Hello" in sanitize_text("<b>Hello</b>")

    def test_escapes_special_chars(self):
        result = sanitize_text('test & "quotes" <angle>')
        assert "&amp;" in result
        assert "&lt;" in result
        assert "&quot;" in result

    def test_truncates_to_max_length(self):
        long_text = "a" * 1000
        assert len(sanitize_text(long_text, max_length=100)) == 100

    def test_removes_null_bytes(self):
        assert "\x00" not in sanitize_text("hello\x00world")

    def test_removes_control_chars(self):
        assert "\x01" not in sanitize_text("hello\x01world")

    def test_none_returns_empty(self):
        assert sanitize_text(None) == ""

    def test_preserves_korean(self):
        assert "삼겹살" in sanitize_text("신선한 삼겹살 500g")

    def test_collapses_whitespace(self):
        assert sanitize_text("hello    world") == "hello world"


class TestSanitizeUrl:
    def test_blocks_javascript_scheme(self):
        assert sanitize_url("javascript:alert(1)") == ""

    def test_blocks_data_scheme(self):
        assert sanitize_url("data:text/html,<script>alert(1)</script>") == ""

    def test_allows_http(self):
        assert sanitize_url("http://example.com") == "http://example.com"

    def test_allows_https(self):
        assert sanitize_url("https://example.com/path") == "https://example.com/path"

    def test_truncates_long_url(self):
        url = "https://example.com/" + "a" * 3000
        assert len(sanitize_url(url)) == 2048

    def test_none_returns_empty(self):
        assert sanitize_url(None) == ""

    def test_removes_control_chars(self):
        assert "\x00" not in sanitize_url("https://example.com/\x00path")


class TestSanitizeNumber:
    def test_valid_int(self):
        assert sanitize_number(12500) == 12500.0

    def test_valid_float(self):
        assert sanitize_number(99.9) == 99.9

    def test_string_number(self):
        assert sanitize_number("12500") == 12500.0

    def test_out_of_range_negative(self):
        assert sanitize_number(-1) is None

    def test_out_of_range_high(self):
        assert sanitize_number(999_999_999) is None

    def test_none_returns_none(self):
        assert sanitize_number(None) is None

    def test_invalid_string(self):
        assert sanitize_number("not a number") is None


class TestSanitizeRecord:
    def test_sanitizes_all_fields(self):
        record = {
            "product_name": '<script>alert("xss")</script>Fresh Pork',
            "store": "E-Mart",
            "source_url": "javascript:alert(1)",
            "price": 12500,
            "original_price": -100,
        }
        result = sanitize_record(record)
        assert "<script>" not in result["product_name"]
        assert result["source_url"] == ""
        assert result["price"] == 12500.0
        assert result["original_price"] is None

    def test_preserves_unknown_fields(self):
        record = {"custom_field": "value", "product_name": "test"}
        result = sanitize_record(record)
        assert result["custom_field"] == "value"
```

### 10.3 Error handling tests: `tests/test_error_handler.py`

```python
"""Tests for safe error handling."""

import pytest
from api.error_handler import safe_error_detail


def test_known_exception_returns_safe_message():
    assert safe_error_detail(KeyError("secret_key")) == "Resource not found"
    assert safe_error_detail(ValueError("invalid input")) == "Invalid input provided"
    assert safe_error_detail(TimeoutError()) == "Operation timed out"
    assert safe_error_detail(ConnectionError("http://internal:5432")) == "Service temporarily unavailable"


def test_unknown_exception_returns_generic():
    assert safe_error_detail(RuntimeError("stack trace here")) == "An internal error occurred"


def test_no_internal_info_leaked():
    """Ensure no internal paths, URLs, or credentials in safe messages."""
    exceptions = [
        KeyError("/app/backend/config.py"),
        ConnectionError("postgresql://user:password@db:5432/wallet"),
        FileNotFoundError("/etc/passwd"),
        RuntimeError("Traceback (most recent call last):\n  File ..."),
    ]
    for exc in exceptions:
        msg = safe_error_detail(exc)
        assert "/" not in msg or msg == "Resource not found"
        assert "password" not in msg
        assert "Traceback" not in msg
```

### 10.4 Audit trail tests: `tests/test_audit.py`

```python
"""Tests for audit logging."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from audit import audit_log, AuditEventType


def test_audit_log_writes_json(tmp_path, monkeypatch):
    """Audit entries are valid JSON."""
    log_file = tmp_path / "audit.jsonl"

    import audit
    monkeypatch.setattr(audit, "_AUDIT_LOG_DIR", tmp_path)

    # Re-init the logger to write to tmp_path
    import logging
    logger = logging.getLogger("audit.test")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    monkeypatch.setattr(audit, "_audit_logger", logger)

    audit_log(
        AuditEventType.CRAWLER_RUN,
        actor_ip="127.0.0.1",
        resource="test-crawler",
        detail={"mode": "manual"},
    )

    handler.flush()
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 1

    entry = json.loads(lines[-1])
    assert entry["event"] == "crawler.run"
    assert entry["resource"] == "test-crawler"
    assert entry["actor_ip"] == "127.0.0.1"
    assert "timestamp" in entry


def test_audit_log_required_fields():
    """Every audit entry must have timestamp, event, and result."""
    mock_request = MagicMock()
    mock_request.client.host = "192.168.1.1"
    mock_request.method = "POST"
    mock_request.url.path = "/api/crawlers/test/run"

    # This should not raise
    audit_log(
        AuditEventType.CRAWLER_RUN,
        request=mock_request,
        resource="test-crawler",
    )
```

### 10.5 Rate limiting tests: `tests/test_rate_limiter.py`

```python
"""Tests for outbound domain rate limiter."""

import asyncio
import time
import pytest
from engine.rate_limiter import DomainRateLimiter


@pytest.mark.asyncio
async def test_first_request_immediate():
    """First request to a domain should not block."""
    limiter = DomainRateLimiter(min_interval=1.0)
    start = time.monotonic()
    await limiter.wait("https://example.com/page1")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_second_request_delayed():
    """Second request to same domain should wait min_interval."""
    limiter = DomainRateLimiter(min_interval=0.5)
    await limiter.wait("https://example.com/page1")
    start = time.monotonic()
    await limiter.wait("https://example.com/page2")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.4  # Allow small timing margin


@pytest.mark.asyncio
async def test_different_domains_independent():
    """Different domains should not block each other."""
    limiter = DomainRateLimiter(min_interval=1.0)
    await limiter.wait("https://example.com/page1")
    start = time.monotonic()
    await limiter.wait("https://other-site.com/page1")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1
```

---

## 11. Rollout Checklist

### Phase 1 — Immediate (Day 1–2)

| # | Task | File(s) | Risk if Skipped |
|---|---|---|---|
| 1 | Change default bind to `127.0.0.1` | `config.py:66` | LAN-wide exposure |
| 2 | Add `concurrency.py` | New file | Unbounded crawl tasks |
| 3 | Wire concurrency into `crawlers.py` | `routes/crawlers.py` | Race conditions, OOM |
| 4 | Add `sanitizer.py` | New file | Stored XSS |
| 5 | Wire sanitizer into `transformer.py` | `pipeline/transformer.py` | Data injection |
| 6 | Replace `str(e)` in error responses | 5 route files | Info leakage |

### Phase 2 — Within First Week

| # | Task | File(s) | Risk if Skipped |
|---|---|---|---|
| 7 | Add `error_handler.py` + register | New file + `app.py` | Unhandled exception leaks |
| 8 | Add `audit.py` + instrument routes | New file + 4 route files | No forensic trail |
| 9 | Install `slowapi` + add rate limits | `requirements.txt` + `app.py` + routes | API DoS |
| 10 | Add cumulative timeout to executor | `engine/executor.py` | Zombie crawl cascade |
| 11 | Add browser resource flags | 3 strategy files | Browser memory bombs |
| 12 | Add `rate_limiter.py` for outbound | New file + `executor.py` | Target site IP bans |

### Phase 3 — Week 2

| # | Task | File(s) | Risk if Skipped |
|---|---|---|---|
| 13 | Add SSE stream timeout | `routes/crawlers.py` | Connection slot exhaustion |
| 14 | Docker resource limits | `docker-compose.yml` | Container escapes host limits |
| 15 | Run all test suites | `tests/` | Regressions |
| 16 | Log rotation for audit | `audit.py` | Disk fill |

### Verification Commands

```bash
# Run the new test suites
cd packages/crawler-admin/backend
python -m pytest tests/test_concurrency.py tests/test_sanitizer.py tests/test_error_handler.py tests/test_audit.py tests/test_rate_limiter.py -v

# Verify bind address
grep -n "API_HOST" config.py

# Verify no str(e) in HTTP responses
grep -rn "str(e)" api/routes/ --include="*.py"
grep -rn "str(exc)" api/routes/ --include="*.py"

# Verify sanitizer is wired
grep -rn "sanitize_record" pipeline/transformer.py

# Check audit log is created on first crawl
cat logs/audit.jsonl | python -m json.tool --no-ensure-ascii
```

---

## File Change Summary

| Action | File | Audit Refs |
|---|---|---|
| **Modify** | `config.py` | CRIT-06, HIGH-04 |
| **Modify** | `api/app.py` | HIGH-02, M-01 |
| **Modify** | `api/routes/crawlers.py` | M-06, HIGH-02, MED-01, M-01 |
| **Modify** | `api/routes/schedules.py` | M-01, MED-01 |
| **Modify** | `api/routes/plugins.py` | M-01, MED-01 |
| **Modify** | `api/routes/ingestion.py` | M-01, MED-01 |
| **Modify** | `engine/executor.py` | HIGH-04 |
| **Modify** | `engine/strategies/selenium_st.py` | HIGH-04 |
| **Modify** | `engine/strategies/playwright_st.py` | HIGH-04 |
| **Modify** | `engine/strategies/undetected_st.py` | HIGH-04 |
| **Modify** | `pipeline/transformer.py` | H-05 |
| **Modify** | `requirements.txt` | HIGH-02 |
| **Modify** | `docker-compose.yml` | HIGH-04, CRIT-06 |
| **Create** | `concurrency.py` | M-06 |
| **Create** | `api/error_handler.py` | M-01 |
| **Create** | `audit.py` | MED-01 |
| **Create** | `pipeline/sanitizer.py` | H-05 |
| **Create** | `engine/rate_limiter.py` | HIGH-02 |
| **Create** | `tests/test_concurrency.py` | — |
| **Create** | `tests/test_sanitizer.py` | — |
| **Create** | `tests/test_error_handler.py` | — |
| **Create** | `tests/test_audit.py` | — |
| **Create** | `tests/test_rate_limiter.py` | — |
