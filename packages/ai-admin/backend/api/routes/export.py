"""export.py — 외부 분류 워크플로우 export 라우트.

⚠️  DEPRECATED (RD7) — 이 엔드포인트들은 410 Gone을 반환합니다.
    외부 분류 export는 crawler-admin /api/export/raw-batch 로 이전됐습니다.
    기존 로직은 복귀 시 참조용으로 보존합니다. 실제 처리는 하지 않습니다.

이전 엔드포인트:
    POST   /api/export/unmatched          — [GONE → crawler-admin /api/export/raw-batch]
    GET    /api/export/unmatched/recent   — [GONE → crawler-admin /api/export/raw-batch/recent]
    GET    /api/export/unmatched/download — [GONE → crawler-admin /api/export/raw-batch/{id}/download]
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_db_session
from services.matching_db import bulk_lookup_hit_keys, get_matching_session
from storage.models import RawCrawlRecord

# ── 경로 보정 ─────────────────────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"

for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.match_key import build_match_key  # noqa: E402

_PROJECT_ROOT = _BACKEND_DIR.parent.parent.parent
_EXPORT_BASE_DIR: Path = _PROJECT_ROOT / "artifacts" / "exports" / "unmatched"

router = APIRouter(prefix="/api/export", tags=["export"])

# ── RD7: 이전 안내 메시지 ────────────────────────────────────────────────────
_GONE_DETAIL = "외부 분류 export는 crawler-admin /api/export/raw-batch로 이동됨"


# ── Pydantic 요청 스키마 (복귀 시 참조용, 현재 미사용) ───────────────────────

class UnmatchedExportRequest(BaseModel):
    mart: Optional[List[str]] = Field(default=None)
    captured_since: Optional[str] = Field(default=None)
    limit: Optional[int] = Field(default=None, ge=1)
    formats: List[str] = Field(default=["jsonl", "csv"])


# ── 내부 헬퍼 (복귀 시 참조용, 현재 미사용) ──────────────────────────────────

def _extract_str(d: dict, keys: list[str]) -> Optional[str]:
    for k in keys:
        val = d.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _extract_float(d: dict, keys: list[str]) -> Optional[float]:
    for k in keys:
        val = d.get(k)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _build_match_key_and_reason(payload: dict) -> tuple[Optional[str], Optional[str]]:
    brand = _extract_str(payload, ["brand", "brandName", "brandNm", "brand_name"])
    name = _extract_str(
        payload,
        ["name", "name_core", "nameCore", "productName", "itemName", "prdtName", "goodsName"],
    )
    pack_qty = _extract_float(payload, ["pack_qty", "packQty", "pack_quantity", "packQuantity"])
    pack_unit = _extract_str(payload, ["pack_unit", "packUnit", "unitName"])
    if not brand:
        return None, "no_brand"
    if not name:
        return None, "no_name"
    return build_match_key(brand, name, pack_qty, pack_unit), None


def _generate_batch_id() -> str:
    now = datetime.now(timezone.utc)
    rand = uuid.uuid4().hex[:4]
    return f"exp-{now.strftime('%Y%m%d%H%M%S')}-{rand}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_previous_batch_id(base_dir: Path) -> Optional[str]:
    if not base_dir.exists():
        return None
    manifests = sorted(
        base_dir.glob("*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for mf in manifests:
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            return data.get("batch_id")
        except Exception:
            continue
    return None


def _row_to_dict(record: RawCrawlRecord, match_key: Optional[str], miss_reason: Optional[str]) -> dict:
    return {
        "raw_record_id": record.raw_record_id,
        "batch_id": record.batch_id,
        "source_name": record.source_name,
        "raw_title": record.raw_title,
        "raw_price": record.raw_price,
        "crawled_at": record.crawled_at.isoformat() if record.crawled_at else None,
        "match_key": match_key,
        "miss_reason": miss_reason,
        "raw_payload": record.raw_payload,
    }


# ── POST /api/export/unmatched — DEPRECATED (RD7) 410 Gone ──────────────────

@router.post("/unmatched")
def export_unmatched(
    body: UnmatchedExportRequest,
    session: Session = Depends(get_db_session),
    matching_session: Session = Depends(get_matching_session),
) -> dict[str, Any]:
    """[DEPRECATED RD7] 410 Gone — crawler-admin /api/export/raw-batch 로 이전됨."""
    raise HTTPException(status_code=410, detail=_GONE_DETAIL)


# ── GET /api/export/unmatched/recent — DEPRECATED (RD7) 410 Gone ────────────

@router.get("/unmatched/recent")
def list_recent_exports(
    n: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    """[DEPRECATED RD7] 410 Gone — crawler-admin /api/export/raw-batch/recent 로 이전됨."""
    raise HTTPException(status_code=410, detail=_GONE_DETAIL)


# ── GET /api/export/unmatched/download — DEPRECATED (RD7) 410 Gone ──────────

@router.get("/unmatched/download")
def download_export(
    batch_id: str = Query(...),
    format: str = Query(default="jsonl"),
):
    """[DEPRECATED RD7] 410 Gone — crawler-admin /api/export/raw-batch/{id}/download 로 이전됨."""
    raise HTTPException(status_code=410, detail=_GONE_DETAIL)