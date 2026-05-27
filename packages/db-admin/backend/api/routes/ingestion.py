"""대기열(Pending Ingestion) API — 크롤 결과 수신, 검토, 승인/거부"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Callable, Optional, TypeVar

from fastapi import APIRouter, HTTPException, Query, Request, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from services.base import get_session, managed_session
from api.auth import (
    require_viewer,
    require_moderator,
    require_admin,
    require_ai_publisher,
    get_current_identity,
)
from services.audit import log_action
from services.normalized_mart3 import publish_mart3_rows
from services.product_match_rules import (
    apply_rule_to_product,
    find_matching_rule,
    is_missing_or_one_depth_category,
    record_rule_hit,
)
from api.middleware.rate_limit import limiter, INGESTION_LIMIT
from starlette.requests import Request as StarletteRequest
from storage.models import (
    PendingIngestion,
    IngestionStatus,
    BaselinePrice,
    Category,
    DiscountHistory,
    HotdealPrice,
    Keyword,
    Product,
    ProductKeyword,
    PendingCategorization,
)

from api.security import (
    MAX_INGESTION_ITEMS, MAX_INGESTION_ERRORS, MAX_CRAWLER_NAME_LEN,
    MAX_STRATEGY_LEN, MAX_URL_LEN, MAX_NOTES_LEN, MAX_REASON_LEN,
    MAX_BULK_IDS, MAX_NAME_LEN, ALLOWED_SCHEMA_TYPES, ALLOWED_CRAWL_STATUSES,
    MAX_REVIEW_ACTION_VALUES, MAX_CLEANUP_STATUS_VALUES,
)
from api.source_normalization import normalize_source_key
from core.product_units import normalize_unit_metadata

router = APIRouter(prefix="/api/ingestions", tags=["ingestions"])


logger = logging.getLogger(__name__)

INGESTION_SERVER_CHUNK_SIZE = 1_000
BULK_APPROVE_COMMIT_CHUNK_SIZE = 100
SQLITE_LOCK_RETRY_ATTEMPTS = 5
_SQLITE_LOCK_RETRY_BASE_DELAY = 0.25
T = TypeVar("T")

# --- Request 모델 ---


class IngestionSubmit(BaseModel):
    crawler_name: str = Field(..., min_length=1, max_length=MAX_CRAWLER_NAME_LEN)
    crawl_status: str = Field("success", max_length=20)
    items: list[dict] = Field(default_factory=list, max_length=MAX_INGESTION_ITEMS)
    schema_type: str = Field("DiscountItem", max_length=50)
    strategy_used: Optional[str] = Field(None, max_length=MAX_STRATEGY_LEN)
    duration_seconds: Optional[float] = Field(None, ge=0, le=86_400)
    errors: list[dict] = Field(default_factory=list, max_length=MAX_INGESTION_ERRORS)
    source_url: Optional[str] = Field(None, max_length=MAX_URL_LEN)
    quality_score: Optional[float] = Field(None, ge=0, le=100)
    quality_details: Optional[dict] = None

    @field_validator("crawl_status")
    @classmethod
    def validate_crawl_status(cls, v: str) -> str:
        if v not in ALLOWED_CRAWL_STATUSES:
            raise ValueError(f"crawl_status는 {ALLOWED_CRAWL_STATUSES} 중 하나여야 합니다.")
        return v

    @field_validator("schema_type")
    @classmethod
    def validate_schema_type(cls, v: str) -> str:
        if v not in ALLOWED_SCHEMA_TYPES:
            raise ValueError(f"schema_type은 {ALLOWED_SCHEMA_TYPES} 중 하나여야 합니다.")
        return v


class ReviewRequest(BaseModel):
    action: str = Field(..., max_length=20)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES_LEN)
    approved_item_indices: Optional[list[int]] = Field(None, max_length=MAX_INGESTION_ITEMS)
    rejected_reason: Optional[str] = Field(None, max_length=MAX_REASON_LEN)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in MAX_REVIEW_ACTION_VALUES:
            raise ValueError(f"action은 {MAX_REVIEW_ACTION_VALUES} 중 하나여야 합니다.")
        return v


class IngestionRowUpdateRequest(BaseModel):
    item: dict = Field(...)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES_LEN)


class PublishedRowRollbackRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=MAX_REASON_LEN)


class PublishedRowReReviewRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=MAX_REASON_LEN)
    corrected_item: Optional[dict] = None


class BulkApproveRequest(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=MAX_BULK_IDS)
    reviewer: Optional[str] = Field(None, max_length=MAX_NAME_LEN)
    notes: Optional[str] = Field(None, max_length=MAX_NOTES_LEN)


class CleanupRequest(BaseModel):
    status: list[str] = Field(
        default=["approved", "rejected"],
        min_length=1,
        max_length=5,
    )
    older_than_days: Optional[int] = Field(None, ge=1, le=3650)
    confirm: bool = False

    @field_validator("status")
    @classmethod
    def validate_status_values(cls, v: list[str]) -> list[str]:
        invalid = set(v) - MAX_CLEANUP_STATUS_VALUES
        if invalid:
            raise ValueError(f"허용되지 않는 status 값: {invalid}")
        return v


# --- 품질 점수 계산 ---


def _chunked(values: list[T], size: int) -> list[list[T]]:
    return [values[idx:idx + size] for idx in range(0, len(values), size)]


def _is_sqlite_locked(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if "database is locked" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False


def _with_sqlite_lock_retry(operation: Callable[[], T]) -> T:
    for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
        try:
            return operation()
        except OperationalError as exc:
            if not _is_sqlite_locked(exc) or attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
                raise
            delay = _SQLITE_LOCK_RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning("SQLite lock detected; retrying in %.2fs (%d/%d)", delay, attempt + 1, SQLITE_LOCK_RETRY_ATTEMPTS)
            time.sleep(delay)
    return operation()


def _calculate_quality(items: list[dict], schema_type: str) -> tuple[float, dict]:
    """크롤 데이터의 품질 점수(0.0~1.0)와 상세 내역 반환."""
    if not items:
        return 0.0, {"error": "항목 없음"}

    # 필수 필드 검사
    if schema_type == "HotdealPost":
        required = ["title", "url", "price"]
    else:
        required = ["name", "sale_price", "source"]

    missing_count = 0
    for item in items:
        for field in required:
            if not item.get(field):
                missing_count += 1
                break

    missing_ratio = missing_count / len(items)

    # 가격 이상치 검사
    price_field = "price" if schema_type == "HotdealPost" else "sale_price"
    prices = [
        item[price_field]
        for item in items
        if isinstance(item.get(price_field), (int, float)) and item[price_field] > 0
    ]

    outlier_count = 0
    if len(prices) >= 3:
        avg = sum(prices) / len(prices)
        for p in prices:
            if p > avg * 5 or p < avg * 0.05:
                outlier_count += 1

    outlier_ratio = outlier_count / len(items)

    # 중복 검사
    name_field = "title" if schema_type == "HotdealPost" else "name"
    seen: set[tuple] = set()
    dup_count = 0
    for item in items:
        key = (item.get(name_field, ""), item.get(price_field))
        if key in seen:
            dup_count += 1
        seen.add(key)

    dup_ratio = dup_count / len(items)

    # 점수 계산 (0-100 스케일)
    score = 1.0 - (missing_ratio * 0.4) - (outlier_ratio * 0.3) - (dup_ratio * 0.3)
    score = max(0, min(100, round(score * 100, 1)))

    details = {
        "total_items": len(items),
        "missing_fields": missing_count,
        "outliers": outlier_count,
        "duplicates": dup_count,
        "missing_ratio": round(missing_ratio, 3),
        "outlier_ratio": round(outlier_ratio, 3),
        "duplicate_ratio": round(dup_ratio, 3),
    }
    return score, details


# --- 엔드포인트 ---


@router.get("/stats")
def ingestion_stats(identity: dict = Depends(require_viewer)):
    """대기열 통계 — 상태별 건수, 크롤러별 건수."""
    session = get_session()
    try:
        status_rows = (
            session.query(PendingIngestion.status, func.count())
            .group_by(PendingIngestion.status)
            .all()
        )
        status_counts: dict[str, int] = {s.value: 0 for s in IngestionStatus}
        for status_val, cnt in status_rows:
            key = status_val.value if hasattr(status_val, "value") else status_val
            status_counts[key] = cnt

        crawler_rows = (
            session.query(PendingIngestion.crawler_name, func.count())
            .group_by(PendingIngestion.crawler_name)
            .all()
        )
        by_crawler = {name: cnt for name, cnt in crawler_rows}

        return {
            "total_pending": status_counts.get("pending", 0),
            "total_approved": status_counts.get("approved", 0),
            "total_rejected": status_counts.get("rejected", 0),
            "total_crawler_approved": status_counts.get("crawler_approved", 0),
            "total_partial": status_counts.get("partial", 0),
            "by_crawler": by_crawler,
        }
    finally:
        session.close()


@router.post("/bulk-approve")
def bulk_approve(body: BulkApproveRequest, identity: dict = Depends(require_moderator)):
    """선택된 여러 수집을 일괄 승인. SQLite writer lock 완화를 위해 청크별로 커밋한다."""
    if not body.ids:
        raise HTTPException(400, "ids가 비어 있습니다")

    results = []
    for id_chunk in _chunked(body.ids, BULK_APPROVE_COMMIT_CHUNK_SIZE):
        def approve_chunk() -> list[dict]:
            chunk_results = []
            with managed_session() as session:
                for ingestion_id in id_chunk:
                    row = session.get(PendingIngestion, ingestion_id)
                    if not row:
                        chunk_results.append({"id": ingestion_id, "status": "not_found"})
                        continue
                    if row.status != IngestionStatus.CRAWLER_APPROVED:
                        chunk_results.append({
                            "id": ingestion_id,
                            "status": "skipped",
                            "reason": f"상태가 {row.status.value if hasattr(row.status, 'value') else row.status}",
                        })
                        continue
                    items = json.loads(row.items_json) if row.items_json else []
                    saved = _insert_items(session, items, row.schema_type)
                    row.db_reviewer_notes = body.notes or f"벌크 승인 (reviewer: {body.reviewer or 'system'})"
                    row.db_reviewed_at = datetime.utcnow()
                    if saved == len(items):
                        row.status = IngestionStatus.APPROVED
                        chunk_results.append({"id": ingestion_id, "status": "approved", "saved": saved})
                    else:
                        row.status = IngestionStatus.CRAWLER_APPROVED
                        reason = f"{len(items) - saved}개 항목이 필수 공개 메타데이터 누락/오류로 저장되지 않았습니다"
                        row.db_reviewer_notes = f"{row.db_reviewer_notes or ''}\n{reason}".strip()
                        chunk_results.append({"id": ingestion_id, "status": "pending", "saved": saved, "reason": reason})
                session.flush()
            return chunk_results

        results.extend(_with_sqlite_lock_retry(approve_chunk))

    approved_count = sum(1 for r in results if r["status"] == "approved")
    return {
        "approved": approved_count,
        "total_requested": len(body.ids),
        "chunks_committed": len(_chunked(body.ids, BULK_APPROVE_COMMIT_CHUNK_SIZE)),
        "results": results,
    }


@router.post("/cleanup")
def cleanup_ingestions(body: CleanupRequest, identity: dict = Depends(require_admin)):
    """처리 완료(승인/거부)된 대기열 항목 일괄 삭제."""
    if not body.confirm:
        raise HTTPException(400, "confirm이 true여야 삭제를 진행합니다")

    status_map = {
        "approved": IngestionStatus.APPROVED,
        "rejected": IngestionStatus.REJECTED,
        "partial": IngestionStatus.PARTIAL,
    }
    target_statuses = []
    for s in body.status:
        if s not in status_map:
            raise HTTPException(400, f"잘못된 상태: {s} (approved, rejected, partial 중 선택)")
        target_statuses.append(status_map[s])

    if not target_statuses:
        return {"deleted": 0}

    with managed_session() as session:
        q = session.query(PendingIngestion).filter(
            PendingIngestion.status.in_(target_statuses)
        )
        if body.older_than_days is not None:
            cutoff = datetime.utcnow() - timedelta(days=body.older_than_days)
            q = q.filter(PendingIngestion.crawled_at < cutoff)

        count = q.count()
        if count > 0:
            q.delete(synchronize_session="fetch")
        return {"deleted": count}


@router.post("")
@limiter.limit(INGESTION_LIMIT)
def submit_ingestion(request: StarletteRequest, body: IngestionSubmit, identity: dict = Depends(get_current_identity)):
    """크롤러가 데이터를 대기열에 제출. 서버도 1,000건 단위로 안전하게 분할 저장한다."""
    if identity["role"] not in ("service", "moderator", "admin"):
        raise HTTPException(403, "크롤러 서비스 또는 관리자 권한이 필요합니다.")

    item_chunks = _chunked(body.items, INGESTION_SERVER_CHUNK_SIZE) or [[]]
    created_rows = []
    for chunk_index, item_chunk in enumerate(item_chunks, start=1):
        def insert_chunk() -> dict:
            with managed_session() as session:
                quality_score, quality_details = (
                    (body.quality_score, body.quality_details or {})
                    if body.quality_score is not None and len(item_chunks) == 1
                    else _calculate_quality(item_chunk, body.schema_type)
                )
                strategy = body.strategy_used
                if len(item_chunks) > 1:
                    suffix = f"server_chunk={chunk_index}/{len(item_chunks)} size={len(item_chunk)}"
                    strategy = f"{strategy}; {suffix}" if strategy else suffix
                row = PendingIngestion(
                    crawler_name=body.crawler_name,
                    crawl_status=body.crawl_status,
                    strategy_used=strategy,
                    items_count=len(item_chunk),
                    items_json=json.dumps(item_chunk, ensure_ascii=False, default=str),
                    schema_type=body.schema_type,
                    quality_score=quality_score,
                    quality_details=quality_details,
                    errors_json=(
                        json.dumps(body.errors, ensure_ascii=False, default=str)
                        if body.errors and chunk_index == 1
                        else None
                    ),
                    status=IngestionStatus.PENDING,
                    crawled_at=datetime.utcnow(),
                    duration_seconds=body.duration_seconds,
                    source_url=body.source_url,
                )
                session.add(row)
                session.flush()
                session.refresh(row)
                return {"id": row.id, "items_count": row.items_count, "quality_score": quality_score}

        created_rows.append(_with_sqlite_lock_retry(insert_chunk))

    if len(created_rows) == 1:
        row = created_rows[0]
        return {"id": row["id"], "status": "pending", "quality_score": row["quality_score"]}
    return {
        "ids": [row["id"] for row in created_rows],
        "status": "pending",
        "chunks": len(created_rows),
        "chunk_size": INGESTION_SERVER_CHUNK_SIZE,
        "total_items": len(body.items),
        "items_per_chunk": [row["items_count"] for row in created_rows],
    }


@router.get("")
def list_ingestions(
    status: Optional[str] = Query(None, description="상태 필터"),
    crawler_name: Optional[str] = Query(None, description="크롤러 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    limit: int = Query(None, ge=1, le=500, description="(하위호환) limit"),
    offset: int = Query(None, ge=0, description="(하위호환) offset"),
    identity: dict = Depends(require_viewer),
):
    """대기열 목록 조회 (summary) — page/per_page 또는 limit/offset."""
    session = get_session()
    try:
        q = session.query(PendingIngestion)
        if status:
            q = q.filter(PendingIngestion.status == status)
        if crawler_name:
            q = q.filter(PendingIngestion.crawler_name == crawler_name)
        q = q.order_by(PendingIngestion.crawled_at.desc())
        total = q.count()

        if limit is not None or offset is not None:
            real_limit = limit or 50
            real_offset = offset or 0
            rows = q.offset(real_offset).limit(real_limit).all()
            total_pages = max(1, -(-total // real_limit))
            current_page = (real_offset // real_limit) + 1
        else:
            real_offset = (page - 1) * per_page
            rows = q.offset(real_offset).limit(per_page).all()
            total_pages = max(1, -(-total // per_page))
            current_page = page

        return {
            "total": total,
            "page": current_page,
            "per_page": per_page if limit is None else (limit or 50),
            "total_pages": total_pages,
            "items": [
                _build_list_item(r)
                for r in rows
            ],
        }
    finally:
        session.close()


@router.get("/{ingestion_id}")
def get_ingestion(ingestion_id: int, identity: dict = Depends(require_viewer)):
    """대기열 항목 상세 조회 — 항목 미리보기 + 품질 breakdown + 이전 비교."""
    session = get_session()
    try:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")

        return _build_detail_item(session, row)
    finally:
        session.close()


@router.post("/{ingestion_id}/crawler-review")
def crawler_review(ingestion_id: int, body: ReviewRequest, identity: dict = Depends(require_moderator)):
    """크롤러 관리자 1차 검토 — 승인/거부."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        if row.status != IngestionStatus.PENDING:
            raise HTTPException(
                400,
                f"현재 상태({row.status.value})에서는 크롤러 검토가 불가합니다",
            )

        if body.action == "approve":
            row.status = IngestionStatus.CRAWLER_APPROVED
        elif body.action == "reject":
            row.status = IngestionStatus.REJECTED
            row.rejected_reason = body.rejected_reason or body.notes
        else:
            raise HTTPException(
                400, f"잘못된 액션: {body.action} (approve 또는 reject)"
            )

        row.crawler_reviewer_notes = body.notes
        row.crawler_reviewed_at = datetime.utcnow()
        return {"id": row.id, "status": row.status.value}


@router.post("/{ingestion_id}/db-review")
def db_review(ingestion_id: int, body: ReviewRequest, identity: dict = Depends(require_moderator)):
    """DB 관리자 최종 검토 — 승인 시 실제 DB 테이블에 삽입."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        if row.status != IngestionStatus.CRAWLER_APPROVED:
            raise HTTPException(
                400,
                "크롤러 관리자 승인(crawler_approved) 상태에서만 DB 검토가 가능합니다",
            )

        items = json.loads(row.items_json) if row.items_json else []

        if body.action == "approve":
            saved = _insert_items(session, items, row.schema_type)
            row.db_reviewer_notes = body.notes
            row.db_reviewed_at = datetime.utcnow()
            if saved != len(items):
                row.status = IngestionStatus.CRAWLER_APPROVED
                reason = f"{len(items) - saved}개 항목이 필수 공개 메타데이터 누락/오류로 저장되지 않았습니다"
                row.db_reviewer_notes = f"{row.db_reviewer_notes or ''}\n{reason}".strip()
                return {"id": row.id, "status": "crawler_approved", "saved": saved, "failed": len(items) - saved, "reason": reason}
            row.status = IngestionStatus.APPROVED
            return {"id": row.id, "status": "approved", "saved": saved}

        elif body.action == "reject":
            row.status = IngestionStatus.REJECTED
            row.rejected_reason = body.rejected_reason or body.notes
            row.db_reviewer_notes = body.notes
            row.db_reviewed_at = datetime.utcnow()
            return {"id": row.id, "status": "rejected"}

        elif body.action == "partial":
            if not body.approved_item_indices:
                raise HTTPException(
                    400, "partial 승인 시 approved_item_indices가 필요합니다"
                )
            approved = [
                items[i]
                for i in body.approved_item_indices
                if i < len(items)
            ]
            saved = _insert_items(session, approved, row.schema_type)
            row.approved_items_json = json.dumps(
                approved, ensure_ascii=False, default=str
            )
            row.db_reviewer_notes = body.notes
            row.db_reviewed_at = datetime.utcnow()
            if saved != len(approved):
                row.status = IngestionStatus.CRAWLER_APPROVED
                reason = f"{len(approved) - saved}개 부분 승인 항목이 필수 공개 메타데이터 누락/오류로 저장되지 않았습니다"
                row.db_reviewer_notes = f"{row.db_reviewer_notes or ''}\n{reason}".strip()
                return {"id": row.id, "status": "crawler_approved", "saved": saved, "failed": len(approved) - saved, "reason": reason}
            row.status = IngestionStatus.PARTIAL
            return {"id": row.id, "status": "partial", "saved": saved}

        else:
            raise HTTPException(400, f"잘못된 액션: {body.action}")


@router.post("/{ingestion_id}/ai-safe-final-approve")
def ai_safe_final_approve(
    ingestion_id: int,
    body: ReviewRequest,
    request: Request = None,
    identity: dict = Depends(require_ai_publisher),
):
    """AI-admin safe-enough rows: one operator action to publish with audit evidence."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        if row.status != IngestionStatus.PENDING:
            raise HTTPException(400, "AI 안전 최종 승인은 pending 상태에서만 가능합니다")
        if body.action != "approve":
            raise HTTPException(400, "AI 안전 최종 승인 경로는 approve 액션만 지원합니다")

        items = json.loads(row.items_json) if row.items_json else []
        blockers = _ai_safe_final_approve_blockers(row, items)
        if blockers:
            reason = "AI 안전 최종 승인 차단: " + "; ".join(blockers[:5])
            _append_db_review_note(row, "ai-safe final approve blocked", body.notes or reason)
            log_action(
                session,
                action="ingestion_ai_safe_final_blocked",
                entity_type="pending_ingestion",
                entity_id=row.id,
                old_value={"status": "pending"},
                new_value={"status": "pending", "blockers": blockers},
                request=request,
                user_id=str(identity.get("email") or identity.get("id")),
                metadata={"notes": body.notes, "one_final_action": True},
            )
            session.flush()
            return {"id": row.id, "status": "pending", "blocked": True, "blockers": blockers}

        reviewed_at = datetime.utcnow()
        saved = _insert_items(session, items, row.schema_type)
        if saved != len(items):
            reason = f"{len(items) - saved}개 항목이 필수 공개 메타데이터 누락/오류로 저장되지 않았습니다"
            _append_db_review_note(row, "ai-safe final approve blocked", body.notes or reason)
            raise HTTPException(400, {"reason": reason, "saved": saved, "failed": len(items) - saved})

        public_verification_items = []
        for item_index, item in enumerate(items):
            target = _find_published_row_for_item(session, item, row.schema_type)
            if target is None:
                public_verification_items.append(
                    {"item_index": item_index, "verified": False}
                )
                continue
            table_name, published_row = target
            public_verification_items.append(
                {
                    "item_index": item_index,
                    "verified": True,
                    "published_row": _published_row_snapshot(table_name, published_row),
                }
            )
        public_verification = {
            "verified": len(public_verification_items) == saved
            and all(item["verified"] for item in public_verification_items),
            "verified_count": sum(1 for item in public_verification_items if item["verified"]),
            "expected_count": saved,
            "items": public_verification_items,
        }
        if not public_verification["verified"]:
            reason = "AI 안전 최종 승인 후 공개 DB 행 검증에 실패했습니다"
            _append_db_review_note(row, "ai-safe final approve blocked", reason)
            raise HTTPException(500, {"reason": reason, "public_db_verification": public_verification})

        row.status = IngestionStatus.APPROVED
        row.crawler_reviewed_at = reviewed_at
        row.db_reviewed_at = reviewed_at
        row.crawler_reviewer_notes = (
            f"{row.crawler_reviewer_notes}\nAI safe-enough one-final-action path"
            if row.crawler_reviewer_notes
            else "AI safe-enough one-final-action path"
        )
        _append_db_review_note(row, "ai-safe final approve", body.notes)
        log_action(
            session,
            action="ingestion_ai_safe_final_approve",
            entity_type="pending_ingestion",
            entity_id=row.id,
            old_value={"status": "pending", "items": items},
            new_value={
                "status": "approved",
                "saved": saved,
                "public_db_verification": public_verification,
                "raw_evidence_retained": True,
                "rollback_supported": True,
                "re_review_supported": True,
                "operator_next_action": "If a published row is wrong, call rollback or re-review on /api/ingestions/{id}/published-items/{item_index}.",
            },
            request=request,
            user_id=str(identity.get("email") or identity.get("id")),
            metadata={"notes": body.notes, "one_final_action": True},
        )
        session.flush()
        return {
            "id": row.id,
            "status": "approved",
            "saved": saved,
            "public_db_verification": public_verification,
            "raw_evidence_retained": True,
            "rollback_supported": True,
            "re_review_supported": True,
            "operator_next_action": "If a published row is wrong, call rollback or re-review on /api/ingestions/{id}/published-items/{item_index}.",
        }


@router.put("/{ingestion_id}/items/{item_index}")
def update_ingestion_item(
    ingestion_id: int,
    item_index: int,
    body: IngestionRowUpdateRequest,
    request: Request,
    identity: dict = Depends(require_moderator),
):
    """대기열 항목의 단일 행을 수정하고 품질 지표를 재계산."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        _ensure_ingestion_rows_editable(row)

        items = json.loads(row.items_json) if row.items_json else []
        if item_index < 0 or item_index >= len(items):
            raise HTTPException(404, "수정할 행을 찾을 수 없습니다")

        old_item = items[item_index]
        items[item_index] = body.item
        _persist_items_and_quality(row, items)
        _append_review_note(row, f"row {item_index + 1} edited", body.notes)
        log_action(
            session,
            action="ingestion_row_update",
            entity_type="pending_ingestion",
            entity_id=row.id,
            old_value={"index": item_index, "item": old_item},
            new_value={"index": item_index, "item": body.item},
            request=request,
            user_id=str(identity.get("email") or identity.get("id")),
            metadata={"notes": body.notes},
        )
        session.flush()
        return _build_detail_item(session, row)


@router.delete("/{ingestion_id}/items/{item_index}")
def remove_ingestion_item(
    ingestion_id: int,
    item_index: int,
    request: Request,
    notes: Optional[str] = Query(None, max_length=MAX_NOTES_LEN),
    identity: dict = Depends(require_moderator),
):
    """대기열 항목의 단일 행을 제외/삭제하고 품질 지표를 재계산."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        _ensure_ingestion_rows_editable(row)

        items = json.loads(row.items_json) if row.items_json else []
        if item_index < 0 or item_index >= len(items):
            raise HTTPException(404, "삭제할 행을 찾을 수 없습니다")

        removed = items.pop(item_index)
        _persist_items_and_quality(row, items)
        _append_review_note(row, f"row {item_index + 1} removed", notes)
        log_action(
            session,
            action="ingestion_row_remove",
            entity_type="pending_ingestion",
            entity_id=row.id,
            old_value={"index": item_index, "item": removed},
            new_value={"items_count": len(items)},
            request=request,
            user_id=str(identity.get("email") or identity.get("id")),
            metadata={"notes": notes},
        )
        session.flush()
        return _build_detail_item(session, row)


@router.post("/{ingestion_id}/published-items/{item_index}/rollback")
def rollback_published_ingestion_item(
    ingestion_id: int,
    item_index: int,
    body: PublishedRowRollbackRequest,
    request: Request = None,
    identity: dict = Depends(require_moderator),
):
    """Remove a previously published row while keeping the original evidence/audit trail."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        if row.status not in (IngestionStatus.APPROVED, IngestionStatus.PARTIAL):
            raise HTTPException(400, "승인/부분승인된 항목만 롤백할 수 있습니다")

        items = json.loads(row.approved_items_json or row.items_json or "[]")
        if item_index < 0 or item_index >= len(items):
            raise HTTPException(404, "롤백할 행을 찾을 수 없습니다")
        item = items[item_index]
        target = _find_published_row_for_item(session, item, row.schema_type)
        if target is None:
            raise HTTPException(404, "게시된 가격 행을 찾을 수 없습니다")

        table_name, published_row = target
        old_value = _published_row_snapshot(table_name, published_row)
        rollback_info = {
            "status": "rolled_back",
            "reason": body.reason,
            "rolled_back_at": datetime.utcnow().isoformat(),
            "rolled_back_by": str(identity.get("email") or identity.get("id")),
            "target_table": table_name,
            "target_id": published_row.id,
        }
        item["_db_admin_rollback"] = rollback_info
        items[item_index] = item
        if row.approved_items_json:
            row.approved_items_json = json.dumps(items, ensure_ascii=False, default=str)
        else:
            row.items_json = json.dumps(items, ensure_ascii=False, default=str)
        _append_db_review_note(row, f"published row {item_index + 1} rolled back", body.reason)

        product_id = getattr(published_row, "product_id", None)
        session.delete(published_row)
        if product_id is not None:
            _deactivate_empty_product_after_rollback(session, product_id)
        log_action(
            session,
            action="ingestion_published_row_rollback",
            entity_type="pending_ingestion",
            entity_id=row.id,
            old_value=old_value,
            new_value={"index": item_index, "rollback": rollback_info},
            request=request,
            user_id=str(identity.get("email") or identity.get("id")),
            metadata={"reason": body.reason},
        )
        session.flush()
        return {
            "id": row.id,
            "status": row.status.value if hasattr(row.status, "value") else row.status,
            "rollback": rollback_info,
            "raw_evidence_retained": True,
        }


@router.post("/{ingestion_id}/published-items/{item_index}/re-review")
def queue_published_ingestion_item_for_re_review(
    ingestion_id: int,
    item_index: int,
    body: PublishedRowReReviewRequest,
    request: Request = None,
    identity: dict = Depends(require_moderator),
):
    """Copy a published row back into DB review so operators can correct it with evidence intact."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        if row.status not in (IngestionStatus.APPROVED, IngestionStatus.PARTIAL):
            raise HTTPException(400, "승인/부분승인된 항목만 재검토 대기열로 보낼 수 있습니다")

        source_items = json.loads(row.approved_items_json or row.items_json or "[]")
        if item_index < 0 or item_index >= len(source_items):
            raise HTTPException(404, "재검토할 행을 찾을 수 없습니다")
        original_item = source_items[item_index]
        review_item = body.corrected_item if body.corrected_item is not None else dict(original_item)
        review_item.setdefault("raw_data", {})
        if isinstance(review_item["raw_data"], dict):
            review_item["raw_data"] = {
                **review_item["raw_data"],
                "re_review_source": {
                    "ingestion_id": row.id,
                    "item_index": item_index,
                    "reason": body.reason,
                    "original_item": original_item,
                },
            }
        review_item["_db_admin_re_review"] = {
            "source_ingestion_id": row.id,
            "source_item_index": item_index,
            "reason": body.reason,
            "queued_at": datetime.utcnow().isoformat(),
            "queued_by": str(identity.get("email") or identity.get("id")),
        }
        quality_score, quality_details = _calculate_quality([review_item], row.schema_type or "DiscountItem")
        new_row = PendingIngestion(
            crawler_name=f"{row.crawler_name}:re-review",
            crawl_status=row.crawl_status,
            strategy_used="published_row_re_review",
            items_count=1,
            items_json=json.dumps([review_item], ensure_ascii=False, default=str),
            schema_type=row.schema_type,
            quality_score=quality_score,
            quality_details=quality_details,
            status=IngestionStatus.CRAWLER_APPROVED,
            crawler_reviewer_notes=(
                f"Queued from ingestion {row.id} item {item_index + 1} for re-review: {body.reason}"
            ),
            crawled_at=datetime.utcnow(),
            source_url=row.source_url,
        )
        session.add(new_row)
        session.flush()
        _append_db_review_note(row, f"published row {item_index + 1} queued for re-review", body.reason)
        log_action(
            session,
            action="ingestion_published_row_re_review",
            entity_type="pending_ingestion",
            entity_id=row.id,
            old_value={"index": item_index, "item": original_item},
            new_value={"new_ingestion_id": new_row.id, "item": review_item},
            request=request,
            user_id=str(identity.get("email") or identity.get("id")),
            metadata={"reason": body.reason},
        )
        return {
            "id": row.id,
            "status": row.status.value if hasattr(row.status, "value") else row.status,
            "re_review_ingestion_id": new_row.id,
            "re_review_status": new_row.status.value,
            "raw_evidence_retained": True,
        }


@router.delete("/{ingestion_id}")
def delete_ingestion(ingestion_id: int, identity: dict = Depends(require_admin)):
    """대기열 항목 삭제."""
    with managed_session() as session:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        session.delete(row)
        return {"status": "deleted", "id": ingestion_id}


# --- 내부 헬퍼 ---


def _ensure_ingestion_rows_editable(row) -> None:
    if row.status not in (IngestionStatus.PENDING, IngestionStatus.CRAWLER_APPROVED):
        status_value = row.status.value if hasattr(row.status, "value") else row.status
        raise HTTPException(400, f"현재 상태({status_value})에서는 행 수정이 불가합니다")


def _persist_items_and_quality(row, items: list[dict]) -> None:
    row.items_json = json.dumps(items, ensure_ascii=False, default=str)
    row.items_count = len(items)
    row.quality_score, row.quality_details = _calculate_quality(items, row.schema_type or "DiscountItem")
    row.approved_items_json = None


def _ai_safe_final_approve_blockers(row, items: list[dict]) -> list[str]:
    blockers: list[str] = []
    if not _is_ai_admin_ingestion(row, items):
        blockers.append("ingestion is not from AI-admin/AI review")
    if not items:
        blockers.append("items are empty")
        return blockers
    schema_type = row.schema_type or "DiscountItem"
    if schema_type != "DiscountItem":
        blockers.append(f"schema_type {schema_type} is not eligible for AI safe final approval")
        return blockers
    for idx, item in enumerate(items):
        try:
            _validate_discount_item_for_publish(item)
        except ValueError as exc:
            blockers.append(f"item {idx + 1}: {exc}")
        if not _is_ai_review_publish(item):
            blockers.append(f"item {idx + 1}: missing AI review audit/provenance")
    return blockers


def _is_ai_admin_ingestion(row, items: list[dict]) -> bool:
    crawler_name = (row.crawler_name or "").lower()
    strategy = (row.strategy_used or "").lower()
    return (
        crawler_name.startswith("ai-admin")
        or "ai_review" in strategy
        or bool(items and all(_is_ai_review_publish(item) for item in items))
    )


def _append_review_note(row, action: str, notes: Optional[str]) -> None:
    if not notes:
        return
    stamp = datetime.utcnow().isoformat(timespec="seconds")
    addition = f"[{stamp}] {action}: {notes}"
    row.crawler_reviewer_notes = (
        f"{row.crawler_reviewer_notes}\n{addition}"
        if row.crawler_reviewer_notes
        else addition
    )


def _append_db_review_note(row, action: str, notes: Optional[str]) -> None:
    stamp = datetime.utcnow().isoformat(timespec="seconds")
    addition = f"[{stamp}] {action}: {notes or ''}".strip()
    row.db_reviewer_notes = (
        f"{row.db_reviewer_notes}\n{addition}"
        if row.db_reviewer_notes
        else addition
    )


def _build_detail_item(session, row) -> dict:
    items = json.loads(row.items_json) if row.items_json else []
    schema_type = row.schema_type or "DiscountItem"
    quality_breakdown = _build_quality_breakdown(items, schema_type, row)
    problem_indices = _find_problem_items(items, schema_type)
    prev_comparison = _compare_with_previous(session, row)

    return {
        "id": row.id,
        "crawler_name": row.crawler_name,
        "crawl_status": row.crawl_status,
        "items_count": row.items_count,
        "schema_type": schema_type,
        "quality_score": row.quality_score,
        "status": row.status.value if hasattr(row.status, "value") else row.status,
        "crawled_at": row.crawled_at.isoformat() if row.crawled_at else None,
        "duration_seconds": row.duration_seconds,
        "items": items,
        "quality_details": row.quality_details,
        "quality_breakdown": quality_breakdown,
        "problem_indices": problem_indices,
        "previous_comparison": prev_comparison,
        "errors": json.loads(row.errors_json) if row.errors_json else [],
        "crawler_reviewer_notes": row.crawler_reviewer_notes,
        "db_reviewer_notes": row.db_reviewer_notes,
        "rejected_reason": row.rejected_reason,
        "approved_items": (
            json.loads(row.approved_items_json)
            if row.approved_items_json
            else None
        ),
        "strategy_used": row.strategy_used,
        "source_url": row.source_url,
        "crawler_reviewed_at": (
            row.crawler_reviewed_at.isoformat()
            if row.crawler_reviewed_at
            else None
        ),
        "db_reviewed_at": (
            row.db_reviewed_at.isoformat() if row.db_reviewed_at else None
        ),
    }


def _build_list_item(r) -> dict:
    """목록 조회용 요약 딕셔너리 (freshness + field quality 포함)."""
    items_data = json.loads(r.items_json) if r.items_json else []
    field_quality = _compute_field_quality(items_data, r.schema_type or "DiscountItem")
    date_range = _extract_date_range(items_data)

    processed_at = None
    if r.db_reviewed_at:
        processed_at = r.db_reviewed_at.isoformat()
    elif r.crawler_reviewed_at:
        processed_at = r.crawler_reviewed_at.isoformat()

    return {
        "id": r.id,
        "crawler_name": r.crawler_name,
        "crawl_status": r.crawl_status,
        "items_count": r.items_count,
        "schema_type": r.schema_type,
        "quality_score": r.quality_score,
        "quality_details": r.quality_details,
        "field_quality": field_quality,
        "status": r.status.value if hasattr(r.status, "value") else r.status,
        "crawled_at": r.crawled_at.isoformat() if r.crawled_at else None,
        "processed_at": processed_at,
        "crawler_reviewed_at": (
            r.crawler_reviewed_at.isoformat() if r.crawler_reviewed_at else None
        ),
        "db_reviewed_at": (
            r.db_reviewed_at.isoformat() if r.db_reviewed_at else None
        ),
        "valid_from": date_range.get("valid_from"),
        "valid_to": date_range.get("valid_to"),
        "duration_seconds": r.duration_seconds,
        "source_url": r.source_url,
    }


def _compute_field_quality(items: list[dict], schema_type: str) -> dict:
    """필드별 완성도 체크리스트를 반환."""
    if not items:
        return {"fields": [], "filled": 0, "total": 0}

    if schema_type == "HotdealPost":
        check_fields = [
            ("title", "제목"),
            ("url", "URL"),
            ("price", "가격"),
            ("source_community", "출처"),
        ]
    else:
        check_fields = [
            ("name", "상품명"),
            ("sale_price", "가격"),
            ("original_price", "원래가"),
            ("image_url", "이미지"),
            ("unit", "단위"),
            ("source", "출처"),
        ]

    result_fields = []
    filled = 0
    for key, label in check_fields:
        present_count = sum(1 for item in items if item.get(key))
        ratio = present_count / len(items) if items else 0
        if ratio >= 0.9:
            status = "ok"
        elif ratio >= 0.3:
            status = "warn"
        else:
            status = "missing"
        if status == "ok":
            filled += 1
        result_fields.append({
            "key": key,
            "label": label,
            "status": status,
            "ratio": round(ratio, 2),
        })

    return {
        "fields": result_fields,
        "filled": filled,
        "total": len(check_fields),
    }


def _extract_date_range(items: list[dict]) -> dict:
    """아이템에서 할인 기간 정보를 추출."""
    date_fields = [
        ("valid_from", "start_date", "event_start", "sale_start"),
        ("valid_to", "end_date", "event_end", "sale_end"),
    ]
    result = {"valid_from": None, "valid_to": None}
    for result_key, *candidates in date_fields:
        for item in items:
            for field in [result_key] + candidates:
                val = item.get(field)
                if val:
                    result[result_key] = str(val)
                    break
            if result[result_key]:
                break
    return result


def _build_quality_breakdown(
    items: list[dict], schema_type: str, row
) -> dict:
    """품질 점수의 상세 breakdown을 반환."""
    if not items:
        return {"field_completeness": 0, "duplicates": 0, "outliers": 0, "format_errors": 0}

    if schema_type == "HotdealPost":
        required = ["title", "url", "price"]
        price_field = "price"
    else:
        required = ["name", "sale_price", "source"]
        price_field = "sale_price"

    # 필드 완성도
    total_fields = len(required) * len(items)
    filled = 0
    missing_fields_detail = []
    for idx, item in enumerate(items):
        item_missing = []
        for f in required:
            if item.get(f):
                filled += 1
            else:
                item_missing.append(f)
        if item_missing:
            missing_fields_detail.append({"index": idx, "fields": item_missing})
    completeness = round(filled / total_fields * 100, 1) if total_fields > 0 else 0

    # 이상치
    prices = [
        item[price_field]
        for item in items
        if isinstance(item.get(price_field), (int, float)) and item[price_field] > 0
    ]
    outlier_indices = []
    if len(prices) >= 3:
        avg = sum(prices) / len(prices)
        for idx, item in enumerate(items):
            p = item.get(price_field)
            if isinstance(p, (int, float)) and p > 0:
                if p > avg * 5 or p < avg * 0.05:
                    outlier_indices.append(idx)

    # 중복
    name_field = "title" if schema_type == "HotdealPost" else "name"
    seen: dict[tuple, int] = {}
    dup_indices = []
    for idx, item in enumerate(items):
        key = (item.get(name_field, ""), item.get(price_field))
        if key in seen:
            dup_indices.append(idx)
            if seen[key] not in dup_indices:
                dup_indices.append(seen[key])
        else:
            seen[key] = idx

    # 형식 오류 (가격이 숫자가 아닌 경우 등)
    format_errors = []
    for idx, item in enumerate(items):
        p = item.get(price_field)
        if p is not None and not isinstance(p, (int, float)):
            format_errors.append({"index": idx, "field": price_field, "value": str(p)[:50]})

    return {
        "field_completeness": completeness,
        "missing_fields": len(missing_fields_detail),
        "missing_fields_detail": missing_fields_detail[:20],
        "duplicates": len(set(dup_indices)),
        "duplicate_indices": sorted(set(dup_indices))[:50],
        "outliers": len(outlier_indices),
        "outlier_indices": outlier_indices[:50],
        "format_errors": len(format_errors),
        "format_errors_detail": format_errors[:20],
        "total_items": len(items),
    }


def _find_problem_items(items: list[dict], schema_type: str) -> list[dict]:
    """각 항목의 문제점을 식별하여 인덱스별 문제 목록 반환."""
    if not items:
        return []

    if schema_type == "HotdealPost":
        required = ["title", "url", "price"]
        price_field = "price"
    else:
        required = ["name", "sale_price", "source"]
        price_field = "sale_price"

    prices = [
        item[price_field]
        for item in items
        if isinstance(item.get(price_field), (int, float)) and item[price_field] > 0
    ]
    avg_price = sum(prices) / len(prices) if prices else 0

    name_field = "title" if schema_type == "HotdealPost" else "name"
    seen: dict[tuple, int] = {}
    dup_map: dict[int, bool] = {}
    for idx, item in enumerate(items):
        key = (item.get(name_field, ""), item.get(price_field))
        if key in seen:
            dup_map[idx] = True
            dup_map[seen[key]] = True
        else:
            seen[key] = idx

    problems = []
    for idx, item in enumerate(items):
        item_problems = []
        # 필수 필드 누락
        for f in required:
            if not item.get(f):
                item_problems.append(f"missing:{f}")
        # 가격 이상치
        p = item.get(price_field)
        if isinstance(p, (int, float)) and avg_price > 0:
            if p > avg_price * 5 or p < avg_price * 0.05:
                item_problems.append("outlier")
        # 형식 오류
        if p is not None and not isinstance(p, (int, float)):
            item_problems.append("format_error")
        # 중복
        if dup_map.get(idx):
            item_problems.append("duplicate")

        if item_problems:
            problems.append({"index": idx, "issues": item_problems})
    return problems


def _compare_with_previous(session, current_row) -> Optional[dict]:
    """같은 크롤러의 이전 수집과 비교."""
    try:
        prev = (
            session.query(PendingIngestion)
            .filter(
                PendingIngestion.crawler_name == current_row.crawler_name,
                PendingIngestion.id != current_row.id,
                PendingIngestion.crawled_at < current_row.crawled_at,
            )
            .order_by(PendingIngestion.crawled_at.desc())
            .first()
        )
        if not prev:
            return None

        prev_items = json.loads(prev.items_json) if prev.items_json else []
        curr_items = json.loads(current_row.items_json) if current_row.items_json else []

        return {
            "previous_id": prev.id,
            "previous_crawled_at": prev.crawled_at.isoformat() if prev.crawled_at else None,
            "previous_items_count": len(prev_items),
            "current_items_count": len(curr_items),
            "items_diff": len(curr_items) - len(prev_items),
            "previous_quality_score": prev.quality_score,
            "current_quality_score": current_row.quality_score,
            "quality_diff": round(
                (current_row.quality_score or 0) - (prev.quality_score or 0), 3
            ),
            "previous_status": prev.status.value if hasattr(prev.status, "value") else prev.status,
        }
    except Exception:
        return None


def _find_published_row_for_item(session, item: dict, schema_type: str):
    if schema_type == "HotdealPost":
        query = session.query(HotdealPrice)
        if item.get("url"):
            found = query.filter(HotdealPrice.source_url == item.get("url")).order_by(HotdealPrice.id.desc()).first()
            if found:
                return "hotdeal_prices", found
        if item.get("title"):
            found = query.filter(HotdealPrice.title == item.get("title")).order_by(HotdealPrice.id.desc()).first()
            if found:
                return "hotdeal_prices", found
        return None

    source = _resolve_source(item)
    model = BaselinePrice if source == "mart_regular" else DiscountHistory
    table_name = "baseline_prices" if model is BaselinePrice else "discount_history"
    raw_id = item.get("raw_record_id") or _item_provenance(item)
    source_key = item.get("source_record_key")
    source_url = item.get("detail_url") or item.get("source_url")
    product_name = item.get("name", "")
    candidates = session.query(model).join(Product, Product.id == model.product_id)
    if product_name:
        candidates = candidates.filter(Product.name == product_name)
    candidates = candidates.order_by(model.id.desc()).all()
    for candidate in candidates:
        raw_data = candidate.raw_data or {}
        observation = raw_data.get("price_observation") if isinstance(raw_data.get("price_observation"), dict) else {}
        if raw_id and raw_id in {
            raw_data.get("raw_record_id"),
            observation.get("raw_record_id"),
            raw_data.get("source_record_key"),
            observation.get("source_record_key"),
        }:
            return table_name, candidate
        if source_key and source_key in {raw_data.get("source_record_key"), observation.get("source_record_key")}:
            return table_name, candidate
    if raw_id or source_key:
        return None
    for candidate in candidates:
        raw_data = candidate.raw_data or {}
        observation = raw_data.get("price_observation") if isinstance(raw_data.get("price_observation"), dict) else {}
        if source_url and source_url in {candidate.source_url, raw_data.get("source_url"), observation.get("source_url")}:
            return table_name, candidate
    return None


def _published_row_snapshot(table_name: str, row) -> dict:
    snapshot = {
        "table": table_name,
        "id": row.id,
        "product_id": getattr(row, "product_id", None),
        "price": getattr(row, "price", None),
        "source": getattr(row, "source", None),
        "source_url": getattr(row, "source_url", None),
        "raw_data": getattr(row, "raw_data", None),
    }
    if hasattr(row, "original_price"):
        snapshot["original_price"] = row.original_price
    if hasattr(row, "discount_rate"):
        snapshot["discount_rate"] = row.discount_rate
    if hasattr(row, "title"):
        snapshot["title"] = row.title
    return snapshot


def _deactivate_empty_product_after_rollback(session, product_id: int) -> None:
    product = session.get(Product, product_id)
    if not product:
        return
    has_discount = session.query(DiscountHistory.id).filter(DiscountHistory.product_id == product_id).first()
    has_baseline = session.query(BaselinePrice.id).filter(BaselinePrice.product_id == product_id).first()
    has_hotdeal = session.query(HotdealPrice.id).filter(HotdealPrice.product_id == product_id).first()
    if not (has_discount or has_baseline or has_hotdeal):
        product.is_active = False
        product.categorization_method = "rolled_back"


def _resolve_source(item: dict) -> str:
    """크롤러 항목에서 source 키를 결정 (한국어/별칭 → 안정 키 변환 포함)."""
    raw = (
        item.get("source")
        or item.get("_source")
        or item.get("source_name")
        or item.get("source_site")
        or item.get("source_type")
        or item.get("store")
        or item.get("source_url")
        or item.get("detail_url")
        or "mart_discount"
    )
    return normalize_source_key(raw, default="mart_discount")


def _unit_price_display_value(item: dict) -> str | None:
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    value = (
        item.get("unit_price_display")
        or item.get("unit_price_displayed")
        or raw_data.get("unit_price_display")
        or raw_data.get("unit_price_displayed")
    )
    return str(value).strip() if value not in (None, "") else None


def _item_attributes_with_unit_display(item: dict) -> dict | None:
    attrs = dict(item.get("attributes") if isinstance(item.get("attributes"), dict) else {})
    unit_price_display = _unit_price_display_value(item)
    if unit_price_display:
        attrs["unit_price_display"] = unit_price_display
    return attrs or None


def _apply_product_match_rule_if_needed(session, item: dict, product_name: str, category_hint: str | None, product_id: int) -> None:
    if not is_missing_or_one_depth_category(category_hint):
        return
    rule = find_matching_rule(session, product_name)
    if not rule:
        return
    product = session.get(Product, product_id)
    if not product:
        return
    apply_rule_to_product(rule, product)
    record_rule_hit(rule)


# 크롤러 소스 → source_type 매핑
_SOURCE_TYPE_MAP = {
    "emart": "mart_crawl",
    "homeplus": "mart_crawl",
    "lottemart": "mart_crawl",
    "costco": "mart_crawl",
    "ppomppu": "community_deal",
    "fmkorea": "community_deal",
    "ruliweb": "community_deal",
    "clien": "community_deal",
    "algumon": "algumon",
    "mart_regular": "baseline",
}


def _ensure_product(
    session,
    name: str,
    crawler_source: str | None = None,
    *,
    category_id: str | None = None,
    image_url: str | None = None,
    unit: str | None = None,
    attributes: dict | None = None,
    promo_label: str | None = None,
    promo_type: str | None = None,
) -> int:
    """Product 레코드가 없으면 자동 생성하고 id를 반환.

    새 상품 생성 시 source_type을 설정하고 자동 카테고리 분류를 시도한다.
    분류 실패는 상품 생성을 차단하지 않는다.
    """
    if not name:
        return 1
    product = session.execute(
        select(Product).where(Product.name == name)
    ).scalar_one_or_none()
    if product:
        source_type = _SOURCE_TYPE_MAP.get(crawler_source, "unknown") if crawler_source else "unknown"
        if source_type != "unknown" and product.source_type in (None, "", "unknown"):
            product.source_type = source_type
        _apply_approved_product_metadata(
            session,
            product,
            category_id=category_id,
            image_url=image_url,
            unit=unit,
            attributes=attributes,
        )
        if promo_label:
            product.promo_label = str(promo_label)
        if promo_type:
            product.promo_type = str(promo_type)
        return product.id

    # Determine source_type from crawler source
    source_type = _SOURCE_TYPE_MAP.get(crawler_source, "unknown") if crawler_source else "unknown"

    new_product = Product(
        name=name,
        unit=unit or "개",
        source_type=source_type,
        image_url=image_url or None,
        attributes=attributes or None,
    )
    session.add(new_product)
    if promo_label:
        new_product.promo_label = str(promo_label)
    if promo_type:
        new_product.promo_type = str(promo_type)
    session.flush()
    _apply_approved_product_metadata(
        session,
        new_product,
        category_id=category_id,
        image_url=image_url,
        unit=unit,
        attributes=attributes,
    )

    # Auto-categorize inline (같은 세션 사용) — must never crash product creation
    try:
        from services.auto_categorize import auto_categorize

        result = auto_categorize(new_product.name, crawler_source)
        if result is not None:
            confidence = getattr(result, "confidence", 0.0)
            cat_id = getattr(result, "category_id", None)
            candidates = getattr(result, "candidates", [])
            parsed_kw = getattr(result, "parsed_keywords", [])
            parsed_attrs = getattr(result, "attributes", {})

            # FK 제약 조건 위반 방지: 카테고리 존재 여부 확인
            if cat_id is not None:
                cat_exists = session.execute(
                    select(Category.id).where(Category.id == cat_id)
                ).scalar_one_or_none()
                if cat_exists is None:
                    logger.warning(
                        "_ensure_product: category_id=%s does not exist for product '%s', skipping categorization",
                        cat_id, name,
                    )
                    cat_id = None

            new_product.categorization_confidence = confidence

            if confidence >= 0.85 and cat_id:
                new_product.category_id = cat_id
                new_product.categorization_method = "auto"
            elif confidence >= 0.50:
                if cat_id:
                    new_product.category_id = cat_id
                new_product.categorization_method = "suggested"
                pending = PendingCategorization(
                    product_id=new_product.id,
                    suggested_category_id=cat_id,
                    confidence=confidence,
                    candidates_json=[{"category_id": c[0], "score": c[1]} for c in candidates[:5]] if candidates else None,
                    parsed_keywords=parsed_kw if parsed_kw else None,
                    parsed_attributes=parsed_attrs if parsed_attrs else None,
                    status="pending",
                )
                session.add(pending)
            else:
                # Low confidence — 상품은 저장하되 미분류 상태로 유지
                new_product.categorization_method = "none"
                if cat_id:
                    pending = PendingCategorization(
                        product_id=new_product.id,
                        suggested_category_id=cat_id,
                        confidence=confidence,
                        candidates_json=[{"category_id": c[0], "score": c[1]} for c in candidates[:5]] if candidates else None,
                        parsed_keywords=parsed_kw if parsed_kw else None,
                        parsed_attributes=parsed_attrs if parsed_attrs else None,
                        status="pending",
                    )
                    session.add(pending)
    except Exception as e:
        logger.warning(
            "_ensure_product: auto-categorization failed for '%s': %s — %s",
            name, type(e).__name__, str(e)[:200],
        )

    return new_product.id


def _apply_approved_product_metadata(
    session,
    product: Product,
    *,
    category_id: str | None = None,
    image_url: str | None = None,
    unit: str | None = None,
    attributes: dict | None = None,
) -> None:
    if image_url and not product.image_url:
        product.image_url = str(image_url)
    if unit and product.unit in (None, "", "개"):
        product.unit = str(unit)
    if attributes:
        product.attributes = {**(product.attributes or {}), **attributes}
    if not category_id:
        return
    cat_exists = session.execute(
        select(Category.id).where(Category.id == category_id)
    ).scalar_one_or_none()
    if cat_exists:
        product.category_id = category_id
        product.categorization_method = "manual"
        product.categorization_confidence = 1.0
        return
    existing_pending = session.execute(
        select(PendingCategorization).where(
            PendingCategorization.product_id == product.id,
            PendingCategorization.suggested_category_id == category_id,
            PendingCategorization.status == "pending",
        )
    ).scalar_one_or_none()
    if existing_pending is None:
        session.add(
            PendingCategorization(
                product_id=product.id,
                suggested_category_id=category_id,
                confidence=1.0,
                candidates_json=[{"category_id": category_id, "score": 1.0}],
                parsed_keywords=None,
                parsed_attributes=attributes or None,
                status="pending",
            )
        )
    product.categorization_method = product.categorization_method or "suggested"
    product.categorization_confidence = product.categorization_confidence or 1.0


def _insert_items(session, items: list[dict], schema_type: str) -> int:
    """승인된 항목을 최종 DB 테이블에 삽입."""
    saved = 0
    for idx, item in enumerate(items):
        try:
            with session.begin_nested():
                if schema_type == "HotdealPost":
                    product_name = item.get("title", "")
                    price = item.get("price")
                    if price is None:
                        raise ValueError("HotdealPost.price is missing; keep it in review until AI/human supplies a price")
                    hotdeal_source = normalize_source_key(
                        item.get("source_community")
                        or item.get("source")
                        or item.get("source_name")
                        or item.get("source_site")
                        or item.get("source_type")
                        or item.get("url"),
                        default="hotdeal",
                    )
                    pid = _ensure_product(session, product_name, crawler_source=hotdeal_source)
                    row = HotdealPrice(
                        product_id=pid,
                        price=float(price),
                        source=hotdeal_source,
                        source_url=item.get("url", ""),
                        title=product_name,
                        crawled_at=datetime.utcnow(),
                    )
                else:
                    source = _resolve_source(item)
                    if source == "mart_regular":
                        product_name = item.get("name", "")
                        price = _coerce_positive_number(item.get("sale_price") or item.get("price"))
                        if price is None:
                            raise ValueError("BaselinePrice.price is missing or invalid")
                        category_hint = item.get("category_id") or item.get("category")
                        pid = _ensure_product(
                            session,
                            product_name,
                            crawler_source=source,
                            category_id=category_hint,
                            image_url=item.get("image_url"),
                            unit=item.get("display_unit") or item.get("unit"),
                            attributes=_item_attributes_with_unit_display(item),
                            promo_label=item.get("promo_label"),
                            promo_type=item.get("promo_type") or item.get("promotion_type"),
                        )
                        _apply_product_match_rule_if_needed(session, item, product_name, category_hint, pid)
                        row = BaselinePrice(
                            product_id=pid,
                            price=price,
                            source=source,
                            unit=item.get("unit", ""),
                            recorded_at=datetime.utcnow(),
                            region=item.get("region"),
                            raw_data=_build_offer_raw_data(item, product_name),
                        )
                    else:
                        # 마트 할인 데이터 → DiscountHistory
                        product_name = item.get("name", "")
                        _validate_discount_item_for_publish(item)
                        price = _coerce_positive_number(
                            item.get("sale_price") or item.get("current_price") or item.get("price")
                        )
                        original_price = _coerce_nonnegative_number(item.get("original_price"))
                        discount_rate = _coerce_nonnegative_number(
                            item.get("discount_percent") or item.get("discount_rate")
                        )
                        category_hint = item.get("category_id") or item.get("category")
                        pid = _ensure_product(
                            session,
                            product_name,
                            crawler_source=source,
                            category_id=category_hint,
                            image_url=item.get("image_url"),
                            unit=item.get("unit"),
                            attributes=_item_attributes_with_unit_display(item),
                            promo_label=item.get("promo_label"),
                            promo_type=item.get("promo_type") or item.get("promotion_type"),
                        )
                        _apply_product_match_rule_if_needed(session, item, product_name, category_hint, pid)
                        row = DiscountHistory(
                            product_id=pid,
                            price=price,
                            original_price=original_price,
                            discount_rate=discount_rate,
                            source=source,
                            source_url=item.get("detail_url")
                                or item.get("source_url", ""),
                            valid_from=_parse_datetime(item.get("valid_from")),
                            valid_to=_parse_datetime(item.get("valid_to")),
                            crawled_at=datetime.utcnow(),
                            raw_data=_build_offer_raw_data(item, product_name),
                        )
                        publish_mart3_rows(
                            session,
                            [_build_normalized_discount_row(item, product_name, source, price)],
                        )
                session.add(row)
                if schema_type != "HotdealPost":
                    _link_product_keywords(session, pid, item.get("keywords"))
                # 개별 flush로 어느 항목에서 오류가 발생하는지 추적 가능
                session.flush()
            saved += 1
        except Exception as e:
            if _is_sqlite_locked(e):
                raise
            logger.warning(
                "[_insert_items] 항목 %d 삽입 실패 (schema=%s): %s — %s",
                idx, schema_type, type(e).__name__, str(e)[:200],
            )
            continue
    return saved


def _is_ai_review_publish(item: dict) -> bool:
    return bool(item.get("ai_review_audit") or item.get("raw_record_id"))


def _validate_discount_item_for_publish(item: dict) -> None:
    price = _coerce_positive_number(item.get("sale_price") or item.get("current_price") or item.get("price"))
    if price is None:
        raise ValueError("DiscountItem.sale_price is missing or invalid; keep it in review")
    if not item.get("name"):
        raise ValueError("DiscountItem.name is missing; keep it in review")
    if not item.get("source"):
        raise ValueError("DiscountItem.source is missing; keep it in review")
    if not _is_ai_review_publish(item):
        return
    unit_metadata = normalize_unit_metadata(
        name=item.get("source_title") or item.get("name") or "",
        sale_price=price,
        raw_unit=item.get("unit") or item.get("raw_unit"),
    )
    required = {
        "image_url": item.get("image_url"),
        "source_url": item.get("source_url") or item.get("detail_url"),
        "display_unit": item.get("display_unit") or item.get("unit") or unit_metadata.get("display_unit"),
        "package_quantity": _coerce_positive_number(item.get("package_quantity") or unit_metadata.get("package_quantity")),
        "package_unit": item.get("package_unit") or unit_metadata.get("package_unit"),
        "provenance": _item_provenance(item),
    }
    missing = [name for name, value in required.items() if value in (None, "")]
    if missing:
        raise ValueError(f"AI-reviewed offer missing customer-visible fields: {', '.join(missing)}")


def _coerce_positive_number(value) -> float | None:
    number = _coerce_nonnegative_number(value)
    if number is None or number <= 0:
        return None
    return number


def _coerce_nonnegative_number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    if isinstance(value, str):
        cleaned = (
            value.replace(",", "")
            .replace("원", "")
            .replace("₩", "")
            .replace("%", "")
            .strip()
        )
        if not cleaned:
            return None
        try:
            number = float(cleaned)
        except ValueError:
            return None
        return number if number >= 0 else None
    return None


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _item_provenance(item: dict):
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    audit = item.get("ai_review_audit") if isinstance(item.get("ai_review_audit"), dict) else {}
    raw_evidence = item.get("raw_evidence") or raw_data.get("raw_evidence")
    return (
        item.get("raw_record_id")
        or item.get("source_record_key")
        or raw_data.get("raw_record_id")
        or raw_data.get("source_record_key")
        or audit.get("raw_record_id")
        or raw_evidence
    )


def _discount_claim_metadata(item: dict) -> dict:
    original_price = _coerce_positive_number(item.get("original_price"))
    discount_rate = _coerce_nonnegative_number(
        item.get("discount_percent") if item.get("discount_percent") is not None else item.get("discount_rate")
    )
    has_full_discount_metadata = original_price is not None and discount_rate is not None
    has_partial_discount_metadata = original_price is not None or discount_rate is not None
    if has_full_discount_metadata:
        claim_type = "verified_discount"
        claim_status = "source_declared"
        claim_source = "source_declared"
    elif has_partial_discount_metadata:
        claim_type = "discount_claim"
        claim_status = "unverified"
        claim_source = "partial_source_metadata"
    else:
        claim_type = "price_observation"
        claim_status = "unknown"
        claim_source = "none"
    return {
        "record_kind": "price_observation",
        "observation_type": "price_observation",
        "claim_type": claim_type,
        "discount_claim_status": claim_status,
        "claim_source": claim_source,
        "has_discount_metadata": has_full_discount_metadata,
        "is_hotdeal_claim": False,
    }


def _build_offer_raw_data(item: dict, product_name: str) -> dict:
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    preserved = {k: v for k, v in item.items() if k not in {"raw_data"}}
    claim_metadata = _discount_claim_metadata(item)
    publication = raw_data.get("publication") if isinstance(raw_data.get("publication"), dict) else {}
    for key in (
        "publication_kind",
        "price_observation_only",
        "discount_claim_status",
        "claim_basis",
        "claim_blockers",
        "has_discount_metadata",
    ):
        value = item.get(key)
        if value is None and publication:
            value = publication.get(key)
        if value is not None:
            claim_metadata[key] = value
    preserved = {**preserved, **claim_metadata}
    sale_price = item.get("sale_price") or item.get("current_price") or item.get("price")
    unit_metadata = normalize_unit_metadata(
        name=product_name,
        sale_price=sale_price,
        raw_unit=item.get("unit") or raw_data.get("unit"),
    )
    attributes = {
        **(raw_data.get("attributes") if isinstance(raw_data.get("attributes"), dict) else {}),
        **(item.get("attributes") if isinstance(item.get("attributes"), dict) else {}),
        **(unit_metadata.get("attributes") or {}),
    }
    return {
        **raw_data,
        **claim_metadata,
        "price_observation": {
            "price": sale_price,
            "source": item.get("source") or raw_data.get("source"),
            "source_url": item.get("source_url") or item.get("detail_url") or raw_data.get("source_url"),
            "raw_record_id": item.get("raw_record_id") or raw_data.get("raw_record_id"),
            "source_record_key": item.get("source_record_key") or raw_data.get("source_record_key"),
            "observed_at": item.get("crawled_at") or item.get("recorded_at") or datetime.utcnow().isoformat(),
        },
        "discount_claim": claim_metadata,
        "published_item": preserved,
        "image_url": item.get("image_url") or raw_data.get("image_url", ""),
        "promo_label": item.get("promo_label") or raw_data.get("promo_label"),
        "promo_type": item.get("promo_type") or raw_data.get("promo_type"),
        "promotion_type": item.get("promotion_type") or item.get("promo_type") or raw_data.get("promotion_type") or raw_data.get("promo_type"),
        "event_name": item.get("event_name") or item.get("promo_label") or raw_data.get("event_name", ""),
        "unit": item.get("unit") or raw_data.get("unit", ""),
        "display_unit": item.get("display_unit")
            or raw_data.get("display_unit")
            or unit_metadata.get("display_unit")
            or item.get("unit")
            or raw_data.get("unit", ""),
        "package_quantity": item.get("package_quantity")
            or raw_data.get("package_quantity")
            or unit_metadata.get("package_quantity"),
        "package_unit": item.get("package_unit")
            or raw_data.get("package_unit")
            or unit_metadata.get("package_unit"),
        "price_per_100g": item.get("price_per_100g")
            or raw_data.get("price_per_100g")
            or unit_metadata.get("price_per_100g"),
        "unit_price_display": item.get("unit_price_display")
            or item.get("unit_price_displayed")
            or raw_data.get("unit_price_display")
            or raw_data.get("unit_price_displayed"),
        "standard_unit": item.get("standard_unit") or raw_data.get("standard_unit"),
        "standard_unit_price": item.get("standard_unit_price") or raw_data.get("standard_unit_price"),
        "bundle_count": item.get("bundle_count") or raw_data.get("bundle_count") or 1,
        "pack_price": sale_price,
        "raw_sale_price": item.get("sale_price") or raw_data.get("sale_price"),
        "raw_original_price": item.get("original_price") or raw_data.get("original_price"),
        "source_title": item.get("source_title") or raw_data.get("source_title") or product_name,
        "source_record_key": item.get("source_record_key") or raw_data.get("source_record_key"),
        "ai_review_audit": item.get("ai_review_audit") or raw_data.get("ai_review_audit"),
        "raw_evidence": item.get("raw_evidence") or raw_data.get("raw_evidence"),
        "attributes": attributes,
        "category": item.get("category") or raw_data.get("category", ""),
        "category_id": item.get("category_id") or raw_data.get("category_id"),
        "keywords": item.get("keywords") or raw_data.get("keywords") or [],
        "product_name": product_name,
        "store": item.get("store") or raw_data.get("store", ""),
        "source_url": item.get("source_url") or item.get("detail_url") or raw_data.get("source_url"),
    }


def _build_normalized_discount_row(item: dict, product_name: str, source: str, price: float | None) -> dict:
    raw_data = item.get("raw_data") if isinstance(item.get("raw_data"), dict) else {}
    raw_evidence = item.get("raw_evidence") or raw_data.get("raw_evidence") or raw_data.get("price_observation") or {}
    audit = item.get("ai_review_audit") if isinstance(item.get("ai_review_audit"), dict) else {}
    unit_metadata = normalize_unit_metadata(
        name=item.get("source_title") or product_name,
        sale_price=price,
        raw_unit=item.get("unit") or raw_data.get("unit"),
    )
    promotion_type = item.get("promotion_type") or item.get("promo_type") or raw_data.get("promotion_type") or raw_data.get("promo_type") or "final_price"
    return {
        "raw_record_id": item.get("raw_record_id") or raw_data.get("raw_record_id"),
        "source": source,
        "source_name": source,
        "source_record_key": item.get("source_record_key") or raw_data.get("source_record_key"),
        "source_title": item.get("source_title") or raw_data.get("source_title") or product_name,
        "canonical_name": product_name,
        "category_id": item.get("category_id") or raw_data.get("category_id") or item.get("category"),
        "category_name": item.get("category_name") or raw_data.get("category_name") or item.get("category"),
        "image_url": item.get("image_url") or raw_data.get("image_url"),
        "source_url": item.get("source_url") or item.get("detail_url") or raw_data.get("source_url"),
        "package_quantity": item.get("package_quantity") or raw_data.get("package_quantity") or unit_metadata.get("package_quantity"),
        "package_unit": item.get("package_unit") or raw_data.get("package_unit") or unit_metadata.get("package_unit"),
        "display_unit": item.get("display_unit") or raw_data.get("display_unit") or unit_metadata.get("display_unit"),
        "unit": item.get("unit") or raw_data.get("unit"),
        "price": price,
        "current_price": price,
        "original_price": item.get("original_price") or raw_data.get("original_price"),
        "discount_rate": item.get("discount_rate") if item.get("discount_rate") is not None else item.get("discount_percent"),
        "discount_percent": item.get("discount_percent") if item.get("discount_percent") is not None else raw_data.get("discount_percent"),
        "price_state": item.get("price_state") or raw_data.get("price_state"),
        "promotion_type": promotion_type,
        "promo_label": item.get("promo_label") or raw_data.get("promo_label"),
        "promo_type": item.get("promo_type") or raw_data.get("promo_type"),
        "event_name": item.get("event_name") or item.get("promo_label") or raw_data.get("event_name"),
        "standard_unit": item.get("standard_unit") or raw_data.get("standard_unit"),
        "standard_unit_price": item.get("standard_unit_price") or raw_data.get("standard_unit_price"),
        "price_per_100g": item.get("price_per_100g") or raw_data.get("price_per_100g") or unit_metadata.get("price_per_100g"),
        "unit_price_display": item.get("unit_price_display") or item.get("unit_price_displayed") or raw_data.get("unit_price_display") or raw_data.get("unit_price_displayed"),
        "bundle_count": item.get("bundle_count") or raw_data.get("bundle_count") or 1,
        "week_start": item.get("week_start") or raw_data.get("week_start") or item.get("valid_from"),
        "week_end": item.get("week_end") or raw_data.get("week_end") or item.get("valid_to"),
        "valid_from": item.get("valid_from") or raw_data.get("valid_from"),
        "valid_to": item.get("valid_to") or raw_data.get("valid_to"),
        "crawled_at": item.get("crawled_at") or raw_data.get("crawled_at") or item.get("recorded_at"),
        "raw_evidence": raw_evidence if isinstance(raw_evidence, dict) else {"value": raw_evidence},
        "audit_provenance": {
            **audit,
            "publication_kind": item.get("publication_kind") or raw_data.get("publication_kind"),
        },
        "attributes": item.get("attributes") if isinstance(item.get("attributes"), dict) else raw_data.get("attributes"),
        "keywords": item.get("keywords") or raw_data.get("keywords") or [],
    }


def _link_product_keywords(session, product_id: int, keywords) -> None:
    terms = _keyword_terms(keywords)
    for term in terms:
        keyword = session.execute(
            select(Keyword).where(Keyword.word == term, Keyword.is_active.is_(True))
        ).scalar_one_or_none()
        if keyword is None:
            keyword = session.execute(
                select(Keyword).where(Keyword.synonyms.is_not(None), Keyword.is_active.is_(True))
            ).scalars().all()
            keyword = next((kw for kw in keyword if term in (kw.synonyms or [])), None)
        if keyword is None:
            continue
        exists = session.execute(
            select(ProductKeyword).where(
                ProductKeyword.product_id == product_id,
                ProductKeyword.keyword_id == keyword.id,
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(ProductKeyword(product_id=product_id, keyword_id=keyword.id))


def _keyword_terms(keywords) -> list[str]:
    if keywords is None:
        return []
    values = keywords if isinstance(keywords, list) else [keywords]
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        term = value.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result
