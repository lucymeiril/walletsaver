"""FastAPI 미들웨어 — 미처리 예외를 자동 포착하여 error_log DB에 기록."""
import logging
import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class ErrorLoggingMiddleware(BaseHTTPMiddleware):
    """모든 요청을 감싸서 5xx 응답과 미처리 예외를 error_log DB에 자동 기록."""

    def __init__(self, app, server_name: str):
        super().__init__(app)
        self.server_name = server_name

    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                from error_logger import log_error

                err = Exception(
                    f"HTTP {response.status_code} on {request.method} {request.url.path}"
                )
                log_error(
                    server=self.server_name,
                    error=err,
                    method=request.method,
                    path=str(request.url.path),
                    status_code=response.status_code,
                    level="WARNING",
                )
            return response
        except Exception as exc:
            from error_logger import log_error

            request_info = json.dumps(
                {
                    "query": str(request.query_params),
                    "client": request.client.host if request.client else "unknown",
                },
                ensure_ascii=False,
            )

            error_id = log_error(
                server=self.server_name,
                error=exc,
                method=request.method,
                path=str(request.url.path),
                status_code=500,
                request_info=request_info,
            )
            logger.error(
                "[%s] %s %s → %s: %s",
                error_id,
                request.method,
                request.url.path,
                type(exc).__name__,
                str(exc)[:200],
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "서버 내부 오류가 발생했습니다.",
                        "error_id": error_id,
                    }
                },
            )
