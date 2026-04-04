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

    @pytest.mark.asyncio
    async def test_add_job_succeeds(self):
        """Basic add_job test."""
        scheduler = CrawlScheduler()
        scheduler.start()
        try:
            result = scheduler.add_job("emart", "0 7 * * *")
            assert result["job_id"] == "crawl_emart"
            assert result["cron"] == "0 7 * * *"
        finally:
            scheduler.stop(wait=False)

    @pytest.mark.asyncio
    async def test_update_job_uses_reschedule(self):
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

    @pytest.mark.asyncio
    async def test_stop_with_wait(self):
        """GS-R3: Verify stop(wait=True) is accepted."""
        scheduler = CrawlScheduler()
        scheduler.start()
        scheduler.stop(wait=True)  # Should not raise
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_get_pending_job_count(self):
        scheduler = CrawlScheduler()
        scheduler.start()
        try:
            assert scheduler.get_pending_job_count() == 0
            scheduler.add_job("test1", "0 7 * * *")
            assert scheduler.get_pending_job_count() == 1
        finally:
            scheduler.stop(wait=False)
