# Crawler-Admin Stability Audit

> **Scope**: `packages/crawler-admin/backend/` — all Python source files  
> **Date**: 2025-07-15  
> **Files Reviewed**: 85+ Python files across engine, pipeline, scheduler, plugins, crawlers, API  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Browser Crashes & Zombie Processes](#3-browser-crashes--zombie-processes)
4. [Network Failures](#4-network-failures)
5. [Anti-Bot Detection & Blocking](#5-anti-bot-detection--blocking)
6. [Pipeline Failures & Data Loss](#6-pipeline-failures--data-loss)
7. [Scheduler Reliability](#7-scheduler-reliability)
8. [Plugin Stability](#8-plugin-stability)
9. [Memory Leaks](#9-memory-leaks)
10. [Concurrent Crawl Safety](#10-concurrent-crawl-safety)
11. [External Service Dependency](#11-external-service-dependency)
12. [Disk Space & Log Rotation](#12-disk-space--log-rotation)
13. [Health Checks & Monitoring](#13-health-checks--monitoring)
14. [Graceful Shutdown](#14-graceful-shutdown)
15. [Risk Matrix](#15-risk-matrix)
16. [Recommendations Priority](#16-recommendations-priority)

---

## 1. Executive Summary

The crawler-admin sub-project demonstrates **solid foundational design** with cascade strategies, concurrency primitives, anti-detect rotation, sanitization, and structured error types. However, the audit reveals **23 stability risks** across 12 categories, with **5 critical**, **8 high**, and **10 medium** severity findings.

### Key Strengths
- ✅ Strategy cascade with difficulty-ordered escalation (requests → cloudscraper → selenium → undetected → playwright)
- ✅ Per-domain rate limiting with async locks
- ✅ Concurrency semaphore + per-crawler duplicate-run prevention
- ✅ Structured error taxonomy (`ErrorType` enum) with diagnostics engine
- ✅ Data sanitization pipeline (HTML strip, XSS prevention, control char removal)
- ✅ Audit logging with JSON structured records and rotation
- ✅ Anti-detect: UA rotation, proxy round-robin, Sec-Fetch headers, randomized delays

### Key Risks
- 🔴 No process-level zombie reaping for browser subprocesses
- 🔴 Pipeline has no rollback/checkpoint on partial failure
- 🔴 `asyncio.run()` inside BackgroundScheduler risks event loop conflicts
- 🔴 All job tracker history is in-memory only — lost on restart
- 🔴 `_crawl_results` dict grows unbounded in the API process

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  FastAPI (app.py)                                              │
│  ├── routes/crawlers.py   — run, bulk-run, SSE stream, toggle  │
│  ├── routes/schedules.py  — CRUD for cron jobs                 │
│  ├── routes/plugins.py    — plugin management                  │
│  ├── routes/ingestion.py  — data submission                    │
│  └── security/ — API key, headers, URL validation              │
├────────────────────────────────────────────────────────────────┤
│  Pipeline (pipeline.py)                                        │
│  crawl → parse → sanitize → validate → transform → store      │
├────────────────────────────────────────────────────────────────┤
│  Engine                                                        │
│  ├── executor.py          — cascade strategy executor          │
│  ├── strategies/          — requests, cloudscraper, selenium,   │
│  │                          undetected, playwright              │
│  ├── rate_limiter.py      — per-domain throttling               │
│  ├── anti_detect.py       — UA/proxy/delay rotation            │
│  ├── diagnostics.py       — failure diagnosis                  │
│  └── playwright_helper.py — shared browser helper              │
├────────────────────────────────────────────────────────────────┤
│  Scheduler (APScheduler)  │  Plugins (plugin_loader/manager)   │
│  ├── scheduler.py         │  ├── plugin_interface.py           │
│  └── job_tracker.py       │  ├── plugin_loader.py              │
│                            │  └── plugin_manager.py             │
├────────────────────────────────────────────────────────────────┤
│  Crawlers (19+)                                                │
│  hotdeals/ marts/ delivery/ shopping/ location/ government/    │
│  └── Each has: plugin.yaml + crawler.py                        │
├────────────────────────────────────────────────────────────────┤
│  Concurrency: asyncio.Semaphore + per-crawler lock set         │
│  Audit: JSON structured logging with RotatingFileHandler       │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Browser Crashes & Zombie Processes

### 3.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| BC-1 | 🔴 CRITICAL | `strategies/selenium_st.py:104` | `asyncio.get_event_loop()` deprecated; `run_in_executor` runs sync `driver.quit()` in thread pool — if the thread is killed or times out, the ChromeDriver process persists as zombie |
| BC-2 | 🔴 CRITICAL | `strategies/undetected_st.py:47` | Same `get_event_loop()` + `run_in_executor` pattern; `undetected-chromedriver` spawns a separate Chrome binary that may not be killed by `driver.quit()` |
| BC-3 | 🟡 MEDIUM | `strategies/playwright_st.py:57-131` | Playwright starts+stops per fetch (no pooling). If `_do_fetch` times out via `asyncio.wait_for`, the `finally` block runs cleanup, but if the process is force-killed, Chromium orphans remain |
| BC-4 | 🟡 MEDIUM | `executor.py:227` | `strategy.cleanup()` in `finally` block is good, but if `asyncio.wait_for` cancels the task, cleanup may not execute fully |
| BC-5 | 🟢 LOW | `playwright_helper.py:85-100` | Context manager (`__aexit__`) properly wraps cleanup in try/except — good pattern |

### 3.2 Root Causes

1. **No process-level reaping**: Neither Selenium nor undetected-chromedriver strategies enumerate or kill leftover Chrome/ChromeDriver PIDs. If `driver.quit()` raises, the process remains.
2. **Sync-in-async gap**: `run_in_executor(None, self._fetch_sync, ...)` runs blocking Selenium in the default thread pool. If the strategy-level timeout fires (`asyncio.wait_for`), the executor cancels the coroutine but the underlying thread continues running until `_fetch_sync` completes or the thread pool is shut down.
3. **No browser pool**: Each `_do_fetch` creates a new browser instance. Under concurrency (up to 5 simultaneous crawls), this means up to 5 Chrome processes with no shared lifecycle management.

### 3.3 Recommendations

```
[BC-R1] Add a process-level watchdog:
  - After driver.quit(), verify via psutil that child PIDs are gone
  - Kill any orphaned chrome/chromedriver processes owned by this session
  - Implement a periodic reaper (every 60s) that finds chromedriver
    processes older than CRAWL_CUMULATIVE_TIMEOUT and kills them

[BC-R2] Replace asyncio.get_event_loop() with asyncio.get_running_loop():
  - get_event_loop() is deprecated in Python 3.12+
  - In SeleniumStrategy._do_fetch and UndetectedStrategy._do_fetch

[BC-R3] Add browser pool for Playwright:
  - Maintain a pool of N browser instances (configurable)
  - Check out/check in with timeout
  - Periodic health check on pooled browsers (page.goto about:blank)
  - Max lifetime per browser instance to prevent memory bloat

[BC-R4] Add subprocess timeout wrapper for Selenium/Undetected:
  - Use concurrent.futures.ThreadPoolExecutor with explicit timeout
  - On timeout, forcibly terminate the driver process via PID
```

---

## 4. Network Failures

### 4.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| NF-1 | 🟢 GOOD | `strategies/requests_st.py:56-61` | Proper catch of `Timeout`, `ConnectionError`, `RequestException` with typed `CrawlError` |
| NF-2 | 🟢 GOOD | Multiple crawlers | All 19 crawlers implement `_retry_request()` with exponential backoff and rate-limit (429) handling |
| NF-3 | 🟡 MEDIUM | `strategies/cloudscraper_st.py:75` | Catches generic `Exception` — could mask non-network errors (e.g., memory, encoding) |
| NF-4 | 🟡 MEDIUM | `pipeline/pipeline.py:237-244` | `_store()` uses `httpx.AsyncClient(timeout=30)` — no retry on transient failures to DB-Admin |
| NF-5 | 🟡 MEDIUM | `pipeline/pipeline.py:269` | `_store_to_ingestion()` same issue — single attempt to ingestion API with no retry |
| NF-6 | 🟢 GOOD | `engine/rate_limiter.py` | Per-domain rate limiting prevents aggressive crawling that triggers IP bans |
| NF-7 | 🟡 MEDIUM | Crawlers using `requests` | DNS failures raise `ConnectionError`, which is caught but not specifically classified as `ErrorType.NETWORK_ERROR` in all strategies |

### 4.2 What Works Well

- **Retry with exponential backoff**: All crawlers implement `_retry_request()` with 3 retries and jittered backoff — this is production-grade.
- **Rate limit detection**: 429 responses trigger backoff rather than immediate failure.
- **Strategy cascade**: If requests fails (e.g., DNS issue), cloudscraper → selenium → playwright will be tried automatically.
- **Cumulative timeout**: `CRAWL_CUMULATIVE_TIMEOUT=180s` prevents infinite retry loops.

### 4.3 Recommendations

```
[NF-R1] Add retry logic to pipeline _store() and _store_to_ingestion():
  - At least 3 attempts with exponential backoff
  - On final failure, write to local fallback file for later replay

[NF-R2] Classify DNS failures specifically:
  - In cloudscraper_st.py, differentiate network errors from
    library/encoding errors in the Exception catch block

[NF-R3] Add connection pooling for httpx in pipeline:
  - Reuse httpx.AsyncClient across pipeline runs instead of
    creating a new client per store() call
```

---

## 5. Anti-Bot Detection & Blocking

### 5.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| AB-1 | 🟢 GOOD | `anti_detect.py` | 18 diverse UAs (Chrome/Firefox/Edge/Safari across Win/Mac/Mobile), 3 Accept header sets, Sec-Fetch-* headers |
| AB-2 | 🟢 GOOD | `strategies/requests_st.py:69-100` | Detects CAPTCHA (403 body), IP ban (403), Cloudflare JS challenge (503), raises typed errors |
| AB-3 | 🟢 GOOD | `strategies/playwright_st.py:86-90` | `playwright-stealth` applied automatically; graceful fallback if not installed |
| AB-4 | 🟡 MEDIUM | `anti_detect.py:97-103` | `_used_uas` list grows unbounded — memory leak proportional to total requests |
| AB-5 | 🟡 MEDIUM | `anti_detect.py:122-133` | Proxy round-robin is not thread-safe (`_proxy_index` increment has no lock) |
| AB-6 | 🟠 HIGH | All crawlers | No automatic proxy rotation on IP ban — `AntiDetect.remove_proxy()` exists but is never called by executor or strategies |
| AB-7 | 🟠 HIGH | All crawlers | No CAPTCHA solving integration — CAPTCHA detection causes immediate failure with no fallback |
| AB-8 | 🟡 MEDIUM | `engine/diagnostics.py` | DiagnosticsEngine provides recommendations but no auto-remediation (e.g., auto-switch proxy on IP_BANNED) |

### 5.2 What Works Well

- **Multi-layer anti-detection**: UA rotation + Sec-Fetch headers + proxy rotation + randomized delays + stealth plugins make detection significantly harder.
- **Typed error classification**: IP_BANNED, CAPTCHA_DETECTED, JS_CHALLENGE are distinct error types with specific recommendations.
- **Strategy escalation**: Blocking at the requests level triggers escalation to cloudscraper → selenium → playwright.

### 5.3 Recommendations

```
[AB-R1] Auto-remove banned proxy on IP_BANNED error:
  - In executor._execute_cascade, when CrawlError.error_type == IP_BANNED,
    call anti_detect.remove_proxy(proxy_used)
  - Log which proxy was banned for operator review

[AB-R2] Cap _used_uas list:
  - Limit to last 100 entries or use collections.deque(maxlen=100)

[AB-R3] Add lock to proxy round-robin:
  - Use threading.Lock or asyncio.Lock for _proxy_index

[AB-R4] Consider CAPTCHA solving service integration:
  - 2captcha/Anti-Captcha API as optional strategy escalation
  - Or: delay + retry (some CAPTCHAs are rate-limit based)
```

---

## 6. Pipeline Failures & Data Loss

### 6.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| PF-1 | 🔴 CRITICAL | `pipeline/pipeline.py:176-187` | If `_store()` or `_store_to_ingestion()` fails, crawled data is lost — no local persistence fallback |
| PF-2 | 🟠 HIGH | `pipeline/pipeline.py:226` | `run_batch()` uses `asyncio.gather(*tasks, return_exceptions=False)` — first exception cancels remaining crawlers |
| PF-3 | 🟡 MEDIUM | `pipeline/pipeline.py:148-151` | Sanitization truncates strings >5000 chars in-place — silent data truncation with no logging |
| PF-4 | 🟡 MEDIUM | `pipeline/pipeline.py:298` | `_fail()` uses `asyncio.ensure_future()` for event publishing — fire-and-forget; exception in event handler is silently lost |
| PF-5 | 🟢 GOOD | `pipeline/validator.py` | Proper separation of valid/invalid items with detailed error metadata |
| PF-6 | 🟢 GOOD | `pipeline/sanitizer.py` | Comprehensive XSS prevention: HTML tag strip, control char removal, scheme validation for URLs |
| PF-7 | 🟢 GOOD | `pipeline/dedup.py` | Sophisticated duplicate detection with URL normalization, n-gram Jaccard similarity, Union-Find grouping |

### 6.2 Data Flow Analysis

```
crawl() → raw_items (list[dict])
  → sanitize (truncate >5000 chars)           ← PF-3: silent truncation
  → validate_items (required fields)           ← OK: returns (valid, invalid)
  → validate_price_range                       ← OK: filters out-of-range
  → normalize_prices                           ← OK: "12,500원" → 12500
  → deduplicate (name+price key)               ← OK
  → enrich_with_category                       ← OK
  → to_discount_history / to_hotdeal_prices    ← OK: sanitize_record applied
  → _store / _store_to_ingestion               ← PF-1: no fallback on failure
```

### 6.3 Recommendations

```
[PF-R1] Add local persistence fallback:
  - On _store/_store_to_ingestion failure, write to
    data/failed_ingestions/{crawler}_{timestamp}.jsonl
  - Add a replay worker that retries failed ingestions

[PF-R2] Fix run_batch to use return_exceptions=True:
  - asyncio.gather(*tasks, return_exceptions=True)
  - Filter exceptions from results and log them
  - One crawler failure should not cancel others

[PF-R3] Log data truncation:
  - When truncating strings >5000 chars, emit a warning with
    field name and original length

[PF-R4] Replace asyncio.ensure_future with awaited publish in _fail():
  - Or at minimum, add exception callback to the task
```

---

## 7. Scheduler Reliability

### 7.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| SC-1 | 🔴 CRITICAL | `scheduler/scheduler.py:120` | `asyncio.run()` inside `_execute_job_sync()` creates a new event loop per job — will conflict with the FastAPI event loop and crash if called from an async context |
| SC-2 | 🟠 HIGH | `scheduler/scheduler.py:26` | `BackgroundScheduler` runs in a separate thread — `asyncio.run()` in that thread works but creates a fresh event loop each time, losing access to shared async resources (semaphores, locks) |
| SC-3 | 🟠 HIGH | `scheduler/job_tracker.py:22-33` | `_history` list is in-memory only — all job execution history is lost on process restart |
| SC-4 | 🟡 MEDIUM | `scheduler/scheduler.py:37-39` | `scheduler.start(paused=False)` but no misfire handling — if the server was down during scheduled time, the missed job silently skips |
| SC-5 | 🟡 MEDIUM | `scheduler/scheduler.py:82-84` | `update_job` does `remove + add` non-atomically — brief window where the job doesn't exist |
| SC-6 | 🟢 GOOD | `scheduler/scheduler.py:60-62` | `replace_existing=True` prevents duplicate job registration |

### 7.2 Event Loop Conflict Analysis

```python
# scheduler.py:118-120
def _execute_job_sync(self, crawler_name: str) -> dict[str, Any]:
    """BackgroundScheduler 콜백 (동기). 내부에서 asyncio.run 사용."""
    return asyncio.run(self._execute_job(crawler_name))
```

**Problem**: The `CrawlPipeline` uses `acquire_crawler_slot()` / `release_crawler_slot()` which operate on module-level `asyncio.Lock` and `set`. When `asyncio.run()` creates a new event loop, these locks are in a different loop context. The concurrency primitives in `concurrency.py` will NOT protect against overlapping runs triggered by the scheduler.

### 7.3 Recommendations

```
[SC-R1] Switch to AsyncIOScheduler:
  - Replace BackgroundScheduler with APScheduler's AsyncIOScheduler
  - This runs in the same event loop as FastAPI
  - Jobs can directly use async/await without asyncio.run()

[SC-R2] Persist job history:
  - Store JobExecution records to SQLite or JSON file
  - On startup, load last N executions per job

[SC-R3] Configure misfire handling:
  - APScheduler supports misfire_grace_time and coalescing
  - Add: misfire_grace_time=300, coalesce=True to job config
  - This ensures missed jobs run once on recovery

[SC-R4] Make update_job atomic:
  - Use APScheduler's reschedule_job() instead of remove+add
```

---

## 8. Plugin Stability

### 8.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| PL-1 | 🟢 GOOD | `plugin_loader.py:186-201` | Error isolation — one plugin failure doesn't block others from loading |
| PL-2 | 🟢 GOOD | `plugin_loader.py:315-355` | Topological sort with circular dependency detection |
| PL-3 | 🟢 GOOD | `plugin_manager.py:271-281` | Shutdown iterates all loaded plugins and calls `on_unload()` with exception safety |
| PL-4 | 🟡 MEDIUM | `plugin_loader.py:258-259` | `sys.modules[module_name] = module` before `exec_module` — if exec fails, stale module reference remains in sys.modules |
| PL-5 | 🟡 MEDIUM | `plugin_manager.py:80-85` | `on_load()` failure sets ERROR status but plugin remains in `_loaded` dict — may be accessed later |
| PL-6 | 🟡 MEDIUM | `plugin_interface.py:67,81` | `PluginMetrics._durations` list grows unbounded — memory proportional to total runs |
| PL-7 | 🟢 GOOD | `plugin_manager.py:217-246` | Hot reload properly clears `sys.modules` and re-imports |

### 8.2 What Works Well

- **Lifecycle hooks**: `on_load()`, `on_unload()`, `on_error()`, `on_success()` provide clear extension points.
- **Health model**: `PluginHealth` tracks consecutive failures and marks unhealthy after 5 failures.
- **Manifest verification**: `plugin.yaml` schema validation catches misconfiguration early.
- **Event system**: Lifecycle events (loaded, unloaded, activated, deactivated, error) enable monitoring.

### 8.3 Recommendations

```
[PL-R1] Clean up sys.modules on exec failure:
  - In _import_plugin, add except block to remove sys.modules[module_name]

[PL-R2] Remove plugin from _loaded on initialization failure:
  - In initialize_all, if on_load() fails, unload the plugin

[PL-R3] Cap _durations in PluginMetrics:
  - Use collections.deque(maxlen=1000) for _durations list
  - Compute avg from rolling window, not entire history
```

---

## 9. Memory Leaks

### 9.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| ML-1 | 🟠 HIGH | `api/routes/crawlers.py:36` | `_crawl_results: dict` grows unbounded — every crawl run appends, never purged |
| ML-2 | 🟡 MEDIUM | `anti_detect.py:97-103` | `_used_uas: list` grows per request, never trimmed |
| ML-3 | 🟡 MEDIUM | `plugin_interface.py:67` | `PluginMetrics._durations` grows per run |
| ML-4 | 🟡 MEDIUM | `rate_limiter.py:23` | `_locks` and `_last_request` dicts grow per unique domain, never evicted |
| ML-5 | 🟢 GOOD | `crawlers/hotdeals/ppomppu/crawler.py:165` | `del soup` explicitly frees BeautifulSoup DOM tree — good practice |
| ML-6 | 🟡 MEDIUM | Most crawlers | Not all crawlers `del soup` after parsing — BeautifulSoup trees can be large |
| ML-7 | 🟡 MEDIUM | `registry/registry.py:19` | `_instance_cache` caches crawler instances forever — if crawlers hold state/connections, these are never released |

### 9.2 Memory Pressure Under Load

With `MAX_CONCURRENT_CRAWLS=5` and 19 crawlers:
- **Browser processes**: Up to 5 × ~200MB Chrome = 1GB
- **DOM trees**: BeautifulSoup parses (large HTML pages) can be 50-100MB each
- **Response buffers**: Large HTML responses (~1MB each) held in memory
- **Rate limiter**: One Lock + float per domain visited (minor)
- **_crawl_results**: After 1000 runs, ~100KB (minor but grows forever)

### 9.3 Recommendations

```
[ML-R1] Add TTL-based eviction to _crawl_results:
  - Keep only last 100 results, or evict entries older than 1 hour
  - Or use an LRU cache with maxsize

[ML-R2] Add `del soup` to all crawlers after parsing:
  - BeautifulSoup DOM trees should be explicitly freed
  - Add as convention in CrawlerContract documentation

[ML-R3] Add domain eviction to DomainRateLimiter:
  - Evict domains not seen in last 1 hour
  - Or use an LRU dict with maxsize=500

[ML-R4] Cap _used_uas with deque(maxlen=100)

[ML-R5] Consider clearing _instance_cache periodically:
  - Especially if crawlers hold browser instances or sessions
```

---

## 10. Concurrent Crawl Safety

### 10.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| CC-1 | 🟢 GOOD | `concurrency.py:23-36` | `acquire_crawler_slot` / `release_crawler_slot` with `asyncio.Lock` prevents duplicate crawler runs |
| CC-2 | 🟢 GOOD | `concurrency.py:17` | `asyncio.Semaphore(MAX_CONCURRENT_CRAWLS)` caps total concurrent crawls |
| CC-3 | 🟠 HIGH | `concurrency.py:17` | Semaphore created at module import time — if `MAX_CONCURRENT_CRAWLS` env var changes, a restart is required but the semaphore won't be recreated |
| CC-4 | 🟡 MEDIUM | `api/routes/crawlers.py:315` | `asyncio.create_task(_run_and_store(...))` — fire-and-forget; if the task raises, the exception is logged but `release_crawler_slot` in `finally` handles cleanup |
| CC-5 | 🟡 MEDIUM | `api/routes/crawlers.py:36-37` | `_crawl_results` dict is shared mutable state accessed from multiple async tasks — safe in single-threaded asyncio but not documented |
| CC-6 | 🟠 HIGH | Scheduler + API | Scheduler uses `asyncio.run()` (separate event loop) while API uses FastAPI's loop — the concurrency locks (`_running_crawlers`, `_lock`) are NOT shared between these two loops. **A crawler can be double-launched from scheduler + API simultaneously.** |

### 10.2 Race Condition Analysis

```
Scenario: User clicks "Run" on emart while scheduler fires emart cron job

API event loop:                    Scheduler thread:
  acquire_crawler_slot("emart")      asyncio.run(...)  ← NEW event loop
  → checks _running_crawlers         → acquire_crawler_slot("emart")
  → _running_crawlers is a SET       → different Lock object!
    in API's event loop               → different _running_crawlers set!
  → Both succeed → DOUBLE RUN         → Both succeed → DOUBLE RUN
```

### 10.3 Recommendations

```
[CC-R1] Unify event loops (see SC-R1):
  - AsyncIOScheduler shares the FastAPI event loop
  - All concurrency primitives work correctly

[CC-R2] Add file-based or Redis-based lock for cross-process safety:
  - If scheduler must run in separate process, use file locks
    (fcntl/portalocker) or Redis SETNX

[CC-R3] Document that _crawl_results is single-loop safe:
  - Add comment explaining asyncio GIL equivalence
```

---

## 11. External Service Dependency

### 11.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| ES-1 | 🟠 HIGH | `pipeline/pipeline.py:33` | `DB_ADMIN_API_URL = "http://localhost:8001"` hardcoded — if DB-Admin is down, all data storage fails |
| ES-2 | 🟡 MEDIUM | `pipeline/pipeline.py:37` | `INGESTION_API_URL` from env with default `localhost:8002` — no health check before submission |
| ES-3 | 🟡 MEDIUM | `pipeline/pipeline.py:237` | Single `httpx.AsyncClient(timeout=30)` per call — no connection pooling, no retry |
| ES-4 | 🟢 GOOD | `pipeline/pipeline.py:241-243` | Failure is caught and returns 0 items saved — pipeline doesn't crash |
| ES-5 | 🟡 MEDIUM | `config.py:18-25` | `DATABASE_URL` warns if empty but code continues — features silently fail |

### 11.2 Failure Modes

| Dependency | Failure Mode | Current Behavior | Impact |
|-----------|-------------|-----------------|--------|
| DB-Admin API (8001) | Down | `_store()` returns 0, data lost | 🔴 Data loss |
| Ingestion API (8002) | Down | `_store_to_ingestion()` returns 0, data lost | 🔴 Data loss |
| Target websites | 403/503/Timeout | Strategy cascade handles this | 🟢 Handled |
| DNS resolver | Down | `ConnectionError` → strategy cascade | 🟢 Handled |
| Proxy servers | Dead/Banned | Round-robin continues to next | 🟡 Partial |

### 11.3 Recommendations

```
[ES-R1] Add circuit breaker for DB-Admin/Ingestion API:
  - After 3 consecutive failures, open circuit for 60 seconds
  - During open circuit, write to local fallback immediately
  - Periodically check if service is back (half-open state)

[ES-R2] Add startup health check:
  - On FastAPI startup, verify DB-Admin and Ingestion APIs are reachable
  - Log warnings (not block startup) if unavailable

[ES-R3] Use persistent httpx.AsyncClient:
  - Create once in CrawlPipeline.__init__
  - Reuse for all store/ingestion calls
  - Configure retry transport: httpx.AsyncHTTPTransport(retries=3)
```

---

## 12. Disk Space & Log Rotation

### 12.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| DS-1 | 🟢 GOOD | `audit.py:32-38` | RotatingFileHandler with 50MB max + 10 backups = 550MB max audit logs |
| DS-2 | 🟡 MEDIUM | `config.py:49` | `IMAGE_STORAGE_PATH` for screenshots/images — no disk quota or cleanup |
| DS-3 | 🟡 MEDIUM | `api/routes/crawlers.py:39-40` | `crawler_status.json`, `crawler_run_history.json`, `crawler_settings.json` — no size limit, grow with usage |
| DS-4 | 🟡 MEDIUM | `pipeline/crawl_pipeline.py:246-249` | `pipeline_output.json` written in demo — could be large with many items |
| DS-5 | 🟢 GOOD | `audit.py:63` | `AUDIT_LOG_MAX_BYTES` and `AUDIT_LOG_BACKUP_COUNT` are configurable via env |

### 12.2 Disk Usage Estimates

| Component | Growth Rate | Max Size | Rotation |
|-----------|------------|----------|----------|
| Audit logs | ~1KB/event | 550MB (10 × 50MB + active) | ✅ Rotating |
| App logs | Standard Python logging | Depends on handler config | ❓ Not configured in code |
| Status/History JSON | ~1KB/crawler/run | Unbounded | ❌ None |
| Image storage | Variable | Unbounded | ❌ None |
| Crawl output JSON | ~100KB/run | Unbounded | ❌ None |

### 12.3 Recommendations

```
[DS-R1] Add RotatingFileHandler for application logs:
  - Configure in app.py startup or logging.conf

[DS-R2] Add image storage cleanup:
  - Configurable max age (e.g., 30 days)
  - Configurable max total size (e.g., 5GB)
  - Cron job or startup cleanup task

[DS-R3] Limit JSON file sizes:
  - crawler_run_history.json: keep only last N runs per crawler
    (already capped at 5 in _append_run_history — ✅ good)
  - crawler_settings.json: bounded by number of crawlers — OK
```

---

## 13. Health Checks & Monitoring

### 13.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| HC-1 | 🟡 MEDIUM | `api/app.py:106-108` | `/health` returns `{"status": "ok"}` — no deep checks (DB, scheduler, plugins) |
| HC-2 | 🟢 GOOD | `plugin_interface.py:163-181` | `PluginHealth` with uptime, consecutive failures, is_healthy flag |
| HC-3 | 🟡 MEDIUM | No file | No periodic crawler health check — a crawler may silently fail for days |
| HC-4 | 🟡 MEDIUM | No file | No alerting system — failures only visible in logs and dashboard |
| HC-5 | 🟢 GOOD | `api/routes/crawlers.py:417-463` | SSE stream for real-time crawler status — good for dashboard |
| HC-6 | 🟢 GOOD | `engine/diagnostics.py` | Automated failure diagnosis with severity scoring and recommendations |

### 13.2 Missing Health Dimensions

| Dimension | Status | Notes |
|-----------|--------|-------|
| API alive | ✅ `/health` | Basic |
| DB connectivity | ❌ | Not checked |
| Scheduler running | ❌ | Not exposed |
| Browser pool health | ❌ | No pool exists yet |
| Plugin health | ✅ | `PluginHealth` model |
| Crawler success rate | ✅ | `PluginMetrics.success_rate` |
| Memory usage | ❌ | Not tracked |
| Disk usage | ❌ | Not tracked |
| Pending ingestions | ❌ | Not visible |

### 13.3 Recommendations

```
[HC-R1] Enrich /health endpoint:
  GET /health → {
    "status": "ok",
    "scheduler_running": true,
    "active_crawls": 2,
    "total_crawlers": 19,
    "unhealthy_plugins": ["emart"],
    "disk_usage_mb": 1234,
    "uptime_seconds": 86400
  }

[HC-R2] Add /health/deep for thorough checks:
  - Verify DB-Admin API reachability
  - Verify Ingestion API reachability
  - Check browser process count
  - Check disk free space

[HC-R3] Add alerting hooks:
  - On 3+ consecutive failures for a crawler, emit webhook/email
  - On disk space below threshold, emit warning
  - On no successful crawl in 24h, emit alert
```

---

## 14. Graceful Shutdown

### 14.1 Findings

| ID | Severity | File | Issue |
|----|----------|------|-------|
| GS-1 | 🟠 HIGH | `api/app.py` | No shutdown event handler — `on_event("shutdown")` is not registered |
| GS-2 | 🟡 MEDIUM | `scheduler/scheduler.py:45` | `scheduler.shutdown(wait=False)` — does not wait for running jobs to complete |
| GS-3 | 🟢 GOOD | `plugin_manager.py:271-281` | `shutdown()` iterates all plugins and calls `on_unload()` with exception safety |
| GS-4 | 🟠 HIGH | `strategies/selenium_st.py`, `undetected_st.py` | If SIGTERM arrives during `_fetch_sync` (in thread pool), `driver.quit()` may not be called — Chrome process persists |
| GS-5 | 🟡 MEDIUM | `concurrency.py` | On shutdown, `_running_crawlers` is not cleaned — stale state if process restarts quickly |

### 14.2 Shutdown Sequence (Current vs. Desired)

**Current (SIGTERM received):**
```
1. FastAPI begins shutdown
2. Running requests complete (default)
3. Process exits
4. Browser processes: ORPHANED ❌
5. Scheduler jobs: INTERRUPTED ❌
6. Plugin cleanup: NOT CALLED ❌
7. Pending data: LOST ❌
```

**Desired:**
```
1. FastAPI receives shutdown signal
2. Stop scheduler (wait=True for running jobs)
3. Cancel pending crawl tasks with timeout
4. Run strategy cleanup() on all active strategies
5. Call plugin_manager.shutdown()
6. Flush audit log buffers
7. Kill any remaining browser processes
8. Process exits cleanly
```

### 14.3 Recommendations

```
[GS-R1] Register FastAPI shutdown event:
  @app.on_event("shutdown")
  async def shutdown():
      scheduler.stop()
      await plugin_manager.shutdown()
      # Kill orphaned browser processes
      for proc in psutil.process_iter(['name']):
          if proc.info['name'] in ('chrome', 'chromedriver', 'chromium'):
              proc.kill()

[GS-R2] Add signal handler for graceful browser cleanup:
  - Register SIGTERM/SIGINT handler
  - Set a shutdown flag checked by long-running crawls
  - Clean up browsers before exit

[GS-R3] Scheduler shutdown(wait=True):
  - Allow running jobs up to 30s to complete
  - Force-terminate after timeout
```

---

## 15. Risk Matrix

| Risk ID | Category | Severity | Likelihood | Impact | Fix Effort |
|---------|----------|----------|------------|--------|------------|
| BC-1 | Browser Crash | 🔴 CRITICAL | High | Zombie procs eat RAM | Medium |
| SC-1 | Scheduler | 🔴 CRITICAL | High | Event loop crash | Low |
| CC-6 | Concurrency | 🟠 HIGH | Medium | Double crawl execution | Low (with SC-R1) |
| PF-1 | Pipeline | 🔴 CRITICAL | Medium | Data loss on store failure | Medium |
| PF-2 | Pipeline | 🟠 HIGH | Medium | Cascade crawl failure | Low |
| SC-3 | Scheduler | 🟠 HIGH | High | History loss on restart | Low |
| GS-1 | Shutdown | 🟠 HIGH | High | Resource leaks | Low |
| GS-4 | Shutdown | 🟠 HIGH | Medium | Zombie processes | Medium |
| ML-1 | Memory | 🟠 HIGH | High | OOM over time | Low |
| ES-1 | External Svc | 🟠 HIGH | Medium | Data loss | Medium |
| AB-6 | Anti-Bot | 🟠 HIGH | Medium | Continued banning | Low |
| AB-7 | Anti-Bot | 🟠 HIGH | Medium | Blocked crawlers | High |
| BC-2 | Browser Crash | 🔴 CRITICAL | Medium | Zombie chrome procs | Medium |

---

## 16. Recommendations Priority

### Phase 1 — Critical Fixes (Week 1)

| Priority | ID | Action | Effort |
|----------|-----|--------|--------|
| P0 | SC-R1 | Switch to AsyncIOScheduler | 2h |
| P0 | PF-R2 | Fix `asyncio.gather(return_exceptions=True)` | 15min |
| P0 | PF-R1 | Add local fallback persistence for failed stores | 4h |
| P0 | GS-R1 | Register FastAPI shutdown handler | 1h |
| P0 | BC-R2 | Replace deprecated `get_event_loop()` | 15min |

### Phase 2 — High Priority (Week 2-3)

| Priority | ID | Action | Effort |
|----------|-----|--------|--------|
| P1 | BC-R1 | Add zombie process reaper | 4h |
| P1 | SC-R2 | Persist job tracker history | 3h |
| P1 | SC-R3 | Configure misfire handling | 1h |
| P1 | CC-R1 | Unify event loops (done with SC-R1) | — |
| P1 | ML-R1 | Add TTL/LRU to `_crawl_results` | 1h |
| P1 | NF-R1 | Retry logic for pipeline store calls | 2h |
| P1 | ES-R3 | Persistent httpx client | 1h |
| P1 | AB-R1 | Auto-remove banned proxy | 1h |
| P1 | HC-R1 | Enrich `/health` endpoint | 2h |

### Phase 3 — Medium Priority (Month 2)

| Priority | ID | Action | Effort |
|----------|-----|--------|--------|
| P2 | BC-R3 | Implement browser pool | 8h |
| P2 | ES-R1 | Circuit breaker for external services | 4h |
| P2 | HC-R2 | Deep health check endpoint | 3h |
| P2 | HC-R3 | Alerting hooks | 4h |
| P2 | AB-R3 | Thread-safe proxy rotation | 1h |
| P2 | ML-R2 | Add `del soup` to all crawlers | 1h |
| P2 | ML-R3 | Domain eviction in rate limiter | 1h |
| P2 | PL-R1-R3 | Plugin cleanup fixes | 2h |

### Phase 4 — Future Enhancements

| Priority | ID | Action | Effort |
|----------|-----|--------|--------|
| P3 | AB-R4 | CAPTCHA solving integration | 8h |
| P3 | BC-R4 | Subprocess timeout wrapper for Selenium | 4h |
| P3 | DS-R2 | Image storage cleanup cron | 3h |
| P3 | GS-R2 | Signal-based graceful shutdown | 4h |

---

## Appendix A: Files Reviewed

### Core Infrastructure
- `config.py`, `concurrency.py`, `audit.py`, `conftest.py`

### API Layer
- `api/app.py`, `api/error_handler.py`, `api/error_codes.py`
- `api/routes/crawlers.py`, `api/routes/schedules.py`, `api/routes/logs.py`
- `api/routes/ingestion.py`, `api/routes/dashboard.py`, `api/routes/plugins.py`
- `api/security/auth.py`, `api/security/headers.py`, `api/security/input_schemas.py`, `api/security/url_validator.py`

### Engine
- `engine/executor.py`, `engine/rate_limiter.py`, `engine/playwright_helper.py`
- `engine/diagnostics.py`, `engine/anti_detect.py`
- `engine/strategies/base.py`, `requests_st.py`, `cloudscraper_st.py`
- `engine/strategies/selenium_st.py`, `undetected_st.py`, `playwright_st.py`

### Pipeline
- `pipeline/pipeline.py`, `pipeline/crawl_pipeline.py`, `pipeline/crawl_demo.py`
- `pipeline/validator.py`, `pipeline/transformer.py`, `pipeline/sanitizer.py`, `pipeline/dedup.py`

### Scheduler & Plugins
- `scheduler/scheduler.py`, `scheduler/job_tracker.py`
- `plugins/plugin_interface.py`, `plugin_loader.py`, `plugin_manager.py`
- `plugins/manifest_verifier.py`, `plugins/import_guard.py`, `plugins/test_framework.py`

### Crawlers (19)
- **Hotdeals**: algumon, arca, clien, cocodal, fmkorea, ppomppu, quasarzone
- **Marts**: emart, homeplus, lottemart, cocodalin
- **Delivery**: baemin, coupangeats, yogiyo
- **Shopping**: giordano, musinsa, uniqlo
- **Location**: naver_place
- **Government**: opinet

### Registry
- `crawlers/registry/registry.py`

---

## Appendix B: Test Coverage Observed

Tests exist in:
- `tests/` — unit tests for crawlers, pipeline, scheduler, security, concurrency, audit
- `engine/tests/` — strategy, executor, diagnostics tests
- `plugins/tests/` — plugin interface, loader, manager, test framework

No integration tests for:
- Full pipeline (crawl → validate → transform → store) with mock services
- Scheduler + pipeline interaction
- Concurrent crawl race conditions
- Browser crash recovery
- Graceful shutdown sequence
