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
