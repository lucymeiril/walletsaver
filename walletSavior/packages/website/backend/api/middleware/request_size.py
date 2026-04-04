"""
요청 본문 크기 제한 미들웨어.

Findings: H-02, MEDIUM-06
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Content-Length 기반 요청 크기 제한."""

    def __init__(self, app, max_body_size: int = DEFAULT_MAX_BODY_SIZE):
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            if int(content_length) > self.max_body_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "success": False,
                        "error": f"요청 크기가 제한을 초과했습니다 (최대 {self.max_body_size // (1024*1024)}MB).",
                    },
                )
        return await call_next(request)
