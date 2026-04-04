# Crawler-Admin Pipeline & Data Flow Stability Audit

> **Scope**: `packages/crawler-admin` — backend pipeline, engine, API routes, frontend stores & pages  
> **Date**: 2025-07-15  
> **Auditor**: Stability Planner (Pipeline & Data Flow Focus)

---

## Executive Summary

The crawler-admin sub-project implements a multi-stage crawl pipeline (crawl → validate → transform → store) with an SSE-enabled frontend admin dashboard. The architecture is well-structured with clear separation of concerns, but contains **12 stability risks** across pipeline atomicity, ingestion failure handling, SSE reliability, and frontend state management.

### Risk Distribution

| Severity | Count | Categories |
|----------|-------|------------|
| 🔴 Critical | 3 | Pipeline atomicity, ingestion failures, SSE connection management |
| 🟠 High | 4 | Data validation gaps, dedup edge cases, polling errors, store consistency |
| 🟡 Medium | 5 | Config handling, cache growth, race conditions, test gaps |

---

## 1. Pipeline Atomicity

**Files**: `pipeline/pipeline.py` (lines 90–211), `pipeline/crawl_pipeline.py`

### Current Behavior

The pipeline executes 5 sequential stages inside `CrawlPipeline.run_crawler()`:

```
Crawl → Parse → Validate → Transform → Store
```

Each stage operates on the output of the previous one, with no checkpoint or rollback mechanism.

### 🔴 CRITICAL: Partial Pipeline Runs Leave Inconsistent Data

**Problem**: If the pipeline succeeds through validation and transformation but fails at the `_store()` or `_store_to_ingestion()` step (lines 176–187), the pipeline returns `items_saved=0` with `status="success"`. The event bus publishes a `CRAWL_COMPLETED` event with `items_saved=0`, which is semantically misleading — downstream systems see "success" but no data was persisted.

```python
# pipeline.py lines 189-211 — status is always "success" if crawl + validation passed
result = PipelineResult(
    crawler_name=crawler_name,
    status="success",        # ← Even when items_saved == 0
    items_found=items_found,
    items_valid=items_valid,
    items_saved=items_saved,  # ← Could be 0 due to store failure
    ...
)
```

**Impact**: Dashboard shows "success" for runs that stored nothing. Job history accumulates false positives. Scheduled re-runs may not trigger because the job is marked successful.

**Recommendation**:
```python
# Determine status based on actual persistence outcome
if items_saved == 0 and items_valid > 0:
    final_status = "partial"  # Data was valid but storage failed
elif items_saved < items_valid:
    final_status = "partial"
else:
    final_status = "success"
```

### 🟡 MEDIUM: No Checkpoint/Resume for Long-Running Batch Pipelines

**Problem**: `run_batch()` (line 223) uses `asyncio.gather(*tasks, return_exceptions=False)`. If one crawler raises an unhandled exception, `gather` propagates it immediately and cancels the remaining tasks.

```python
async def run_batch(self, crawler_names: list[str]) -> list[PipelineResult]:
    tasks = [self.run_crawler(name) for name in crawler_names]
    return list(await asyncio.gather(*tasks, return_exceptions=False))
    #                                       ↑ One failure kills all
```

**Recommendation**: Change to `return_exceptions=True` and wrap Exception results:
```python
results = await asyncio.gather(*tasks, return_exceptions=True)
return [r if isinstance(r, PipelineResult) else PipelineResult(
    crawler_name=name, status="failed", errors=[str(r)]
) for name, r in zip(crawler_names, results)]
```

---

## 2. Data Validation

**Files**: `pipeline/validator.py`, `pipeline/sanitizer.py`

### ✅ Strengths

- `validate_items()` cleanly separates valid/invalid items with descriptive `_validation_error` annotations
- `validate_price_range()` correctly passes `None` prices (items without prices are valid)
- `sanitize_text()` has comprehensive XSS defense (HTML tag stripping, entity escaping, control char removal)
- `sanitize_url()` blocks `javascript:`, `data:`, `vbscript:` schemes
- `sanitize_number()` enforces range bounds (0 – 100M)
- All sanitization is well-tested in `test_sanitizer.py`

### 🟠 HIGH: Malformed Crawl Data — No Schema Enforcement

**Problem**: Items flowing through the pipeline are untyped `dict[str, Any]`. There is no Pydantic model or JSON Schema validation at the entry point. The `validate_items()` function only checks for field *presence*, not type correctness.

```python
# validator.py line 17 — only checks existence, not type
missing = [f for f in required_fields if not item.get(f)]
```

A malformed item like `{"name": 123, "price": "not-a-number"}` passes field-presence validation but could cause downstream failures in `transformer.py` or DB insertion.

**Impact**: Type errors in the transformer silently produce incorrect records. A string price like `"무료"` is normalized to `None` by `normalize_prices()`, but other fields (e.g., `name` as an integer) are never caught.

**Recommendation**: Add type validation in `validate_items()`:
```python
FIELD_TYPES = {"name": str, "price": (int, float, str, type(None)), "url": str}

for f in required_fields:
    val = item.get(f)
    if not val:
        missing.append(f)
    elif f in FIELD_TYPES and not isinstance(val, FIELD_TYPES[f]):
        type_errors.append(f"field '{f}' expected {FIELD_TYPES[f]}, got {type(val)}")
```

### 🟡 MEDIUM: Sanitizer Applied After Validation, Not Before

**Problem**: In `pipeline.py`, the sanitizer runs *only* through `transformer.py` (which calls `sanitize_record()`), but raw items pass through validation first. An item with `name: "<script>alert(1)</script>"` will pass `validate_items()` (field is present and truthy), then get sanitized later. If validation logic ever depends on field *content* (not just presence), unsanitized data could cause issues.

The inline sanitizer in `pipeline.py` (lines 148–151) only truncates strings > 5000 chars but doesn't run the full sanitization.

**Recommendation**: Move `sanitize_record()` to run on raw items *before* validation, ensuring all downstream logic operates on clean data.

---

## 3. Deduplication

**Files**: `pipeline/validator.py` (lines 70–82), `pipeline/dedup.py`

### Two Dedup Systems

| System | Location | Mechanism | Scope |
|--------|----------|-----------|-------|
| Simple dedup | `validator.py:deduplicate()` | Exact tuple match on key fields | Per-pipeline run |
| Hotdeal dedup | `dedup.py:HotdealDeduplicator` | URL normalization + Jaccard n-gram similarity + Union-Find | Cross-community |

### 🟠 HIGH: Simple Dedup — Hash Collision via None Values

**Problem**: `deduplicate()` uses `tuple(item.get(f) for f in key_fields)` as the dedup key. If both `name` and `price` are `None` (or missing), all such items share the key `(None, None)` and only the first is kept.

```python
# validator.py line 78
key = tuple(item.get(f) for f in key_fields)
# If item has no "name" and no "price": key = (None, None)
# ALL items missing these fields collapse to one entry
```

**Impact**: Items that failed price normalization (price set to `None`) and share the same name will be incorrectly deduplicated. Items missing both key fields are silently dropped.

**Recommendation**: Include a unique fallback (e.g., item index or hash of all fields) when key fields are `None`:
```python
key = tuple(item.get(f, f"__missing_{i}__") for f in key_fields)
```

### 🟡 MEDIUM: Hotdeal Dedup — O(n²) Pairwise Comparison

**Problem**: `HotdealDeduplicator.find_duplicates()` (line 79-95) performs pairwise comparison of all items: `for i in range(n): for j in range(i+1, n)`. With 1000 items, this is ~500,000 comparisons. Each comparison computes Jaccard similarity on pre-computed n-gram sets, which is fast per comparison, but the quadratic growth is a scaling concern.

**Impact**: At scale (10K+ items), dedup becomes a bottleneck. Currently acceptable for typical crawl volumes (< 500 items per run).

**Recommendation**: For future scaling, consider MinHash/LSH for approximate dedup at O(n) complexity.

### ✅ Hotdeal Dedup Strengths

- Union-Find with path compression provides efficient group management
- URL normalization removes tracking parameters (UTM, fbclid, gclid)
- Tiered matching: exact URL → title similarity (≥ 0.85) → title + price combined (≥ 0.6)
- Community tag removal before comparison prevents false negatives
- `_select_best()` prioritizes items with prices, longer titles, earlier timestamps

---

## 4. Ingestion Failures

**Files**: `pipeline/pipeline.py` (lines 230–285), `api/routes/ingestion.py`

### 🔴 CRITICAL: No Retry or Dead Letter Queue for Failed Ingestions

**Problem**: Both `_store()` and `_store_to_ingestion()` catch all exceptions, log a warning, append to the `errors` list, and return `0`. There is no:
- Retry mechanism for transient HTTP failures (network blips, 502/503)
- Dead letter queue for data that consistently fails to ingest
- Local buffering of un-sent records

```python
# pipeline.py lines 241-244
except Exception as exc:
    errors.append(f"store: {exc}")
    logger.warning(f"[Pipeline] store failed: {exc}")
    return 0  # Data is silently lost
```

**Impact**: If the DB-Admin API is temporarily down during a crawl run, all crawled data is permanently lost. The crawl job is marked "success" (see Issue #1), so there's no trigger for re-crawl.

**Recommendation**:
1. **Immediate**: Add exponential backoff retry (3 attempts) with jitter for transient HTTP errors (5xx, connection refused)
2. **Short-term**: Write failed payloads to a local JSON file as a dead letter queue, with a periodic sweep job to retry
3. **Long-term**: Use the existing `_store_to_ingestion()` path (which submits to the ingestion API) as the primary flow, since it has human review built in

```python
async def _store_with_retry(self, records, errors, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.db_api_url, json=records)
                resp.raise_for_status()
                return len(records)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                break  # Client error, no retry
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt + random.random())
        except (httpx.ConnectError, httpx.TimeoutException):
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt + random.random())
    # All retries failed — write to dead letter file
    self._write_dead_letter(records, errors)
    return 0
```

### 🟠 HIGH: Ingestion Proxy API Has No Circuit Breaker

**Problem**: `api/routes/ingestion.py` proxies every request to `DB_ADMIN_URL`. If the DB-Admin service is down, every API call from the frontend results in a 15-second timeout followed by a 502 error. There's no circuit breaker to fast-fail after repeated connection failures.

```python
# ingestion.py — every call creates a new httpx client with 15s timeout
async with httpx.AsyncClient(timeout=15) as client:
    resp = await client.get(DB_ADMIN_URL, params=params)
```

**Impact**: Frontend becomes unresponsive when the DB-Admin service is down — every ingestion list/detail request hangs for 15 seconds before showing an error.

**Recommendation**: Implement a simple circuit breaker:
```python
_circuit_open = False
_circuit_open_until = 0

async def _proxy_request(method, url, **kwargs):
    global _circuit_open, _circuit_open_until
    if _circuit_open and time.time() < _circuit_open_until:
        raise HTTPException(503, "DB Admin service temporarily unavailable")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await getattr(client, method)(url, **kwargs)
            resp.raise_for_status()
            _circuit_open = False
            return resp.json()
    except (httpx.ConnectError, httpx.TimeoutException):
        _circuit_open = True
        _circuit_open_until = time.time() + 30  # 30s cooldown
        raise HTTPException(502, "DB Admin service unreachable")
```

---

## 5. Transformer Errors

**Files**: `pipeline/transformer.py`, `pipeline/sanitizer.py`

### Current Behavior

Transformers (`to_discount_history`, `to_hotdeal_prices`, `to_delivery_items`) use `.get()` with defaults for all field access, making them resilient to missing fields. The `sanitize_record()` call wraps each output record.

### ✅ Strengths

- All field access uses `item.get(field, default)` — no KeyError possible
- `sanitize_record()` applied to every output record
- `enrich_with_category()` skips items that already have a category
- Category mapping is keyword-based and deterministic

### 🟡 MEDIUM: No Fallback for Unsupported model_type

**Problem**: In `pipeline.py` (lines 169–173), the `model_type` switch only handles `"HotdealPost"` and falls through to `to_discount_history()` for everything else. If a new crawler type is registered with an unknown `model_type`, it silently uses the wrong transformer.

```python
if model_type == "HotdealPost":
    records = to_hotdeal_prices(items, source="hotdeal")
else:
    records = to_discount_history(items, source="mart_discount")
```

**Recommendation**: Add explicit model type validation:
```python
_TRANSFORMERS = {
    "HotdealPost": lambda items: to_hotdeal_prices(items, source="hotdeal"),
    "DiscountItem": lambda items: to_discount_history(items, source="mart_discount"),
    "DeliveryItem": lambda items: to_delivery_items(items),
}
transformer = _TRANSFORMERS.get(model_type)
if transformer is None:
    errors.append(f"unknown model_type: {model_type}")
    return self._fail(crawler_name, f"unsupported model_type: {model_type}", start, errors)
records = transformer(items)
```

---

## 6. SSE Streaming

**Files**: `api/routes/crawlers.py` (lines 417–463), `frontend/src/api/client.js` (lines 36–59)

### 🔴 CRITICAL: SSE Connection Management — No Reconnection Strategy

**Backend** (`crawlers.py:stream_crawler_status`):
- ✅ Has max duration limit (`SSE_MAX_DURATION`, default 1800s)
- ✅ Checks `request.is_disconnected()` each loop iteration
- ✅ Uses hash-based change detection to avoid redundant events
- ✅ Terminates stream on success/failed status
- ⚠️ 1-second polling interval means ~1s update latency

**Frontend** (`client.js:subscribeCrawlerStatus`):
- ❌ **No reconnection**: `eventSource.onerror` immediately closes and calls `onError`
- ❌ **No exponential backoff**: Connection drop = permanent failure
- ❌ **No heartbeat detection**: Can't distinguish server-side close from network failure

```javascript
// client.js lines 53-58
eventSource.onerror = () => {
    eventSource.close();
    onError?.(new Error('SSE connection failed'));
    // ← Connection permanently lost, no retry
};
```

**Impact**: Any transient network interruption (Wi-Fi switch, proxy timeout) permanently breaks the real-time status feed. The user sees no further updates and must manually refresh.

**Recommendation**:
```javascript
function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
    let retries = 0;
    const MAX_RETRIES = 5;

    function connect() {
        const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
        const eventSource = new EventSource(url);

        eventSource.onmessage = (event) => {
            retries = 0; // Reset on successful message
            try {
                const data = JSON.parse(event.data);
                onData?.(data);
                if (data.status === 'success' || data.status === 'failed') {
                    eventSource.close();
                    onComplete?.(data);
                }
            } catch (e) {
                onError?.(e);
            }
        };

        eventSource.onerror = () => {
            eventSource.close();
            if (retries < MAX_RETRIES) {
                retries++;
                setTimeout(connect, Math.min(1000 * 2 ** retries, 10000));
            } else {
                onError?.(new Error('SSE connection failed after retries'));
            }
        };

        return eventSource;
    }

    let es = connect();
    return { close: () => es.close() };
}
```

---

## 7. Frontend State

**Files**: `frontend/src/stores/adminStore.js`, `frontend/src/pages/Crawlers/Crawlers.jsx`

### ✅ Strengths

- Zustand store with domain-isolated loading/error states (prevents cross-domain re-renders)
- Optimistic updates with rollback for toggle operations (`toggleCrawlerStatus`, `togglePlugin`, `toggleSchedule`)
- User-friendly error messages via `toUserMessage()` — never exposes raw server errors
- Null-safe data mapping with `??` operator throughout store

### 🟠 HIGH: Crawlers.jsx — Race Condition in Concurrent Crawler Runs

**Problem**: When multiple crawlers are run simultaneously (via individual clicks or bulk run), each starts its own SSE connection or polling timer stored in `pollRefs.current[id]`. If a user clicks "run" on a crawler that's already running:

1. The old SSE/timer reference is overwritten: `pollRefs.current[id] = newRef`
2. The old connection/timer becomes orphaned — no way to clean it up
3. Both old and new SSE connections receive events, causing duplicate state updates

```javascript
// Crawlers.jsx — startPolling overwrites without cleanup
const startPolling = useCallback((id) => {
    const oldRef = pollRefs.current[id];
    // oldRef is checked but only for close/clearTimeout
    // If oldRef is an SSE and new one starts, old may still be active
    pollRefs.current[id] = api.subscribeCrawlerStatus(id, { ... });
}, []);
```

**Impact**: Memory leaks from orphaned EventSource connections. Duplicate state updates cause UI flickering. Backend resources wasted on abandoned SSE streams.

**Recommendation**: Always fully close the previous connection before starting a new one. Add a guard in the run handler to prevent re-runs of active crawlers:
```javascript
if (runStates[id]?.status === 'running') return; // Prevent duplicate runs
```

### 🟡 MEDIUM: Silent Polling Errors

**Problem**: In `Crawlers.jsx`, the polling fallback catches errors with an empty handler:
```javascript
} catch {
    /* 폴링 실패 무시 */
}
```

This means network failures during polling are completely invisible to the user. The polling continues silently returning stale data.

**Recommendation**: Track consecutive failures and show a warning after 3+ failures:
```javascript
} catch (err) {
    failCount++;
    if (failCount >= 3) {
        onError?.(new Error('Status polling repeatedly failed'));
    }
}
```

---

## 8. WebSocket/Polling

**Files**: `api/routes/crawlers.py`, `frontend/src/api/client.js`

### Current Architecture

```
Frontend                    Backend
  │                           │
  ├─ SSE (primary) ─────────→│ /crawlers/{id}/status/stream
  │  (EventSource)            │   └─ 1s poll of _crawl_results dict
  │                           │
  ├─ ETag Polling (fallback)─→│ /crawlers/{id}/status
  │  (exponential backoff)    │   └─ ETag/304 for bandwidth saving
  │                           │
  └─ Fetch (one-shot) ──────→│ /crawlers (list)
```

### ✅ Strengths

- **ETag support**: Status polling uses `If-None-Match` headers; backend returns 304 when status hasn't changed — significant bandwidth savings
- **SSE with polling fallback**: Graceful degradation when SSE isn't available
- **Exponential backoff**: Polling interval grows from 2s → 3s → 4.5s → max 10s
- **Max poll count**: 120 polls (~120 seconds) prevents infinite polling
- **Rate limiting**: `/crawlers/{id}/run` limited to 5/minute; list endpoints at 60/minute

### 🟡 MEDIUM: In-Memory Status Storage

**Problem**: `_crawl_results` in `crawlers.py` is a plain Python dict. In a multi-worker deployment (e.g., gunicorn with multiple workers), each worker has its own `_crawl_results`. A crawl started in worker A won't be visible in worker B's status endpoint.

```python
_crawl_results: dict[str, dict[str, Any]] = {}  # Per-process, not shared
```

**Impact**: For single-worker deployments (current), no issue. For scaled deployments, status queries return inconsistent results depending on which worker handles the request.

**Recommendation**: For future scaling, consider Redis-backed status storage or sticky sessions.

---

## 9. Configuration

**Files**: `backend/config.py`, `backend/concurrency.py`

### ✅ Strengths

- All config values are sourced from environment variables with sensible defaults
- `DATABASE_URL` emits a `RuntimeWarning` when missing (not a silent failure)
- Resource limits are configurable: `MAX_CONCURRENT_CRAWLS`, `CRAWL_CUMULATIVE_TIMEOUT`, `SSE_MAX_DURATION`

### 🟡 MEDIUM: Invalid Config Values Not Validated at Startup

**Problem**: Numeric config values use raw `int()` / `float()` casts without validation:

```python
# config.py
MAX_CONCURRENT_CRAWLS: int = int(os.getenv("MAX_CONCURRENT_CRAWLS", "5"))
```

If `MAX_CONCURRENT_CRAWLS` is set to `"0"` or `"-1"`, the semaphore will behave incorrectly. If `CRAWL_DELAY_MIN` > `CRAWL_DELAY_MAX`, `random.uniform()` in `AntiDetect` will swap them silently (Python behavior), but the semantics are wrong.

**Recommendation**: Add startup validation:
```python
assert MAX_CONCURRENT_CRAWLS >= 1, "MAX_CONCURRENT_CRAWLS must be >= 1"
assert CRAWL_DELAY_MIN <= CRAWL_DELAY_MAX, "CRAWL_DELAY_MIN must be <= CRAWL_DELAY_MAX"
assert REQUEST_TIMEOUT >= 1, "REQUEST_TIMEOUT must be >= 1"
```

### 🟡 MEDIUM: Runtime Config Changes Not Propagated

**Problem**: Config values are read once at import time. Changing `.env` while the server is running has no effect. The `DomainRateLimiter` (line 42: `_limiter = DomainRateLimiter()`) and `_semaphore` (concurrency.py line 17) are module-level singletons initialized at import time.

Additionally, `DomainRateLimiter.set_interval()` is a no-op stub:
```python
def set_interval(self, domain: str, interval: float) -> None:
    pass  # future enhancement
```

**Impact**: Operators cannot adjust rate limits or concurrency without a full server restart.

**Recommendation**: For critical operational values (rate limits, concurrency), implement hot-reload via an admin API endpoint.

---

## 10. Test Gaps

**Files**: `backend/tests/`

### Current Test Coverage

| Module | Test File | Coverage Assessment |
|--------|-----------|-------------------|
| `pipeline/validator.py` | `test_pipeline.py` | ✅ Good — all functions tested |
| `pipeline/transformer.py` | `test_pipeline.py` | ✅ Good — all 3 transformers + category enrichment |
| `pipeline/sanitizer.py` | `test_sanitizer.py` | ✅ Excellent — comprehensive edge cases |
| `pipeline/pipeline.py` | `test_pipeline.py` | ⚠️ Partial — happy path + not-found, no failure paths |
| `pipeline/dedup.py` | — | ❌ No dedicated tests |
| `engine/executor.py` | — | ❌ Not found in test list |
| `engine/rate_limiter.py` | `test_rate_limiter.py` | ✅ Present |
| `api/routes/crawlers.py` | `test_crawler_api.py` | ✅ Present |
| `concurrency.py` | `test_concurrency.py` | ✅ Present |
| `api/error_handler.py` | `test_error_handler.py` | ✅ Present |
| `scheduler/` | `test_scheduler.py` | ✅ Present |

### 🟠 HIGH: Untested Failure Paths

The following critical failure scenarios have no test coverage:

1. **Pipeline store failure** — `_store()` and `_store_to_ingestion()` when httpx raises `ConnectError`, `TimeoutException`, or receives a 500 response
2. **Pipeline with all retries exhausted** — `run_crawler()` when crawler.crawl() fails `retry_count` times
3. **Pipeline with zero items** — `run_crawler()` when crawl succeeds but returns empty items list
4. **Hotdeal deduplication** — `HotdealDeduplicator` has no tests despite complex similarity logic
5. **SSE stream behavior** — `stream_crawler_status` generator lifecycle (timeout, disconnect, status transitions)
6. **Concurrent crawler execution** — `acquire_crawler_slot` / `release_crawler_slot` under concurrent load
7. **Ingestion proxy failures** — `ingestion.py` routes when DB-Admin is unreachable
8. **Bulk run with mixed results** — `bulk_run_crawlers` when some crawlers exist and others don't
9. **`asyncio.ensure_future` in `_fail()`** — line 298 uses `ensure_future` which may not work correctly if no event loop is running

### Recommended Test Additions

```python
# test_pipeline_failures.py

@pytest.mark.asyncio
async def test_store_failure_sets_partial_status():
    """Pipeline should report 'partial' when store fails."""
    # Mock httpx to raise ConnectError
    # Assert result.status == "partial" and result.items_saved == 0

@pytest.mark.asyncio
async def test_all_retries_exhausted():
    """Pipeline should fail after retry_count attempts."""
    # Mock crawler.crawl to always return FAILED status
    # Assert result.status == "failed" and len(result.errors) == retry_count

@pytest.mark.asyncio  
async def test_batch_run_isolates_failures():
    """One crawler failure should not affect others in batch."""
    # Run batch with one failing and one succeeding crawler
    # Assert both results returned, one success and one failed

class TestHotdealDeduplicator:
    def test_url_normalization_removes_tracking():
        """UTM params should be stripped for URL comparison."""
    def test_title_similarity_threshold():
        """Items with >85% title similarity should be grouped."""
    def test_price_plus_title_combined_match():
        """Items with 60-85% title similarity + same price should be grouped."""
    def test_empty_input():
        """Empty list should return empty list."""
    def test_all_unique():
        """All unique items should be returned unchanged."""
```

---

## Risk Summary & Prioritized Remediation

| # | Risk | Severity | Effort | Priority |
|---|------|----------|--------|----------|
| 1 | Pipeline reports "success" when store fails | 🔴 Critical | Low | **P0** |
| 2 | No retry/DLQ for ingestion failures — data loss | 🔴 Critical | Medium | **P0** |
| 3 | SSE no reconnection — permanent status loss | 🔴 Critical | Low | **P0** |
| 4 | No schema enforcement on pipeline input | 🟠 High | Medium | P1 |
| 5 | Dedup key collision on None values | 🟠 High | Low | P1 |
| 6 | Ingestion proxy has no circuit breaker | 🟠 High | Medium | P1 |
| 7 | Frontend race condition: concurrent crawler runs | 🟠 High | Medium | P1 |
| 8 | `run_batch` with `return_exceptions=False` | 🟡 Medium | Low | P2 |
| 9 | Unsupported model_type silently uses wrong transformer | 🟡 Medium | Low | P2 |
| 10 | Config values not validated at startup | 🟡 Medium | Low | P2 |
| 11 | In-memory status not shared across workers | 🟡 Medium | High | P3 |
| 12 | Missing tests for failure paths + dedup module | 🟠 High | Medium | P1 |

---

## Appendix: File Reference

| Layer | File | Lines | Role |
|-------|------|-------|------|
| Pipeline | `pipeline/pipeline.py` | 310 | Main crawl→validate→transform→store orchestrator |
| Pipeline | `pipeline/validator.py` | 107 | Field presence, price range, URL format, dedup |
| Pipeline | `pipeline/transformer.py` | 113 | Dict → DB record conversion + category enrichment |
| Pipeline | `pipeline/sanitizer.py` | 114 | XSS prevention, URL sanitization, number range enforcement |
| Pipeline | `pipeline/dedup.py` | 239 | Hotdeal cross-community deduplication (Jaccard + Union-Find) |
| Engine | `engine/executor.py` | 287 | Multi-strategy cascade executor with timeout control |
| Engine | `engine/diagnostics.py` | 162 | Auto-diagnosis of crawl failures with severity ranking |
| Engine | `engine/rate_limiter.py` | 47 | Per-domain request throttling |
| Engine | `engine/anti_detect.py` | 162 | User-Agent rotation, proxy management, delay randomization |
| API | `api/routes/crawlers.py` | 464 | Crawler CRUD, run, SSE stream, bulk operations |
| API | `api/routes/ingestion.py` | 112 | Ingestion proxy to DB-Admin API |
| API | `api/routes/dashboard.py` | 223 | Dashboard statistics with 60s cache |
| API | `api/routes/logs.py` | 156 | Log listing with server-side pagination + CSV export |
| API | `api/routes/schedules.py` | 343 | Schedule CRUD with APScheduler + file persistence |
| API | `api/error_handler.py` | 56 | Global exception handler with correlation IDs |
| API | `api/error_codes.py` | 56 | Standardized error codes and safe responses |
| Config | `config.py` | 65 | Environment variable configuration |
| Config | `concurrency.py` | 44 | Semaphore + per-crawler lock primitives |
| Frontend | `stores/adminStore.js` | 427 | Zustand store with domain-isolated state |
| Frontend | `api/client.js` | 145 | API client with ETag caching + SSE helper |
| Frontend | `pages/Crawlers/Crawlers.jsx` | 643 | Crawler management with SSE + polling fallback |
| Frontend | `pages/Dashboard/Dashboard.jsx` | 296 | Dashboard with charts and status cards |
| Frontend | `pages/DataReview/DataReviewPage.jsx` | 720 | Ingestion review with bulk approve/reject |
