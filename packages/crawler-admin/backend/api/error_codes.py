"""표준 API 에러 코드 및 안전한 에러 응답 헬퍼."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErrorCode(str, Enum):
    """API 에러 코드 — 클라이언트가 프로그래밍적으로 에러 유형을 식별."""
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    CRAWL_FAILED = "CRAWL_FAILED"
    SCHEDULE_ERROR = "SCHEDULE_ERROR"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    PLUGIN_ERROR = "PLUGIN_ERROR"
    CONFLICT = "CONFLICT"


# 에러 코드별 기본 사용자용 메시지 (스택 트레이스 노출 방지)
_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INTERNAL_ERROR: "서버 내부 오류가 발생했습니다.",
    ErrorCode.INVALID_INPUT: "입력값이 올바르지 않습니다.",
    ErrorCode.NOT_FOUND: "요청한 리소스를 찾을 수 없습니다.",
    ErrorCode.CRAWL_FAILED: "크롤러 실행 중 오류가 발생했습니다.",
    ErrorCode.SCHEDULE_ERROR: "스케줄 처리 중 오류가 발생했습니다.",
    ErrorCode.UPSTREAM_ERROR: "외부 서비스 연결에 실패했습니다.",
    ErrorCode.PLUGIN_ERROR: "플러그인 처리 중 오류가 발생했습니다.",
    ErrorCode.CONFLICT: "리소스 충돌이 발생했습니다.",
}


def safe_error_response(
    status_code: int,
    code: ErrorCode,
    message: str | None = None,
    *,
    detail: str | None = None,
) -> JSONResponse:
    """안전한 JSON 에러 응답 생성 — 내부 정보 노출 방지."""
    body: dict[str, Any] = {
        "error": {
            "code": code.value,
            "message": message or _DEFAULT_MESSAGES.get(code, "오류가 발생했습니다."),
        }
    }
    if detail:
        body["error"]["detail"] = detail
    return JSONResponse(status_code=status_code, content=body)
