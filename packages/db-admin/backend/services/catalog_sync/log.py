"""catalog_sync_log 기록 헬퍼."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from storage.models import CatalogSyncLog


def record_log(
    session: Session,
    *,
    operation: str,
    entities: list[str] | None = None,
    mode: str | None = None,
    scope: dict[str, Any] | None = None,
    counts: dict[str, Any] | None = None,
    file_hash: str | None = None,
    snapshot_path: str | None = None,
    user: str = "anonymous",
    dry_run: bool = False,
    force: bool = False,
    ok: bool = True,
    error_message: str | None = None,
) -> CatalogSyncLog:
    """catalog_sync_log에 한 행을 추가하고 반환한다(commit은 호출자 책임)."""
    row = CatalogSyncLog(
        operation=operation,
        entities=entities,
        mode=mode,
        scope=scope,
        counts=counts,
        file_hash=file_hash,
        snapshot_path=snapshot_path,
        user=user,
        dry_run=dry_run,
        force=force,
        ok=ok,
        error_message=error_message,
    )
    session.add(row)
    return row
