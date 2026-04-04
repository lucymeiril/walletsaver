"""Audit logging service — records all admin and write operations."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from storage.models import AuditLog

logger = logging.getLogger("audit")


def log_action(
    session: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    old_value: Any = None,
    new_value: Any = None,
    request: Request | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert an audit record. Call within the same DB session/transaction."""
    ip = None
    ua = None
    if request:
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent", "")[:500]

    entry = AuditLog(
        timestamp=datetime.utcnow(),
        user_id=user_id or "anonymous",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=_safe_json(old_value),
        new_value=_safe_json(new_value),
        ip_address=ip,
        user_agent=ua,
        request_id=uuid.uuid4().hex[:12],
        metadata_=metadata,
    )
    session.add(entry)
    logger.info(
        "AUDIT | action=%s entity=%s/%s user=%s ip=%s",
        action, entity_type, entity_id, user_id or "anonymous", ip,
    )


def _safe_json(val: Any) -> Any:
    """Ensure value is JSON-serializable; truncate large values."""
    if val is None:
        return None
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, dict):
        serialized = str(val)
        if len(serialized) > 10_000:
            return {"_truncated": True, "preview": serialized[:1000]}
        return val
    if isinstance(val, list):
        if len(val) > 100:
            return {"_truncated": True, "count": len(val), "sample": val[:5]}
        return val
    return str(val)[:1000]
