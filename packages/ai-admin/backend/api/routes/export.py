"""export.py — 외부 분류 워크플로우 export 라우트.

원칙: raw_crawl_records 중 matching_entries hit는 자동 분류된 것으로 간주,
      **miss만 export** 대상이다. 이 원칙은 이 파일 전체에서 유지된다.
      hit된 레코드는 절대 JSONL/CSV에 포함하지 않는다.

엔드포인트:
    POST   /api/export/unmatched          — miss 집합 추출 + JSONL/CSV/manifest 생성
    GET    /api/export/unmatched/recent   — 최근 N개 export 이력 (manifest 목록, 최신 우선)
    GET    /api/export/unmatched/download — 파일 스트리밍 다운로드 (jsonl|csv|zip)

아티팩트 경로: <project_root>/artifacts/exports/unmatched/<batch_id>/
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
# export.py: packages/ai-admin/backend/api/routes/export.py
# parents[2] = packages/ai-admin/backend
# parents[5] = project root (E:/pdf/capston01)
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"

for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.match_key import build_match_key  # noqa: E402

# 아티팩트 기본 디렉토리 — 테스트에서 monkeypatch로 교체 가능
_PROJECT_ROOT = _BACKEND_DIR.parent.parent.parent
_EXPORT_BASE_DIR: Path = _PROJECT_ROOT / "artifacts" / "exports" / "unmatched"

router = APIRouter(prefix="/api/export", tags=["export"])


# ── Pydantic 요청 스키마 ──────────────────────────────────────────────────────

class UnmatchedExportRequest(BaseModel):
    mart: Optional[List[str]] = Field(
        default=None,
        description="마트 필터 목록. None이면 전체 마트 대상.",
    )
    captured_since: Optional[str] = Field(
        default=None,
        description="이 ISO 8601 datetime 이후 crawled_at인 레코드만 포함.",
    )
    limit: Optional[int] = Field(
        default=None,
        ge=1,
        description="최대 레코드 수. None이면 제한 없음.",
    )
    formats: List[str] = Field(
        default=["jsonl", "csv"],
        description="출력 포맷 목록. 'jsonl' | 'csv' 조합.",
    )


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _extract_str(d: dict, keys: list[str]) -> Optional[str]:
    """키 후보 목록 순서대로 dict에서 비어있지 않은 문자열 반환."""
    for k in keys:
        val = d.get(k)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _extract_float(d: dict, keys: list[str]) -> Optional[float]:
    """키 후보 목록 순서대로 dict에서 float 변환 가능한 값 반환."""
    for k in keys:
        val = d.get(k)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return None


def _build_match_key_and_reason(
    payload: dict,
) -> tuple[Optional[str], Optional[str]]:
    """raw_payload dict에서 match_key 생성.

    반환: (match_key, None) — 성공
          (None, miss_reason) — 실패. miss_reason: "no_brand" | "no_name"
    """
    brand = _extract_str(payload, ["brand", "brandName", "brandNm", "brand_name"])
    name = _extract_str(
        payload,
        ["name", "name_core", "nameCore", "productName", "itemName", "prdtName", "goodsName"],
    )
    pack_qty = _extract_float(
        payload, ["pack_qty", "packQty", "pack_quantity", "packQuantity"]
    )
    pack_unit = _extract_str(payload, ["pack_unit", "packUnit", "unitName"])

    if not brand:
        return None, "no_brand"
    if not name:
        return None, "no_name"

    return build_match_key(brand, name, pack_qty, pack_unit), None


def _generate_batch_id() -> str:
    """exp-YYYYMMDDHHMMSS-{4자리 hex} 형식 batch_id 생성."""
    now = datetime.now(timezone.utc)
    rand = uuid.uuid4().hex[:4]
    return f"exp-{now.strftime('%Y%m%d%H%M%S')}-{rand}"


def _sha256_file(path: Path) -> str:
    """파일의 SHA-256 hex digest 반환. 64KB 청크 읽기로 메모리 사용 최소화."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_previous_batch_id(base_dir: Path) -> Optional[str]:
    """base_dir에서 가장 최근 manifest.json의 batch_id 반환.

    재호출 시 이력 연결에 사용 (previous_batch_id 필드).
    """
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


def _row_to_dict(
    record: RawCrawlRecord,
    match_key: Optional[str],
    miss_reason: Optional[str],
) -> dict:
    """RawCrawlRecord → export row dict 변환."""
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


# ── POST /api/export/unmatched ────────────────────────────────────────────────

@router.post("/unmatched")
def export_unmatched(
    body: UnmatchedExportRequest,
    session: Session = Depends(get_db_session),
    matching_session: Session = Depends(get_matching_session),
) -> dict[str, Any]:
    """raw_crawl_records 중 matching_entries에 없는(miss) 레코드만 export.

    처리 흐름:
        1. raw_crawl_records에서 mart / captured_since / limit 필터 적용
        2. 각 레코드의 raw_payload → build_match_key 생성
        3. matching_entries bulk lookup → hit / miss 분류
        4. miss만 JSONL + CSV 파일로 저장
           artifacts/exports/unmatched/<batch_id>/unmatched.{jsonl,csv}
        5. manifest.json (sha256, previous_batch_id 포함) 저장
        6. 결과 반환

    "miss만 export" 원칙:
        matching_entries에 hit된 레코드는 이미 자동 분류 완료 → 파일에 포함하지 않는다.
        miss(key_not_found) + 필드 부족(no_brand, no_name) 레코드가 export 대상이다.
    """
    # ── 1. raw_crawl_records 조회 ─────────────────────────────────────────────
    query = select(RawCrawlRecord)

    if body.mart:
        query = query.where(RawCrawlRecord.source_name.in_(body.mart))

    if body.captured_since:
        try:
            since_dt = datetime.fromisoformat(
                body.captured_since.replace("Z", "+00:00")
            )
        except ValueError as e:
            raise HTTPException(
                status_code=422, detail=f"captured_since 파싱 실패: {e}"
            )
        # SQLite는 timezone-naive datetime으로 저장되므로 naive로 정규화
        since_naive = since_dt.replace(tzinfo=None)
        query = query.where(RawCrawlRecord.crawled_at >= since_naive)

    query = query.order_by(RawCrawlRecord.crawled_at.asc())

    if body.limit:
        query = query.limit(body.limit)

    records = list(session.execute(query).scalars().all())

    # ── 2. match_key 생성 ─────────────────────────────────────────────────────
    record_keys: list[tuple[RawCrawlRecord, Optional[str], Optional[str]]] = []
    for rec in records:
        key, reason = _build_match_key_and_reason(rec.raw_payload or {})
        record_keys.append((rec, key, reason))

    # ── 3. matching_entries bulk lookup → hit / miss 분류 ────────────────────
    # "miss만 export": hit된 레코드는 matching_entries에 이미 등록된 것 → 제외
    valid_keys = [k for _, k, _ in record_keys if k is not None]
    hit_keys = bulk_lookup_hit_keys(matching_session, valid_keys)

    hit_rows: list[dict] = []
    miss_rows: list[dict] = []
    for rec, key, reason in record_keys:
        if key is not None and key in hit_keys:
            # hit: 자동 분류 가능 → export 대상 아님
            hit_rows.append(_row_to_dict(rec, key, None))
        else:
            # miss: 외부 분류 필요 → export 대상
            effective_reason = reason if key is None else "key_not_found"
            miss_rows.append(_row_to_dict(rec, key, effective_reason))

    # ── 4. 파일 생성 ─────────────────────────────────────────────────────────
    batch_id = _generate_batch_id()
    # 현재 모듈의 _EXPORT_BASE_DIR을 사용 (테스트에서 monkeypatch로 교체 가능)
    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    batch_dir = base_dir / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    files_info: dict[str, str] = {}
    formats = [f.lower() for f in (body.formats or ["jsonl", "csv"])]

    # ── JSONL 생성 ─────────────────────────────────────────────────────────────
    if "jsonl" in formats:
        jsonl_path = batch_dir / "unmatched.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for row in miss_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        files_info["jsonl"] = str(jsonl_path)

    # ── CSV 생성 ──────────────────────────────────────────────────────────────
    if "csv" in formats:
        csv_path = batch_dir / "unmatched.csv"
        _CSV_COLS = [
            "raw_record_id",
            "batch_id",
            "source_name",
            "raw_title",
            "raw_price",
            "crawled_at",
            "match_key",
            "miss_reason",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=_CSV_COLS, extrasaction="ignore")
            writer.writeheader()
            for row in miss_rows:
                writer.writerow(row)
        files_info["csv"] = str(csv_path)

    # ── 5. manifest 생성 ──────────────────────────────────────────────────────
    # previous_batch_id: 이력 보존을 위해 가장 최근 export batch를 링크
    previous_batch_id = _find_previous_batch_id(base_dir)

    sha256: dict[str, str] = {}
    if "jsonl" in files_info:
        sha256["unmatched.jsonl"] = _sha256_file(Path(files_info["jsonl"]))
    if "csv" in files_info:
        sha256["unmatched.csv"] = _sha256_file(Path(files_info["csv"]))

    manifest: dict[str, Any] = {
        "batch_id": batch_id,
        "generated_at": generated_at,
        "filter": {
            "mart": body.mart,
            "captured_since": body.captured_since,
            "limit": body.limit,
        },
        "row_count": len(miss_rows),
        "sha256": sha256,
        "previous_batch_id": previous_batch_id,
        "schema_version": 1,
    }

    manifest_path = batch_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    files_info["manifest"] = str(manifest_path)

    return {
        "batch_id": batch_id,
        "hit_count": len(hit_rows),
        "miss_count": len(miss_rows),
        "files": files_info,
        "generated_at": generated_at,
    }


# ── GET /api/export/unmatched/recent ─────────────────────────────────────────

@router.get("/unmatched/recent")
def list_recent_exports(
    n: int = Query(default=20, ge=1, le=200, description="반환할 최대 이력 수"),
) -> dict[str, Any]:
    """최근 N개 export 이력 반환 (최신 우선).

    프론트엔드 '외부 분류 export' 카드에서 이 목록을 표시한다.
    manifest.json 파일을 스캔해 generated_at 기준으로 정렬한다.
    """
    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    if not base_dir.exists():
        return {"exports": [], "total": 0}

    manifests: list[dict] = []
    for mf in base_dir.glob("*/manifest.json"):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            manifests.append(data)
        except Exception:
            continue

    # generated_at 문자열 기준 내림차순 정렬 (ISO 8601은 lexicographic 순서 동일)
    manifests.sort(key=lambda d: d.get("generated_at", ""), reverse=True)

    return {
        "exports": manifests[:n],
        "total": len(manifests),
    }


# ── GET /api/export/unmatched/download ───────────────────────────────────────

@router.get("/unmatched/download")
def download_export(
    batch_id: str = Query(..., description="다운로드할 export의 batch_id"),
    format: str = Query(
        default="jsonl", description="다운로드 포맷: jsonl | csv | zip"
    ),
):
    """지정 batch의 export 파일을 스트리밍 다운로드.

    format=zip: unmatched.jsonl + unmatched.csv + manifest.json을 ZIP으로 묶어 반환.
    """
    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    batch_dir = base_dir / batch_id
    if not batch_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"batch_id {batch_id!r} 를 찾을 수 없습니다.",
        )

    fmt = format.lower()

    if fmt == "jsonl":
        path = batch_dir / "unmatched.jsonl"
        if not path.exists():
            raise HTTPException(status_code=404, detail="unmatched.jsonl 파일이 없습니다.")
        return FileResponse(
            path=str(path),
            media_type="application/x-ndjson",
            filename=f"{batch_id}_unmatched.jsonl",
        )

    if fmt == "csv":
        path = batch_dir / "unmatched.csv"
        if not path.exists():
            raise HTTPException(status_code=404, detail="unmatched.csv 파일이 없습니다.")
        return FileResponse(
            path=str(path),
            media_type="text/csv; charset=utf-8",
            filename=f"{batch_id}_unmatched.csv",
        )

    if fmt == "zip":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fname in ("unmatched.jsonl", "unmatched.csv", "manifest.json"):
                p = batch_dir / fname
                if p.exists():
                    zf.write(p, arcname=fname)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{batch_id}.zip"'
            },
        )

    raise HTTPException(
        status_code=422,
        detail=f"format은 jsonl | csv | zip 중 하나여야 합니다. 받은 값: {format!r}",
    )
