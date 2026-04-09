"""에러 로그 조회 API — 모든 백엔드에서 마운트 가능."""
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/errors", tags=["errors"])


@router.get("/")
def list_errors(
    server: str = Query(None),
    limit: int = Query(50, ge=1, le=500),
    unresolved_only: bool = Query(True),
):
    from error_logger import get_recent_errors

    errors = get_recent_errors(
        server=server, limit=limit, unresolved_only=unresolved_only
    )
    return {"success": True, "data": errors, "meta": {"total": len(errors)}}


@router.post("/{error_id}/resolve")
def resolve_error(error_id: str, note: str = ""):
    from error_logger import mark_resolved

    ok = mark_resolved(error_id, note)
    return {"success": ok}


@router.delete("/resolved")
def clear_resolved():
    """해결된 에러 로그 삭제."""
    from error_logger import _get_conn

    try:
        conn = _get_conn()
        conn.execute("DELETE FROM error_logs WHERE resolved = 1")
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
