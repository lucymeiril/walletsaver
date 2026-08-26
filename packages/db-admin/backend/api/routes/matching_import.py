"""
외부 분류 결과 import HTTP 엔드포인트.

모든 import 엔드포인트는 db-admin의 moderator 이상 인증을 요구한다. 로컬 개발에서
REQUIRE_AUTH=false이면 기존처럼 anonymous admin identity로 동작한다.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from api.auth import require_moderator
from services.base import get_session, managed_session
from services.import_validator import ValidationResult, validate_lenient, validate_strict
from services.matching_sync import ImportDiff, import_from_rows

router = APIRouter(
    prefix="/import",
    tags=["import"],
    dependencies=[Depends(require_moderator)],
)

logger = logging.getLogger(__name__)
MAX_IMPORT_FILE_BYTES: int = 50 * 1024 * 1024
_confirmed_traces: dict[str, dict] = {}
_failure_rows_store: dict[str, list[tuple[int, str]]] = {}


def _parse_uploaded_file(content: bytes, filename: str) -> list[dict]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"UTF-8 디코딩 실패: {exc}") from exc

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
            for key, value in row.items():
                if key is None:
                    continue
                key = key.strip()
                if value is None or value == "":
                    parsed[key] = None
                    continue
                if key in ("confidence", "pack_qty"):
                    try:
                        parsed[key] = float(value)
                    except (ValueError, TypeError):
                        parsed[key] = value
                elif key == "keyword_ids":
                    try:
                        parsed[key] = json.loads(value)
                    except (json.JSONDecodeError, TypeError):
                        parsed[key] = value
                else:
                    parsed[key] = value.strip() if isinstance(value, str) else value
            rows.append(parsed)
        return rows

    raise ValueError(f"지원하지 않는 파일 형식 '{filename}'. .jsonl 또는 .csv 만 허용")


def _compute_trace_id(content: bytes, mode: str) -> str:
    digest = hashlib.sha256(content + mode.encode()).hexdigest()
    return f"tr_{digest[:32]}"


def _diff_to_summary(diff: ImportDiff) -> dict:
    return {
        "added": len(diff.to_add),
        "updated": len(diff.to_update),
        "conflicts": len(diff.conflicts),
        "unchanged": diff.unchanged,
        "total_incoming": diff.total_incoming,
        "preview_rows": [
            {
                "match_key": row.get("match_key"),
                "action": "add",
                "category_id": row.get("category_id"),
                "confidence": row.get("confidence"),
                "source": row.get("source"),
            }
            for row in diff.to_add[:25]
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
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["row_index", "error_message"])
    for row_idx, message in error_rows:
        writer.writerow([row_idx, message])
    return buf.getvalue()


def _validate_upload(content: bytes, filename: str, mode: str) -> list[dict]:
    if mode not in ("strict", "lenient"):
        raise HTTPException(status_code=422, detail="mode 는 'strict' 또는 'lenient' 여야 합니다.")
    if not content:
        raise HTTPException(status_code=422, detail="빈 파일은 업로드할 수 없습니다.")
    if len(content) > MAX_IMPORT_FILE_BYTES:
        limit_mb = MAX_IMPORT_FILE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"파일 크기가 {limit_mb}MB 를 초과합니다.")
    if not (filename.lower().endswith(".jsonl") or filename.lower().endswith(".csv")):
        raise HTTPException(status_code=422, detail="파일 형식은 .jsonl 또는 .csv 여야 합니다.")
    try:
        rows = _parse_uploaded_file(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"파일 파싱 오류: {exc}") from exc
    if not rows:
        raise HTTPException(status_code=422, detail="파일에 데이터 행이 없습니다.")
    return rows


@router.post("/classified/preview")
async def preview_import(
    file: UploadFile = File(...),
    mode: str = Form("strict"),
) -> JSONResponse:
    content = await file.read()
    rows = _validate_upload(content, file.filename or "", mode)

    session = get_session()
    try:
        result: ValidationResult = (
            validate_strict(rows, session) if mode == "strict" else validate_lenient(rows, session)
        )
        if mode == "strict" and result.errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "mode": mode,
                    "total_rows": len(rows),
                    "valid_rows": 0,
                    "errors": [{"row": row, "message": message} for row, message in result.errors],
                    "warnings": result.warnings,
                },
            )
        diff = import_from_rows(session, result.valid_rows, dry_run=True)
    finally:
        session.close()

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "batch_id": f"batch_{uuid.uuid4().hex[:16]}",
            "trace_id": _compute_trace_id(content, mode),
            "mode": mode,
            "total_rows": len(rows),
            "valid_rows": len(result.valid_rows),
            "diff": _diff_to_summary(diff),
            "errors": [{"row": row, "message": message} for row, message in result.errors],
            "warnings": result.warnings,
        },
    )


@router.post("/classified/confirm")
async def confirm_import(
    file: UploadFile = File(...),
    mode: str = Form("strict"),
    trace_id: Optional[str] = Form(None),
) -> JSONResponse:
    content = await file.read()
    rows = _validate_upload(content, file.filename or "", mode)

    computed_trace_id = _compute_trace_id(content, mode)
    effective_trace_id = trace_id or computed_trace_id
    if effective_trace_id in _confirmed_traces:
        return JSONResponse(
            status_code=200,
            content={**_confirmed_traces[effective_trace_id], "idempotent": True},
        )

    with managed_session() as session:
        result: ValidationResult = (
            validate_strict(rows, session) if mode == "strict" else validate_lenient(rows, session)
        )
        if mode == "strict" and result.errors:
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "trace_id": effective_trace_id,
                    "mode": mode,
                    "total_rows": len(rows),
                    "valid_rows": 0,
                    "errors": [{"row": row, "message": message} for row, message in result.errors],
                    "warnings": result.warnings,
                    "failure_csv_url": f"/api/import/classified/failure-csv/{effective_trace_id}",
                    "idempotent": False,
                },
            )
        diff = import_from_rows(session, result.valid_rows, dry_run=False)

    _failure_rows_store[effective_trace_id] = result.errors
    response_body = {
        "ok": True,
        "trace_id": effective_trace_id,
        "mode": mode,
        "total_rows": len(rows),
        "valid_rows": len(result.valid_rows),
        "inserted": len(diff.to_add),
        "updated": len(diff.to_update),
        "conflicts": len(diff.conflicts),
        "skipped": diff.unchanged,
        "errors": [{"row": row, "message": message} for row, message in result.errors],
        "warnings": result.warnings,
        "failure_csv_url": (
            f"/api/import/classified/failure-csv/{effective_trace_id}"
            if result.errors
            else None
        ),
        "idempotent": False,
    }
    _confirmed_traces[effective_trace_id] = response_body
    return JSONResponse(status_code=200, content=response_body)


@router.get("/classified/failure-csv/{trace_id}")
async def download_failure_csv(trace_id: str) -> StreamingResponse:
    errors = _failure_rows_store.get(trace_id)
    if errors is None:
        raise HTTPException(status_code=404, detail=f"trace_id '{trace_id}' 에 해당하는 실패 데이터가 없습니다.")

    csv_text = _make_failure_csv(errors)
    return StreamingResponse(
        content=iter([csv_text.encode("utf-8")]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=failures_{trace_id}.csv"},
    )
