"""external_import.py — RD8 L3 외부 LLM 분류 결과 import HTTP 엔드포인트.

엔드포인트:
    POST /api/external-import/{file_type}/preview   — 파일 업로드 → 검증 → dry-run 미리보기
    POST /api/external-import/{file_type}/apply     — 파일 업로드 → 검증 → DB 적용
    GET  /api/external-import/history?limit=20      — import 이력 조회

file_type 허용값:
    matching    — matching_updates.jsonl
    categories  — categories_keywords_updates.yaml
    products    — products_updates.jsonl

파일 형식:
    matching, products: JSONL (.jsonl) 또는 JSON 배열 (.json)
    categories:         YAML (.yaml / .yml)

운영자 안내 (잘못된 파일 드롭 시):
    - 파일 형식이 file_type과 맞지 않으면 422 + 명확한 오류 메시지 반환
    - ValidationReport 내 failed_items로 행별 오류 사유 확인 가능
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.auth import require_admin
from services.base import managed_session, get_session
from services.external_classification_import import (
    _VALID_FILE_TYPES,
    apply_import,
    preview_import,
)
from storage.models import ImportsAudit

router = APIRouter(prefix="/external-import", tags=["external-import"])
logger = logging.getLogger(__name__)

_MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB
_VALID_FILE_TYPE_LIST = sorted(_VALID_FILE_TYPES)


# ── 파일 파싱 헬퍼 ─────────────────────────────────────────────────────────────

def _parse_payload(content: bytes, filename: str, file_type: str) -> tuple[Any, bytes]:
    """업로드된 파일 바이트를 file_type에 맞게 파싱한다.

    잘못된 파일을 잘못된 endpoint에 업로드하면 ValueError가 발생하여
    422 응답으로 운영자에게 명확한 오류 안내가 제공된다.

    Returns:
        (parsed_payload, raw_bytes)
    """
    fname_lower = (filename or "").lower()
    text = content.decode("utf-8-sig")

    # ── categories: YAML ────────────────────────────────────────────────────
    if file_type == "categories":
        if fname_lower.endswith(".jsonl") or fname_lower.endswith(".json"):
            raise ValueError(
                f"categories 파일은 YAML(.yaml/.yml)이어야 합니다. "
                f"'{filename}' 파일이 업로드되었습니다. "
                f"올바른 파일: categories_keywords_updates.yaml"
            )
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"YAML 파싱 오류: {exc}") from exc
        if data is None:
            data = {"categories": [], "keywords": []}
        if not isinstance(data, dict):
            raise ValueError(
                "YAML 최상위 구조는 dict여야 합니다. "
                "예: {categories: [...], keywords: [...]}"
            )
        return data, content

    # ── matching / products: JSONL 또는 JSON 배열 ───────────────────────────
    if fname_lower.endswith((".yaml", ".yml")):
        raise ValueError(
            f"{file_type} 파일은 JSONL(.jsonl) 또는 JSON(.json)이어야 합니다. "
            f"'{filename}' YAML 파일이 업로드되었습니다. "
            f"올바른 파일: {file_type}_updates.jsonl"
        )

    if fname_lower.endswith(".json"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 파싱 오류: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError("JSON 최상위 구조는 배열(list)이어야 합니다.")
        return data, content

    # JSONL (기본)
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
            raise ValueError(f"JSONL 라인 {lineno}은 dict여야 합니다.")
        rows.append(obj)
    return rows, content


# ── 엔드포인트 ─────────────────────────────────────────────────────────────────

@router.post("/{file_type}/preview")
async def preview_endpoint(
    file_type: str,
    file: UploadFile = File(...),
    identity: dict = Depends(require_admin),
) -> JSONResponse:
    """외부 LLM 분류 결과 파일 → 검증 → dry-run 미리보기.

    DB에 아무것도 쓰지 않는다.

    운영자 드래그&드롭 시:
        - file_type이 URL과 다른 파일을 올리면 422 + 오류 메시지
        - ValidationReport.failed_items로 행별 오류 확인 가능
    """
    if file_type not in _VALID_FILE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"file_type '{file_type}' 은 지원하지 않습니다. "
                f"허용값: {_VALID_FILE_TYPE_LIST}"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="빈 파일은 업로드할 수 없습니다.")
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 {_MAX_FILE_BYTES // (1024 * 1024)}MB를 초과합니다.",
        )

    filename = file.filename or ""

    try:
        payload, raw_bytes = _parse_payload(content, filename, file_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"파일 파싱 오류: {exc}",
        )

    session = get_session()
    try:
        report = preview_import(file_type, payload, session)
    finally:
        session.close()

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "importer": identity.get("email", "anonymous"),
            **report.to_dict(),
        },
    )


@router.post("/{file_type}/apply")
async def apply_endpoint(
    file_type: str,
    file: UploadFile = File(...),
    identity: dict = Depends(require_admin),
) -> JSONResponse:
    """외부 LLM 분류 결과 파일 → 검증 → DB 적용.

    트랜잭션 1개로 처리. 실패 시 자동 롤백.
    audit log row가 imports_audit 테이블에 기록된다.

    멱등성:
        같은 파일을 2회 apply해도 DB 상태는 변화 없음.
        audit 기록은 2건.
    """
    if file_type not in _VALID_FILE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"file_type '{file_type}' 은 지원하지 않습니다. "
                f"허용값: {_VALID_FILE_TYPE_LIST}"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="빈 파일은 업로드할 수 없습니다.")
    if len(content) > _MAX_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"파일 크기가 {_MAX_FILE_BYTES // (1024 * 1024)}MB를 초과합니다.",
        )

    filename = file.filename or ""

    try:
        payload, raw_bytes = _parse_payload(content, filename, file_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"파일 파싱 오류: {exc}",
        )

    importer = identity.get("email", "anonymous")

    try:
        with managed_session() as session:
            result = apply_import(
                file_type,
                payload,
                raw_bytes,
                session,
                dry_run=False,
                importer=importer,
            )
    except Exception as exc:
        logger.exception("apply_import 실패: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"import 적용 중 오류 발생: {exc}",
        )

    if not result.ok:
        return JSONResponse(
            status_code=422,
            content={
                "ok": False,
                "file_type": result.file_type,
                "file_hash": result.file_hash,
                "error": result.error,
                "counts": result.counts,
            },
        )

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "file_type": result.file_type,
            "file_hash": result.file_hash,
            "importer": importer,
            "counts": result.counts,
        },
    )


@router.get("/history")
async def history_endpoint(
    limit: int = Query(default=20, ge=1, le=200),
    file_type: Optional[str] = Query(default=None),
    identity: dict = Depends(require_admin),
) -> JSONResponse:
    """import 이력 조회.

    Args:
        limit:      최근 N건 (기본 20, 최대 200)
        file_type:  matching | categories | products (None이면 전체)
    """
    session = get_session()
    try:
        q = session.query(ImportsAudit).order_by(ImportsAudit.timestamp.desc())
        if file_type and file_type in _VALID_FILE_TYPES:
            q = q.filter(ImportsAudit.file_type == file_type)
        rows = q.limit(limit).all()

        items = [
            {
                "id": r.id,
                "file_type": r.file_type,
                "file_hash": r.file_hash[:12] + "…",
                "importer": r.importer,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "dry_run": r.dry_run,
                "total_rows": r.total_rows,
                "passed_rows": r.passed_rows,
                "ok": r.ok,
                "counts": r.applied_counts,
                "error_message": r.error_message,
            }
            for r in rows
        ]
    finally:
        session.close()

    return JSONResponse(
        status_code=200,
        content={"ok": True, "total": len(items), "items": items},
    )
