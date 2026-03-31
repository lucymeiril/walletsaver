"""작업 추적기 — 스케줄 실행 이력 관리."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class JobExecution:
    """단일 작업 실행 기록."""
    job_id: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: str = "running"  # running | success | failed
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class JobTracker:
    """스케줄 작업 실행 이력 관리."""

    def __init__(self, max_history: int = 500) -> None:
        self._history: list[JobExecution] = []
        self._max_history = max_history

    def start(self, job_id: str) -> JobExecution:
        """작업 실행 시작 기록."""
        execution = JobExecution(job_id=job_id, started_at=datetime.now())
        self._history.append(execution)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        return execution

    def complete(
        self,
        execution: JobExecution,
        result: dict[str, Any] | None = None,
    ) -> None:
        """작업 성공 기록."""
        execution.ended_at = datetime.now()
        execution.status = "success"
        execution.result = result

    def fail(self, execution: JobExecution, error: str) -> None:
        """작업 실패 기록."""
        execution.ended_at = datetime.now()
        execution.status = "failed"
        execution.error = error

    def get_history(
        self,
        job_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """실행 이력 조회."""
        items = self._history
        if job_id:
            items = [e for e in items if e.job_id == job_id]
        items = items[-limit:]
        return [
            {
                "job_id": e.job_id,
                "started_at": e.started_at.isoformat(),
                "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                "status": e.status,
                "result": e.result,
                "error": e.error,
            }
            for e in reversed(items)
        ]

    def last_execution(self, job_id: str) -> dict[str, Any] | None:
        """특정 작업의 마지막 실행 기록."""
        for e in reversed(self._history):
            if e.job_id == job_id:
                return {
                    "job_id": e.job_id,
                    "started_at": e.started_at.isoformat(),
                    "ended_at": e.ended_at.isoformat() if e.ended_at else None,
                    "status": e.status,
                }
        return None
