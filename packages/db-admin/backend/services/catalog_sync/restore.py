"""Phase 4 — 스냅샷 롤백(복원) 서비스.

apply/recategorize는 변경 직전 `services.backup.create_backup`로 SQLite 스냅샷을
남긴다. 이 모듈은 그 스냅샷 목록을 보여주고, 선택한 스냅샷으로 현재 DB를 되돌린다.

안전장치(rubber-duck 검토 반영):
  - 파일명은 basename만 허용(경로 탈출 차단). BACKUP_DIR 안에 실제로 존재해야 한다.
  - 복원 전 무결성 검사(PRAGMA integrity_check)를 통과해야 한다.
  - 선택한 스냅샷을 먼저 임시본으로 복사 → 회전(rotate)으로 사라지는 것을 막는다.
  - 복원 직전 현재 DB의 pre-restore 백업을 따로 남긴다.
  - 라이브 엔진을 reset_engine()으로 정리한 뒤 파일을 교체(os.replace)하고,
    남아있는 -wal/-shm 파일을 제거한다. 이후 다음 요청이 새 연결을 만든다.
  - SQLite 전용. 동시 복원을 막기 위해 프로세스 단위 락을 사용한다.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any

from services.backup import BACKUP_DIR, list_backups

_RESTORE_LOCK = threading.Lock()


def list_snapshots() -> list[dict[str, Any]]:
    """복원 가능한 스냅샷 목록(최신순)."""
    return list_backups()


def _sqlite_path(database_url: str) -> str:
    if not database_url.startswith("sqlite"):
        raise ValueError("복원은 SQLite 데이터베이스에서만 지원됩니다.")
    path = database_url.replace("sqlite:///", "").replace("sqlite://", "")
    if not path or path == ":memory:":
        raise ValueError("인메모리 SQLite는 복원할 수 없습니다.")
    return path


def _integrity_ok(db_file: Path) -> bool:
    conn = sqlite3.connect(str(db_file))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"
    finally:
        conn.close()


def restore_snapshot(filename: str, database_url: str) -> dict[str, Any]:
    """선택한 스냅샷으로 현재 DB를 되돌린다. 복원 전 현재 상태를 따로 백업한다."""
    db_path = _sqlite_path(database_url)

    safe = Path(filename).name
    if safe != filename:
        raise ValueError("잘못된 파일명입니다(경로 포함 불가).")
    backup_root = Path(BACKUP_DIR).resolve()
    chosen = (backup_root / safe).resolve()
    if chosen.parent != backup_root or not chosen.is_file():
        raise FileNotFoundError("해당 스냅샷을 찾을 수 없습니다.")
    if not _integrity_ok(chosen):
        raise ValueError("스냅샷 무결성 검사 실패 — 손상된 백업입니다.")

    from services.backup import create_backup
    from services.base import reset_engine

    with _RESTORE_LOCK:
        # 1) 선택 스냅샷을 먼저 임시본으로 복사(회전으로 사라지는 것 방지)
        tmp_dir = Path(tempfile.mkdtemp(prefix="catsync_restore_"))
        staged = tmp_dir / "snapshot.db"
        shutil.copy2(chosen, staged)

        # 2) 현재 DB를 pre-restore 백업으로 보존
        pre_backup = create_backup(database_url, reason="pre-restore")

        # 3) 라이브 엔진 정리 후 파일 교체
        reset_engine()
        target = Path(db_path)
        os.replace(staged, target)
        for suffix in ("-wal", "-shm"):
            stale = Path(str(target) + suffix)
            if stale.exists():
                try:
                    stale.unlink()
                except OSError:
                    pass
        reset_engine()
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except OSError:
            pass

    return {
        "ok": True,
        "restored_from": safe,
        "pre_restore_backup": Path(pre_backup).name,
        "database": db_path,
    }
