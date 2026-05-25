"""import_bundle.py — RD7 3종 파일 번들 import HTTP 엔드포인트.

엔드포인트:
    POST /api/import/bundle/preview  — 3종 파일 → 통합 diff 반환 (DB 무변경)
    POST /api/import/bundle/confirm  — 3종 파일 → 실제 적용 (트랜잭션)
    GET  /api/import/bundle/{batch_id}/failures.csv — 실패 행 CSV 다운로드

멱등성:
    batch_id = 사용자 제공 또는 서버 생성 (imp-YYYYMMDDHHMMSS-<8hex>).
    같은 batch_id confirm 두 번 → 두 번째는 idempotent=True 반환, DB 재쓰기 없음.

충돌 정책: matching_sync.py 참조 (human > external-ai > crawler-auto).

기존 /api/import/classified/* 엔드포인트는 [deprecated] 표시만 하고 제거하지 않는다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from services.base import get_session, managed_session
from services.bundle_import import (
    BundlePreview,
    BundleResult,
    apply_bundle,
    compute_bundle_preview,
    make_failure_csv,
    parse_jsonl,
    parse_yaml,
)

router = APIRouter(prefix="/import", tags=["import-bundle"])
logger = logging.getLogger(__name__)

MAX_BUNDLE_FILE_BYTES: int = 50 * 1024 * 1024  # 50 MB

# ── In-memory 멱등성 저장소 ──────────────────────────────────────────────────
# batch_id → BundleResult dict  (프로세스 재시작 시 초기화)
_confirmed_bundles: dict[str, dict] = {}

# batch_id → failure_rows list
_bundle_failures: dict[str, list[dict]] = {}


def _gen_batch_id() -> str:
    """imp-YYYYMMDDHHMMSS-<8hex> 형식 batch_id 생성."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    rand = uuid.uuid4().hex[:8]
    return f"imp-{ts}-{rand}"


def _preview_to_dict(prev: BundlePreview) -> dict:
    return {
        "batch_id": prev.batch_id,
        "matching": {
            "to_add": prev.matching.to_add,
            "to_update": prev.matching.to_update,
            "conflicts": prev.matching.conflicts,
            "pending_human": prev.matching.pending_human,
        },
        "taxonomy": {
            "new_categories": prev.taxonomy.new_categories,
            "new_keywords": prev.taxonomy.new_keywords,
            "merges": prev.taxonomy.merges,
            "errors": prev.taxonomy.errors,
        },
        "products": {
            "to_add": prev.products.to_add,
            "skipped_no_match": prev.products.skipped_no_match,
            "errors": prev.products.errors,
        },
    }


def _result_to_dict(res: BundleResult) -> dict:
    return {
        "ok": res.ok,
        "batch_id": res.batch_id,
        "matching_inserted": res.matching_inserted,
        "matching_updated": res.matching_updated,
        "matching_conflicts": res.matching_conflicts,
        "taxonomy_categories_added": res.taxonomy_categories_added,
        "taxonomy_keywords_added": res.taxonomy_keywords_added,
        "products_added": res.products_added,
        "products_skipped": res.products_skipped,
        "failure_rows": res.failure_rows,
        "failure_csv_url": (
            f"/api/import/bundle/{res.batch_id}/failures.csv"
            if res.failure_rows else None
        ),
        "idempotent": res.idempotent,
    }


async def _read_optional_file(f: Optional[UploadFile]) -> Optional[bytes]:
    if f is None:
        return None
    content = await f.read()
    if not content:
        return None
    if len(content) > MAX_BUNDLE_FILE_BYTES:
        limit_mb = MAX_BUNDLE_FILE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"파일 '{f.filename}' 크기가 {limit_mb}MB 를 초과합니다.",
        )
    return content


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/import/bundle/preview
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/bundle/preview")
async def bundle_preview(
    matching_file: Optional[UploadFile] = File(None),
    taxonomy_file: Optional[UploadFile] = File(None),
    products_file: Optional[UploadFile] = File(None),
    batch_id: Optional[str] = Form(None),
    mode: str = Form("strict"),
) -> JSONResponse:
    """3종 파일을 받아 통합 diff를 반환한다. DB에 아무것도 쓰지 않는다.

    - matching_file: matching_updates.jsonl
    - taxonomy_file: categories_keywords_updates.yaml
    - products_file: products.jsonl
    """
    if mode not in ("strict", "lenient"):
        raise HTTPException(status_code=422, detail="mode 는 'strict' 또는 'lenient' 여야 합니다.")

    if not any([matching_file, taxonomy_file, products_file]):
        raise HTTPException(status_code=422, detail="최소 1개 파일이 필요합니다.")

    # 파일 읽기
    m_content = await _read_optional_file(matching_file)
    t_content = await _read_optional_file(taxonomy_file)
    p_content = await _read_optional_file(products_file)

    # 파싱
    try:
        m_rows = parse_jsonl(m_content) if m_content else None
        t_data = parse_yaml(t_content) if t_content else None
        p_rows = parse_jsonl(p_content) if p_content else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"파일 파싱 오류: {e}")

    effective_batch_id = batch_id or _gen_batch_id()

    session = get_session()
    try:
        preview = compute_bundle_preview(
            session=session,
            batch_id=effective_batch_id,
            matching_rows=m_rows,
            taxonomy_data=t_data,
            products_rows=p_rows,
        )
    finally:
        session.close()

    return JSONResponse(status_code=200, content=_preview_to_dict(preview))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/import/bundle/confirm
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/bundle/confirm")
async def bundle_confirm(
    matching_file: Optional[UploadFile] = File(None),
    taxonomy_file: Optional[UploadFile] = File(None),
    products_file: Optional[UploadFile] = File(None),
    batch_id: Optional[str] = Form(None),
    mode: str = Form("strict"),
) -> JSONResponse:
    """3종 파일을 받아 실제 DB에 적용한다.

    트랜잭션 순서: matching → categories/keywords → products.
    mode='strict' : 어느 단계 실패라도 전체 rollback.
    mode='lenient': 실패 row skip, 나머지 commit.
    멱등성: 같은 batch_id 재호출 시 idempotent=True 반환, DB 재쓰기 없음.
    """
    if mode not in ("strict", "lenient"):
        raise HTTPException(status_code=422, detail="mode 는 'strict' 또는 'lenient' 여야 합니다.")

    if not any([matching_file, taxonomy_file, products_file]):
        raise HTTPException(status_code=422, detail="최소 1개 파일이 필요합니다.")

    effective_batch_id = batch_id or _gen_batch_id()

    # ── 멱등성 체크 ──
    if effective_batch_id in _confirmed_bundles:
        cached = _confirmed_bundles[effective_batch_id]
        return JSONResponse(status_code=200, content={**cached, "idempotent": True})

    # 파일 읽기
    m_content = await _read_optional_file(matching_file)
    t_content = await _read_optional_file(taxonomy_file)
    p_content = await _read_optional_file(products_file)

    # 파싱
    try:
        m_rows = parse_jsonl(m_content) if m_content else None
        t_data = parse_yaml(t_content) if t_content else None
        p_rows = parse_jsonl(p_content) if p_content else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"파일 파싱 오류: {e}")

    # ── 적용 ──
    try:
        with managed_session() as session:
            result = apply_bundle(
                session=session,
                batch_id=effective_batch_id,
                matching_rows=m_rows,
                taxonomy_data=t_data,
                products_rows=p_rows,
                mode=mode,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"번들 적용 실패: {e}")

    # 멱등성 캐시 저장
    response_body = _result_to_dict(result)
    _confirmed_bundles[effective_batch_id] = response_body

    # 실패 행 저장소
    if result.failure_rows:
        _bundle_failures[effective_batch_id] = result.failure_rows

    return JSONResponse(status_code=200, content=response_body)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/import/bundle/{batch_id}/failures.csv
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/bundle/{batch_id}/failures.csv")
async def bundle_failures_csv(batch_id: str) -> StreamingResponse:
    """confirm 시 실패한 행 목록을 UTF-8 BOM CSV로 다운로드한다."""
    failure_rows = _bundle_failures.get(batch_id)
    if failure_rows is None:
        raise HTTPException(
            status_code=404,
            detail=f"batch_id '{batch_id}' 에 해당하는 실패 데이터가 없습니다.",
        )

    csv_bytes = make_failure_csv(failure_rows)
    return StreamingResponse(
        content=iter([csv_bytes]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=failures_{batch_id}.csv",
        },
    )
