"""P0#14 — 서비스간 권한 표 + scope enforce 최소판.

db-FINAL §5-2. db-admin / web-api / ai-admin / crawler-admin 권한 행렬.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class Role(str, Enum):
    CRAWLER = "crawler"             # crawler-admin 서비스 토큰
    AI_PUBLISHER = "ai_publisher"   # ai-admin 서비스 토큰
    WEB_API = "web_api"             # web-api 서비스 토큰
    DB_ADMIN_MODERATOR = "db_admin_moderator"
    DB_ADMIN_ADMIN = "db_admin_admin"


# Scope id는 §5-1 API 경계와 1:1.
SCOPES = {
    "ingest.observation",
    "ingest.alias",
    "ingest.wholesale",
    "ai.suggest",
    "snapshot.read",
    "match.candidates",
    "match.select_reject",
    "community.pull",
    "queue.claim",
    "queue.resolve",
    "category.move",
    "category.activate",
    "brand_alias.approve",
    "backup",
    "restore",
}


DEFAULT_MATRIX: dict[Role, frozenset[str]] = {
    Role.CRAWLER: frozenset({"ingest.observation", "ingest.alias"}),
    Role.AI_PUBLISHER: frozenset({"ai.suggest", "snapshot.read"}),
    Role.WEB_API: frozenset({
        "snapshot.read", "match.candidates", "match.select_reject", "community.pull",
    }),
    Role.DB_ADMIN_MODERATOR: frozenset({
        "queue.claim", "queue.resolve", "category.move",
        "ingest.observation", "ingest.alias", "ingest.wholesale",
    }),
    Role.DB_ADMIN_ADMIN: frozenset(SCOPES),
}


class PermissionDenied(PermissionError):
    """role이 해당 scope를 가지지 않음. 호출 거부."""


class PermissionMatrix:
    def __init__(self, matrix: dict[Role, Iterable[str]] | None = None) -> None:
        src = matrix if matrix is not None else DEFAULT_MATRIX
        self._matrix: dict[Role, frozenset[str]] = {
            r: frozenset(s) for r, s in src.items()
        }
        for r, scopes in self._matrix.items():
            unknown = set(scopes) - SCOPES
            if unknown:
                raise ValueError(f"unknown scopes for {r}: {unknown}")

    def allows(self, role: Role, scope: str) -> bool:
        if scope not in SCOPES:
            return False
        return scope in self._matrix.get(role, frozenset())

    def enforce(self, role: Role, scope: str) -> None:
        if not self.allows(role, scope):
            raise PermissionDenied(f"role={role.value} cannot access scope={scope}")
