"""통합 카탈로그 동기화 API (Phase 1: export + dry-run validate + logs).

모든 엔드포인트는 require_admin. apply/재분류는 Phase 2/3에서 추가한다.
"""
from __future__ import annotations

import io
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import File as FastFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from api.auth import require_admin
from config import settings
from services.base import get_session, managed_session
from services.catalog_sync import apply as apply_svc
from services.catalog_sync import export as export_svc
from services.catalog_sync import recategorize as recat_svc
from services.catalog_sync import restore as restore_svc
from services.catalog_sync import validate as validate_svc
from services.catalog_sync.log import record_log
from storage.models import CatalogSyncLog

router = APIRouter(prefix="/admin/catalog-sync", tags=["admin", "catalog-sync"])

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "catalog-sync"

_VALID_ENTITIES = set(export_svc.ENTITIES)


def _stamp_dir(prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACT_ROOT / f"{prefix}-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class ExportRequest(BaseModel):
    entities: list[str]
    scopes: dict[str, dict[str, Any]] | None = None


@router.post("/export")
def export_catalog_endpoint(body: ExportRequest, identity: dict = Depends(require_admin)) -> JSONResponse:
    invalid = [e for e in body.entities if e not in _VALID_ENTITIES]
    if invalid:
        raise HTTPException(422, f"지원하지 않는 엔티티: {invalid} (허용: {sorted(_VALID_ENTITIES)})")
    if not body.entities:
        raise HTTPException(422, "엔티티를 1개 이상 선택해야 합니다.")

    out_dir = _stamp_dir("export")
    session = get_session()
    try:
        result = export_svc.export_catalog(
            out_dir, session, entities=body.entities, scopes=body.scopes
        )
    except ValueError as e:
        session.close()
        raise HTTPException(422, str(e)) from e
    finally:
        if session.is_active:
            session.close()

    with managed_session() as log_session:
        record_log(
            log_session,
            operation="export",
            entities=result.entities,
            scope=result.scope,
            counts=result.counts,
            user=identity.get("email", "anonymous"),
            dry_run=False,
            ok=True,
        )
    return JSONResponse({
        "ok": True,
        "name": out_dir.name,
        "out_dir": str(out_dir),
        "manifest_path": str(out_dir / "manifest.json"),
        "manifest": result.to_dict(),
    })


@router.get("/export/download")
def download_export(name: str, identity: dict = Depends(require_admin)) -> StreamingResponse:
    """이전에 생성한 export 번들 폴더(name)를 zip으로 묶어 다운로드한다."""
    safe = Path(name).name
    root = ARTIFACT_ROOT.resolve()
    target = (root / safe).resolve()
    if target.parent != root or not target.is_dir():
        raise HTTPException(404, "내보내기 결과를 찾을 수 없습니다.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(target.iterdir()):
            if fpath.is_file():
                zf.write(fpath, arcname=fpath.name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )


def _save_uploads(files: list[UploadFile]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="catsync_in_"))
    have_manifest = False
    for uf in files:
        name = Path(uf.filename or "").name
        if not name:
            continue
        if name == "manifest.json":
            have_manifest = True
        dest = tmp / name
        dest.write_bytes(uf.file.read())
    if not have_manifest:
        raise HTTPException(422, "manifest.json이 업로드에 포함되어야 합니다.")
    return tmp


@router.post("/validate")
def validate_catalog_endpoint(
    files: list[UploadFile] = FastFile(...),
    mode: str = "upsert",
    force: bool = False,
    identity: dict = Depends(require_admin),
) -> JSONResponse:
    """업로드한 export 번들(manifest.json + *.jsonl)을 dry-run 검증한다. DB 미변경."""
    in_dir = _save_uploads(files)
    try:
        report = validate_svc.validate_import(get_session(), in_dir, mode=mode, force=force)
    except (FileNotFoundError, ValueError) as e:
        with managed_session() as log_session:
            record_log(log_session, operation="validate", dry_run=True, ok=False,
                       user=identity.get("email", "anonymous"), error_message=str(e))
        raise HTTPException(422, str(e)) from e

    with managed_session() as log_session:
        record_log(
            log_session,
            operation="validate",
            entities=report.entities,
            mode=report.mode,
            counts={k: v.to_dict() for k, v in report.diff.items()},
            user=identity.get("email", "anonymous"),
            dry_run=True,
            ok=report.ok,
            error_message="; ".join(report.errors[:5]) if report.errors else None,
        )
    return JSONResponse(report.to_dict())


@router.post("/apply")
def apply_catalog_endpoint(
    files: list[UploadFile] = FastFile(...),
    mode: str = "upsert",
    force: bool = False,
    identity: dict = Depends(require_admin),
) -> JSONResponse:
    """업로드한 export 번들을 검증→백업→upsert 적용한다. 검증 실패 시 변경 없이 거부."""
    in_dir = _save_uploads(files)
    user = identity.get("email", "anonymous")
    try:
        with managed_session() as session:
            result = apply_svc.apply_import(
                session, in_dir,
                mode=mode, force=force,
                database_url=settings.DATABASE_URL,
                make_snapshot=True,
            )
    except ValueError as e:
        with managed_session() as log_session:
            record_log(log_session, operation="apply", mode=mode, force=force,
                       dry_run=False, ok=False, user=user, error_message=str(e))
        raise HTTPException(422, str(e)) from e

    with managed_session() as log_session:
        record_log(
            log_session,
            operation="apply",
            entities=result.entities,
            mode=result.mode,
            counts=result.counts,
            file_hash=result.file_hash,
            snapshot_path=result.snapshot_path,
            user=user,
            dry_run=False,
            force=result.force,
            ok=result.ok,
            error_message=result.error_message,
        )
    status = 200 if result.ok else 422
    return JSONResponse(result.to_dict(), status_code=status)


class RecategorizeRequest(BaseModel):
    scope: dict[str, Any] | None = None
    force: bool = False


@router.post("/recategorize/preview")
def recategorize_preview_endpoint(
    body: RecategorizeRequest, identity: dict = Depends(require_admin)
) -> JSONResponse:
    """매칭규칙으로 상품 재분류 시 영향 미리보기. DB 미변경."""
    session = get_session()
    try:
        preview = recat_svc.preview_recategorization(
            session, scope=body.scope, force=body.force
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    finally:
        session.close()
    return JSONResponse(preview.to_dict())


@router.post("/recategorize/apply")
def recategorize_apply_endpoint(
    body: RecategorizeRequest, identity: dict = Depends(require_admin)
) -> JSONResponse:
    """매칭규칙으로 상품 카테고리 일괄 재분류 적용(스냅샷 선행)."""
    user = identity.get("email", "anonymous")
    try:
        with managed_session() as session:
            result = recat_svc.apply_recategorization(
                session, scope=body.scope, force=body.force,
                database_url=settings.DATABASE_URL, make_snapshot=True,
            )
    except ValueError as e:
        with managed_session() as log_session:
            record_log(log_session, operation="recategorize", force=body.force,
                       dry_run=False, ok=False, user=user, error_message=str(e))
        raise HTTPException(422, str(e)) from e

    with managed_session() as log_session:
        record_log(
            log_session,
            operation="recategorize",
            scope=result.scope,
            counts={
                "changed": result.changed,
                "newly_classified": result.newly_classified,
                "reclassified": result.reclassified,
                "unchanged": result.unchanged,
                "no_rule_match": result.no_rule_match,
                "protected_skipped": result.protected_skipped,
            },
            snapshot_path=result.snapshot_path,
            user=user,
            dry_run=False,
            force=result.force,
            ok=result.ok,
            error_message=result.error_message,
        )
    return JSONResponse(result.to_dict(), status_code=200 if result.ok else 422)


@router.get("/snapshots")
def list_snapshots_endpoint(identity: dict = Depends(require_admin)) -> JSONResponse:
    """복원 가능한 DB 스냅샷(백업) 목록을 최신순으로 반환한다."""
    return JSONResponse({"ok": True, "snapshots": restore_svc.list_snapshots()})


class RestoreRequest(BaseModel):
    filename: str


@router.post("/restore")
def restore_snapshot_endpoint(
    body: RestoreRequest, identity: dict = Depends(require_admin)
) -> JSONResponse:
    """선택한 스냅샷으로 현재 DB를 되돌린다(복원 직전 현재 상태를 따로 백업)."""
    user = identity.get("email", "anonymous")
    try:
        info = restore_svc.restore_snapshot(body.filename, settings.DATABASE_URL)
    except (FileNotFoundError, ValueError) as e:
        with managed_session() as log_session:
            record_log(log_session, operation="restore", dry_run=False, ok=False,
                       user=user, error_message=str(e))
        code = 404 if isinstance(e, FileNotFoundError) else 422
        raise HTTPException(code, str(e)) from e

    with managed_session() as log_session:
        record_log(
            log_session,
            operation="restore",
            snapshot_path=info.get("restored_from"),
            counts={"pre_restore_backup": info.get("pre_restore_backup")},
            user=user,
            dry_run=False,
            ok=True,
        )
    return JSONResponse(info)


@router.get("/logs")
def list_logs(limit: int = 50, identity: dict = Depends(require_admin)) -> JSONResponse:
    limit = max(1, min(limit, 500))
    session = get_session()
    try:
        rows = session.scalars(
            select(CatalogSyncLog).order_by(CatalogSyncLog.id.desc()).limit(limit)
        ).all()
        out = [{
            "id": r.id,
            "operation": r.operation,
            "entities": r.entities,
            "mode": r.mode,
            "counts": r.counts,
            "file_hash": r.file_hash,
            "snapshot_path": r.snapshot_path,
            "user": r.user,
            "dry_run": r.dry_run,
            "force": r.force,
            "ok": r.ok,
            "error_message": r.error_message,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        } for r in rows]
    finally:
        session.close()
    return JSONResponse({"ok": True, "logs": out})
