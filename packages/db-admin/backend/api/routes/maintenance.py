"""DB 유지보수 (maintenance) API.

기능:
  1. POST /admin/maintenance/purge — scope(raw|mappings|all) 단위 즉시 삭제
  2. POST /admin/maintenance/migrate — Alembic upgrade head 실행
  3. GET  /admin/maintenance/integrity — null/duplicate/orphan FK 빠른 검사

모든 변경 작업은 services.audit.log_action 으로 DB AuditLog 테이블에 영속화된다.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from starlette.requests import Request

from api.auth import require_admin, require_moderator
from api.middleware.rate_limit import limiter, ADMIN_LIMIT, DESTRUCTIVE_LIMIT
from config import settings
from services.audit import log_action
from services.base import get_session
from storage.models import (
    BaselinePrice,
    CategoryCorrection,
    CrawlLog,
    DiscountHistory,
    HotdealPrice,
    Keyword,
    PendingCategorization,
    PendingIngestion,
    Product,
    ProductKeyword,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/maintenance", tags=["admin", "maintenance"])

VALID_SCOPES = ("raw", "mappings", "all")


class PurgeRequest(BaseModel):
    scope: str = Field(..., description="raw | mappings | all")
    confirm: bool = Field(False, description="모달에서 사용자가 확인한 플래그")
    note: Optional[str] = Field(default=None, max_length=500)


def _purge_raw(session) -> dict[str, int]:
    """원시 수집/실행 기록(PendingIngestion, CrawlLog) 삭제."""
    counts: dict[str, int] = {}
    counts["pending_ingestions"] = session.query(PendingIngestion).delete(
        synchronize_session=False
    )
    counts["crawl_logs"] = session.query(CrawlLog).delete(synchronize_session=False)
    return counts


def _purge_mappings(session) -> dict[str, int]:
    """카테고리/키워드 매핑 데이터 삭제 (Product/Category 본체는 보존)."""
    counts: dict[str, int] = {}
    counts["product_keywords"] = session.query(ProductKeyword).delete(
        synchronize_session=False
    )
    counts["keywords"] = session.query(Keyword).delete(synchronize_session=False)
    counts["category_corrections"] = session.query(CategoryCorrection).delete(
        synchronize_session=False
    )
    counts["pending_categorizations"] = session.query(PendingCategorization).delete(
        synchronize_session=False
    )
    return counts


def _purge_all(session) -> dict[str, int]:
    """현재 working DB의 도메인 데이터 삭제 (Category 마스터는 보존)."""
    counts: dict[str, int] = {}

    counts.update({f"raw.{k}": v for k, v in _purge_raw(session).items()})
    counts.update({f"mappings.{k}": v for k, v in _purge_mappings(session).items()})

    counts["discount_history"] = session.query(DiscountHistory).delete(
        synchronize_session=False
    )
    counts["baseline_prices"] = session.query(BaselinePrice).delete(
        synchronize_session=False
    )
    counts["hotdeal_prices"] = session.query(HotdealPrice).delete(
        synchronize_session=False
    )
    counts["products"] = session.query(Product).delete(synchronize_session=False)
    return counts


_PURGE_DISPATCH = {
    "raw": _purge_raw,
    "mappings": _purge_mappings,
    "all": _purge_all,
}


@router.post("/purge")
@limiter.limit(DESTRUCTIVE_LIMIT)
def purge(
    request: Request,
    body: PurgeRequest = Body(...),
    identity: dict = Depends(require_admin),
):
    """선택한 scope의 데이터를 즉시 삭제하고 AuditLog 에 영속 기록한다."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm=true 가 필요합니다.")
    if body.scope not in VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"알 수 없는 scope: {body.scope}")

    session = get_session()
    try:
        handler = _PURGE_DISPATCH[body.scope]
        counts = handler(session)
        total = sum(int(v) for v in counts.values())

        log_action(
            session,
            action="maintenance.purge",
            entity_type="database",
            entity_id=body.scope,
            new_value={"counts": counts, "total": total, "note": body.note},
            request=request,
            user_id=(identity or {}).get("email")
            or str((identity or {}).get("user_id") or "anonymous"),
            metadata={"scope": body.scope},
        )
        session.commit()

        logger.warning(
            "[MAINT] purge scope=%s total=%d by=%s",
            body.scope,
            total,
            (identity or {}).get("email") or "anonymous",
        )
        return {
            "action": "maintenance.purge",
            "scope": body.scope,
            "deleted": counts,
            "total": total,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class MigrateRequest(BaseModel):
    revision: str = Field(default="head", min_length=1, max_length=64)


@router.post("/migrate")
@limiter.limit(ADMIN_LIMIT)
def migrate(
    request: Request,
    body: MigrateRequest = Body(default_factory=MigrateRequest),
    identity: dict = Depends(require_admin),
):
    """Alembic upgrade <revision> 을 실행한다 (기본: head)."""
    backend_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    env = os.environ.copy()
    env.setdefault("DATABASE_URL", settings.DATABASE_URL)

    cmd = [sys.executable, "-m", "alembic", "upgrade", body.revision]
    try:
        proc = subprocess.run(
            cmd,
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as e:
        raise HTTPException(
            status_code=504, detail=f"Alembic 마이그레이션 타임아웃: {e}"
        )

    success = proc.returncode == 0
    session = get_session()
    try:
        log_action(
            session,
            action="maintenance.migrate",
            entity_type="database",
            entity_id=body.revision,
            new_value={
                "returncode": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-1000:],
                "stderr_tail": (proc.stderr or "")[-1000:],
            },
            request=request,
            user_id=(identity or {}).get("email")
            or str((identity or {}).get("user_id") or "anonymous"),
        )
        session.commit()
    finally:
        session.close()

    if not success:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "alembic upgrade 실패",
                "stderr": (proc.stderr or "")[-1500:],
                "stdout": (proc.stdout or "")[-500:],
            },
        )
    return {
        "action": "maintenance.migrate",
        "revision": body.revision,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/integrity")
@limiter.limit(ADMIN_LIMIT)
def integrity(
    request: Request,
    identity: dict = Depends(require_moderator),
):
    """이상 데이터 빠른 검토 — null / duplicate / orphan FK 요약."""
    session = get_session()
    try:
        null_products_category = session.query(func.count(Product.id)).filter(
            Product.category_id.is_(None)
        ).scalar() or 0
        null_products_name = session.query(func.count(Product.id)).filter(
            (Product.name.is_(None)) | (Product.name == "")
        ).scalar() or 0

        dup_rows = (
            session.query(
                Product.name,
                Product.source_type,
                func.count(Product.id).label("cnt"),
            )
            .group_by(Product.name, Product.source_type)
            .having(func.count(Product.id) > 1)
            .limit(50)
            .all()
        )
        duplicate_products = sum(int(r.cnt) - 1 for r in dup_rows)
        duplicate_samples = [
            {"name": r.name, "source_type": r.source_type, "count": int(r.cnt)}
            for r in dup_rows[:10]
        ]

        orphan_counts: dict[str, int] = {}
        for label, Model in (
            ("baseline_prices", BaselinePrice),
            ("discount_history", DiscountHistory),
            ("hotdeal_prices", HotdealPrice),
        ):
            orphan_q = (
                session.query(func.count(Model.id))
                .outerjoin(Product, Model.product_id == Product.id)
                .filter(Product.id.is_(None))
            )
            orphan_counts[label] = int(orphan_q.scalar() or 0)
        orphan_pk = session.query(func.count(ProductKeyword.id)).outerjoin(
            Product, ProductKeyword.product_id == Product.id
        ).filter(Product.id.is_(None)).scalar() or 0
        orphan_counts["product_keywords"] = int(orphan_pk)

        total_issues = (
            null_products_category
            + null_products_name
            + duplicate_products
            + sum(orphan_counts.values())
        )

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "issue_total": total_issues,
            "null": {
                "products_without_category": null_products_category,
                "products_without_name": null_products_name,
            },
            "duplicates": {
                "products": duplicate_products,
                "samples": duplicate_samples,
            },
            "orphan_fk": orphan_counts,
        }
    finally:
        session.close()
