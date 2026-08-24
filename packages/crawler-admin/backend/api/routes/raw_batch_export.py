"""외부 분류용 raw export 라우트.

현재 데이터 원본은 db-admin의 ``pending_ingestions`` 하나뿐이다. 폐기된
ai-admin control DB나 ``raw_crawl_records``를 읽지 않는다.

엔드포인트:
    POST  /api/export/raw-batch
    GET   /api/export/raw-batch/recent
    GET   /api/export/raw-batch/{export_id}/download
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.db_admin_readonly import (
    bulk_lookup_match_statuses,
    get_all_categories,
    get_all_keywords,
    get_all_matching_entries,
    get_db_admin_session,
    get_pending_ingestion_records,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.match_key import build_match_key  # noqa: E402

_PROJECT_ROOT = _BACKEND_DIR.parent.parent.parent
_EXPORT_BASE_DIR: Path = _PROJECT_ROOT / "artifacts" / "exports" / "raw-batch"

router = APIRouter(prefix="/api/export/raw-batch", tags=["raw-batch-export"])


class RawBatchExportRequest(BaseModel):
    ingestion_ids: list[int] = Field(
        min_length=1,
        max_length=100,
        description="db-admin pending_ingestions ID 목록. 최소 1개를 명시해야 한다.",
    )
    include_matched: bool = Field(
        default=False,
        description="True이면 matching_entries hit 항목도 함께 내보낸다.",
    )
    format: list[str] = Field(
        default_factory=lambda: ["jsonl", "csv"],
        min_length=1,
        max_length=2,
        description="출력 포맷: jsonl, csv",
    )


def _generate_export_id() -> str:
    now = datetime.now(timezone.utc)
    return f"exp-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_previous_export_id(base_dir: Path) -> Optional[str]:
    if not base_dir.exists():
        return None
    manifests = sorted(
        base_dir.glob("*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for mf in manifests:
        try:
            return json.loads(mf.read_text(encoding="utf-8")).get("export_id")
        except Exception:
            continue
    return None


def _extract_str(d: dict, keys: list[str]) -> Optional[str]:
    for key in keys:
        value = d.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _extract_float(d: dict, keys: list[str]) -> Optional[float]:
    for key in keys:
        value = d.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _build_match_key_from_payload(payload: dict) -> tuple[Optional[str], Optional[str]]:
    """Return the same canonical identity used by crawler runtime lookup.

    Fresh crawler rows stamped by ``matching_enrichment`` keep their stored
    ``match_key``. Runtime enrichment may replace display/name/pack fields with
    canonical Product metadata after the key was computed, so rebuilding those
    rows could incorrectly turn a real hit into a miss.

    Legacy PendingIngestion rows usually have no ``matching_status``. When their
    source identity fields are available, rebuild the key through the current
    shared SSOT instead of trusting a stale historical key. If the legacy row no
    longer carries enough identity to rebuild, fall back to its stored key.
    Missing brand is valid and becomes ``__no_brand__`` inside ``build_match_key``.
    """
    existing_key = str(payload.get("match_key") or "").strip()
    matching_status = str(payload.get("matching_status") or "").strip().lower()
    if existing_key and matching_status in {"hit", "miss"}:
        return existing_key, None

    brand = _extract_str(payload, ["brand", "brandName", "brandNm", "brand_name"])
    name = _extract_str(
        payload,
        [
            "name_core",
            "normalized_name",
            "name",
            "nameCore",
            "productName",
            "itemName",
            "prdtName",
            "goodsName",
            "title",
        ],
    )
    pack_qty = _extract_float(payload, ["pack_qty", "packQty", "pack_quantity", "packQuantity"])
    pack_unit = _extract_str(payload, ["pack_unit", "packUnit", "unitName", "unit"])

    if name:
        return build_match_key(brand, name, pack_qty, pack_unit), None
    if existing_key:
        return existing_key, None
    return None, "no_name"


def _record_to_export_row(
    rec: dict,
    match_key: Optional[str],
    miss_reason: Optional[str],
) -> dict:
    payload = rec.get("raw_payload") or {}
    return {
        "raw_record_id": rec.get("raw_record_id"),
        "ingestion_id": rec.get("ingestion_id"),
        "batch_id": rec.get("batch_id"),
        "source_name": rec.get("source_name"),
        "raw_title": rec.get("raw_title"),
        "raw_price": rec.get("raw_price"),
        "crawled_at": rec.get("crawled_at"),
        "schema_type": rec.get("schema_type"),
        "match_key": match_key,
        "miss_reason": miss_reason,
        "brand": _extract_str(payload, ["brand", "brandName", "brandNm", "brand_name"]),
        "name": _extract_str(
            payload,
            ["name", "name_core", "nameCore", "productName", "itemName", "prdtName", "goodsName", "title"],
        ),
        "raw_payload": payload,
    }


_CSV_FIELDS = [
    "raw_record_id",
    "ingestion_id",
    "batch_id",
    "source_name",
    "raw_title",
    "raw_price",
    "crawled_at",
    "schema_type",
    "match_key",
    "miss_reason",
    "brand",
    "name",
]
_CSV_KOREAN_HEADERS = {
    "raw_record_id": "레코드_ID",
    "ingestion_id": "대기열_ID",
    "batch_id": "배치_ID",
    "source_name": "마트",
    "raw_title": "상품명",
    "raw_price": "가격",
    "crawled_at": "수집시각",
    "schema_type": "스키마",
    "match_key": "매치키",
    "miss_reason": "미스_사유",
    "brand": "브랜드",
    "name": "상품명_core",
}


@router.post("")
def export_raw_batch(
    body: RawBatchExportRequest,
    db_session: Session = Depends(get_db_admin_session),
) -> dict[str, Any]:
    ingestion_ids = list(dict.fromkeys(body.ingestion_ids))
    formats = [fmt.lower() for fmt in body.format]
    invalid_formats = sorted(set(formats) - {"jsonl", "csv"})
    if invalid_formats:
        raise HTTPException(422, f"지원하지 않는 출력 형식: {invalid_formats}")

    records = get_pending_ingestion_records(db_session, ingestion_ids)
    found_ids = {int(rec["ingestion_id"]) for rec in records}
    missing_ids = [value for value in ingestion_ids if value not in found_ids]
    if missing_ids:
        raise HTTPException(
            404,
            f"대기열 ID를 찾을 수 없거나 원본 items가 비어 있습니다: {missing_ids}",
        )

    keyed: list[tuple[dict, Optional[str], Optional[str]]] = []
    for rec in records:
        key, reason = _build_match_key_from_payload(rec.get("raw_payload") or {})
        keyed.append((rec, key, reason))

    valid_keys = [key for _, key, _ in keyed if key is not None]
    match_statuses = bulk_lookup_match_statuses(db_session, valid_keys)

    hit_rows: list[dict] = []
    miss_rows: list[dict] = []
    for rec, key, reason in keyed:
        if key is None:
            miss_rows.append(_record_to_export_row(rec, key, reason or "unkeyable"))
            continue

        status = match_statuses.get(key, "key_not_found")
        if status == "hit":
            hit_rows.append(_record_to_export_row(rec, key, None))
        else:
            miss_rows.append(_record_to_export_row(rec, key, status))

    export_rows = miss_rows if not body.include_matched else (miss_rows + hit_rows)

    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    previous_export_id = _find_previous_export_id(base_dir)
    export_id = _generate_export_id()
    export_dir = base_dir / export_id
    export_dir.mkdir(parents=True, exist_ok=False)
    context_dir = export_dir / "context"
    context_dir.mkdir()

    created_at = datetime.now(timezone.utc).isoformat()
    file_sha256s: dict[str, str] = {}

    if "jsonl" in formats:
        jsonl_path = export_dir / "raw_products.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for row in export_rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        file_sha256s["raw_products.jsonl"] = _sha256_file(jsonl_path)

    if "csv" in formats:
        csv_path = export_dir / "raw_products.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=list(_CSV_KOREAN_HEADERS.values()),
                extrasaction="ignore",
            )
            writer.writeheader()
            for row in export_rows:
                writer.writerow({_CSV_KOREAN_HEADERS[key]: row.get(key) for key in _CSV_FIELDS})
        file_sha256s["raw_products.csv"] = _sha256_file(csv_path)

    me_path = context_dir / "matching_entries.jsonl"
    try:
        matching_entries = get_all_matching_entries(db_session)
    except Exception:
        matching_entries = []
    with open(me_path, "w", encoding="utf-8") as fh:
        for entry in matching_entries:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    file_sha256s["context/matching_entries.jsonl"] = _sha256_file(me_path)

    cat_path = context_dir / "categories.yaml"
    try:
        categories = get_all_categories(db_session)
    except Exception:
        categories = []
    cat_path.write_text(
        yaml.safe_dump({"categories": categories}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    file_sha256s["context/categories.yaml"] = _sha256_file(cat_path)

    kw_path = context_dir / "keywords.yaml"
    try:
        keywords = get_all_keywords(db_session)
    except Exception:
        keywords = []
    kw_path.write_text(
        yaml.safe_dump({"keywords": keywords}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    file_sha256s["context/keywords.yaml"] = _sha256_file(kw_path)

    manifest: dict[str, Any] = {
        "export_id": export_id,
        "created_at": created_at,
        "source": "db-admin.pending_ingestions",
        "source_ingestions": ingestion_ids,
        "total_rows": len(records),
        "miss_rows": len(miss_rows),
        "hit_rows": len(hit_rows),
        "exported_rows": len(export_rows),
        "include_matched": body.include_matched,
        "file_sha256s": file_sha256s,
        "schema_version": 2,
        "previous_export_id": previous_export_id,
    }
    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        **manifest,
        "export_dir": str(export_dir),
        "files": {
            "raw_products_jsonl": str(export_dir / "raw_products.jsonl") if "jsonl" in formats else None,
            "raw_products_csv": str(export_dir / "raw_products.csv") if "csv" in formats else None,
            "context_matching_entries": str(me_path),
            "context_categories": str(cat_path),
            "context_keywords": str(kw_path),
            "manifest": str(manifest_path),
        },
    }


@router.get("/recent")
def list_recent_exports(limit: int = 20) -> dict[str, Any]:
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    if not base_dir.exists():
        return {"exports": [], "total": 0}

    manifests: list[dict] = []
    for mf in base_dir.glob("*/manifest.json"):
        try:
            manifests.append(json.loads(mf.read_text(encoding="utf-8")))
        except Exception:
            continue
    manifests.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return {"exports": manifests[:limit], "total": len(manifests)}


@router.get("/{export_id}/download")
def download_export(export_id: str) -> StreamingResponse:
    if not re.match(r"^exp-\d{14}-[0-9a-f]{8}$", export_id):
        raise HTTPException(
            status_code=422,
            detail="export_id 형식이 올바르지 않습니다. (exp-YYYYMMDDHHMMSS-{8hex})",
        )

    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    export_dir = base_dir / export_id
    if not export_dir.exists():
        raise HTTPException(404, f"export_id {export_id!r}를 찾을 수 없습니다.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(export_dir.rglob("*")):
            if fpath.is_file():
                zf.write(fpath, arcname=fpath.relative_to(export_dir).as_posix())
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{export_id}.zip"'},
    )
