from fastapi import APIRouter, HTTPException, Query

from services.snapshot_repo import SnapshotRepo, get_conn
from services.search import autocomplete_suggest

router = APIRouter()


@router.get("/autocomplete")
def autocomplete(
    prefix: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
):
    try:
        conn = get_conn()
        repo = SnapshotRepo(conn)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e))

    results = autocomplete_suggest(repo, prefix, limit=limit)
    return {"prefix": prefix, "suggestions": results}
