"""DB integrity dashboard API.

Read-only diagnostics for FK/orphan/zombie data, expired discounts,
ingestion/crawl failures, backup status and placeholders for projection
and DLQ checks. Manual recheck/repair hooks are exposed but never
auto-mutate user data.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.requests import Request

from api.auth import require_admin, require_moderator
from api.middleware.rate_limit import limiter, ADMIN_LIMIT
from config import settings
from services.base import get_session
from services.integrity import scan_integrity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/integrity", tags=["admin", "integrity"])


# ── Request schemas ──────────────────────────────────────────────────────

class RecheckRequest(BaseModel):
    """Optional filter — when `check` is provided, run only that check."""
    check: Optional[str] = Field(default=None, max_length=64)


class RepairRequest(BaseModel):
    """Manual repair hook. `confirm` must equal `REPAIR_<CHECK_NAME>`.

    Currently no destructive repair is implemented server-side; this
    endpoint records the request and returns a structured response so
    the dashboard can wire UI without breaking. Future implementations
    will dispatch to specific repair routines per `check` name.
    """
    check: str = Field(..., min_length=1, max_length=64)
    confirm: str = Field(..., min_length=1, max_length=128)


# ── Routes ───────────────────────────────────────────────────────────────


@router.get("/summary")
@limiter.limit(ADMIN_LIMIT)
def integrity_summary(request: Request, identity: dict = Depends(require_moderator)):
    """Return the latest integrity scan."""
    session = get_session()
    try:
        return scan_integrity(session, database_url=settings.DATABASE_URL)
    finally:
        session.close()


@router.post("/recheck")
@limiter.limit(ADMIN_LIMIT)
def integrity_recheck(
    request: Request,
    body: RecheckRequest = RecheckRequest(),
    identity: dict = Depends(require_moderator),
):
    """Re-run the integrity scan. Equivalent to /summary but POST so it
    can be tied to a manual button click without browser caching."""
    session = get_session()
    try:
        report = scan_integrity(session, database_url=settings.DATABASE_URL)
        if body and body.check:
            report["checks"] = [c for c in report["checks"] if c.get("name") == body.check]
            if not report["checks"]:
                raise HTTPException(status_code=404, detail=f"unknown check: {body.check}")
        return report
    finally:
        session.close()


@router.post("/repair")
@limiter.limit(ADMIN_LIMIT)
def integrity_repair(
    request: Request,
    body: RepairRequest,
    identity: dict = Depends(require_admin),
):
    """Manual repair hook (placeholder).

    No automated repair is performed by default — destructive cleanup
    must go through the existing /admin/reset-* endpoints. This route
    exists so the dashboard can wire a "repair" button per check; once a
    repair routine is implemented for a given check, dispatch happens
    here.
    """
    expected = f"REPAIR_{body.check.upper()}"
    if body.confirm != expected:
        raise HTTPException(status_code=400, detail="확인 문자열이 올바르지 않습니다.")

    logger.warning("[ADMIN] integrity.repair requested: check=%s by=%s",
                   body.check, identity.get("email") or identity.get("user_id"))
    return {
        "action": "integrity.repair",
        "check": body.check,
        "status": "not_implemented",
        "message": "수동 복구 루틴이 아직 구성되지 않았습니다. /admin/reset-* 사용을 검토하세요.",
    }
