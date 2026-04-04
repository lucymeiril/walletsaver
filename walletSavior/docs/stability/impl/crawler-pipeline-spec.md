# Crawler-Admin Pipeline Stability — Implementation Spec

> **Source**: `crawler-admin-stability-audit.md`, `crawler-admin-pipeline-audit.md`  
> **Scope**: Pipeline reliability, data safety, frontend resilience  
> **Date**: 2025-07-15

---

## Table of Contents

1. [Pipeline Store Failure — Status Propagation](#1-pipeline-store-failure)
2. [Dead Letter Queue — Local File Fallback](#2-dead-letter-queue)
3. [Circuit Breaker — Ingestion Proxy](#3-circuit-breaker)
4. [Dedup Fix — None-Field Hash Collisions](#4-dedup-fix)
5. [Schema Enforcement — Type-Level Validation](#5-schema-enforcement)
6. [Frontend SSE Race Condition](#6-frontend-sse-race-condition)
7. [Error Boundary — React Error Boundaries](#7-error-boundary)
8. [Structured Logging — JSON Logging](#8-structured-logging)

---

## 1. Pipeline Store Failure

**Audit Refs**: PF-1, Pipeline Audit §1  
**Severity**: 🔴 CRITICAL  
**File**: `packages/crawler-admin/backend/pipeline/pipeline.py`

### Problem

When `_store()` or `_store_to_ingestion()` fails, `items_saved` is `0` but pipeline still returns `status="success"`. Downstream systems (dashboard, scheduler) see false positives.

### Before (lines 189–198)

```python
duration = time.monotonic() - start
result = PipelineResult(
    crawler_name=crawler_name,
    status="success",            # ← Always "success" even when items_saved == 0
    items_found=items_found,
    items_valid=items_valid,
    items_saved=items_saved,     # ← Could be 0 due to store failure
    duration=duration,
    errors=errors,
)
```

### After

```python
        duration = time.monotonic() - start

        # Determine status based on actual persistence outcome
        if items_saved == 0 and items_valid > 0:
            final_status = "partial_failure"
        elif 0 < items_saved < items_valid:
            final_status = "partial_failure"
        else:
            final_status = "success"

        result = PipelineResult(
            crawler_name=crawler_name,
            status=final_status,
            items_found=items_found,
            items_valid=items_valid,
            items_saved=items_saved,
            duration=duration,
            errors=errors,
        )
```

Also fix `run_batch` (line 226) to isolate failures:

### Before (line 223–226)

```python
async def run_batch(self, crawler_names: list[str]) -> list[PipelineResult]:
    """지정된 크롤러들을 동시 실행."""
    tasks = [self.run_crawler(name) for name in crawler_names]
    return list(await asyncio.gather(*tasks, return_exceptions=False))
```

### After

```python
async def run_batch(self, crawler_names: list[str]) -> list[PipelineResult]:
    """지정된 크롤러들을 동시 실행. 개별 실패가 다른 크롤러에 영향을 주지 않는다."""
    tasks = [self.run_crawler(name) for name in crawler_names]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)
    results: list[PipelineResult] = []
    for name, r in zip(crawler_names, raw_results):
        if isinstance(r, PipelineResult):
            results.append(r)
        elif isinstance(r, BaseException):
            logger.error("[Pipeline] batch: %s raised %s", name, r)
            results.append(PipelineResult(
                crawler_name=name,
                status="failed",
                errors=[f"unhandled: {r}"],
            ))
    return results
```

### Test Cases

```python
# File: packages/crawler-admin/backend/tests/test_pipeline_store_failure.py

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.pipeline import CrawlPipeline, PipelineResult
from core.models import CrawlResult, CrawlStatus


def _make_pipeline(mock_registry, mock_crawler, db_url="http://fake:9999/api/prices/bulk"):
    mock_registry.get_crawler.return_value = mock_crawler
    return CrawlPipeline(registry=mock_registry, db_api_url=db_url)


def _make_registry():
    reg = MagicMock()
    reg._registry = {
        "test": {
            "config": {
                "output": {"model": "DiscountItem", "required_fields": ["name", "price"]},
                "schedule": {"retry_count": 1},
            }
        }
    }
    reg.list_crawlers.return_value = [{"name": "test", "category": "mart"}]
    return reg


def _make_crawler(items):
    c = MagicMock()
    c.crawl = AsyncMock(return_value=CrawlResult(
        status=CrawlStatus.SUCCESS, crawler_name="test",
        items_count=len(items), items=items,
    ))
    return c


class TestStoreFailurePropagation:
    """Pipeline must report 'partial_failure' when valid items exist but store returns 0."""

    @pytest.mark.asyncio
    async def test_store_failure_sets_partial_status(self):
        reg = _make_registry()
        crawler = _make_crawler([{"name": "사과", "price": 3000}])
        pipeline = _make_pipeline(reg, crawler)

        with patch("pipeline.pipeline.SKIP_REVIEW", True):
            with patch.object(pipeline, "_store", new_callable=AsyncMock, return_value=0):
                result = await pipeline.run_crawler("test")

        assert result.status == "partial_failure"
        assert result.items_saved == 0
        assert result.items_valid >= 1

    @pytest.mark.asyncio
    async def test_store_success_keeps_success_status(self):
        reg = _make_registry()
        crawler = _make_crawler([{"name": "사과", "price": 3000}])
        pipeline = _make_pipeline(reg, crawler)

        with patch("pipeline.pipeline.SKIP_REVIEW", True):
            with patch.object(pipeline, "_store", new_callable=AsyncMock, return_value=1):
                result = await pipeline.run_crawler("test")

        assert result.status == "success"
        assert result.items_saved == 1


class TestBatchIsolation:
    """One crawler failure in run_batch must not cancel the others."""

    @pytest.mark.asyncio
    async def test_batch_isolates_exception(self):
        reg = MagicMock()
        reg._registry = {
            "good": {"config": {"output": {"model": "DiscountItem", "required_fields": ["name"]}, "schedule": {"retry_count": 1}}},
            "bad": {"config": {"output": {"model": "DiscountItem", "required_fields": ["name"]}, "schedule": {"retry_count": 1}}},
        }
        good_crawler = _make_crawler([{"name": "사과", "price": 3000}])
        bad_crawler = MagicMock()
        bad_crawler.crawl = AsyncMock(side_effect=RuntimeError("boom"))

        def get_crawler(name):
            return good_crawler if name == "good" else bad_crawler

        reg.get_crawler.side_effect = get_crawler
        pipeline = CrawlPipeline(registry=reg, db_api_url="http://fake:9999/api/prices/bulk")
        results = await pipeline.run_batch(["good", "bad"])

        assert len(results) == 2
        statuses = {r.crawler_name: r.status for r in results}
        assert statuses["bad"] == "failed"
```

---

## 2. Dead Letter Queue

**Audit Refs**: PF-1, Pipeline Audit §4  
**Severity**: 🔴 CRITICAL  
**File**: `packages/crawler-admin/backend/pipeline/pipeline.py` (new helper + changes to `_store` / `_store_to_ingestion`)

### Problem

When DB-Admin or Ingestion API is down, crawled data is permanently lost. No local fallback exists.

### Implementation

Add a `dead_letter.py` module and modify the two store methods to retry with exponential backoff, then fall back to local JSONL files.

#### New File: `packages/crawler-admin/backend/pipeline/dead_letter.py`

```python
"""Dead-letter queue — local file fallback for failed ingestion attempts.

On store/ingestion failure, records are written to a JSONL file under
``data/dead_letter/``. A background sweep can replay them later.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DLQ_DIR = Path(os.getenv(
    "DLQ_DIR",
    str(Path(__file__).resolve().parent.parent / "data" / "dead_letter"),
))


def write_dead_letter(
    records: list[dict[str, Any]],
    *,
    crawler_name: str = "unknown",
    target: str = "store",
    error_msg: str = "",
) -> Path:
    """Persist *records* to a timestamped JSONL file and return its path."""
    _DLQ_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{crawler_name}_{target}_{ts}.jsonl"
    path = _DLQ_DIR / filename

    envelope = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "crawler_name": crawler_name,
        "target": target,
        "error": error_msg,
        "record_count": len(records),
        "records": records,
    }

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(envelope, ensure_ascii=False, default=str))

    logger.warning(
        "[DLQ] wrote %d records → %s (target=%s, error=%s)",
        len(records), path, target, error_msg,
    )
    return path


def list_dead_letters() -> list[Path]:
    """Return all pending dead-letter files, oldest first."""
    if not _DLQ_DIR.exists():
        return []
    return sorted(_DLQ_DIR.glob("*.jsonl"))


def read_dead_letter(path: Path) -> dict[str, Any]:
    """Read a single dead-letter file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.loads(fh.read())


def remove_dead_letter(path: Path) -> None:
    """Delete a dead-letter file after successful replay."""
    path.unlink(missing_ok=True)
```

#### Modified `_store()` — retry + DLQ fallback

```python
# pipeline.py — replace the existing _store method entirely

    async def _store(
        self, records: list[dict[str, Any]], errors: list[str],
        *, _max_retries: int = 3,
    ) -> int:
        """DB-Admin API 로 레코드 전송. 재시도 후 실패 시 DLQ에 기록."""
        import random
        from pipeline.dead_letter import write_dead_letter

        if not records:
            return 0

        last_exc: Exception | None = None
        for attempt in range(1, _max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(self.db_api_url, json=records)
                    resp.raise_for_status()
                    return len(records)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500:
                    break  # client error — no retry
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())

        # All retries exhausted — write to DLQ
        err_msg = str(last_exc) if last_exc else "unknown"
        errors.append(f"store: {err_msg}")
        logger.warning("[Pipeline] store failed after %d retries: %s", _max_retries, err_msg)
        write_dead_letter(records, target="db_admin", error_msg=err_msg)
        return 0
```

#### Modified `_store_to_ingestion()` — retry + DLQ fallback

```python
# pipeline.py — replace the existing _store_to_ingestion method entirely

    async def _store_to_ingestion(
        self,
        crawler_name: str,
        crawl_status: str,
        items: list[dict[str, Any]],
        schema_type: str,
        strategy_used: str | None,
        duration_seconds: float,
        errors: list[str],
        *,
        _max_retries: int = 3,
    ) -> int:
        """대기열(Pending Ingestion)에 크롤 결과 제출. 재시도 후 실패 시 DLQ에 기록."""
        import random
        from pipeline.dead_letter import write_dead_letter

        if not items:
            return 0

        payload = {
            "crawler_name": crawler_name,
            "crawl_status": crawl_status,
            "items": items,
            "schema_type": schema_type,
            "strategy_used": strategy_used,
            "duration_seconds": round(duration_seconds, 2),
            "errors": [{"message": e} for e in errors],
        }

        last_exc: Exception | None = None
        for attempt in range(1, _max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(INGESTION_API_URL, json=payload)
                    resp.raise_for_status()
                    audit_log(
                        AuditEventType.DATA_SUBMISSION,
                        resource=crawler_name,
                        detail={
                            "item_count": len(items),
                            "schema_type": schema_type,
                            "strategy": strategy_used,
                        },
                    )
                    return len(items)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code < 500:
                    break
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < _max_retries:
                    await asyncio.sleep(2 ** attempt + random.random())

        err_msg = str(last_exc) if last_exc else "unknown"
        errors.append(f"ingestion_submit: {err_msg}")
        logger.warning("[Pipeline] ingestion submit failed after %d retries: %s", _max_retries, err_msg)
        write_dead_letter(
            payload.get("items", []),
            crawler_name=crawler_name,
            target="ingestion",
            error_msg=err_msg,
        )
        return 0
```

### Test Cases

```python
# File: packages/crawler-admin/backend/tests/test_dead_letter.py

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from pipeline.dead_letter import (
    write_dead_letter,
    list_dead_letters,
    read_dead_letter,
    remove_dead_letter,
)


@pytest.fixture
def dlq_dir(tmp_path):
    with patch("pipeline.dead_letter._DLQ_DIR", tmp_path):
        yield tmp_path


class TestDeadLetterQueue:
    def test_write_creates_file(self, dlq_dir):
        records = [{"name": "사과", "price": 3000}]
        path = write_dead_letter(records, crawler_name="emart", target="db_admin")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["record_count"] == 1
        assert data["crawler_name"] == "emart"
        assert data["records"] == records

    def test_list_returns_sorted(self, dlq_dir):
        write_dead_letter([{"a": 1}], crawler_name="a", target="x")
        write_dead_letter([{"b": 2}], crawler_name="b", target="x")
        files = list_dead_letters()
        assert len(files) == 2
        assert files[0].name < files[1].name  # alphabetical/timestamp order

    def test_read_round_trip(self, dlq_dir):
        records = [{"x": 42}]
        path = write_dead_letter(records, crawler_name="test", target="store")
        data = read_dead_letter(path)
        assert data["records"] == records

    def test_remove_deletes_file(self, dlq_dir):
        path = write_dead_letter([{"x": 1}], crawler_name="test", target="store")
        assert path.exists()
        remove_dead_letter(path)
        assert not path.exists()

    def test_list_empty_when_no_dir(self, tmp_path):
        with patch("pipeline.dead_letter._DLQ_DIR", tmp_path / "nonexistent"):
            assert list_dead_letters() == []
```

---

## 3. Circuit Breaker

**Audit Refs**: Pipeline Audit §4, ES-R1  
**Severity**: 🟠 HIGH  
**File**: `packages/crawler-admin/backend/api/routes/ingestion.py`

### Problem

Every ingestion proxy request creates a new `httpx.AsyncClient` with a 15s timeout. When DB-Admin is down, the frontend hangs for 15s per request before getting a 502. No fast-fail mechanism exists.

### Implementation

Add a `circuit_breaker.py` module and integrate it into the ingestion proxy.

#### New File: `packages/crawler-admin/backend/pipeline/circuit_breaker.py`

```python
"""Lightweight async circuit breaker for external service calls.

States:
  CLOSED  — requests flow normally
  OPEN    — requests fast-fail with CircuitOpenError
  HALF_OPEN — one probe request allowed; success closes, failure re-opens
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open (service assumed down)."""

    def __init__(self, service: str, retry_after: float):
        self.service = service
        self.retry_after = retry_after
        super().__init__(f"circuit open for {service}, retry after {retry_after:.0f}s")


class CircuitBreaker:
    """Async-safe circuit breaker.

    Args:
        service_name: Human-readable service name for logging.
        failure_threshold: Consecutive failures before opening.
        recovery_timeout: Seconds to wait before entering half-open state.
        success_threshold: Consecutive successes in half-open to close.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        service_name: str = "external",
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        success_threshold: int = 1,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.monotonic() - self._opened_at >= self.recovery_timeout:
                return self.HALF_OPEN
        return self._state

    async def __aenter__(self):
        await self.before_request()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            await self.on_success()
        elif exc_type is not CircuitOpenError:
            await self.on_failure()
        return False  # don't suppress

    async def before_request(self) -> None:
        """Call before making a request. Raises CircuitOpenError if open."""
        current = self.state
        if current == self.OPEN:
            remaining = self.recovery_timeout - (time.monotonic() - self._opened_at)
            raise CircuitOpenError(self.service_name, max(remaining, 0))
        # HALF_OPEN and CLOSED: allow the request

    async def on_success(self) -> None:
        async with self._lock:
            if self._state == self.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = self.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("[CircuitBreaker] %s: CLOSED (recovered)", self.service_name)
            else:
                self._failure_count = 0

    async def on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "[CircuitBreaker] %s: OPEN after %d failures (cooldown %.0fs)",
                    self.service_name, self._failure_count, self.recovery_timeout,
                )
            elif self._state == self.HALF_OPEN:
                self._state = self.OPEN
                self._opened_at = time.monotonic()
                logger.warning(
                    "[CircuitBreaker] %s: re-OPENED from half-open",
                    self.service_name,
                )
```

#### Modified: `packages/crawler-admin/backend/api/routes/ingestion.py`

Add circuit breaker around every DB-Admin proxy call:

```python
"""대기열(Pending Ingestion) 프록시 API — DB 관리 API로 요청을 전달."""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from api.app import limiter
from api.security.input_schemas import CleanupRequest
from audit import audit_log, AuditEventType
from pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingestions", tags=["ingestions"])

DB_ADMIN_URL = os.getenv(
    "DB_ADMIN_INGESTION_URL", "http://localhost:8002/api/ingestions"
)

# Circuit breaker: fast-fail after 3 consecutive failures, 30s cooldown
_cb = CircuitBreaker(service_name="db-admin", failure_threshold=3, recovery_timeout=30.0)


class ReviewRequest(BaseModel):
    action: str  # "approve", "reject"
    notes: Optional[str] = None
    approved_item_indices: Optional[list[int]] = None
    rejected_reason: Optional[str] = None


async def _proxy(method: str, url: str, **kwargs):
    """Execute a proxied HTTP request with circuit breaker protection."""
    try:
        async with _cb:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await getattr(client, method)(url, **kwargs)
                resp.raise_for_status()
                return resp.json()
    except CircuitOpenError:
        raise HTTPException(
            status_code=503,
            detail="DB 관리 서비스가 일시적으로 사용 불가합니다. 잠시 후 다시 시도해 주세요.",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, exc.response.text)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        logger.error("DB 관리 API 연결 실패: %s", exc)
        raise HTTPException(502, "DB 관리 API에 연결할 수 없습니다.")


@router.get("")
async def list_ingestions(
    status: Optional[str] = Query(None, description="상태 필터"),
    crawler_name: Optional[str] = Query(None, description="크롤러 필터"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """대기열 목록 — DB 관리 API 프록시."""
    params: dict = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    if crawler_name:
        params["crawler_name"] = crawler_name
    return await _proxy("get", DB_ADMIN_URL, params=params)


@router.get("/{ingestion_id}")
async def get_ingestion(ingestion_id: int):
    """대기열 상세 — DB 관리 API 프록시."""
    return await _proxy("get", f"{DB_ADMIN_URL}/{ingestion_id}")


@router.post("/{ingestion_id}/crawler-review")
async def crawler_review(ingestion_id: int, request: Request, body: ReviewRequest):
    """크롤러 관리자 1차 검토 — DB 관리 API 프록시."""
    audit_log(
        AuditEventType.DATA_INGESTION,
        request=request,
        detail={"ingestion_id": ingestion_id, "action": body.action},
    )
    return await _proxy(
        "post",
        f"{DB_ADMIN_URL}/{ingestion_id}/crawler-review",
        json=body.model_dump(),
    )


@router.post("/cleanup")
async def cleanup_ingestions(body: CleanupRequest):
    """처리 완료 항목 정리 — DB 관리 API 프록시."""
    return await _proxy(
        "post",
        f"{DB_ADMIN_URL}/cleanup",
        json=body.model_dump(exclude_none=True),
    )
```

### Test Cases

```python
# File: packages/crawler-admin/backend/tests/test_circuit_breaker.py

import asyncio
import pytest
from pipeline.circuit_breaker import CircuitBreaker, CircuitOpenError


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_by_default(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)
        for _ in range(2):
            await cb.on_failure()
        assert cb.state == "open"

    @pytest.mark.asyncio
    async def test_open_circuit_raises(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        await cb.on_failure()
        with pytest.raises(CircuitOpenError):
            await cb.before_request()

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        await cb.on_failure()
        await cb.on_failure()
        await cb.on_success()  # reset
        await cb.on_failure()  # count = 1 again
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        await cb.on_failure()
        assert cb.state == "half_open"  # recovery_timeout=0 → immediate

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0, success_threshold=1)
        await cb.on_failure()
        assert cb.state == "half_open"
        cb._state = cb.HALF_OPEN  # force for test
        await cb.on_success()
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_context_manager_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        async with cb:
            pass  # no exception → on_success
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_context_manager_failure(self):
        cb = CircuitBreaker(failure_threshold=3)
        with pytest.raises(ValueError):
            async with cb:
                raise ValueError("test")
        assert cb._failure_count == 1
```

---

## 4. Dedup Fix

**Audit Refs**: Pipeline Audit §3  
**Severity**: 🟠 HIGH  
**File**: `packages/crawler-admin/backend/pipeline/validator.py`

### Problem

`deduplicate()` uses `tuple(item.get(f) for f in key_fields)` as the dedup key. If key fields are `None` (or missing), all such items collapse to the same key `(None, None)` — only the first is kept.

### Before (lines 70–82)

```python
def deduplicate(
    items: list[dict[str, Any]],
    key_fields: list[str],
) -> list[dict[str, Any]]:
    """중복 제거. key_fields 조합이 같으면 첫 번째만 유지."""
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = tuple(item.get(f) for f in key_fields)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
```

### After

```python
def deduplicate(
    items: list[dict[str, Any]],
    key_fields: list[str],
) -> list[dict[str, Any]]:
    """중복 제거. key_fields 조합이 같으면 첫 번째만 유지.

    None/missing 필드가 포함된 키는 인덱스로 구별하여 false dedup을 방지한다.
    """
    seen: set[tuple] = set()
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        values = tuple(item.get(f) for f in key_fields)
        # If all key fields are None/missing, use index as tiebreaker
        # to prevent collapsing unrelated items
        if all(v is None for v in values):
            key = (*values, f"__idx_{idx}__")
        else:
            key = values
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
```

### Test Cases

```python
# Add to: packages/crawler-admin/backend/tests/test_pipeline.py  (TestDeduplicate class)

    def test_none_fields_not_collapsed(self):
        """Items with all-None key fields must not be falsely deduplicated."""
        items = [
            {"name": None, "price": None, "url": "https://a.com"},
            {"name": None, "price": None, "url": "https://b.com"},
            {"name": None, "price": None, "url": "https://c.com"},
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 3

    def test_partial_none_still_deduped(self):
        """Items sharing same name but None price should still dedup on (name, None)."""
        items = [
            {"name": "사과", "price": None},
            {"name": "사과", "price": None},
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 1  # same name, same None price → dedup

    def test_mixed_none_and_values(self):
        """Items with some None and some non-None key fields work correctly."""
        items = [
            {"name": "사과", "price": 3000},
            {"name": None, "price": None, "url": "https://a.com"},
            {"name": None, "price": None, "url": "https://b.com"},
            {"name": "사과", "price": 3000},  # duplicate of first
        ]
        result = deduplicate(items, key_fields=["name", "price"])
        assert len(result) == 3  # first 사과 + 2 unique None items
```

---

## 5. Schema Enforcement

**Audit Refs**: Pipeline Audit §2  
**Severity**: 🟠 HIGH  
**File**: `packages/crawler-admin/backend/pipeline/validator.py`

### Problem

`validate_items()` only checks field *presence* (`not item.get(f)`), not field *type*. A malformed item like `{"name": 123, "price": "not-a-number"}` passes validation but causes downstream failures.

### Before (lines 10–23)

```python
def validate_items(
    items: list[dict[str, Any]],
    required_fields: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """필수 필드 존재 확인. (valid, invalid) 튜플 반환."""
    valid, invalid = [], []
    for item in items:
        missing = [f for f in required_fields if not item.get(f)]
        if missing:
            item["_validation_error"] = f"missing fields: {missing}"
            invalid.append(item)
        else:
            valid.append(item)
    return valid, invalid
```

### After

```python
# Expected types per field. Fields not listed here skip type checking.
FIELD_TYPE_RULES: dict[str, tuple[type, ...]] = {
    "name": (str,),
    "title": (str,),
    "url": (str,),
    "source_url": (str,),
    "detail_url": (str,),
    "store": (str,),
    "price": (int, float, str, type(None)),
    "original_price": (int, float, str, type(None)),
    "sale_price": (int, float, str, type(None)),
    "discount_percent": (int, float, type(None)),
}


def validate_items(
    items: list[dict[str, Any]],
    required_fields: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """필수 필드 존재 및 타입 확인. (valid, invalid) 튜플 반환."""
    valid, invalid = [], []
    for item in items:
        errors: list[str] = []

        # 1. Required field presence
        missing = [f for f in required_fields if not item.get(f)]
        if missing:
            errors.append(f"missing fields: {missing}")

        # 2. Type validation for known fields
        for field, expected_types in FIELD_TYPE_RULES.items():
            val = item.get(field)
            if val is not None and field in item and not isinstance(val, expected_types):
                errors.append(
                    f"field '{field}': expected {expected_types}, got {type(val).__name__}"
                )

        if errors:
            item["_validation_error"] = "; ".join(errors)
            invalid.append(item)
        else:
            valid.append(item)
    return valid, invalid
```

### Test Cases

```python
# Add to: packages/crawler-admin/backend/tests/test_pipeline.py  (TestValidateItems class)

    def test_wrong_type_name_rejected(self):
        """name field must be str; integer name should be rejected."""
        items = [{"name": 12345, "price": 3000}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "expected" in invalid[0]["_validation_error"]

    def test_string_price_accepted(self):
        """Price as string is allowed (normalize_prices handles it later)."""
        items = [{"name": "사과", "price": "12,500원"}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 1

    def test_list_price_rejected(self):
        """Price as list should be rejected."""
        items = [{"name": "사과", "price": [1, 2, 3]}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(invalid) == 1

    def test_extra_fields_no_type_check(self):
        """Fields not in FIELD_TYPE_RULES should not be type-checked."""
        items = [{"name": "사과", "price": 3000, "custom_data": {"nested": True}}]
        valid, invalid = validate_items(items, ["name", "price"])
        assert len(valid) == 1
```

---

## 6. Frontend SSE Race Condition

**Audit Refs**: Pipeline Audit §6, §7  
**Severity**: 🔴 CRITICAL + 🟠 HIGH  
**Files**:
- `packages/crawler-admin/frontend/src/api/client.js`
- `packages/crawler-admin/frontend/src/pages/Crawlers/Crawlers.jsx`

### Problem A: SSE `subscribeCrawlerStatus` — No Reconnection

`eventSource.onerror` immediately closes and calls `onError`. Any transient network blip permanently kills the status feed.

### Before (`client.js` lines 36–59)

```javascript
function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
  const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (event) => {
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
    onError?.(new Error('SSE connection failed'));
  };

  return { close: () => eventSource.close() };
}
```

### After

```javascript
/**
 * SSE 연결 헬퍼 — 크롤러 실행 상태를 실시간 수신.
 * 네트워크 끊김 시 지수 백오프로 자동 재연결 (최대 5회).
 * @returns {{ close: () => void }} 연결 해제 핸들
 */
function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
  const MAX_RETRIES = 5;
  let retries = 0;
  let currentEs = null;
  let closed = false;

  function connect() {
    if (closed) return;

    const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
    const eventSource = new EventSource(url);
    currentEs = eventSource;

    eventSource.onmessage = (event) => {
      retries = 0; // reset on successful message
      try {
        const data = JSON.parse(event.data);
        onData?.(data);
        if (data.status === 'success' || data.status === 'failed') {
          closed = true;
          eventSource.close();
          onComplete?.(data);
        }
      } catch (e) {
        onError?.(e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      if (closed) return;
      if (retries < MAX_RETRIES) {
        retries++;
        const delay = Math.min(1000 * 2 ** retries, 10000);
        setTimeout(connect, delay);
      } else {
        onError?.(new Error('SSE 연결이 재시도 후에도 실패했습니다'));
      }
    };
  }

  connect();

  return {
    close: () => {
      closed = true;
      currentEs?.close();
    },
  };
}
```

### Problem B: Crawlers.jsx — SSE Connection Race Condition

When a user clicks "run" on an already-running crawler, `startPolling` overwrites `pollRefs.current[id]` before the `onComplete` callback of the old SSE fires. The old SSE connection becomes orphaned.

### Before (`Crawlers.jsx` lines 136–187 — `startPolling`)

The existing code does close the old ref at lines 139–144 before opening a new one. However, the race condition exists because:
1. There is no guard preventing re-run of an active crawler
2. Bulk run can trigger duplicate SSE connections for the same crawler

### After — Add run guard in `handleRun`

Locate the `handleRun` function in Crawlers.jsx and add a guard:

```javascript
  // Find the handleRun callback (typically around line 246-270)
  // Add guard at the top of handleRun:
  const handleRun = useCallback(async (id) => {
    // Prevent duplicate runs — ignore if crawler is already running
    if (runStates[id]?.phase === 'running') return;

    setRunState(id, { phase: 'running', success: true, message: '⏳ 크롤링 시작 중...' });
    try {
      await api.runCrawler(id);
      startPolling(id);
    } catch (err) {
      setRunState(id, {
        phase: 'done',
        success: false,
        message: `❌ 실행 실패: ${err.message || '알 수 없는 오류'}`,
      });
      clearRunState(id);
    }
  }, [runStates, setRunState, clearRunState, startPolling]);
```

Also fix `startPolling` to always fully close previous connections before starting a new one. The existing code already does this (lines 139–144), but add `delete pollRefs.current[id]` after cleanup:

```javascript
  const startPolling = useCallback((id) => {
    const startTime = Date.now();

    // Always fully close previous SSE/timer before opening new one
    const oldRef = pollRefs.current[id];
    if (oldRef) {
      if (typeof oldRef === 'object' && oldRef.close) oldRef.close();
      else if (typeof oldRef === 'number') clearTimeout(oldRef);
      delete pollRefs.current[id];
    }

    // ... rest of SSE connection setup unchanged ...
```

### Problem C: Silent Polling Errors

The polling fallback catches errors with `catch { /* 폴링 실패 무시 */ }`. Network failures are invisible.

### After — Track consecutive failures

```javascript
  const startPollingFallback = useCallback((id, startTime) => {
    let pollCount = 0;
    let currentInterval = POLL_INTERVAL_BASE;
    let consecutiveFailures = 0;

    const poll = async () => {
      pollCount++;
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
      try {
        const data = await api.getCrawlerStatus(id);
        consecutiveFailures = 0; // reset on success
        if (data.status === 'success') {
          // ... existing success handling ...
          return;
        } else if (data.status === 'failed') {
          // ... existing failure handling ...
          return;
        }
      } catch {
        consecutiveFailures++;
        if (consecutiveFailures >= 3) {
          setRunState(id, {
            phase: 'running',
            success: false,
            message: `⚠️ 상태 확인 연결 불안정 (${consecutiveFailures}회 실패)`,
          });
        }
      }

      // ... rest of polling logic unchanged ...
    };

    pollRefs.current[id] = setTimeout(poll, currentInterval);
  }, [setRunState, clearRunState, fetchCrawlers]);
```

### Test Cases

```javascript
// File: packages/crawler-admin/frontend/src/test/client.test.js

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock EventSource for SSE tests
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.readyState = 0; // CONNECTING
    MockEventSource.instances.push(this);
  }
  close() { this.readyState = 2; }
  static instances = [];
  static reset() { MockEventSource.instances = []; }
}

describe('subscribeCrawlerStatus', () => {
  beforeEach(() => {
    MockEventSource.reset();
    globalThis.EventSource = MockEventSource;
  });

  afterEach(() => {
    delete globalThis.EventSource;
  });

  it('should close handle stop reconnections', () => {
    // Test that calling close() prevents further reconnection attempts
    const { api } = require('../api/client');
    const handle = api.subscribeCrawlerStatus('test-id', {
      onData: vi.fn(),
      onError: vi.fn(),
    });

    handle.close();
    const es = MockEventSource.instances[0];
    expect(es.readyState).toBe(2); // CLOSED
  });
});
```

---

## 7. Error Boundary

**Audit Refs**: General best practice, no existing error boundary  
**Severity**: 🟠 HIGH  
**Files**:
- `packages/crawler-admin/frontend/src/components/ErrorBoundary.jsx` (new)
- `packages/crawler-admin/frontend/src/App.jsx` (modified)

### Problem

No React error boundary exists. An unhandled exception in any page component crashes the entire app with a blank screen.

### New File: `packages/crawler-admin/frontend/src/components/ErrorBoundary.jsx`

```jsx
import { Component } from 'react';

/**
 * Top-level error boundary — catches render errors in child components
 * and shows a recoverable fallback UI instead of a blank screen.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary]', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '200px', padding: '2rem',
          color: '#64748b',
        }}>
          <h2 style={{ marginBottom: '0.5rem', color: '#ef4444' }}>
            오류가 발생했습니다
          </h2>
          <p style={{ marginBottom: '1rem', textAlign: 'center' }}>
            페이지를 표시하는 중 문제가 발생했습니다.
          </p>
          <button
            onClick={this.handleReset}
            style={{
              padding: '0.5rem 1.5rem', borderRadius: '6px',
              border: '1px solid #e2e8f0', background: '#fff',
              cursor: 'pointer', fontSize: '0.875rem',
            }}
          >
            다시 시도
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
```

### Modified: `packages/crawler-admin/frontend/src/App.jsx`

```jsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import AdminLayout from './components/AdminLayout';
import Dashboard from './pages/Dashboard/Dashboard';
import Crawlers from './pages/Crawlers/Crawlers';
import Plugins from './pages/Plugins/Plugins';
import Logs from './pages/Logs/Logs';
import Schedule from './pages/Schedule/Schedule';
import DataReviewPage from './pages/DataReview/DataReviewPage';

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <Routes>
          <Route element={<AdminLayout />}>
            <Route path="/" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
            <Route path="/crawlers" element={<ErrorBoundary><Crawlers /></ErrorBoundary>} />
            <Route path="/data-review" element={<ErrorBoundary><DataReviewPage /></ErrorBoundary>} />
            <Route path="/plugins" element={<ErrorBoundary><Plugins /></ErrorBoundary>} />
            <Route path="/logs" element={<ErrorBoundary><Logs /></ErrorBoundary>} />
            <Route path="/schedule" element={<ErrorBoundary><Schedule /></ErrorBoundary>} />
          </Route>
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
```

**Design notes**:
- Outer `<ErrorBoundary>` catches layout-level crashes (sidebar, routing).
- Per-route `<ErrorBoundary>` isolates page crashes — sidebar navigation remains functional so the user can navigate away.

### Test Cases

```javascript
// File: packages/crawler-admin/frontend/src/test/ErrorBoundary.test.jsx

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ErrorBoundary from '../components/ErrorBoundary';

function BrokenComponent() {
  throw new Error('test crash');
}

function WorkingComponent() {
  return <div>정상 컴포넌트</div>;
}

describe('ErrorBoundary', () => {
  it('renders children when no error', () => {
    render(
      <ErrorBoundary>
        <WorkingComponent />
      </ErrorBoundary>
    );
    expect(screen.getByText('정상 컴포넌트')).toBeTruthy();
  });

  it('renders fallback on error', () => {
    // Suppress console.error for expected error
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <BrokenComponent />
      </ErrorBoundary>
    );
    expect(screen.getByText('오류가 발생했습니다')).toBeTruthy();
    spy.mockRestore();
  });

  it('recovers on retry click', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    let shouldThrow = true;
    function MaybeThrow() {
      if (shouldThrow) throw new Error('boom');
      return <div>복구됨</div>;
    }
    render(
      <ErrorBoundary>
        <MaybeThrow />
      </ErrorBoundary>
    );
    expect(screen.getByText('오류가 발생했습니다')).toBeTruthy();

    shouldThrow = false;
    fireEvent.click(screen.getByText('다시 시도'));
    expect(screen.getByText('복구됨')).toBeTruthy();
    spy.mockRestore();
  });
});
```

---

## 8. Structured Logging

**Audit Refs**: DS-R1, general audit  
**Severity**: 🟡 MEDIUM  
**File**: `packages/crawler-admin/backend/pipeline/pipeline.py`, all backend modules using `logging`

### Problem

Application logging uses bare `logger.info(f"...")` string formatting. Audit logging (`audit.py`) is properly structured JSON, but pipeline/engine/API logs are unstructured text. This makes log aggregation, querying, and alerting difficult.

### Implementation

Add a JSON log formatter configured at startup. This approach requires **no changes to individual log call sites** — only the formatter changes.

#### New File: `packages/crawler-admin/backend/logging_config.py`

```python
"""Structured JSON logging configuration.

Call ``setup_logging()`` once during FastAPI startup to switch all
application loggers from plain text to JSON-formatted output.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Forward extra fields if attached via `logger.info("msg", extra={...})`
        for key in ("crawler_name", "items_found", "items_saved",
                     "duration", "status", "error_type", "correlation_id"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val

        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(
    level: str = "INFO",
    log_dir: str | Path | None = None,
    max_bytes: int = 20 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Configure root logger with JSON formatting.

    - Console handler (stderr): always added.
    - File handler (``logs/app.jsonl``): added when *log_dir* is provided
      or defaults to ``<backend>/logs/``.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)

    # Remove any pre-existing handlers (avoid duplicate output on reload)
    for h in root.handlers[:]:
        root.removeHandler(h)

    formatter = JSONFormatter()

    # Console
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(log_level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_dir / "app.jsonl",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Don't propagate audit logger records to root (already handled by audit.py)
    logging.getLogger("audit").propagate = False
```

#### Integration Point: `packages/crawler-admin/backend/api/app.py`

Add at the top of the FastAPI app startup, before any routes are registered:

```python
# At the top of app.py, after imports:
from logging_config import setup_logging

# In the startup event or at module level:
setup_logging(level=os.getenv("LOG_LEVEL", "INFO"))
```

#### Enhanced Pipeline Log Calls (optional enrichment)

Existing `logger.info(f"...")` calls continue to work unchanged. For key events, add structured extra data:

```python
# pipeline.py — replace the existing logger.info at line 206-210 with:

        logger.info(
            "[Pipeline] %s: found=%d valid=%d saved=%d duration=%.2fs",
            crawler_name, items_found, items_valid, items_saved, duration,
            extra={
                "crawler_name": crawler_name,
                "items_found": items_found,
                "items_saved": items_saved,
                "duration": round(duration, 2),
                "status": final_status,
            },
        )
```

### Example Output

```json
{"timestamp":"2025-07-15T14:32:01+00:00","level":"INFO","logger":"pipeline.pipeline","message":"[Pipeline] emart: found=45 valid=42 saved=42 duration=12.34s","module":"pipeline","function":"run_crawler","line":210,"crawler_name":"emart","items_found":45,"items_saved":42,"duration":12.34,"status":"success"}
```

### Test Cases

```python
# File: packages/crawler-admin/backend/tests/test_logging_config.py

import json
import logging
import pytest
from logging_config import JSONFormatter


class TestJSONFormatter:
    def test_basic_format(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello %s", args=("world",), exc_info=None,
        )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["message"] == "hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "test"
        assert "timestamp" in data

    def test_exception_included(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=1, msg="fail", args=(), exc_info=sys.exc_info(),
            )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["exception"]["type"] == "ValueError"
        assert "test error" in data["exception"]["message"]

    def test_extra_fields_forwarded(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="crawl done", args=(), exc_info=None,
        )
        record.crawler_name = "emart"
        record.items_found = 45
        line = formatter.format(record)
        data = json.loads(line)
        assert data["crawler_name"] == "emart"
        assert data["items_found"] == 45

    def test_output_is_valid_json(self):
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.한글", level=logging.WARNING, pathname="test.py",
            lineno=1, msg="한글 메시지", args=(), exc_info=None,
        )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["message"] == "한글 메시지"
```

---

## Change Summary

| # | Fix | Files Changed | Files Created | Severity |
|---|-----|---------------|---------------|----------|
| 1 | Pipeline store failure status | `pipeline/pipeline.py` | `tests/test_pipeline_store_failure.py` | 🔴 Critical |
| 2 | Dead letter queue | `pipeline/pipeline.py` | `pipeline/dead_letter.py`, `tests/test_dead_letter.py` | 🔴 Critical |
| 3 | Circuit breaker | `api/routes/ingestion.py` | `pipeline/circuit_breaker.py`, `tests/test_circuit_breaker.py` | 🟠 High |
| 4 | Dedup None fix | `pipeline/validator.py` | (add to `tests/test_pipeline.py`) | 🟠 High |
| 5 | Schema enforcement | `pipeline/validator.py` | (add to `tests/test_pipeline.py`) | 🟠 High |
| 6 | SSE race condition | `frontend/src/api/client.js`, `frontend/src/pages/Crawlers/Crawlers.jsx` | `frontend/src/test/client.test.js` | 🔴 Critical |
| 7 | Error boundary | `frontend/src/App.jsx` | `frontend/src/components/ErrorBoundary.jsx`, `frontend/src/test/ErrorBoundary.test.jsx` | 🟠 High |
| 8 | Structured logging | `api/app.py` (1-line import), `pipeline/pipeline.py` (optional) | `logging_config.py`, `tests/test_logging_config.py` | 🟡 Medium |

### Execution Order

```
P0 (do first — data loss risk):
  1. Pipeline store failure status propagation
  2. Dead letter queue
  3. SSE reconnection

P1 (do next — correctness):
  4. Dedup None fix
  5. Schema enforcement
  6. Circuit breaker
  7. Error boundary

P2 (do last — observability):
  8. Structured logging
```

### File Tree (new/modified)

```
packages/crawler-admin/
├── backend/
│   ├── logging_config.py                           NEW
│   ├── pipeline/
│   │   ├── pipeline.py                             MODIFIED (§1, §2)
│   │   ├── validator.py                            MODIFIED (§4, §5)
│   │   ├── dead_letter.py                          NEW (§2)
│   │   └── circuit_breaker.py                      NEW (§3)
│   ├── api/
│   │   ├── app.py                                  MODIFIED (§8 — 1 line)
│   │   └── routes/
│   │       └── ingestion.py                        MODIFIED (§3)
│   └── tests/
│       ├── test_pipeline.py                        MODIFIED (§4, §5 — add cases)
│       ├── test_pipeline_store_failure.py           NEW (§1)
│       ├── test_dead_letter.py                      NEW (§2)
│       ├── test_circuit_breaker.py                  NEW (§3)
│       └── test_logging_config.py                   NEW (§8)
├── frontend/
│   └── src/
│       ├── App.jsx                                  MODIFIED (§7)
│       ├── api/
│       │   └── client.js                            MODIFIED (§6)
│       ├── components/
│       │   └── ErrorBoundary.jsx                    NEW (§7)
│       ├── pages/
│       │   └── Crawlers/
│       │       └── Crawlers.jsx                     MODIFIED (§6)
│       └── test/
│           ├── client.test.js                       NEW (§6)
│           └── ErrorBoundary.test.jsx               NEW (§7)
```
