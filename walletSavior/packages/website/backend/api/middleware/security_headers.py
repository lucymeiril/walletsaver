"""
보안 헤더 미들웨어 — 모든 응답에 보안 HTTP 헤더를 추가합니다.

Findings: H-03, MEDIUM-01
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_EXTRA_CONNECT_SRC = os.getenv("CSP_EXTRA_CONNECT_SRC", "")
_EXTRA_SCRIPT_SRC = os.getenv("CSP_EXTRA_SCRIPT_SRC", "")
_IS_DEV = os.getenv("ENVIRONMENT", "development") == "development"

_SCRIPT_SRC_DEV = "'self' 'unsafe-eval'" if _IS_DEV else "'self'"
_SCRIPT_SRC = f"{_SCRIPT_SRC_DEV} {_EXTRA_SCRIPT_SRC}".strip()

_CSP_DIRECTIVES = {
    "default-src":      "'self'",
    "script-src":       _SCRIPT_SRC,
    "style-src":        "'self' 'unsafe-inline'",
    "img-src":          "'self' data: https:",
    "font-src":         "'self'",
    "connect-src":      f"'self' https://openapi.naver.com https://map.naver.com {_EXTRA_CONNECT_SRC}".strip(),
    "frame-src":        "https://map.naver.com",
    "frame-ancestors":  "'none'",
    "base-uri":         "'self'",
    "form-action":      "'self'",
    "object-src":       "'none'",
    "worker-src":       "'self'",
    "manifest-src":     "'self'",
}

CSP_HEADER_VALUE = "; ".join(f"{k} {v}" for k, v in _CSP_DIRECTIVES.items())

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": os.getenv("CSP_POLICY", CSP_HEADER_VALUE),
    "X-Frame-Options": "SAMEORIGIN",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "geolocation=(self), "
        "camera=(), "
        "microphone=(), "
        "payment=(), "
        "usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 응답에 보안 헤더를 추가합니다."""

    def __init__(self, app, headers: dict[str, str] | None = None):
        super().__init__(app)
        self._headers = headers or SECURITY_HEADERS

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers[name] = value
        if "Server" in response.headers:
            del response.headers["Server"]
        return response
