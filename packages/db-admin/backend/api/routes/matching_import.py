"""
matching_import.py — 외부 분류 결과 import HTTP 엔드포인트.

엔드포인트:
    POST /api/import/classified/preview  — 파일 업로드 → validate → dry-run diff 반환
    POST /api/import/classified/confirm  — 파일 업로드 → validate → DB commit

흐름:
    1. 파일 업로드 (.jsonl / .csv)
    2. import_validator 로 row 검증 (strict / lenient 모드)
    3. preview: matching_sync.import_from_rows(dry_run=True) → ImportDiff
    4. confirm:  matching_sync.import_from_rows(dry_run=False) → ImportDiff + DB commit

멱등성:
    trace_id = sha256(file_bytes + mode) → 동일 trace_id 재confirm 시 DB 재쓰기 없음.
    redis 없이 in-memory dict 사용 (프로세스 재시작 시 초기화됨).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from services.base import get_session, managed_session
from services.import_validator import (
    IMPORT_ALLOWED_SOURCES,
    ValidationResult,
    validate_strict,
    validate_lenient,
    _build_match_key,
)
from services.matching_sync import ImportDiff, import_from_rows

router = APIRouter(prefix="/import", tags=["import"])

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────────────
MAX_IMPORT_FILE_BYTES: int = 50 * 1024 * 1024  # 50 MB

# ── In-memory 멱등성 저장소 ────────────────────────────────────────────────────
# trace_id → confirm 응답 dict
# 프로세스 재시작 시 초기화됨 (redis 없는 단순 구현)
_confirmed_traces: dict[str, dict] = {}

# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _parse_uploaded_file(content: bytes, filename: str) -> list[dict]:
    """업로드된 파일 바이트를 파싱하여 row dict 리스트로 반환한다."""
    try:
        text = content.decode("utf-8-sig")  # BOM 제거
    except UnicodeDecodeError as e:
        raise ValueError(f"UTF-8 디코딩 실패: {e}") from e

    fname = (filename or "").lower()

    if fname.endswith(".jsonl"):
        rows: list[dict] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL 파싱 오류 (라인 {lineno}): {exc}") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"JSONL 라인 {lineno} 은 object(dict) 여야 합니다")
            rows.append(obj)
        return rows

    if fname.endswith(".csv"):
        rows = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            parsed: dict = {}
            for k, v in row.items():
                if k is None:
                    continue
                k = k.strip()
                if v is None or v == "":
                    parsed[k] = None
                    continue
                if k in ("confidence", "pack_qty"):
                    try:
                        parsed[k] = float(v)
                    except (ValueError, TypeError):
                        parsed[k] = v
                elif k == "keyword_ids":
                    try:
                        parsed[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        parsed[k] = v
                else:
                    parsed[k] = v.strip() if isinstance(v, str) else v
            rows.append(parsed)
        return rows

    raise ValueError(f"지원하지 않는 파일 형식 '{filename}'. .jsonl 또는 .csv 만 허용")


def _compute_trace_id(content: bytes, mode: str) -> str:
    """파일 내용 + 모드 기반의 결정적 trace_id 를 계산한다."""
    h = hashlib.sha256(content + mode.encode()).hexdigest()
    return f"tr_{h[:32]}"


def _diff_to_summary(diff: ImportDiff) -> dict:
    """ImportDiff 를 응답용 summary dict 로 변환한다."""
    return {
        "added": len(diff.to_add),
        "updated": len(diff.to_update),
        "conflicts": len(diff.conflicts),
        "unchanged": diff.unchanged,
        "total_incoming": diff.total_incoming,
        "preview_rows": [
            {
                "match_key": r.get("match_key"),
                "action": "add",
                "category_id": r.get("category_id"),
                "confidence": r.get("confidence"),
                "source": r.get("source"),
            }
            for r in diff.to_add[:25]
        ] + [
            {
                "match_key": new.get("match_key"),
                "action": "update",
                "category_id": new.get("category_id"),
                "confidence": new.get("confidence"),
                "source": new.get("source"),
            }
            for _old, new in diff.to_update[:25]
        ],
    }


def _make_failure_csv(error_rows: list[tuple[int, str]]) -> str:
    """오류 row 목록을 CSV 텍스트로 직렬화한다."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row_index", "error_message"])
    for row_idx, msg in error_rows:
        writer.writerow([row_idx, msg])
    return buf.getvalue()


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.post("/classified/preview")
async def preview_import(
    file: UploadFile = File(...),
    mode: str = Form("strict"),
) -> JSONResponse:
    """분류 결과 파일 → validate → dry-run diff 반환.

    DB 에 아무것도 쓰지 않는다.
    """
    # ── 파라미터 검증 ──
    if mode not in ("strict", "lenient"):
        raise HTTPException(status_code=422, detail="mode 는 'strict' 또는 'lenient' 여야 합니다.")

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=422, detail="빈 파일은 업로드할 수 없습니다.")

    if len(content) > MAX_IMPORT_FILE_BYTES:
        limit_mb = MAX_IMPORT_FILE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 {limit_mb}MB 를 초과합니다.",
        )

    filename = file.filename or ""
    if not (filename.lower().endswith(".jsonl") or filename.lower().endswith(".csv")):
        raise HTTPException(
            status_code=422,
            detail="파일 형식은 .jsonl 또는 .csv 여야 합니다.",
        )

    # ── 파싱 ──
    try:
        rows = _parse_uploaded_file(content, filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"파일 파싱 오류: {e}")

    if not rows:
        raise HTTPException(status_code=422, detail="파일에 데이터 행이 없습니다.")

    # ── validate + diff (read-only) ──
    session = get_session()
    try:
        if mode == "strict":
            result: ValidationResult = validate_strict(rows, session)
        else:
            result = validate_lenient(rows, session)

        if mode == "strict" and result.errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "mode": mode,
                    "total_rows": len(rows),
                    "valid_rows": 0,
                    "errors": [{"row": r, "message": m} for r, m in result.errors],
                    "warnings": result.warnings,
                },
            )

        # dry-run diff
        diff = import_from_rows(session, result.valid_rows, dry_run=True)
    finally:
        session.close()

    batch_id = f"batch_{uuid.uuid4().hex[:16]}"
    trace_id = _compute_trace_id(content, mode)

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "batch_id": batch_id,
            "trace_id": trace_id,
            "mode": mode,
            "total_rows": len(rows),
            "valid_rows": len(result.valid_rows),
            "diff": _diff_to_summary(diff),
            "errors": [{"row": r, "message": m} for r, m in result.errors],
            "warnings": result.warnings,
        },
    )


@router.post("/classified/confirm")
async def confirm_import(
    file: UploadFile = File(...),
    mode: str = Form("strict"),
    trace_id: Optional[str] = Form(None),
) -> JSONResponse:
    """분류 결과 파일 → validate → DB commit.

    trace_id 기반 멱등성: 같은 trace_id 로 재confirm 시 DB 재쓰기 없이 동일 응답 반환.
    """
    # ── 파라미터 검증 ──
    if mode not in ("strict", "lenient"):
        raise HTTPException(status_code=422, detail="mode 는 'strict' 또는 'lenient' 여야 합니다.")

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=422, detail="빈 파일은 업로드할 수 없습니다.")

    if len(content) > MAX_IMPORT_FILE_BYTES:
        limit_mb = MAX_IMPORT_FILE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 {limit_mb}MB 를 초과합니다.",
        )

    filename = file.filename or ""
    if not (filename.lower().endswith(".jsonl") or filename.lower().endswith(".csv")):
        raise HTTPException(
            status_code=422,
            detail="파일 형식은 .jsonl 또는 .csv 여야 합니다.",
        )

    # ── 멱등성 체크 ──
    computed_trace_id = _compute_trace_id(content, mode)
    effective_trace_id = trace_id or computed_trace_id

    if effective_trace_id in _confirmed_traces:
        return JSONResponse(
            status_code=200,
            content={**_confirmed_traces[effective_trace_id], "idempotent": True},
        )

    # ── 파싱 ──
    try:
        rows = _parse_uploaded_file(content, filename)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"파일 파싱 오류: {e}")

    if not rows:
        raise HTTPException(status_code=422, detail="파일에 데이터 행이 없습니다.")

    # ── validate + commit ──
    with managed_session() as session:
        if mode == "strict":
            result: ValidationResult = validate_strict(rows, session)
        else:
            result = validate_lenient(rows, session)

        if mode == "strict" and result.errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "trace_id": effective_trace_id,
                    "mode": mode,
                    "total_rows": len(rows),
                    "valid_rows": 0,
                    "errors": [{"row": r, "message": m} for r, m in result.errors],
                    "warnings": result.warnings,
                    "failure_csv_url": f"/api/import/classified/failure-csv/{effective_trace_id}",
                    "idempotent": False,
                },
            )

        diff = import_from_rows(session, result.valid_rows, dry_run=False)

    # ── 실패 행 CSV 저장 (failure_csv_url 용) ──
    _failure_rows_store[effective_trace_id] = result.errors

    response_body: dict = {
        "ok": True,
        "trace_id": effective_trace_id,
        "mode": mode,
        "total_rows": len(rows),
        "valid_rows": len(result.valid_rows),
        "inserted": len(diff.to_add),
        "updated": len(diff.to_update),
        "conflicts": len(diff.conflicts),
        "skipped": diff.unchanged,
        "errors": [{"row": r, "message": m} for r, m in result.errors],
        "warnings": result.warnings,
        "failure_csv_url": (
            f"/api/import/classified/failure-csv/{effective_trace_id}"
            if result.errors
            else None
        ),
        "idempotent": False,
    }

    # 멱등성 캐시에 저장
    _confirmed_traces[effective_trace_id] = response_body

    return JSONResponse(status_code=200, content=response_body)


# ── 실패 행 저장소 ─────────────────────────────────────────────────────────────
# trace_id → list[(row_index, message)]
_failure_rows_store: dict[str, list[tuple[int, str]]] = {}


@router.get("/classified/failure-csv/{trace_id}")
async def download_failure_csv(trace_id: str) -> StreamingResponse:
    """confirm 시 실패한 row 목록을 CSV 로 다운로드한다."""
    errors = _failure_rows_store.get(trace_id)
    if errors is None:
        raise HTTPException(status_code=404, detail=f"trace_id '{trace_id}' 에 해당하는 실패 데이터가 없습니다.")

    csv_text = _make_failure_csv(errors)
    return StreamingResponse(
        content=iter([csv_text.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=failures_{trace_id}.csv"},
    )
