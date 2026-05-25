"""raw_batch_export.py — raw-batch 외부 분류 export 라우트.

원칙:
    raw_crawl_records 중 matching_entries miss 항목만 export 대상이다.
    컨텍스트 파일(matching_entries/categories/keywords 스냅샷)을 함께 동봉하여
    외부 LLM이 기존 분류 패턴을 학습할 수 있게 한다.

엔드포인트:
    POST  /api/export/raw-batch                   — miss 집합 추출 + 컨텍스트 파일 생성
    GET   /api/export/raw-batch/recent            — 최근 N개 export 이력
    GET   /api/export/raw-batch/{export_id}/download — zip 다운로드

아티팩트 경로:
    <project_root>/artifacts/exports/raw-batch/<export_id>/
    ├── raw_products.jsonl
    ├── raw_products.csv
    ├── context/
    │   ├── matching_entries.jsonl
    │   ├── categories.yaml
    │   └── keywords.yaml
    └── manifest.json
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
from typing import Any, Iterator, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from services.ai_admin_readonly import get_ai_admin_session, get_records_by_batch_ids
from services.db_admin_readonly import (
    bulk_lookup_hit_keys,
    get_all_categories,
    get_all_keywords,
    get_all_matching_entries,
    get_db_admin_session,
)

# ── sys.path — shared/core 접근 ────────────────────────────────────────────────
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_SHARED_DIR = _BACKEND_DIR.parent.parent / "shared"
for _p in (str(_SHARED_DIR), str(_BACKEND_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.match_key import build_match_key  # noqa: E402

# ── 아티팩트 기본 디렉토리 (테스트에서 monkeypatch로 교체 가능) ─────────────────
_PROJECT_ROOT = _BACKEND_DIR.parent.parent.parent
_EXPORT_BASE_DIR: Path = _PROJECT_ROOT / "artifacts" / "exports" / "raw-batch"

router = APIRouter(prefix="/api/export/raw-batch", tags=["raw-batch-export"])


# ── Pydantic 스키마 ────────────────────────────────────────────────────────────

class RawBatchExportRequest(BaseModel):
    raw_batch_ids: List[str] = Field(
        default_factory=list,
        description="export 대상 raw_crawl_batch ID 목록. 빈 리스트면 전체 대상.",
    )
    include_matched: bool = Field(
        default=False,
        description="True이면 matching_entries hit된 항목도 포함. 기본은 miss만.",
    )
    format: List[str] = Field(
        default=["jsonl", "csv"],
        description="출력 포맷 목록. 'jsonl' | 'csv' 조합.",
    )


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _generate_export_id() -> str:
    """exp-YYYYMMDDHHMMSS-{8자리 hex} 형식 export_id 생성."""
    now = datetime.now(timezone.utc)
    rand = uuid.uuid4().hex[:8]
    return f"exp-{now.strftime('%Y%m%d%H%M%S')}-{rand}"


def _sha256_file(path: Path) -> str:
    """파일의 SHA-256 hex digest 반환. 64KB 청크 읽기."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_previous_export_id(base_dir: Path) -> Optional[str]:
    """base_dir에서 가장 최근 manifest.json의 export_id 반환."""
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
            return data.get("export_id")
        except Exception:
            continue
    return None


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


def _build_match_key_from_payload(
    payload: dict,
) -> tuple[Optional[str], Optional[str]]:
    """raw_payload → match_key 생성.

    반환: (match_key, None) — 성공
          (None, miss_reason) — 실패. "no_brand" | "no_name"
    """
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


def _record_to_export_row(rec: dict, match_key: Optional[str], miss_reason: Optional[str]) -> dict:
    """raw_crawl_record dict → export row dict."""
    payload = rec.get("raw_payload") or {}
    return {
        "raw_record_id": rec.get("raw_record_id"),
        "batch_id": rec.get("batch_id"),
        "source_name": rec.get("source_name"),
        "raw_title": rec.get("raw_title"),
        "raw_price": rec.get("raw_price"),
        "crawled_at": rec.get("crawled_at"),
        "match_key": match_key,
        "miss_reason": miss_reason,
        "brand": _extract_str(payload, ["brand", "brandName", "brandNm", "brand_name"]),
        "name": _extract_str(
            payload,
            ["name", "name_core", "nameCore", "productName", "itemName", "prdtName", "goodsName"],
        ),
        "raw_payload": payload,
    }


# ── CSV 한글 헤더 매핑 ─────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "raw_record_id", "batch_id", "source_name", "raw_title",
    "raw_price", "crawled_at", "match_key", "miss_reason", "brand", "name",
]
_CSV_KOREAN_HEADERS = {
    "raw_record_id": "레코드_ID",
    "batch_id": "배치_ID",
    "source_name": "마트",
    "raw_title": "상품명",
    "raw_price": "가격",
    "crawled_at": "수집시각",
    "match_key": "매치키",
    "miss_reason": "미스_사유",
    "brand": "브랜드",
    "name": "상품명_core",
}


# ── POST /api/export/raw-batch ────────────────────────────────────────────────

@router.post("")
def export_raw_batch(
    body: RawBatchExportRequest,
    ai_session: Session = Depends(get_ai_admin_session),
    db_session: Session = Depends(get_db_admin_session),
) -> dict[str, Any]:
    """raw_batch_ids 기준으로 miss 항목 + 컨텍스트 파일을 묶어 export.

    처리 흐름:
        1. ai-admin control DB에서 raw_crawl_records 조회 (batch_ids 필터)
        2. 각 레코드의 raw_payload → match_key 생성
        3. db-admin matching_entries bulk lookup → hit / miss 분류
        4. miss 항목(include_matched=True이면 hit 포함)을 JSONL + CSV 저장
        5. context/: matching_entries.jsonl, categories.yaml, keywords.yaml 생성
        6. manifest.json 저장
    """
    # ── 1. raw_crawl_records 조회 ─────────────────────────────────────────────
    include_all = len(body.raw_batch_ids) == 0
    records = get_records_by_batch_ids(ai_session, body.raw_batch_ids, include_all=include_all)

    # ── 2. match_key 생성 ─────────────────────────────────────────────────────
    keyed: list[tuple[dict, Optional[str], Optional[str]]] = []
    for rec in records:
        key, reason = _build_match_key_from_payload(rec.get("raw_payload") or {})
        keyed.append((rec, key, reason))

    # ── 3. matching_entries bulk lookup → hit / miss 분류 ────────────────────
    valid_keys = [k for _, k, _ in keyed if k is not None]
    hit_keys = bulk_lookup_hit_keys(db_session, valid_keys)

    hit_rows: list[dict] = []
    miss_rows: list[dict] = []
    for rec, key, reason in keyed:
        if key is not None and key in hit_keys:
            row = _record_to_export_row(rec, key, None)
            hit_rows.append(row)
        else:
            effective_reason = reason if key is None else "key_not_found"
            row = _record_to_export_row(rec, key, effective_reason)
            miss_rows.append(row)

    export_rows = miss_rows if not body.include_matched else (miss_rows + hit_rows)

    # ── 4. 출력 디렉토리 생성 ─────────────────────────────────────────────────
    export_id = _generate_export_id()
    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    export_dir = base_dir / export_id
    export_dir.mkdir(parents=True, exist_ok=True)
    context_dir = export_dir / "context"
    context_dir.mkdir(exist_ok=True)

    created_at = datetime.now(timezone.utc).isoformat()
    file_sha256s: dict[str, str] = {}
    formats = [f.lower() for f in (body.format or ["jsonl", "csv"])]

    # ── 4a. raw_products.jsonl ────────────────────────────────────────────────
    if "jsonl" in formats:
        jsonl_path = export_dir / "raw_products.jsonl"
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for row in export_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        file_sha256s["raw_products.jsonl"] = _sha256_file(jsonl_path)

    # ── 4b. raw_products.csv ──────────────────────────────────────────────────
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
                korean_row = {_CSV_KOREAN_HEADERS[k]: row.get(k) for k in _CSV_FIELDS}
                writer.writerow(korean_row)
        file_sha256s["raw_products.csv"] = _sha256_file(csv_path)

    # ── 5. context 파일 생성 ──────────────────────────────────────────────────

    # 5a. context/matching_entries.jsonl — 현재 matching_entries 전량
    me_path = context_dir / "matching_entries.jsonl"
    try:
        matching_entries = get_all_matching_entries(db_session)
    except Exception:
        matching_entries = []
    with open(me_path, "w", encoding="utf-8") as fh:
        for entry in matching_entries:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    file_sha256s["context/matching_entries.jsonl"] = _sha256_file(me_path)

    # 5b. context/categories.yaml — categories 트리
    cat_path = context_dir / "categories.yaml"
    try:
        categories = get_all_categories(db_session)
    except Exception:
        categories = []
    with open(cat_path, "w", encoding="utf-8") as fh:
        yaml.dump(
            {"categories": categories},
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    file_sha256s["context/categories.yaml"] = _sha256_file(cat_path)

    # 5c. context/keywords.yaml — keywords 사전
    kw_path = context_dir / "keywords.yaml"
    try:
        keywords = get_all_keywords(db_session)
    except Exception:
        keywords = []
    with open(kw_path, "w", encoding="utf-8") as fh:
        yaml.dump(
            {"keywords": keywords},
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    file_sha256s["context/keywords.yaml"] = _sha256_file(kw_path)

    # ── 6. manifest.json ──────────────────────────────────────────────────────
    previous_export_id = _find_previous_export_id(base_dir)
    # 방금 만든 export_dir이 가장 최신이므로 자기 자신은 제외
    # (mtime 기준이라 방금 만든 것이 가장 최신일 수 있으니 previous를 먼저 구했음)

    manifest: dict[str, Any] = {
        "export_id": export_id,
        "created_at": created_at,
        "source_batches": body.raw_batch_ids,
        "total_rows": len(records),
        "miss_rows": len(miss_rows),
        "hit_rows": len(hit_rows),
        "exported_rows": len(export_rows),
        "include_matched": body.include_matched,
        "file_sha256s": file_sha256s,
        "schema_version": 1,
        "previous_export_id": previous_export_id,
    }

    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "export_id": export_id,
        "created_at": created_at,
        "total_rows": len(records),
        "miss_rows": len(miss_rows),
        "hit_rows": len(hit_rows),
        "exported_rows": len(export_rows),
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


# ── GET /api/export/raw-batch/recent ─────────────────────────────────────────

@router.get("/recent")
def list_recent_exports(
    limit: int = 20,
) -> dict[str, Any]:
    """최근 N개 export 이력 반환 (최신 우선).

    manifest.json 파일을 스캔해 created_at 기준으로 정렬한다.
    """
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
            data = json.loads(mf.read_text(encoding="utf-8"))
            manifests.append(data)
        except Exception:
            continue

    # created_at ISO 문자열 기준 내림차순 (lexicographic = 시간 순서 동일)
    manifests.sort(key=lambda d: d.get("created_at", ""), reverse=True)

    return {
        "exports": manifests[:limit],
        "total": len(manifests),
    }


# ── GET /api/export/raw-batch/{export_id}/download ───────────────────────────

@router.get("/{export_id}/download")
def download_export(export_id: str) -> StreamingResponse:
    """지정 export의 전체 파일을 ZIP으로 묶어 스트리밍 다운로드.

    export_id는 exp-YYYYMMDDHHMMSS-{8hex} 형식.
    """
    # 경로 순회 공격 방어
    if not re.match(r"^exp-\d{14}-[0-9a-f]{8}$", export_id):
        raise HTTPException(
            status_code=422,
            detail="export_id 형식이 올바르지 않습니다. (exp-YYYYMMDDHHMMSS-{8hex})",
        )

    base_dir: Path = globals().get("_EXPORT_BASE_DIR", _EXPORT_BASE_DIR)
    export_dir = base_dir / export_id
    if not export_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"export_id {export_id!r}를 찾을 수 없습니다.",
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(export_dir.rglob("*")):
            if fpath.is_file():
                arcname = fpath.relative_to(export_dir).as_posix()
                zf.write(fpath, arcname=arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{export_id}.zip"'
        },
    )
