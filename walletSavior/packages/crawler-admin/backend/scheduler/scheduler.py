"""크롤 스케줄러 — APScheduler 기반 자동 크롤 스케줄링."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from scheduler.job_tracker import JobTracker

logger = logging.getLogger(__name__)


class CrawlScheduler:
    """APScheduler 기반 자동 크롤 스케줄러."""

    def __init__(
        self,
        pipeline: Any = None,
        registry: Any = None,
    ) -> None:
        self._scheduler = BackgroundScheduler()
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
        logger.info("[Scheduler] started")

    def stop(self) -> None:
        """스케줄러 중지."""
        if not self._running:
            return
        self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("[Scheduler] stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # --- job management ---

    def add_job(self, crawler_name: str, cron: str) -> dict[str, Any]:
        """크롤 작업 추가. cron 형식: '0 7 * * *'."""
        job_id = f"crawl_{crawler_name}"
        trigger = CronTrigger.from_crontab(cron)
        self._scheduler.add_job(
            self._execute_job_sync,
            trigger=trigger,
            id=job_id,
            args=[crawler_name],
            replace_existing=True,
            name=f"crawl:{crawler_name}",
        )
        logger.info(f"[Scheduler] added job {job_id} cron={cron}")
        return {"job_id": job_id, "crawler_name": crawler_name, "cron": cron}

    def remove_job(self, crawler_name: str) -> bool:
        """작업 제거."""
        job_id = f"crawl_{crawler_name}"
        try:
            self._scheduler.remove_job(job_id)
            logger.info(f"[Scheduler] removed job {job_id}")
            return True
        except Exception:
            return False

    def update_job(self, crawler_name: str, cron: str) -> dict[str, Any]:
        """스케줄 변경 (remove + add)."""
        self.remove_job(crawler_name)
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

    # --- internal ---

    def _execute_job_sync(self, crawler_name: str) -> dict[str, Any]:
        """BackgroundScheduler 콜백 (동기). 내부에서 asyncio.run 사용."""
        return asyncio.run(self._execute_job(crawler_name))

    async def _execute_job(self, crawler_name: str) -> dict[str, Any]:
        """작업 실행 + 추적."""
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
            logger.error(f"[Scheduler] job {crawler_name} failed: {exc}")
            return {"crawler_name": crawler_name, "status": "failed", "error": str(exc)}
