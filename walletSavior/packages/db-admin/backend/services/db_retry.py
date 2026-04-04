"""Retry logic for transient database errors."""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable, TypeVar

from sqlalchemy.exc import OperationalError

logger = logging.getLogger("db.retry")

# SQLite error messages that are transient and retryable
RETRYABLE_MESSAGES = (
    "database is locked",
    "database is busy",
    "disk I/O error",
    "unable to open database",
)

# Default retry config
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 0.1  # seconds
DEFAULT_MAX_DELAY = 2.0   # seconds

T = TypeVar("T")


def is_retryable(exc: Exception) -> bool:
    """Check if an exception is a transient, retryable DB error."""
    if not isinstance(exc, OperationalError):
        return False
    msg = str(exc).lower()
    return any(pattern in msg for pattern in RETRYABLE_MESSAGES)


def retry_on_db_error(
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
) -> Callable:
    """
    Decorator: retry a function on transient DB errors with exponential backoff.

    Usage:
        @retry_on_db_error(max_retries=3)
        def save_product(session, product):
            session.add(product)
            session.commit()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    if not is_retryable(e) or attempt == max_retries:
                        raise
                    last_exc = e
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        "Transient DB error on %s (attempt %d/%d), "
                        "retrying in %.2fs: %s",
                        func.__name__, attempt + 1, max_retries,
                        delay, e,
                        extra={
                            "component": "db_retry",
                            "function": func.__name__,
                            "attempt": attempt + 1,
                            "delay_seconds": delay,
                        },
                    )
                    time.sleep(delay)
            raise last_exc  # pragma: no cover
        return wrapper
    return decorator


def execute_with_retry(
    session,
    stmt,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
):
    """
    Execute a SQLAlchemy statement with retry on transient errors.

    Usage:
        result = execute_with_retry(session, select(Product).where(...))
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return session.execute(stmt)
        except OperationalError as e:
            if not is_retryable(e) or attempt == max_retries:
                raise
            last_exc = e
            delay = min(base_delay * (2 ** attempt), DEFAULT_MAX_DELAY)
            logger.warning(
                "Transient DB error on execute (attempt %d/%d), "
                "retrying in %.2fs: %s",
                attempt + 1, max_retries, delay, e,
            )
            time.sleep(delay)
    raise last_exc  # pragma: no cover
