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
        assert len(app.router.on_shutdown) > 0, \
            "App must register at least one shutdown handler"

    def test_app_has_startup_handler(self):
        """Verify the app registers a startup event handler."""
        from api.app import create_app
        app = create_app()
        assert len(app.router.on_startup) > 0, \
            "App must register at least one startup handler"
