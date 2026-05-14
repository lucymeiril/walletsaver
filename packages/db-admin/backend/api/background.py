"""Safe background task utilities for FastAPI."""
from __future__ import annotations

import logging
import functools
from typing import Callable, Any

from fastapi import BackgroundTasks

logger = logging.getLogger("background")


def safe_task(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that wraps a background task function with try/except.
    Logs any exception with full traceback — never lets it propagate
    silently (FastAPI swallows background task exceptions).
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.error(
                "Background task '%s' failed",
                func.__name__,
                exc_info=True,
                extra={"component": "background_task", "task_name": func.__name__},
            )
    return wrapper


def add_safe_task(
    bg_tasks: BackgroundTasks,
    func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> None:
    """
    Add a task to FastAPI's BackgroundTasks with automatic error wrapping.

    Usage:
        from api.background import add_safe_task

        @router.post("/admin/backup")
        def create_backup(..., background_tasks: BackgroundTasks):
            path = backup_sqlite(db_path, reason="manual")
            add_safe_task(background_tasks, rotate_backups)
            return {"path": path}
    """
    bg_tasks.add_task(safe_task(func), *args, **kwargs)
