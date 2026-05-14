"""Shared security utilities for input sanitization and error responses."""
from __future__ import annotations

import re
import uuid
import logging
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger("security")


# ── LIKE Pattern Escaping ──────────────────────────────────────────────

def escape_like(value: str) -> str:
    """Escape SQL LIKE special characters (%, _, \\).

    Use with SQLAlchemy .ilike() / .like():
        Model.col.ilike(f"%{escape_like(user_input)}%")
    """
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# ── Standard Error Response Schema ─────────────────────────────────────

class ErrorDetail(BaseModel):
    code: str            # machine-readable, e.g. "VALIDATION_ERROR"
    message: str         # human-readable, safe for client display
    request_id: str      # trace ID for log correlation


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ── Error Response Builder ─────────────────────────────────────────────

_ERROR_MESSAGES = {
    "VALIDATION_ERROR":    "입력 데이터가 올바르지 않습니다.",
    "NOT_FOUND":           "요청한 리소스를 찾을 수 없습니다.",
    "CONFLICT":            "이미 존재하는 리소스입니다.",
    "CONFIRM_MISMATCH":    "확인 문자열이 올바르지 않습니다.",
    "PAYLOAD_TOO_LARGE":   "요청 본문이 너무 큽니다.",
    "INTERNAL_ERROR":      "서버 내부 오류가 발생했습니다.",
    "INVALID_SORT_FIELD":  "허용되지 않는 정렬 필드입니다.",
    "INVALID_TABLE":       "허용되지 않는 테이블입니다.",
    "INVALID_FIELD":       "허용되지 않는 필드입니다.",
    "BULK_LIMIT_EXCEEDED": "벌크 작업 항목 수가 한도를 초과했습니다.",
}


def make_error(code: str, status_code: int = 400, detail_override: str | None = None) -> dict:
    """Build a standard error dict for HTTPException.

    Usage:
        raise HTTPException(**make_error("CONFIRM_MISMATCH"))
    """
    request_id = uuid.uuid4().hex[:12]
    message = detail_override or _ERROR_MESSAGES.get(code, "오류가 발생했습니다.")
    return {
        "status_code": status_code,
        "detail": {
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    }


# ── Input Constraints (constants) ──────────────────────────────────────

MAX_BULK_IDS = 500
MAX_INGESTION_ITEMS = 10_000
MAX_INGESTION_ERRORS = 1_000
MAX_BULK_PRICE_ITEMS = 5_000
MAX_SYNONYM_COUNT = 20
MAX_VALIDATE_ITEMS = 10_000
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MB

# String length limits (aligned with DB column sizes)
MAX_NAME_LEN = 255
MAX_CATEGORY_ID_LEN = 100
MAX_UNIT_LEN = 50
MAX_DESCRIPTION_LEN = 5_000
MAX_URL_LEN = 2_048
MAX_KEYWORD_LEN = 100
MAX_ICON_LEN = 50
MAX_SOURCE_LEN = 100
MAX_NOTES_LEN = 2_000
MAX_REASON_LEN = 2_000
MAX_CRAWLER_NAME_LEN = 100
MAX_STRATEGY_LEN = 200
MAX_REVIEW_ACTION_VALUES = {"approve", "reject", "partial"}
MAX_CLEANUP_STATUS_VALUES = {"approved", "rejected", "pending", "crawler_approved", "partial"}
ALLOWED_SCHEMA_TYPES = {"DiscountItem", "HotdealPost", "BaselineItem"}
ALLOWED_CRAWL_STATUSES = {"success", "partial", "failed"}
ALLOWED_DATA_TYPES = {"baseline", "discount"}
