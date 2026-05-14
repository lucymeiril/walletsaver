"""
레이트 리밋 설정 — slowapi 기반 per-IP 요청 제한.

Findings: M-02, HIGH-04, HIGH-06
"""

import os
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

logger = logging.getLogger(__name__)

STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


def _get_client_ip(request: Request) -> str:
    """
    프록시 환경에서 실제 클라이언트 IP를 추출합니다.

    우선순위:
    1. X-Real-IP (nginx 등 신뢰할 수 있는 리버스 프록시가 설정)
    2. X-Forwarded-For 의 첫 번째 IP
    3. request.client.host (직접 연결)
    """
    trusted_proxies = set(
        os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    )

    client_host = request.client.host if request.client else "unknown"

    if client_host in trusted_proxies:
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return client_host


limiter = Limiter(
    key_func=_get_client_ip,
    storage_uri=STORAGE_URI,
    default_limits=["100/minute"],
)
