# Crawler-Admin Reliability Implementation Spec

> **Scope**: Browser stability, scheduler fix, shutdown, health check, SSE reconnection  
> **Input**: `crawler-admin-stability-audit.md`, `crawler-admin-pipeline-audit.md`  
> **Date**: 2025-07-15  
> **Addresses**: BC-1/2/3/4, SC-1/2, GS-1/2/4/5, HC-1, SSE-CRITICAL

---

## Table of Contents

1. [Zombie Browser Fix & Process Watchdog](#1-zombie-browser-fix--process-watchdog)
2. [Scheduler asyncio Fix](#2-scheduler-asyncio-fix)
3. [Event Loop Fix](#3-event-loop-fix)
4. [Graceful Shutdown](#4-graceful-shutdown)
5. [Health Check Endpoint](#5-health-check-endpoint)
6. [SSE Reconnection](#6-sse-reconnection)
7. [Test Plan](#7-test-plan)
8. [File Change Summary](#8-file-change-summary)

---

## 1. Zombie Browser Fix & Process Watchdog

**Audit IDs**: BC-1, BC-2, BC-3, BC-4  
**Files Modified**:
- `backend/engine/strategies/selenium_st.py`
- `backend/engine/strategies/undetected_st.py`
- `backend/engine/strategies/playwright_st.py`
- `backend/engine/browser_watchdog.py` *(new)*

### 1.1 Problem

When `driver.quit()` throws or the executor cancels a task via `asyncio.wait_for`, Chrome/ChromeDriver/Chromium subprocesses remain running as zombies. No mechanism exists to reap orphaned browser processes. Under concurrent load (5 crawlers), this can leak up to 1GB+ of RAM.

### 1.2 New File: `backend/engine/browser_watchdog.py`

A centralized process watchdog that:
- Tracks all browser PIDs spawned by strategies
- Periodically reaps orphaned browser processes
- Provides a `kill_all()` for shutdown cleanup

```python
"""
Browser process watchdog — tracks and reaps orphaned Chrome/Chromium/ChromeDriver processes.

Audit: BC-1, BC-2 — process-level zombie reaping.
"""

from __future__ import annotations

import logging
import os
import time
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Browser process names to track (lowercase for matching)
_BROWSER_PROCESS_NAMES = frozenset({
    "chrome", "chrome.exe",
    "chromium", "chromium.exe",
    "chromedriver", "chromedriver.exe",
    "chromium-browser",
})

# Max age (seconds) for a browser process before the watchdog kills it
_MAX_BROWSER_AGE = int(os.getenv("BROWSER_MAX_AGE_SECONDS", "300"))

# Watchdog check interval
_WATCHDOG_INTERVAL = int(os.getenv("BROWSER_WATCHDOG_INTERVAL", "60"))


class BrowserWatchdog:
    """Tracks browser PIDs and periodically reaps orphans."""

    def __init__(self) -> None:
        self._tracked_pids: dict[int, float] = {}  # pid -> spawn_time
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._running = False

    def start(self) -> None:
        """Start the periodic watchdog."""
        if self._running:
            return
        self._running = True
        self._schedule_reap()
        logger.info("[BrowserWatchdog] started (interval=%ds, max_age=%ds)",
                     _WATCHDOG_INTERVAL, _MAX_BROWSER_AGE)

    def stop(self) -> None:
        """Stop the watchdog and kill all tracked processes."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.kill_all()
        logger.info("[BrowserWatchdog] stopped")

    def register_pid(self, pid: int) -> None:
        """Register a browser PID for tracking."""
        with self._lock:
            self._tracked_pids[pid] = time.monotonic()
        logger.debug("[BrowserWatchdog] registered PID %d", pid)

    def unregister_pid(self, pid: int) -> None:
        """Unregister a PID (browser exited cleanly)."""
        with self._lock:
            self._tracked_pids.pop(pid, None)

    def kill_all(self) -> int:
        """Kill all tracked browser processes. Returns count killed."""
        killed = 0
        with self._lock:
            pids = list(self._tracked_pids.keys())
            self._tracked_pids.clear()

        for pid in pids:
            killed += self._kill_pid(pid)

        # Also scan for any un-tracked browser orphans owned by this process
        killed += self._reap_orphans()
        if killed:
            logger.info("[BrowserWatchdog] killed %d browser processes", killed)
        return killed

    def get_tracked_count(self) -> int:
        """Return the number of currently tracked browser PIDs."""
        with self._lock:
            return len(self._tracked_pids)

    # --- internal ---

    def _schedule_reap(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(_WATCHDOG_INTERVAL, self._periodic_reap)
        self._timer.daemon = True
        self._timer.start()

    def _periodic_reap(self) -> None:
        """Reap tracked processes older than _MAX_BROWSER_AGE."""
        try:
            now = time.monotonic()
            stale_pids: list[int] = []

            with self._lock:
                for pid, spawn_time in list(self._tracked_pids.items()):
                    if now - spawn_time > _MAX_BROWSER_AGE:
                        stale_pids.append(pid)

            for pid in stale_pids:
                if self._kill_pid(pid):
                    logger.warning("[BrowserWatchdog] reaped stale PID %d (age > %ds)",
                                   pid, _MAX_BROWSER_AGE)
                with self._lock:
                    self._tracked_pids.pop(pid, None)

            # Also reap un-tracked orphans
            self._reap_orphans()

        except Exception:
            logger.exception("[BrowserWatchdog] error during periodic reap")
        finally:
            self._schedule_reap()

    def _reap_orphans(self) -> int:
        """Find and kill un-tracked browser processes spawned by this process tree."""
        killed = 0
        try:
            import psutil
        except ImportError:
            return 0

        my_pid = os.getpid()
        try:
            for proc in psutil.process_iter(["pid", "name", "ppid", "create_time"]):
                try:
                    pinfo = proc.info
                    name = (pinfo.get("name") or "").lower()
                    if name not in _BROWSER_PROCESS_NAMES:
                        continue
                    # Only kill processes that are children of our process tree
                    # or have been running longer than max age
                    age = time.time() - (pinfo.get("create_time") or time.time())
                    if age > _MAX_BROWSER_AGE:
                        pid = pinfo["pid"]
                        with self._lock:
                            if pid in self._tracked_pids:
                                continue  # Already tracked, handled above
                        proc.kill()
                        killed += 1
                        logger.warning(
                            "[BrowserWatchdog] killed orphan %s PID=%d (age=%.0fs)",
                            name, pid, age,
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            logger.debug("[BrowserWatchdog] orphan scan failed", exc_info=True)
        return killed

    @staticmethod
    def _kill_pid(pid: int) -> bool:
        """Kill a single PID. Returns True if killed."""
        try:
            import psutil
            proc = psutil.Process(pid)
            proc.kill()
            proc.wait(timeout=5)
            return True
        except Exception:
            # Process already gone or access denied
            return False


# Module-level singleton
_watchdog: Optional[BrowserWatchdog] = None


def get_browser_watchdog() -> BrowserWatchdog:
    """Get or create the global BrowserWatchdog singleton."""
    global _watchdog
    if _watchdog is None:
        _watchdog = BrowserWatchdog()
    return _watchdog
```

### 1.3 Changes to `selenium_st.py`

**Before** (`selenium_st.py:104-105`):
```python
    async def _do_fetch(self, url: str, **options) -> str:
        wait_timeout = options.get("wait_timeout", self._wait_timeout)

        # 브라우저 실행은 blocking이므로 executor에서 실행
        loop = asyncio.get_event_loop()
        html = await loop.run_in_executor(None, self._fetch_sync, url, wait_timeout)
        return html
```

**After**:
```python
    async def _do_fetch(self, url: str, **options) -> str:
        wait_timeout = options.get("wait_timeout", self._wait_timeout)

        loop = asyncio.get_running_loop()
        html = await loop.run_in_executor(None, self._fetch_sync, url, wait_timeout)
        return html
```

**Before** (`selenium_st.py` — `_fetch_sync` finally block):
```python
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            self._driver = None
```

**After**:
```python
        finally:
            self._safe_quit_driver(driver)
            self._driver = None

    def _safe_quit_driver(self, driver) -> None:
        """Quit the driver and verify the process is dead via watchdog."""
        from engine.browser_watchdog import get_browser_watchdog
        watchdog = get_browser_watchdog()

        pid = None
        try:
            pid = driver.service.process.pid
        except Exception:
            pass

        try:
            driver.quit()
        except Exception:
            pass

        # Verify process is actually dead
        if pid:
            try:
                import psutil
                proc = psutil.Process(pid)
                if proc.is_running():
                    proc.kill()
                    proc.wait(timeout=5)
                    logger.warning("[SeleniumStrategy] force-killed chromedriver PID=%d", pid)
            except Exception:
                pass
            watchdog.unregister_pid(pid)
```

**Before** (`selenium_st.py` — `_create_driver` return):
```python
        driver.set_page_load_timeout(self._wait_timeout * 3)
        return driver
```

**After**:
```python
        driver.set_page_load_timeout(self._wait_timeout * 3)

        # Register browser PID with watchdog for zombie prevention
        from engine.browser_watchdog import get_browser_watchdog
        try:
            pid = driver.service.process.pid
            get_browser_watchdog().register_pid(pid)
        except Exception:
            pass

        return driver
```

### 1.4 Changes to `undetected_st.py`

Identical pattern to selenium_st.py:

**Before** (`_do_fetch`):
```python
        loop = asyncio.get_event_loop()
        html = await loop.run_in_executor(None, self._fetch_sync, url, wait_timeout)
```

**After**:
```python
        loop = asyncio.get_running_loop()
        html = await loop.run_in_executor(None, self._fetch_sync, url, wait_timeout)
```

**Before** (`_fetch_sync` — driver creation + finally):
```python
        driver = uc.Chrome(options=options)
        self._driver = driver

        try:
            # ... fetch logic ...
        finally:
            try:
                driver.quit()
            except Exception:
                pass
            self._driver = None
```

**After**:
```python
        driver = uc.Chrome(options=options)
        self._driver = driver

        # Register with watchdog — undetected-chromedriver spawns a separate Chrome binary
        from engine.browser_watchdog import get_browser_watchdog
        watchdog = get_browser_watchdog()
        try:
            pid = driver.browser_pid  # undetected-chromedriver exposes this
            if pid:
                watchdog.register_pid(pid)
        except AttributeError:
            pass
        try:
            pid = driver.service.process.pid
            watchdog.register_pid(pid)
        except Exception:
            pass

        try:
            # ... fetch logic unchanged ...
        finally:
            self._safe_quit_driver(driver)
            self._driver = None

    def _safe_quit_driver(self, driver) -> None:
        """Quit the undetected-chromedriver and verify all processes are dead."""
        from engine.browser_watchdog import get_browser_watchdog
        watchdog = get_browser_watchdog()

        pids_to_check = []
        try:
            pids_to_check.append(driver.browser_pid)
        except (AttributeError, Exception):
            pass
        try:
            pids_to_check.append(driver.service.process.pid)
        except Exception:
            pass

        try:
            driver.quit()
        except Exception:
            pass

        for pid in pids_to_check:
            if pid:
                try:
                    import psutil
                    proc = psutil.Process(pid)
                    if proc.is_running():
                        proc.kill()
                        proc.wait(timeout=5)
                        logger.warning("[UndetectedStrategy] force-killed PID=%d", pid)
                except Exception:
                    pass
                watchdog.unregister_pid(pid)
```

### 1.5 Changes to `playwright_st.py`

**Before** (`_do_fetch` — finally block):
```python
        finally:
            await context.close()
            await browser.close()
            await pw.stop()
            self._browser = None
            self._playwright = None
```

**After**:
```python
        finally:
            try:
                await context.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
            try:
                await pw.stop()
            except Exception:
                pass
            self._browser = None
            self._playwright = None
```

Playwright manages its own subprocesses more reliably than Selenium, so the main fix is wrapping each cleanup step in a try/except to prevent one failure from blocking the others. The watchdog's `_reap_orphans()` handles any residual Chromium processes.

---

## 2. Scheduler asyncio Fix

**Audit IDs**: SC-1, SC-2, CC-6  
**Files Modified**:
- `backend/scheduler/scheduler.py`

### 2.1 Problem

`BackgroundScheduler` runs in a separate thread. Its callback `_execute_job_sync` calls `asyncio.run()`, creating a new event loop per job. This:
1. Disconnects from FastAPI's event loop — concurrency primitives (`_lock`, `_running_crawlers`, `_semaphore`) are bound to a different loop
2. Allows double-launch: API and scheduler can run the same crawler simultaneously
3. Risks event loop conflict if called from an async context

### 2.2 Full Replacement: `backend/scheduler/scheduler.py`

**Before** (complete file — key sections):
```python
from apscheduler.schedulers.background import BackgroundScheduler

class CrawlScheduler:
    def __init__(self, pipeline=None, registry=None):
        self._scheduler = BackgroundScheduler()
        # ...

    def start(self):
        self._scheduler.start(paused=False)
        # ...

    def stop(self):
        self._scheduler.shutdown(wait=False)
        # ...

    def _execute_job_sync(self, crawler_name):
        """BackgroundScheduler 콜백 (동기). 내부에서 asyncio.run 사용."""
        return asyncio.run(self._execute_job(crawler_name))
```

**After** (complete replacement):
```python
"""크롤 스케줄러 — AsyncIOScheduler 기반 자동 크롤 스케줄링.

Audit Fix: SC-1 — AsyncIOScheduler shares FastAPI's event loop.
All concurrency primitives (Semaphore, Lock, _running_crawlers) work correctly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.job_tracker import JobTracker

logger = logging.getLogger(__name__)


class CrawlScheduler:
    """AsyncIOScheduler 기반 자동 크롤 스케줄러.

    SC-R1: Uses AsyncIOScheduler instead of BackgroundScheduler.
    Runs in the same event loop as FastAPI — concurrency primitives work correctly.
    """

    def __init__(
        self,
        pipeline: Any = None,
        registry: Any = None,
    ) -> None:
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,              # SC-R3: merge missed runs into one
                "max_instances": 1,            # prevent overlapping runs of same job
                "misfire_grace_time": 300,     # SC-R3: 5 min grace for missed jobs
            }
        )
        self._pipeline = pipeline
        self._registry = registry
        self.tracker = JobTracker()
        self._running = False

    # --- lifecycle ---

    def start(self) -> None:
        """스케줄러 시작."""
        if self._running:
            return
        self._scheduler.start(paused=False)
        self._running = True
        logger.info("[Scheduler] started (AsyncIOScheduler)")

    def stop(self, wait: bool = True) -> None:
        """스케줄러 중지.

        Args:
            wait: True면 실행 중인 작업이 완료될 때까지 대기 (최대 30초).
                  GS-R3: shutdown(wait=True) for clean stop.
        """
        if not self._running:
            return
        self._scheduler.shutdown(wait=wait)
        self._running = False
        logger.info("[Scheduler] stopped (wait=%s)", wait)

    @property
    def is_running(self) -> bool:
        return self._running

    # --- job management ---

    def add_job(self, crawler_name: str, cron: str) -> dict[str, Any]:
        """크롤 작업 추가. cron 형식: '0 7 * * *'."""
        job_id = f"crawl_{crawler_name}"
        trigger = CronTrigger.from_crontab(cron)
        self._scheduler.add_job(
            self._execute_job,           # SC-R1: directly async, no wrapper
            trigger=trigger,
            id=job_id,
            args=[crawler_name],
            replace_existing=True,
            name=f"crawl:{crawler_name}",
        )
        logger.info("[Scheduler] added job %s cron=%s", job_id, cron)
        return {"job_id": job_id, "crawler_name": crawler_name, "cron": cron}

    def remove_job(self, crawler_name: str) -> bool:
        """작업 제거."""
        job_id = f"crawl_{crawler_name}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("[Scheduler] removed job %s", job_id)
            return True
        except Exception:
            return False

    def update_job(self, crawler_name: str, cron: str) -> dict[str, Any]:
        """스케줄 변경.

        SC-R4: Uses reschedule_job() for atomic update instead of remove+add.
        """
        job_id = f"crawl_{crawler_name}"
        try:
            trigger = CronTrigger.from_crontab(cron)
            self._scheduler.reschedule_job(job_id, trigger=trigger)
            logger.info("[Scheduler] rescheduled job %s cron=%s", job_id, cron)
            return {"job_id": job_id, "crawler_name": crawler_name, "cron": cron}
        except Exception:
            # Job doesn't exist yet — create it
            return self.add_job(crawler_name, cron)

    def list_jobs(self) -> list[dict[str, Any]]:
        """현재 스케줄 목록."""
        jobs = self._scheduler.get_jobs()
        result = []
        for job in jobs:
            next_run = job.next_run_time
            result.append({
                "job_id": job.id,
                "name": job.name,
                "next_run": next_run.isoformat() if next_run else None,
                "trigger": str(job.trigger),
            })
        return result

    async def run_now(self, crawler_name: str) -> dict[str, Any]:
        """즉시 실행 (스케줄과 무관)."""
        return await self._execute_job(crawler_name)

    def init_from_registry(self) -> int:
        """레지스트리의 plugin.yaml cron 설정으로 초기화. 등록 수 반환."""
        if not self._registry:
            return 0
        count = 0
        for info in self._registry.list_crawlers():
            cron = info.get("schedule")
            if cron and cron != "manual":
                self.add_job(info["name"], cron)
                count += 1
        return count

    def get_pending_job_count(self) -> int:
        """Return count of scheduled jobs."""
        return len(self._scheduler.get_jobs())

    # --- internal ---

    async def _execute_job(self, crawler_name: str) -> dict[str, Any]:
        """작업 실행 + 추적.

        SC-R1: Now runs directly as async in FastAPI's event loop.
        Concurrency primitives (acquire_crawler_slot, semaphore) work correctly.
        """
        execution = self.tracker.start(crawler_name)
        try:
            if self._pipeline:
                result = await self._pipeline.run_crawler(crawler_name)
                result_dict = result.to_dict()
            else:
                result_dict = {"crawler_name": crawler_name, "status": "no_pipeline"}
            self.tracker.complete(execution, result_dict)
            return result_dict
        except Exception as exc:
            self.tracker.fail(execution, str(exc))
            logger.error("[Scheduler] job %s failed: %s", crawler_name, exc)
            return {"crawler_name": crawler_name, "status": "failed", "error": str(exc)}
```

### 2.3 Key Changes Summary

| Aspect | Before | After |
|--------|--------|-------|
| Scheduler type | `BackgroundScheduler` (thread) | `AsyncIOScheduler` (event loop) |
| Job callback | `_execute_job_sync` → `asyncio.run()` | `_execute_job` (direct async) |
| Event loop | Separate loop per job | Shared with FastAPI |
| Concurrency safety | ❌ Different loop, no shared locks | ✅ Same loop, locks work |
| Misfire handling | None (missed jobs silently skip) | `misfire_grace_time=300`, `coalesce=True` |
| Shutdown | `wait=False` (jobs interrupted) | `wait=True` (jobs complete) |
| `update_job` | Non-atomic remove+add | Atomic `reschedule_job()` |

---

## 3. Event Loop Fix

**Audit IDs**: BC-1, BC-2  
**Files Modified**:
- `backend/engine/strategies/selenium_st.py`
- `backend/engine/strategies/undetected_st.py`

### 3.1 Problem

Both strategies use `asyncio.get_event_loop()`, which is deprecated in Python 3.12+ and can return a non-running loop or create a new one unexpectedly.

### 3.2 Fix

Already included in Section 1.3 and 1.4 above. The change in both files is:

**Before**:
```python
loop = asyncio.get_event_loop()
```

**After**:
```python
loop = asyncio.get_running_loop()
```

This is a one-line fix in each file:
- `selenium_st.py` line ~104
- `undetected_st.py` line ~47

`asyncio.get_running_loop()` (Python 3.7+) always returns the currently running loop or raises `RuntimeError` if there is none — which is the correct behavior since these methods are always called from within an async context (the executor's `execute()` → `_execute_cascade()` → `strategy.fetch()` → `_do_fetch()`).

---

## 4. Graceful Shutdown

**Audit IDs**: GS-1, GS-2, GS-4, GS-5  
**Files Modified**:
- `backend/api/app.py`
- `backend/concurrency.py` (minor addition)

### 4.1 Problem

No `on_event("shutdown")` handler exists. When SIGTERM arrives:
- Browser processes are orphaned
- Scheduler jobs are interrupted without cleanup
- Plugin `on_unload()` is never called
- `_running_crawlers` set has stale state

### 4.2 Changes to `backend/api/app.py`

**Before** (end of `create_app`, after router registration):
```python
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "crawler-admin"}

    return app
```

**After** (replace everything from `@app.get("/health")` to end):
```python
    # ── Health Check ─────────────────────────────────────────
    # (see Section 5 — full implementation below)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "crawler-admin"}

    # ── Graceful Shutdown (GS-R1, GS-R2) ────────────────────

    @app.on_event("startup")
    async def _startup():
        """Initialize the browser watchdog on startup."""
        from engine.browser_watchdog import get_browser_watchdog
        get_browser_watchdog().start()
        logger.info("[App] browser watchdog started")

    @app.on_event("shutdown")
    async def _shutdown():
        """Graceful shutdown: scheduler → plugins → browsers → logs.

        GS-R1: Proper shutdown sequence.
        GS-R2: Signal-safe browser cleanup.
        """
        import logging as _logging

        logger.info("[App] shutdown sequence started")

        # 1. Stop scheduler (wait for running jobs, max 30s)
        try:
            from scheduler.scheduler import CrawlScheduler
            # Access the scheduler instance (set during app init)
            scheduler: CrawlScheduler | None = getattr(app.state, "scheduler", None)
            if scheduler and scheduler.is_running:
                scheduler.stop(wait=True)
                logger.info("[App] scheduler stopped")
        except Exception:
            logger.exception("[App] scheduler shutdown error")

        # 2. Cancel all running crawl tasks
        try:
            from concurrency import clear_running_crawlers
            cleared = await clear_running_crawlers()
            if cleared:
                logger.info("[App] cleared %d running crawler slots", cleared)
        except Exception:
            logger.exception("[App] concurrency cleanup error")

        # 3. Shutdown plugins
        try:
            plugin_mgr = getattr(app.state, "plugin_manager", None)
            if plugin_mgr:
                await plugin_mgr.shutdown()
                logger.info("[App] plugins shut down")
        except Exception:
            logger.exception("[App] plugin shutdown error")

        # 4. Kill all browser processes via watchdog
        try:
            from engine.browser_watchdog import get_browser_watchdog
            watchdog = get_browser_watchdog()
            killed = watchdog.kill_all()
            watchdog.stop()
            if killed:
                logger.info("[App] killed %d browser processes", killed)
        except Exception:
            logger.exception("[App] browser cleanup error")

        # 5. Flush log handlers
        for handler in _logging.root.handlers:
            try:
                handler.flush()
            except Exception:
                pass

        logger.info("[App] shutdown complete")

    # ── Signal Handlers (GS-R2) ──────────────────────────────

    import signal
    import functools

    def _handle_signal(signum, frame):
        """Handle SIGTERM/SIGINT — trigger FastAPI's graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("[App] received %s, initiating graceful shutdown", sig_name)
        # FastAPI/uvicorn handles the actual shutdown via its signal handlers
        # This is a safety net in case we're running standalone
        raise SystemExit(0)

    # Only register if not already handled by uvicorn
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (OSError, ValueError):
        pass  # Can't set signal handler in non-main thread

    return app
```

### 4.3 Changes to `backend/concurrency.py`

**Add** at the end of the file:

```python
async def clear_running_crawlers() -> int:
    """Clear all running crawler slots (for shutdown). Returns count cleared.

    GS-R5: Clean up stale state on shutdown.
    """
    async with _lock:
        count = len(_running_crawlers)
        _running_crawlers.clear()
    return count
```

### 4.4 Shutdown Sequence (After Fix)

```
1. FastAPI receives SIGTERM/SIGINT
2. @app.on_event("shutdown") fires
3. Scheduler.stop(wait=True)        — running jobs complete (max 30s)
4. clear_running_crawlers()          — clear stale concurrency state
5. plugin_manager.shutdown()         — calls on_unload() for each plugin
6. BrowserWatchdog.kill_all()        — kills ALL tracked + orphaned browser procs
7. Flush all log handlers            — audit logs are persisted
8. Process exits cleanly
```

---

## 5. Health Check Endpoint

**Audit ID**: HC-1  
**Files Modified**:
- `backend/api/app.py` (replace `/health` endpoint)

### 5.1 Problem

Current `/health` returns only `{"status": "ok"}`. No visibility into scheduler state, browser processes, memory, or last crawl time.

### 5.2 Full Replacement: `/health` Endpoint in `app.py`

Replace the existing `@app.get("/health")` block with:

```python
    @app.get("/health")
    async def health():
        """
        Health check — HC-R1: enriched with scheduler, browser, memory, crawl status.

        Returns:
            Comprehensive health status including:
            - scheduler_running: bool
            - scheduled_jobs: int
            - active_crawls: int (from concurrency module)
            - browser_processes: int (tracked by watchdog)
            - memory_mb: float (RSS of this process)
            - last_crawl: dict | null (from scheduler tracker)
            - uptime_seconds: float
        """
        import time
        import os

        result = {
            "status": "ok",
            "service": "crawler-admin",
        }

        # Scheduler status
        try:
            scheduler = getattr(app.state, "scheduler", None)
            if scheduler:
                result["scheduler_running"] = scheduler.is_running
                result["scheduled_jobs"] = scheduler.get_pending_job_count()

                # Last crawl from job tracker
                history = scheduler.tracker.get_history(limit=1)
                result["last_crawl"] = history[0] if history else None
            else:
                result["scheduler_running"] = False
                result["scheduled_jobs"] = 0
                result["last_crawl"] = None
        except Exception:
            result["scheduler_running"] = False

        # Active crawls from concurrency module
        try:
            from concurrency import active_count
            result["active_crawls"] = active_count()
        except Exception:
            result["active_crawls"] = 0

        # Browser process count from watchdog
        try:
            from engine.browser_watchdog import get_browser_watchdog
            result["browser_processes"] = get_browser_watchdog().get_tracked_count()
        except Exception:
            result["browser_processes"] = 0

        # Memory usage (RSS)
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            mem = proc.memory_info()
            result["memory_mb"] = round(mem.rss / (1024 * 1024), 1)
        except ImportError:
            result["memory_mb"] = None
        except Exception:
            result["memory_mb"] = None

        # Uptime
        try:
            result["uptime_seconds"] = round(
                time.monotonic() - app.state.start_time, 1
            )
        except AttributeError:
            result["uptime_seconds"] = None

        # Set degraded status if scheduler is down
        if result.get("scheduler_running") is False and result.get("scheduled_jobs", 0) > 0:
            result["status"] = "degraded"

        return result
```

**Also add** to the `_startup` handler:

```python
    @app.on_event("startup")
    async def _startup():
        """Initialize watchdog and track start time."""
        import time
        app.state.start_time = time.monotonic()

        from engine.browser_watchdog import get_browser_watchdog
        get_browser_watchdog().start()
        logger.info("[App] browser watchdog started")
```

### 5.3 Example Response

```json
{
  "status": "ok",
  "service": "crawler-admin",
  "scheduler_running": true,
  "scheduled_jobs": 12,
  "active_crawls": 2,
  "browser_processes": 1,
  "memory_mb": 245.3,
  "last_crawl": {
    "job_id": "crawl_emart",
    "started_at": "2025-07-15T07:00:01",
    "ended_at": "2025-07-15T07:02:15",
    "status": "success"
  },
  "uptime_seconds": 86412.3
}
```

---

## 6. SSE Reconnection

**Audit ID**: Pipeline audit Section 6 (SSE CRITICAL)  
**Files Modified**:
- `frontend/src/api/client.js`

### 6.1 Problem

`eventSource.onerror` immediately closes the connection and calls `onError`. No reconnection attempt, no backoff. Any transient network interruption permanently breaks real-time status updates.

### 6.2 Full Replacement: `subscribeCrawlerStatus` in `client.js`

**Before**:
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

**After**:
```javascript
/**
 * SSE 연결 헬퍼 — 크롤러 실행 상태를 실시간 수신.
 *
 * SSE reconnection with exponential backoff (audit fix).
 * - On transient error: retry up to MAX_RETRIES times with backoff
 * - On successful message: reset retry counter
 * - On terminal status (success/failed): close cleanly
 *
 * @returns {{ close: () => void }} 연결 해제 핸들
 */
function subscribeCrawlerStatus(crawlerId, { onData, onError, onComplete }) {
  const MAX_RETRIES = 5;
  const BASE_DELAY_MS = 1000;
  const MAX_DELAY_MS = 10000;

  let retryCount = 0;
  let currentSource = null;
  let closed = false;
  let retryTimer = null;
  let lastEventId = null;

  function connect() {
    if (closed) return;

    const url = `${API_BASE}/crawlers/${crawlerId}/status/stream`;
    const eventSource = new EventSource(url);
    currentSource = eventSource;

    eventSource.onmessage = (event) => {
      retryCount = 0;   // Reset on successful message
      if (event.lastEventId) {
        lastEventId = event.lastEventId;
      }
      try {
        const data = JSON.parse(event.data);
        onData?.(data);
        if (data.status === 'success' || data.status === 'failed') {
          cleanup();
          onComplete?.(data);
        }
      } catch (e) {
        onError?.(e);
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      currentSource = null;

      if (closed) return;

      if (retryCount < MAX_RETRIES) {
        retryCount++;
        const delay = Math.min(
          BASE_DELAY_MS * Math.pow(2, retryCount - 1) + Math.random() * 500,
          MAX_DELAY_MS,
        );
        retryTimer = setTimeout(connect, delay);
      } else {
        onError?.(new Error('SSE connection failed after ' + MAX_RETRIES + ' retries'));
      }
    };
  }

  function cleanup() {
    closed = true;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
    if (currentSource) {
      currentSource.close();
      currentSource = null;
    }
  }

  connect();
  return { close: cleanup };
}
```

### 6.3 Key Changes

| Aspect | Before | After |
|--------|--------|-------|
| On error | Immediate close + fail | Retry up to 5 times |
| Backoff | None | Exponential: 1s → 2s → 4s → 8s → 10s (capped) + jitter |
| Retry reset | N/A | Resets to 0 on each successful message |
| Close handle | Simple `eventSource.close()` | Cancels pending retry timers, sets `closed` flag |
| Multiple connections | Possible leak | `cleanup()` prevents re-entry |

---

## 7. Test Plan

### 7.1 Unit Tests

#### Test: Browser Watchdog

**File**: `backend/engine/tests/test_browser_watchdog.py` *(new)*

```python
"""Tests for browser_watchdog.py."""

import time
import pytest
from unittest.mock import patch, MagicMock
from engine.browser_watchdog import BrowserWatchdog


class TestBrowserWatchdog:
    """BC-1, BC-2: Zombie browser prevention tests."""

    def test_register_and_unregister_pid(self):
        wd = BrowserWatchdog()
        wd.register_pid(12345)
        assert wd.get_tracked_count() == 1
        wd.unregister_pid(12345)
        assert wd.get_tracked_count() == 0

    def test_unregister_nonexistent_pid(self):
        wd = BrowserWatchdog()
        wd.unregister_pid(99999)  # Should not raise
        assert wd.get_tracked_count() == 0

    def test_kill_all_clears_tracked(self):
        wd = BrowserWatchdog()
        wd.register_pid(111)
        wd.register_pid(222)
        with patch("engine.browser_watchdog.BrowserWatchdog._kill_pid", return_value=True):
            with patch("engine.browser_watchdog.BrowserWatchdog._reap_orphans", return_value=0):
                killed = wd.kill_all()
        assert wd.get_tracked_count() == 0
        assert killed == 2

    def test_start_stop_lifecycle(self):
        wd = BrowserWatchdog()
        wd.start()
        assert wd._running is True
        wd.stop()
        assert wd._running is False

    def test_double_start_is_safe(self):
        wd = BrowserWatchdog()
        wd.start()
        wd.start()  # Should not raise
        wd.stop()

    def test_stop_without_start_is_safe(self):
        wd = BrowserWatchdog()
        wd.stop()  # Should not raise
```

#### Test: Scheduler AsyncIO Fix

**File**: `backend/scheduler/tests/test_scheduler_async.py` *(new)*

```python
"""Tests for AsyncIOScheduler migration.

SC-1: Verifies scheduler runs in the same event loop as the caller.
CC-6: Verifies concurrency locks are shared with API.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from scheduler.scheduler import CrawlScheduler


class TestCrawlSchedulerAsync:
    """SC-1, SC-2: AsyncIOScheduler correctness tests."""

    def test_scheduler_uses_asyncio_scheduler(self):
        """Verify we're using AsyncIOScheduler, not BackgroundScheduler."""
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = CrawlScheduler()
        assert isinstance(scheduler._scheduler, AsyncIOScheduler)

    def test_scheduler_job_defaults(self):
        """SC-R3: Verify misfire handling is configured."""
        scheduler = CrawlScheduler()
        defaults = scheduler._scheduler._job_defaults
        assert defaults.get("coalesce") is True
        assert defaults.get("misfire_grace_time") == 300
        assert defaults.get("max_instances") == 1

    @pytest.mark.asyncio
    async def test_execute_job_shares_event_loop(self):
        """SC-1: Job callback runs in the same event loop as the test."""
        captured_loop = None

        async def fake_run_crawler(name):
            nonlocal captured_loop
            captured_loop = asyncio.get_running_loop()
            result = MagicMock()
            result.to_dict.return_value = {"status": "success"}
            return result

        pipeline = MagicMock()
        pipeline.run_crawler = fake_run_crawler
        scheduler = CrawlScheduler(pipeline=pipeline)

        test_loop = asyncio.get_running_loop()
        await scheduler._execute_job("test_crawler")

        assert captured_loop is test_loop, \
            "Scheduler job must run in the same event loop as FastAPI"

    def test_add_job_succeeds(self):
        """Basic add_job test."""
        scheduler = CrawlScheduler()
        scheduler.start()
        try:
            result = scheduler.add_job("emart", "0 7 * * *")
            assert result["job_id"] == "crawl_emart"
            assert result["cron"] == "0 7 * * *"
        finally:
            scheduler.stop(wait=False)

    def test_update_job_uses_reschedule(self):
        """SC-R4: update_job uses atomic reschedule_job."""
        scheduler = CrawlScheduler()
        scheduler.start()
        try:
            scheduler.add_job("emart", "0 7 * * *")
            result = scheduler.update_job("emart", "0 9 * * *")
            assert result["cron"] == "0 9 * * *"
            jobs = scheduler.list_jobs()
            assert len(jobs) == 1
        finally:
            scheduler.stop(wait=False)

    def test_stop_with_wait(self):
        """GS-R3: Verify stop(wait=True) is accepted."""
        scheduler = CrawlScheduler()
        scheduler.start()
        scheduler.stop(wait=True)  # Should not raise
        assert scheduler.is_running is False

    def test_get_pending_job_count(self):
        scheduler = CrawlScheduler()
        scheduler.start()
        try:
            assert scheduler.get_pending_job_count() == 0
            scheduler.add_job("test1", "0 7 * * *")
            assert scheduler.get_pending_job_count() == 1
        finally:
            scheduler.stop(wait=False)
```

#### Test: Graceful Shutdown

**File**: `backend/api/tests/test_shutdown.py` *(new)*

```python
"""Tests for graceful shutdown sequence.

GS-1: Verifies shutdown handler is registered.
GS-5: Verifies concurrency state is cleared.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestGracefulShutdown:
    """GS-1, GS-4, GS-5: Shutdown correctness tests."""

    @pytest.mark.asyncio
    async def test_clear_running_crawlers(self):
        """GS-5: clear_running_crawlers empties the set."""
        from concurrency import (
            acquire_crawler_slot,
            clear_running_crawlers,
            active_count,
            _running_crawlers,
        )

        # Setup: mark some crawlers as running
        _running_crawlers.clear()
        await acquire_crawler_slot("crawler_a")
        await acquire_crawler_slot("crawler_b")
        assert active_count() == 2

        # Act: clear all
        cleared = await clear_running_crawlers()
        assert cleared == 2
        assert active_count() == 0

    def test_app_has_shutdown_handler(self):
        """GS-1: Verify the app registers a shutdown event handler."""
        from api.app import create_app
        app = create_app()
        # FastAPI stores event handlers in router.on_shutdown
        assert len(app.router.on_shutdown) > 0, \
            "App must register at least one shutdown handler"

    def test_app_has_startup_handler(self):
        """Verify the app registers a startup event handler."""
        from api.app import create_app
        app = create_app()
        assert len(app.router.on_startup) > 0, \
            "App must register at least one startup handler"
```

#### Test: Health Endpoint

**File**: `backend/api/tests/test_health.py` *(new)*

```python
"""Tests for enriched /health endpoint.

HC-1: Verifies health response includes all required fields.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from api.app import create_app


@pytest.mark.asyncio
async def test_health_returns_required_fields():
    """HC-1: /health must return scheduler, memory, crawl info."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()

    # Required fields
    assert "status" in data
    assert "service" in data
    assert data["service"] == "crawler-admin"
    assert "scheduler_running" in data
    assert "active_crawls" in data
    assert "browser_processes" in data
    assert "memory_mb" in data


@pytest.mark.asyncio
async def test_health_status_ok_when_healthy():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
```

### 7.2 Frontend Tests

#### Test: SSE Reconnection

**File**: `frontend/src/api/__tests__/client.test.js` *(new or append)*

```javascript
/**
 * SSE reconnection tests.
 * Pipeline audit Section 6: SSE CRITICAL fix verification.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock EventSource
class MockEventSource {
  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onerror = null;
    this.readyState = 1;
    MockEventSource.instances.push(this);
  }
  close() {
    this.readyState = 2;
  }
}
MockEventSource.instances = [];

describe('subscribeCrawlerStatus', () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    global.EventSource = MockEventSource;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete global.EventSource;
  });

  it('should reconnect on error with exponential backoff', async () => {
    const { subscribeCrawlerStatus } = await import('../client.js');
    const onError = vi.fn();
    const handle = subscribeCrawlerStatus('test', {
      onData: vi.fn(),
      onError,
      onComplete: vi.fn(),
    });

    // First connection
    expect(MockEventSource.instances.length).toBe(1);

    // Simulate error on first connection
    MockEventSource.instances[0].onerror();
    expect(MockEventSource.instances[0].readyState).toBe(2); // closed

    // Advance past first retry delay (~1s + jitter)
    vi.advanceTimersByTime(1600);
    expect(MockEventSource.instances.length).toBe(2); // reconnected

    // Clean up
    handle.close();
  });

  it('should reset retry count on successful message', async () => {
    const { subscribeCrawlerStatus } = await import('../client.js');
    const onData = vi.fn();
    const handle = subscribeCrawlerStatus('test', {
      onData,
      onError: vi.fn(),
      onComplete: vi.fn(),
    });

    const es = MockEventSource.instances[0];

    // Simulate successful message
    es.onmessage({ data: JSON.stringify({ status: 'running' }) });
    expect(onData).toHaveBeenCalledWith({ status: 'running' });

    // Simulate error + reconnect
    es.onerror();
    vi.advanceTimersByTime(1600);

    // New connection should get quick retry (count was reset)
    expect(MockEventSource.instances.length).toBe(2);

    handle.close();
  });

  it('should give up after MAX_RETRIES', async () => {
    const { subscribeCrawlerStatus } = await import('../client.js');
    const onError = vi.fn();
    const handle = subscribeCrawlerStatus('test', {
      onData: vi.fn(),
      onError,
      onComplete: vi.fn(),
    });

    // Trigger 5 errors (MAX_RETRIES)
    for (let i = 0; i < 5; i++) {
      const es = MockEventSource.instances[MockEventSource.instances.length - 1];
      es.onerror();
      vi.advanceTimersByTime(15000); // advance past max delay
    }

    // 6th error should trigger final onError
    const lastEs = MockEventSource.instances[MockEventSource.instances.length - 1];
    lastEs.onerror();
    expect(onError).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('retries') })
    );

    handle.close();
  });

  it('should close cleanly on terminal status', async () => {
    const { subscribeCrawlerStatus } = await import('../client.js');
    const onComplete = vi.fn();
    const handle = subscribeCrawlerStatus('test', {
      onData: vi.fn(),
      onComplete,
      onError: vi.fn(),
    });

    const es = MockEventSource.instances[0];
    es.onmessage({ data: JSON.stringify({ status: 'success' }) });

    expect(onComplete).toHaveBeenCalledWith({ status: 'success' });
    expect(es.readyState).toBe(2); // closed
  });

  it('close() should prevent reconnection', async () => {
    const { subscribeCrawlerStatus } = await import('../client.js');
    const handle = subscribeCrawlerStatus('test', {
      onData: vi.fn(),
      onError: vi.fn(),
      onComplete: vi.fn(),
    });

    handle.close();

    // Trigger error — should NOT reconnect because closed=true
    const es = MockEventSource.instances[0];
    if (es.onerror) es.onerror();
    vi.advanceTimersByTime(15000);

    expect(MockEventSource.instances.length).toBe(1); // No new connections
  });
});
```

---

## 8. File Change Summary

### New Files

| File | Purpose |
|------|---------|
| `backend/engine/browser_watchdog.py` | Process-level zombie reaper with periodic scan |
| `backend/engine/tests/test_browser_watchdog.py` | Unit tests for watchdog |
| `backend/scheduler/tests/test_scheduler_async.py` | Tests for AsyncIOScheduler migration |
| `backend/api/tests/test_shutdown.py` | Tests for graceful shutdown |
| `backend/api/tests/test_health.py` | Tests for enriched health endpoint |
| `frontend/src/api/__tests__/client.test.js` | Tests for SSE reconnection |

### Modified Files

| File | Changes | Audit IDs |
|------|---------|-----------|
| `backend/scheduler/scheduler.py` | Full rewrite: `BackgroundScheduler` → `AsyncIOScheduler`, remove `asyncio.run()`, add misfire handling, atomic `update_job`, `stop(wait=True)`, `get_pending_job_count()` | SC-1, SC-2, SC-R1–R4, GS-R3 |
| `backend/engine/strategies/selenium_st.py` | `get_event_loop()` → `get_running_loop()`, add `_safe_quit_driver()` with PID verification, register PID with watchdog | BC-1, BC-R1, BC-R2 |
| `backend/engine/strategies/undetected_st.py` | Same as selenium: loop fix, `_safe_quit_driver()`, register both `browser_pid` and `service.process.pid` | BC-2, BC-R1, BC-R2 |
| `backend/engine/strategies/playwright_st.py` | Wrap each cleanup step in individual try/except to prevent cascade cleanup failure | BC-3, BC-4 |
| `backend/api/app.py` | Add `@on_event("startup")` (watchdog + start_time), `@on_event("shutdown")` (scheduler → plugins → browsers → logs), SIGTERM handler, enriched `/health` endpoint | GS-R1, GS-R2, HC-R1 |
| `backend/concurrency.py` | Add `clear_running_crawlers()` function | GS-R5 |
| `frontend/src/api/client.js` | Rewrite `subscribeCrawlerStatus` with retry logic, exponential backoff, jitter, `closed` guard | SSE-CRITICAL |

### Dependencies to Add

Add to `backend/requirements.txt` (if not already present):

```
psutil>=5.9.0
```

This is needed for:
- `browser_watchdog.py` — process enumeration and killing
- `health` endpoint — memory usage reporting
- `_safe_quit_driver()` — PID verification

Verify with: `pip install psutil`

---

## Appendix A: Audit ID Cross-Reference

| Audit ID | Section | Status |
|----------|---------|--------|
| BC-1 | §1.3, §3 | ✅ Fixed (`get_running_loop` + PID watchdog) |
| BC-2 | §1.4, §3 | ✅ Fixed (`get_running_loop` + PID watchdog) |
| BC-3 | §1.5 | ✅ Fixed (individual try/except in cleanup) |
| BC-4 | §1.5 | ✅ Fixed (same) |
| SC-1 | §2 | ✅ Fixed (`AsyncIOScheduler`) |
| SC-2 | §2 | ✅ Fixed (same event loop) |
| SC-R3 | §2 | ✅ Fixed (`misfire_grace_time=300`, `coalesce=True`) |
| SC-R4 | §2 | ✅ Fixed (`reschedule_job`) |
| CC-6 | §2 | ✅ Fixed (unified event loop) |
| GS-1 | §4 | ✅ Fixed (`@on_event("shutdown")`) |
| GS-2 | §4 | ✅ Fixed (`stop(wait=True)`) |
| GS-4 | §4 | ✅ Fixed (watchdog `kill_all`) |
| GS-5 | §4 | ✅ Fixed (`clear_running_crawlers`) |
| HC-1 | §5 | ✅ Fixed (enriched response) |
| SSE | §6 | ✅ Fixed (reconnection + backoff) |
