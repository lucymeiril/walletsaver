"""P0#2, #8, #9 — atomic snapshot publish + idempotent restore_job + AuditLog 트랜잭션 그룹.

db-FINAL §2-3 / §4-3.

snapshot publish:
    .next → fsync → sha256 사이드카 → os.replace 의 atomic 흐름.
    실패 시 .next 폐기, 현재 파일 보존.
restore_job:
    6단계 자동, 단계별 재시도 가능, 중간 abort 시 임시 파일 정리, idempotent.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field, ConfigDict


class SnapshotBuildLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    snapshot_version: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    file_size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    row_counts_json: dict = Field(default_factory=dict)
    status: str = "running"   # running|success|failure
    error_message: Optional[str] = None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_publish(
    target_path: Path,
    write_fn: Callable[[Path], dict],
    *,
    snapshot_version: str,
) -> SnapshotBuildLog:
    """`.next → fsync → checksum sidecar → os.replace` publish.

    write_fn(path) → row_counts dict. 실패 예외 시 .next 정리 후 target 보존.

    Windows에서 열린 핸들 replace 위험은 §2-3에 따라 빌더가 publish 알림 → web-api가
    명시적 핸들 close → 다음 요청에서 새로 open으로 해결. 이 함수는 파일 시스템 레벨만 책임.
    """
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    next_path = target_path.with_suffix(target_path.suffix + ".next")
    sha_sidecar = target_path.with_suffix(target_path.suffix + ".sha256")

    started = datetime.now(timezone.utc)
    log = SnapshotBuildLog(
        snapshot_version=snapshot_version,
        started_at=started,
    )

    try:
        # 1) .next 작성
        if next_path.exists():
            next_path.unlink()
        row_counts = write_fn(next_path)

        # 2) fsync — durability hint. Windows에서 read 모드 fd는 fsync 불가하므로
        #    write 모드로 한번 더 열어 flush. 실패해도 atomic replace 자체에는 영향 없음.
        try:
            fd = os.open(str(next_path), os.O_RDWR)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

        # 3) checksum
        sha = _sha256_file(next_path)
        sha_sidecar.write_text(sha, encoding="utf-8")

        # 4) atomic replace (POSIX/NTFS 모두 같은 볼륨에서 atomic)
        os.replace(next_path, target_path)

        finished = datetime.now(timezone.utc)
        log = log.model_copy(update={
            "finished_at": finished,
            "duration_ms": int((finished - started).total_seconds() * 1000),
            "file_size_bytes": target_path.stat().st_size,
            "sha256": sha,
            "row_counts_json": row_counts,
            "status": "success",
        })
        return log
    except Exception as e:
        # 실패 시 .next 폐기, 현재 파일 유지.
        if next_path.exists():
            try:
                next_path.unlink()
            except OSError:
                pass
        finished = datetime.now(timezone.utc)
        log = log.model_copy(update={
            "finished_at": finished,
            "duration_ms": int((finished - started).total_seconds() * 1000),
            "status": "failure",
            "error_message": str(e),
        })
        return log


class RestoreJobStep(str, Enum):
    INGESTION_PAUSE = "ingestion_pause"
    PRE_RESTORE_BACKUP = "pre_restore_backup"
    RESTORE_FILE = "restore_file"
    INTEGRITY_CHECK = "integrity_check"
    HANDLE_SWAP_REBUILD = "handle_swap_rebuild"
    INGESTION_RESUME = "ingestion_resume"


RESTORE_STEPS_ORDER: tuple[RestoreJobStep, ...] = (
    RestoreJobStep.INGESTION_PAUSE,
    RestoreJobStep.PRE_RESTORE_BACKUP,
    RestoreJobStep.RESTORE_FILE,
    RestoreJobStep.INTEGRITY_CHECK,
    RestoreJobStep.HANDLE_SWAP_REBUILD,
    RestoreJobStep.INGESTION_RESUME,
)


class RestoreJobStatus(str, Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


class RestoreJob(BaseModel):
    """idempotent restore job — 같은 restore_job_id로 재시도 가능 (§4-3)."""

    model_config = ConfigDict(extra="forbid")

    restore_job_id: str
    backup_source: str
    snapshot_version_paired: Optional[str] = None
    completed_steps: list[RestoreJobStep] = Field(default_factory=list)
    current_step: Optional[RestoreJobStep] = RestoreJobStep.INGESTION_PAUSE
    status: RestoreJobStatus = RestoreJobStatus.RUNNING
    error_step: Optional[RestoreJobStep] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def new_restore_job(
    backup_source: str,
    snapshot_version_paired: Optional[str] = None,
) -> RestoreJob:
    return RestoreJob(
        restore_job_id=secrets.token_urlsafe(12),
        backup_source=backup_source,
        snapshot_version_paired=snapshot_version_paired,
    )


def advance_restore_job(
    job: RestoreJob,
    step: RestoreJobStep,
    success: bool,
    *,
    error: str = "",
) -> RestoreJob:
    """단계 진행. idempotent: 이미 완료된 step을 다시 success로 전달해도 안전.

    실패 시 status=failed, error_step 기록. 재시도는 같은 step에 다시 success=True로 호출.
    """
    if job.status == RestoreJobStatus.SUCCESS:
        return job   # 완전 종료된 job은 변경 금지

    now = datetime.now(timezone.utc)
    if not success:
        return job.model_copy(update={
            "status": RestoreJobStatus.FAILED,
            "error_step": step,
            "error_message": error,
            "current_step": step,
            "updated_at": now,
        })

    completed = list(job.completed_steps)
    if step not in completed:
        completed.append(step)
    # 다음 step 찾기
    try:
        idx = RESTORE_STEPS_ORDER.index(step)
        next_step: Optional[RestoreJobStep] = (
            RESTORE_STEPS_ORDER[idx + 1] if idx + 1 < len(RESTORE_STEPS_ORDER) else None
        )
    except ValueError:
        next_step = None

    final_status = (
        RestoreJobStatus.SUCCESS
        if next_step is None and step == RESTORE_STEPS_ORDER[-1]
        else RestoreJobStatus.RUNNING
    )
    return job.model_copy(update={
        "completed_steps": completed,
        "current_step": next_step,
        "status": final_status,
        "error_step": None,
        "error_message": None,
        "updated_at": now,
    })


class AuditLogEntry(BaseModel):
    """P0#9 — 운영자 행위 기록. transaction_group_key로 대량 reverse 가능."""

    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    actor_user_id: str
    action: str
    target_kind: str            # canonical_product | alias | category | escalation | ...
    target_id: str
    before_json: Optional[dict] = None
    after_json: Optional[dict] = None
    transaction_group_key: Optional[str] = None    # 대량 이동 reverse를 위한 그룹 키 (§4-1)
    caller_id: Optional[str] = None
    bot_like: bool = False
    request_id: Optional[str] = None               # idempotency (§6-5)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
