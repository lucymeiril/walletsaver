import json
import sqlite3

from fastapi import APIRouter, HTTPException

from services.snapshot_repo import get_db_path

router = APIRouter()


@router.get("/health")
def health():
    db = get_db_path()
    if not db.exists():
        raise HTTPException(status_code=503, detail=f"Snapshot not found: {db}")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM canonical_product")
        count = cur.fetchone()[0]
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

    meta_path = db.parent / "public_meta.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)

    return {
        "status": "ok",
        "snapshot_exists": True,
        "canonical_count": count,
        "generated_at": meta.get("generated_at"),
        "snapshot_path": str(db),
    }
