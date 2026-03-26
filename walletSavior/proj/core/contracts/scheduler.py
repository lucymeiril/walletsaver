"""
스케줄러 계약 (SchedulerContract).

크롤링 작업 스케줄링 인터페이스.
"""

from abc import ABC, abstractmethod
from typing import Optional


class SchedulerContract(ABC):
    """스케줄러가 구현해야 하는 계약."""

    @abstractmethod
    async def add_job(
        self,
        crawler_name: str,
        cron_expression: str,
        job_id: Optional[str] = None,
    ) -> str:
        """
        크롤링 작업을 스케줄에 등록한다.

        Args:
            crawler_name: 크롤러 이름
            cron_expression: cron 표현식 (예: "0 9 * * *")
            job_id: 작업 ID (없으면 자동 생성)

        Returns:
            job_id
        """
        ...

    @abstractmethod
    async def remove_job(self, job_id: str) -> bool:
        """스케줄된 작업 제거."""
        ...

    @abstractmethod
    async def list_jobs(self) -> list[dict]:
        """
        등록된 스케줄 작업 목록.

        Returns:
            [{"job_id": str, "crawler_name": str, "cron": str, "next_run": str, "status": str}]
        """
        ...

    @abstractmethod
    async def pause_job(self, job_id: str) -> bool:
        """작업 일시 정지."""
        ...

    @abstractmethod
    async def resume_job(self, job_id: str) -> bool:
        """정지된 작업 재개."""
        ...
