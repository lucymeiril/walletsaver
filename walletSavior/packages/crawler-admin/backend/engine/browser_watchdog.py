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
                    # Only kill processes that have been running longer than max age
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
