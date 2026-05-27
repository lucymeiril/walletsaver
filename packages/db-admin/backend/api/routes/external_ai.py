"""Round R G4 외부 AI 분류 사이클 API."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from api.auth import require_admin
from services.base import get_session, managed_session
from services.external_ai_export import export_unclassified_bundle
from services.external_ai_import import apply_import_bundle

router = APIRouter(prefix="/admin/external-ai", tags=["admin", "external-ai"])

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parents[2]
ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "external-ai"
_REQUIRED_UPLOADS = {
    "matching_updates.jsonl": "matching_file",
    "category_keyword_updates.yaml": "category_keyword_file",
    "product_updates.jsonl": "product_file",
}


def _bundle_dir(prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACT_ROOT / f"{prefix}-{stamp}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/export")
def export_external_ai_bundle(identity: dict = Depends(require_admin)) -> JSONResponse:
    out_dir = _bundle_dir("export")
    session = get_session()
    try:
        manifest = export_unclassified_bundle(out_dir, session=session)
    finally:
        session.close()
    return JSONResponse(
        {
            "ok": True,
            "out_dir": str(out_dir),
            "download_path": str(out_dir),
            "manifest_path": str(out_dir / "manifest.json"),
            "manifest": manifest.to_dict(),
        }
    )


async def _json_path_request(request: Request) -> tuple[str | None, bool | None]:
    if not request.headers.get("content-type", "").startswith("application/json"):
        return None, None
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(422, "JSON body는 object여야 합니다.")
    return payload.get("path"), payload.get("dry_run")


async def _materialize_uploads(
    in_dir: Path,
    matching_file: UploadFile | None,
    category_keyword_file: UploadFile | None,
    product_file: UploadFile | None,
) -> None:
    files = {
        "matching_updates.jsonl": matching_file,
        "category_keyword_updates.yaml": category_keyword_file,
        "product_updates.jsonl": product_file,
    }
    missing = [label for label, upload in files.items() if upload is None]
    if missing:
        raise HTTPException(422, f"필수 업로드 누락: {', '.join(missing)}")
    for filename, upload in files.items():
        assert upload is not None
        target = in_dir / filename
        with target.open("wb") as f:
            shutil.copyfileobj(upload.file, f)


@router.post("/import")
async def import_external_ai_bundle(
    request: Request,
    path: Optional[str] = Form(default=None),
    dry_run: bool = Form(default=True),
    matching_file: UploadFile | None = File(default=None),
    category_keyword_file: UploadFile | None = File(default=None),
    product_file: UploadFile | None = File(default=None),
    identity: dict = Depends(require_admin),
) -> JSONResponse:
    json_path, json_dry_run = await _json_path_request(request)
    if json_path is not None:
        path = json_path
    if json_dry_run is not None:
        dry_run = bool(json_dry_run)

    if path:
        in_dir = Path(path)
        if not in_dir.exists() or not in_dir.is_dir():
            raise HTTPException(422, f"import 경로를 찾을 수 없습니다: {path}")
    else:
        in_dir = _bundle_dir("import")
        await _materialize_uploads(in_dir, matching_file, category_keyword_file, product_file)

    try:
        with managed_session() as session:
            report = apply_import_bundle(in_dir, session=session, dry_run=dry_run)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    status = 200 if report.get("ok") else 422
    return JSONResponse(status_code=status, content={"ok": report.get("ok", False), "in_dir": str(in_dir), "importer": identity.get("email", "admin"), **report})
