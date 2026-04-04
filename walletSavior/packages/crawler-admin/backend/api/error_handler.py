"""
Safe error handling for API responses.

Never expose internal details (paths, stack traces, SQL, URLs) to API clients.
Log full details server-side for debugging.
"""

import logging
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("security.errors")

_SAFE_MESSAGES = {
    KeyError: "Resource not found",
    ValueError: "Invalid input provided",
    FileNotFoundError: "Resource not found",
    PermissionError: "Operation not permitted",
    TimeoutError: "Operation timed out",
    ConnectionError: "Service temporarily unavailable",
}


def safe_error_detail(exc: Exception) -> str:
    """Return a generic, safe error message for the given exception."""
    for exc_type, message in _SAFE_MESSAGES.items():
        if isinstance(exc, exc_type):
            return message
    return "An internal error occurred"


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global exception handler — logs full details, returns safe response.

    Attaches a correlation ID so operators can match user-reported errors
    to server-side log entries.
    """
    error_id = uuid.uuid4().hex[:12]

    logger.error(
        f"[{error_id}] Unhandled exception on {request.method} {request.url.path}: "
        f"{type(exc).__name__}: {exc}",
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "error_id": error_id,
        },
    )
