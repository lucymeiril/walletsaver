"""ai-admin 헬스체크 — 스켈레톤이라 외부 의존성 없이 단순 응답만 반환."""
from __future__ import annotations

import time
from typing import Any

_START_TIME = time.monotonic()


def run_health_check() -> tuple[int, dict[str, Any]]:
    """서비스 가동 여부와 uptime을 반환. 추후 워커/provider 상태를 추가한다."""
    return 200, {
        "status": "ok",
        "service": "ai-admin",
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
    }
