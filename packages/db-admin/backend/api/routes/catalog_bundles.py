"""Capstone catalog bundle preview/apply/review-report endpoints."""
from __future__ import annotations

import csv
import html
import io

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from api.auth import require_moderator
from config import settings
from services.backup import create_backup
from services.base import get_session, managed_session
from services.catalog_bundle import apply_bundle, parse_bundle, validate_bundle
from services.public_snapshot_publisher import public_snapshot_path
from services.public_snapshot_v2 import (
    build_public_snapshot,
    previous_snapshot_path,
    rollback_public_snapshot,
    validate_public_snapshot,
)

router = APIRouter(prefix="/catalog-bundles", tags=["catalog-bundles"])
MAX_BUNDLE_BYTES = 50 * 1024 * 1024


@router.get("/snapshot/status")
def catalog_snapshot_status(identity: dict = Depends(require_moderator)):
    target = public_snapshot_path()
    previous = previous_snapshot_path(target)
    return {
        "approved": validate_public_snapshot(target) if target.is_file() else None,
        "rollback": validate_public_snapshot(previous) if previous.is_file() else None,
        "path": str(target),
    }


@router.post("/snapshot/publish")
def publish_catalog_snapshot(identity: dict = Depends(require_moderator)):
    """Explicit moderator approval boundary for the public catalog read model."""
    return build_public_snapshot(public_snapshot_path())


@router.post("/snapshot/rollback")
def rollback_catalog_snapshot(identity: dict = Depends(require_moderator)):
    try:
        return rollback_public_snapshot(public_snapshot_path())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _read(file: UploadFile) -> tuple[dict, str]:
    content = await file.read(MAX_BUNDLE_BYTES + 1)
    if len(content) > MAX_BUNDLE_BYTES:
        raise HTTPException(status_code=413, detail="catalog bundle은 50MB를 초과할 수 없습니다")
    try:
        return parse_bundle(content, file.filename or "bundle.json")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/preview")
async def preview_catalog_bundle(
    file: UploadFile = File(...),
    identity: dict = Depends(require_moderator),
):
    bundle, file_hash = await _read(file)
    session = get_session()
    try:
        result = validate_bundle(session, bundle, file_hash)
    finally:
        session.close()
    return result.as_dict()


@router.post("/apply")
async def apply_catalog_bundle(
    file: UploadFile = File(...),
    identity: dict = Depends(require_moderator),
):
    bundle, file_hash = await _read(file)
    session = get_session()
    try:
        validation = validate_bundle(session, bundle, file_hash)
    finally:
        session.close()
    if not validation.ok:
        raise HTTPException(status_code=422, detail=validation.as_dict())

    # File-backed SQLite receives a hot backup before the single apply
    # transaction. In-memory tests and non-SQLite deployments skip this step.
    backup_path = None
    if settings.DATABASE_URL.startswith("sqlite") and ":memory:" not in settings.DATABASE_URL:
        try:
            backup_path = create_backup(settings.DATABASE_URL, reason="catalog-bundle")
        except FileNotFoundError:
            # A clean checkout can create the DB during app startup; no previous
            # state exists to protect in that case.
            backup_path = None

    try:
        with managed_session() as tx:
            result = apply_bundle(
                tx,
                bundle,
                file_hash,
                user=str(identity.get("username") or identity.get("sub") or "moderator"),
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result["backup_path"] = backup_path
    return result


@router.post("/review-report")
async def catalog_bundle_review_report(
    file: UploadFile = File(...),
    format: str = Query("csv", pattern="^(csv|html)$"),
    identity: dict = Depends(require_moderator),
):
    bundle, file_hash = await _read(file)
    session = get_session()
    try:
        result = validate_bundle(session, bundle, file_hash)
    finally:
        session.close()

    rows = []
    for index, row in enumerate(bundle.get("products", [])):
        confidence = float(row.get("classification_confidence", 1.0))
        if confidence < 0.80 or row.get("review_status") not in {None, "auto", "approved"}:
            rows.append({
                "kind": "product",
                "id": row.get("public_product_id"),
                "name": row.get("canonical_name"),
                "category": row.get("unified_category_id"),
                "confidence": confidence,
                "status": row.get("review_status") or "pending",
                "reason": "low_confidence" if confidence < 0.80 else "review_status",
            })
    for index, row in enumerate(bundle.get("unresolved", [])):
        rows.append({
            "kind": "unresolved", "id": row.get("raw_record_id") or index,
            "name": row.get("source_title") or row.get("name"),
            "category": row.get("proposed_category_id"),
            "confidence": row.get("confidence"), "status": "pending",
            "reason": row.get("reason") or "unresolved",
        })

    if format == "html":
        body = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(row.get(key) or ''))}</td>" for key in ("kind", "id", "name", "category", "confidence", "status", "reason")) + "</tr>"
            for row in rows
        )
        document = (
            "<!doctype html><meta charset='utf-8'><title>WalletSaver 분류 검수 보고서</title>"
            "<style>body{font-family:sans-serif;margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}</style>"
            f"<h1>분류 검수 보고서</h1><p>bundle {html.escape(file_hash[:12])} · 오류 {len(result.errors)} · 경고 {len(result.warnings)}</p>"
            "<table><thead><tr><th>종류</th><th>ID</th><th>이름</th><th>카테고리</th><th>신뢰도</th><th>상태</th><th>사유</th></tr></thead>"
            f"<tbody>{body}</tbody></table>"
        )
        return HTMLResponse(document)

    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=["kind", "id", "name", "category", "confidence", "status", "reason"])
    writer.writeheader()
    writer.writerows(rows)
    return StreamingResponse(
        iter([stream.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=catalog-review.csv"},
    )
