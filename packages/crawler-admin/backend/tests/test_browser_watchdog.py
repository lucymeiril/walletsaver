"""Browser watchdog contracts used by crawler-admin lifecycle cleanup."""

from unittest.mock import patch

from engine.browser_watchdog import BrowserWatchdog


def test_browser_watchdog_register_unregister_and_kill_all():
    watchdog = BrowserWatchdog()
    watchdog.register_pid(111)
    watchdog.register_pid(222)
    assert watchdog.get_tracked_count() == 2

    watchdog.unregister_pid(111)
    assert watchdog.get_tracked_count() == 1

    with patch("engine.browser_watchdog.BrowserWatchdog._kill_pid", return_value=True), patch(
        "engine.browser_watchdog.BrowserWatchdog._reap_orphans", return_value=0
    ):
        killed = watchdog.kill_all()

    assert killed == 1
    assert watchdog.get_tracked_count() == 0


def test_browser_watchdog_start_stop_is_idempotent():
    watchdog = BrowserWatchdog()
    watchdog.start()
    watchdog.start()
    assert watchdog._running is True

    watchdog.stop()
    watchdog.stop()
    assert watchdog._running is False
