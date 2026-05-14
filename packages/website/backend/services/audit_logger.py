"""
감사 로깅 — 보안 관련 이벤트 구조화 로깅.

모든 인증, 콘텐츠 변경, 관리자 작업을 JSON 형식으로 기록한다.
"""
import logging
import json
import os
from datetime import datetime, timezone
from typing import Optional


_LOG_DIR = os.getenv("AUDIT_LOG_DIR", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "audit.jsonl")


class _JsonFormatter(logging.Formatter):
    """한 줄 JSON 로그 포매터."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "module": record.module,
        }
        for key in ("user_id", "email", "ip", "action", "resource",
                     "resource_id", "detail", "status", "provider"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False)


def setup_audit_logging() -> logging.Logger:
    """감사 로거 초기화 — 앱 시작 시 한 번 호출."""
    os.makedirs(_LOG_DIR, exist_ok=True)

    logger = logging.getLogger("audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setFormatter(_JsonFormatter())
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setFormatter(_JsonFormatter())
        logger.addHandler(ch)

    return logger


audit_logger = setup_audit_logging()


def log_auth_event(
    action: str,
    *,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    ip: Optional[str] = None,
    status: str = "success",
    detail: Optional[str] = None,
    provider: Optional[str] = None,
):
    """인증 이벤트 기록."""
    audit_logger.info(action, extra={
        "user_id": user_id,
        "email": email,
        "ip": ip,
        "action": action,
        "status": status,
        "detail": detail,
        "provider": provider,
    })


def log_content_event(
    action: str,
    *,
    user_id: int,
    resource: str,
    resource_id: Optional[int] = None,
    ip: Optional[str] = None,
    detail: Optional[str] = None,
):
    """콘텐츠 변경 이벤트 기록."""
    audit_logger.info(action, extra={
        "user_id": user_id,
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "ip": ip,
        "detail": detail,
    })
