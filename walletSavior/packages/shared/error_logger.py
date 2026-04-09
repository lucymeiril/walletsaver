"""
중앙 에러 로깅 시스템 — 모든 백엔드 서버의 미처리 예외를 자동 기록.

에러는 별도 SQLite DB에 저장되어 에이전트가 자동으로 읽고 진단할 수 있다.
"""
import logging
import traceback
import uuid
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# DB location — logs/ directory at project root
_DB_PATH = Path(__file__).resolve().parent.parent.parent / "logs" / "error_log.db"
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    """스레드별 SQLite 연결 반환 (thread-safe)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
        _local.conn.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                server TEXT NOT NULL,
                level TEXT DEFAULT 'ERROR',
                method TEXT,
                path TEXT,
                status_code INTEGER,
                error_type TEXT,
                error_message TEXT,
                traceback TEXT,
                request_info TEXT,
                resolved INTEGER DEFAULT 0,
                resolution_note TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        _local.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_error_logs_server ON error_logs(server)
        """)
        _local.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_error_logs_timestamp ON error_logs(timestamp DESC)
        """)
        _local.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_error_logs_resolved ON error_logs(resolved)
        """)
        _local.conn.commit()
    return _local.conn


def log_error(
    server: str,
    error: Exception,
    method: str = "",
    path: str = "",
    status_code: int = 500,
    request_info: str = "",
    level: str = "ERROR",
) -> str:
    """에러를 DB에 기록하고 error_id를 반환."""
    error_id = uuid.uuid4().hex[:12]
    tb = traceback.format_exception(type(error), error, error.__traceback__)
    tb_str = "".join(tb)

    try:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO error_logs
               (id, timestamp, server, level, method, path, status_code,
                error_type, error_message, traceback, request_info)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                error_id,
                datetime.now(timezone.utc).isoformat(),
                server,
                level,
                method,
                path,
                status_code,
                type(error).__name__,
                str(error)[:2000],
                tb_str[:10000],
                request_info[:2000],
            ),
        )
        conn.commit()
    except Exception as e:
        logger.error("Failed to log error to DB: %s", e)

    return error_id


def get_recent_errors(
    server: str = None, limit: int = 50, unresolved_only: bool = True
) -> list[dict]:
    """최근 에러 목록 조회."""
    try:
        conn = _get_conn()
        query = "SELECT * FROM error_logs"
        params: list = []
        conditions: list[str] = []
        if server:
            conditions.append("server = ?")
            params.append(server)
        if unresolved_only:
            conditions.append("resolved = 0")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to read error logs: %s", e)
        return []


def mark_resolved(error_id: str, note: str = "") -> bool:
    """에러를 해결 완료로 표시."""
    try:
        conn = _get_conn()
        conn.execute(
            "UPDATE error_logs SET resolved = 1, resolution_note = ? WHERE id = ?",
            (note, error_id),
        )
        conn.commit()
        return True
    except Exception:
        return False
