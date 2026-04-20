"""DB-Admin JWT 인증 관리 — 토큰 자동 취득 및 갱신.

crawler-admin → db-admin 서비스 간 통신에 사용.
환경변수로 자격 증명을 주입하고, JWT 토큰을 캐시하여 반복 로그인을 방지한다.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Environment variables (dev defaults provided)
DB_ADMIN_URL = os.getenv("DB_ADMIN_URL", "http://localhost:8002")
DB_ADMIN_EMAIL = os.getenv("DB_ADMIN_EMAIL", "admin@walletsavior.com")
DB_ADMIN_PASSWORD = os.getenv("DB_ADMIN_PASSWORD", "admin1234!")

# Refresh 5분 전에 갱신 (access token TTL 기본 60분)
_TOKEN_TTL_SECONDS = 3300  # 55분


class DbAdminAuth:
    """JWT 토큰을 자동 취득/갱신하여 Authorization 헤더를 제공."""

    def __init__(
        self,
        base_url: str = DB_ADMIN_URL,
        email: str = DB_ADMIN_EMAIL,
        password: str = DB_ADMIN_PASSWORD,
    ):
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._password = password
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_acquired_at: float = 0.0

    @property
    def _is_token_expired(self) -> bool:
        if not self._access_token:
            return True
        return (time.monotonic() - self._token_acquired_at) >= _TOKEN_TTL_SECONDS

    async def get_headers(self) -> dict[str, str]:
        """Authorization 헤더 반환. 필요 시 로그인/갱신 자동 수행."""
        if self._is_token_expired:
            if self._refresh_token:
                try:
                    await self._refresh()
                except Exception:
                    logger.debug("[DbAdminAuth] refresh failed, falling back to login")
                    await self._login()
            else:
                await self._login()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def handle_401(self) -> dict[str, str]:
        """401 응답 시 강제 재로그인 후 새 헤더 반환."""
        self._access_token = None
        self._refresh_token = None
        await self._login()
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _login(self) -> None:
        url = f"{self._base_url}/api/auth/login"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "email": self._email,
                "password": self._password,
            })
            resp.raise_for_status()
            data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        self._token_acquired_at = time.monotonic()
        logger.info("[DbAdminAuth] login OK (email=%s)", self._email)

    async def _refresh(self) -> None:
        url = f"{self._base_url}/api/auth/refresh"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={
                "refresh_token": self._refresh_token,
            })
            resp.raise_for_status()
            data = resp.json()
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._token_acquired_at = time.monotonic()
        logger.info("[DbAdminAuth] token refreshed")


# Singleton — 프로세스 전체에서 공유
_auth_instance: Optional[DbAdminAuth] = None


def get_db_admin_auth() -> DbAdminAuth:
    """싱글턴 DbAdminAuth 인스턴스 반환."""
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = DbAdminAuth()
    return _auth_instance
