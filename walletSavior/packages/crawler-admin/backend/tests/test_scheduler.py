"""Job scheduling, listing, manual run 테스트."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from scheduler.scheduler import CrawlScheduler
from scheduler.job_tracker import JobTracker


# ── JobTracker tests ─────────────────────────────────────────


class TestJobTracker:
    def test_start_and_complete(self):
        tracker = JobTracker()
        ex = tracker.start("test_job")
        assert ex.status == "running"
        tracker.complete(ex, result={"items": 10})
        assert ex.status == "success"
        assert ex.result == {"items": 10}
        assert ex.ended_at is not None

    def test_start_and_fail(self):
        tracker = JobTracker()
        ex = tracker.start("test_job")
        tracker.fail(ex, "connection error")
        assert ex.status == "failed"
        assert ex.error == "connection error"

    def test_get_history(self):
        tracker = JobTracker()
        ex1 = tracker.start("job_a")
        tracker.complete(ex1)
        ex2 = tracker.start("job_b")
        tracker.complete(ex2)
        history = tracker.get_history()
        assert len(history) == 2

    def test_get_history_filter_by_job_id(self):
        tracker = JobTracker()
        ex1 = tracker.start("job_a")
        tracker.complete(ex1)
        ex2 = tracker.start("job_b")
        tracker.complete(ex2)
        history = tracker.get_history(job_id="job_a")
        assert len(history) == 1
        assert history[0]["job_id"] == "job_a"

    def test_last_execution(self):
        tracker = JobTracker()
        ex = tracker.start("job_x")
        tracker.complete(ex)
        last = tracker.last_execution("job_x")
        assert last is not None
        assert last["job_id"] == "job_x"

    def test_last_execution_not_found(self):
        tracker = JobTracker()
        assert tracker.last_execution("nope") is None

    def test_max_history_cap(self):
        tracker = JobTracker(max_history=5)
        for i in range(10):
            ex = tracker.start(f"job_{i}")
            tracker.complete(ex)
        assert len(tracker._history) == 5


# ── CrawlScheduler tests ────────────────────────────────────


class TestCrawlScheduler:
    def test_start_stop(self):
        sched = CrawlScheduler()
        sched.start()
        assert sched.is_running is True
        sched.stop()
        assert sched.is_running is False

    def test_double_start_idempotent(self):
        sched = CrawlScheduler()
        sched.start()
        sched.start()
        assert sched.is_running is True
        sched.stop()

    def test_double_stop_idempotent(self):
        sched = CrawlScheduler()
        sched.stop()
        assert sched.is_running is False

    def test_add_job(self):
        sched = CrawlScheduler()
        sched.start()
        result = sched.add_job("emart", "0 7 * * *")
        assert result["crawler_name"] == "emart"
        assert result["cron"] == "0 7 * * *"
        jobs = sched.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "crawl_emart"
        sched.stop()

    def test_remove_job(self):
        sched = CrawlScheduler()
        sched.start()
        sched.add_job("emart", "0 7 * * *")
        removed = sched.remove_job("emart")
        assert removed is True
        assert len(sched.list_jobs()) == 0
        sched.stop()

    def test_remove_nonexistent(self):
        sched = CrawlScheduler()
        sched.start()
        removed = sched.remove_job("nope")
        assert removed is False
        sched.stop()

    def test_update_job(self):
        sched = CrawlScheduler()
        sched.start()
        sched.add_job("emart", "0 7 * * *")
        result = sched.update_job("emart", "0 12 * * *")
        assert result["cron"] == "0 12 * * *"
        sched.stop()

    def test_list_jobs_empty(self):
        sched = CrawlScheduler()
        sched.start()
        assert sched.list_jobs() == []
        sched.stop()

    @pytest.mark.asyncio
    async def test_run_now_no_pipeline(self):
        sched = CrawlScheduler()
        result = await sched.run_now("test")
        assert result["status"] == "no_pipeline"

    @pytest.mark.asyncio
    async def test_run_now_with_pipeline(self):
        from pipeline.pipeline import PipelineResult

        mock_pipeline = MagicMock()
        mock_pipeline.run_crawler = AsyncMock(
            return_value=PipelineResult(
                crawler_name="test",
                status="success",
                items_found=5,
                items_valid=5,
                items_saved=5,
            )
        )
        sched = CrawlScheduler(pipeline=mock_pipeline)
        result = await sched.run_now("test")
        assert result["status"] == "success"
        assert result["items_found"] == 5
        # Verify tracker recorded it
        history = sched.tracker.get_history(job_id="test")
        assert len(history) == 1
        assert history[0]["status"] == "success"

    def test_init_from_registry(self):
        mock_reg = MagicMock()
        mock_reg.list_crawlers.return_value = [
            {"name": "emart", "schedule": "0 7 * * *"},
            {"name": "algumon", "schedule": "*/30 * * * *"},
            {"name": "manual_only", "schedule": "manual"},
        ]
        sched = CrawlScheduler(registry=mock_reg)
        sched.start()
        count = sched.init_from_registry()
        assert count == 2
        assert len(sched.list_jobs()) == 2
        sched.stop()
