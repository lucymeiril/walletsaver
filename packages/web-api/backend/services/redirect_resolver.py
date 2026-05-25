"""p1-web-api-resolver-contract — stable_id redirect 서비스.

snapshot DB의 canonical_id_redirect 테이블을 로드해
in-memory RedirectResolver에 적재하고, stable_id → canonical_id 해소를 담당한다.

설계 의도:
  - RedirectResolver(공유 모듈)는 비즈니스 로직만 담당; DB 연동은 이 서비스가 담당.
  - 스냅샷은 read-only SQLite이므로 요청 시마다 전체 redirect 행을 로드한다
    (행 수가 적은 스냅샷 특성상 성능 문제 없음; 운영 DB 도입 시 캐시 레이어 추가 예정).
"""
from __future__ import annotations

import sqlite3
from typing import Optional

import sys
from pathlib import Path

# shared 패키지 경로 — conftest와 동일한 추가 방식
_PACKAGES_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(_PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_DIR))

from shared.core.db_p0.identity import (
    CanonicalIdRedirect,
    RedirectCycleError,
    RedirectDepthExceeded,
    RedirectReason,
    RedirectResolver,
)


def _load_resolver(conn: sqlite3.Connection) -> RedirectResolver:
    """DB에서 redirect 행 전체를 읽어 in-memory resolver를 반환."""
    resolver = RedirectResolver()
    cur = conn.cursor()

    # 테이블이 없을 수도 있다 (스냅샷 구 버전 호환)
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='canonical_id_redirect'"
    )
    if cur.fetchone() is None:
        return resolver

    cur.execute("SELECT from_id, to_id, reason, created_at FROM canonical_id_redirect")
    for row in cur.fetchall():
        try:
            reason_val = row["reason"] if isinstance(row, sqlite3.Row) else row[2]
            try:
                reason = RedirectReason(reason_val)
            except ValueError:
                reason = RedirectReason.MANUAL

            redirect = CanonicalIdRedirect(
                from_id=row["from_id"] if isinstance(row, sqlite3.Row) else row[0],
                to_id=row["to_id"] if isinstance(row, sqlite3.Row) else row[1],
                reason=reason,
            )
            resolver.add(redirect)
        except (RedirectCycleError, RedirectDepthExceeded):
            # 손상된 redirect 행 — 무시하고 계속 로드
            pass
    return resolver


class SnapshotRedirectService:
    """스냅샷 DB 기반 stable_id resolver."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._resolver: Optional[RedirectResolver] = None

    @property
    def resolver(self) -> RedirectResolver:
        if self._resolver is None:
            self._resolver = _load_resolver(self._conn)
        return self._resolver

    def resolve(self, stable_id: str) -> str:
        """stable_id → terminal canonical_id 반환."""
        return self.resolver.resolve(stable_id)

    def resolve_or_none(self, stable_id: str) -> Optional[str]:
        """에러 발생 시 None 반환 (cycle / depth 초과 방어용)."""
        try:
            return self.resolve(stable_id)
        except (RedirectCycleError, RedirectDepthExceeded):
            return None
