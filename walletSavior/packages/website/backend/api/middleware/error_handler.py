"""
글로벌 에러 핸들러 — 내부 정보 노출 방지 및 구조화된 에러 응답.

Findings: M-04, M-05
"""

import logging
import traceback
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("walletguardian.errors")


def register_error_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 글로벌 에러 핸들러를 등록합니다."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """HTTPException — detail은 그대로 반환 (개발자가 의도적으로 설정한 메시지)."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.detail,
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Pydantic 유효성 검사 실패 — 필드명과 메시지만 반환."""
        safe_errors = []
        for err in exc.errors():
            safe_errors.append({
                "field": " → ".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", "유효하지 않은 값"),
            })
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "입력값 유효성 검사 실패",
                "details": safe_errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """처리되지 않은 예외 — 내부 정보를 절대 클라이언트에 노출하지 않습니다."""
        error_id = uuid.uuid4().hex[:12]
        logger.error(
            "Unhandled exception [%s] %s %s: %s\n%s",
            error_id,
            request.method,
            request.url.path,
            str(exc),
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "서버 내부 오류가 발생했습니다.",
                "error_id": error_id,
            },
        )
