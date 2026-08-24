"""크롤 스케줄러 — AsyncIOScheduler 기반 자동 크롤 스케줄링.

Audit Fix: SC-1 — AsyncIOScheduler shares FastAPI's event loop.
All concurrency primitives (Semaphore, Lock, _running_crawlers) work correctly.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.job_tracker import JobTracker

logger = logging.getLogger(__name__)


class CrawlScheduler:
    """AsyncIOScheduler 기반 자동 크롤 스케줄러."""

    def __init__(
        self,
        pipeline: Any = None,
        registry: Any = None,
    ) -> None:
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 300,
            }
        )
        self._pipeline = pipeline
        self._registry = registry
        self.tracker = JobTracker()
        self._running = False

    def start(self) -> None:
        if self._running:
            return
        self._scheduler.start(paused=False)
        self._running = True
        logger.info("[Scheduler] started (AsyncIOScheduler)")

    def stop(self, wait: bool = True) -> None:
        if not self._running:
            return
        self._scheduler.shutdown(wait=wait)
        self._running = False
        logger.info("[Scheduler] stopped (wait=%s)", wait)

    @property
    def is_running(self) -> bool:
        return self._running

    def add_job(self, crawler_name: str, cron: str) -> dict[str, Any]:
        """크롤 작업 추가. cron 형식: '0 7 * * *'."""
        job_id = f"crawl_{crawler_name}"
        trigger = CronTrigger.from_crontab(cron)
        self._scheduler.add_job(
            self._execute_job,
            trigger=trigger,
            id=job_id,
            args=[crawler_name],
            replace_existing=True,
            name=f"crawl:{crawler_name}",
        )
        logger.info("[Scheduler] added job %s cron=%s", job_id, cron)
        return {"job_id": job_id, "crawler_name": crawler_name, "cron": cron}

    def remove_job(self, crawler_name: str) -> bool:
        job_id = f"crawl_{crawler_name}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info("[Scheduler] removed job %s", job_id)
            return True
        except Exception:
            return False

    def update_job(self, crawler_name: str, cron: str) -> dict[str, Any]:
        job_id = f"crawl_{crawler_name}"
        try:
            trigger = CronTrigger.from_crontab(cron)
            self._scheduler.reschedule_job(job_id, trigger=trigger)
            logger.info("[Scheduler] rescheduled job %s cron=%s", job_id, cron)
            return {"job_id": job_id, "crawler_name": crawler_name, "cron": cron}
        except Exception:
            return self.add_job(crawler_name, cron)

    def list_jobs(self) -> list[dict[str, Any]]:
        result = []
        for job in self._scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            result.append(
                {
                    "job_id": job.id,
                    "name": job.name,
                    "next_run": next_run.isoformat() if next_run else None,
                    "trigger": str(job.trigger),
                }
            )
        return result

    async def run_now(self, crawler_name: str) -> dict[str, Any]:
        return await self._execute_job(crawler_name)

    def init_from_registry(self) -> int:
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
        return len(self._scheduler.get_jobs())

    async def _execute_job(self, crawler_name: str) -> dict[str, Any]:
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
