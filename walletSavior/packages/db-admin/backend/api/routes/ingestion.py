"""대기열(Pending Ingestion) API — 크롤 결과 수신, 검토, 승인/거부"""

import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from services.base import get_session
from api.middleware.rate_limit import limiter, INGESTION_LIMIT
from starlette.requests import Request as StarletteRequest
from storage.models import (
    PendingIngestion,
    IngestionStatus,
    BaselinePrice,
    DiscountHistory,
    HotdealPrice,
    Product,
    PendingCategorization,
)

router = APIRouter(prefix="/api/ingestions", tags=["ingestions"])


# --- Request 모델 ---


class IngestionSubmit(BaseModel):
    crawler_name: str
    crawl_status: str = "success"
    items: list[dict] = []
    schema_type: str = "DiscountItem"
    strategy_used: Optional[str] = None
    duration_seconds: Optional[float] = None
    errors: list[dict] = []
    source_url: Optional[str] = None


class ReviewRequest(BaseModel):
    action: str  # "approve", "reject", "partial"
    notes: Optional[str] = None
    approved_item_indices: Optional[list[int]] = None
    rejected_reason: Optional[str] = None


class BulkApproveRequest(BaseModel):
    ids: list[int]
    reviewer: Optional[str] = None
    notes: Optional[str] = None


class CleanupRequest(BaseModel):
    status: list[str] = ["approved", "rejected"]
    older_than_days: Optional[int] = None
    confirm: bool = False


# --- 품질 점수 계산 ---


def _calculate_quality(items: list[dict], schema_type: str) -> tuple[float, dict]:
    """크롤 데이터의 품질 점수(0.0~1.0)와 상세 내역 반환."""
    if not items:
        return 0.0, {"error": "항목 없음"}

    # 필수 필드 검사
    if schema_type == "HotdealPost":
        required = ["title", "url"]
    else:
        required = ["name", "sale_price"]

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

    # 점수 계산
    score = 1.0 - (missing_ratio * 0.4) - (outlier_ratio * 0.3) - (dup_ratio * 0.3)
    score = max(0.0, min(1.0, round(score, 3)))

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
def ingestion_stats():
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
def bulk_approve(body: BulkApproveRequest):
    """선택된 여러 수집을 일괄 승인."""
    if not body.ids:
        raise HTTPException(400, "ids가 비어 있습니다")
    session = get_session()
    try:
        results = []
        for ingestion_id in body.ids:
            row = session.get(PendingIngestion, ingestion_id)
            if not row:
                results.append({"id": ingestion_id, "status": "not_found"})
                continue
            if row.status != IngestionStatus.CRAWLER_APPROVED:
                results.append({
                    "id": ingestion_id,
                    "status": "skipped",
                    "reason": f"상태가 {row.status.value if hasattr(row.status, 'value') else row.status}",
                })
                continue
            items = json.loads(row.items_json) if row.items_json else []
            saved = _insert_items(session, items, row.schema_type)
            row.status = IngestionStatus.APPROVED
            row.db_reviewer_notes = body.notes or f"벌크 승인 (reviewer: {body.reviewer or 'system'})"
            row.db_reviewed_at = datetime.utcnow()
            results.append({"id": ingestion_id, "status": "approved", "saved": saved})
        session.commit()
        approved_count = sum(1 for r in results if r["status"] == "approved")
        return {
            "approved": approved_count,
            "total_requested": len(body.ids),
            "results": results,
        }
    finally:
        session.close()


@router.post("/cleanup")
def cleanup_ingestions(body: CleanupRequest):
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

    session = get_session()
    try:
        q = session.query(PendingIngestion).filter(
            PendingIngestion.status.in_(target_statuses)
        )
        if body.older_than_days is not None:
            cutoff = datetime.utcnow() - timedelta(days=body.older_than_days)
            q = q.filter(PendingIngestion.crawled_at < cutoff)

        count = q.count()
        if count > 0:
            q.delete(synchronize_session="fetch")
            session.commit()
        return {"deleted": count}
    finally:
        session.close()


@router.post("")
@limiter.limit(INGESTION_LIMIT)
def submit_ingestion(request: StarletteRequest, body: IngestionSubmit):
    """크롤러가 데이터를 대기열에 제출."""
    session = get_session()
    try:
        quality_score, quality_details = _calculate_quality(
            body.items, body.schema_type
        )
        row = PendingIngestion(
            crawler_name=body.crawler_name,
            crawl_status=body.crawl_status,
            strategy_used=body.strategy_used,
            items_count=len(body.items),
            items_json=json.dumps(body.items, ensure_ascii=False, default=str),
            schema_type=body.schema_type,
            quality_score=quality_score,
            quality_details=quality_details,
            errors_json=(
                json.dumps(body.errors, ensure_ascii=False, default=str)
                if body.errors
                else None
            ),
            status=IngestionStatus.PENDING,
            crawled_at=datetime.utcnow(),
            duration_seconds=body.duration_seconds,
            source_url=body.source_url,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {"id": row.id, "status": "pending", "quality_score": quality_score}
    finally:
        session.close()


@router.get("")
def list_ingestions(
    status: Optional[str] = Query(None, description="상태 필터"),
    crawler_name: Optional[str] = Query(None, description="크롤러 필터"),
    page: int = Query(1, ge=1, description="페이지 번호"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    limit: int = Query(None, ge=1, le=500, description="(하위호환) limit"),
    offset: int = Query(None, ge=0, description="(하위호환) offset"),
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
def get_ingestion(ingestion_id: int):
    """대기열 항목 상세 조회 — 항목 미리보기 + 품질 breakdown + 이전 비교."""
    session = get_session()
    try:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")

        items = json.loads(row.items_json) if row.items_json else []
        schema_type = row.schema_type or "DiscountItem"

        # 품질 breakdown 계산
        quality_breakdown = _build_quality_breakdown(items, schema_type, row)

        # 문제 항목 인덱스 표시
        problem_indices = _find_problem_items(items, schema_type)

        # 이전 수집과 비교
        prev_comparison = _compare_with_previous(session, row)

        return {
            "id": row.id,
            "crawler_name": row.crawler_name,
            "crawl_status": row.crawl_status,
            "items_count": row.items_count,
            "schema_type": schema_type,
            "quality_score": row.quality_score,
            "status": row.status.value
            if hasattr(row.status, "value")
            else row.status,
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
    finally:
        session.close()


@router.post("/{ingestion_id}/crawler-review")
def crawler_review(ingestion_id: int, body: ReviewRequest):
    """크롤러 관리자 1차 검토 — 승인/거부."""
    session = get_session()
    try:
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
        session.commit()
        return {"id": row.id, "status": row.status.value}
    finally:
        session.close()


@router.post("/{ingestion_id}/db-review")
def db_review(ingestion_id: int, body: ReviewRequest):
    """DB 관리자 최종 검토 — 승인 시 실제 DB 테이블에 삽입."""
    session = get_session()
    try:
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
            row.status = IngestionStatus.APPROVED
            row.db_reviewer_notes = body.notes
            row.db_reviewed_at = datetime.utcnow()
            session.commit()
            return {"id": row.id, "status": "approved", "saved": saved}

        elif body.action == "reject":
            row.status = IngestionStatus.REJECTED
            row.rejected_reason = body.rejected_reason or body.notes
            row.db_reviewer_notes = body.notes
            row.db_reviewed_at = datetime.utcnow()
            session.commit()
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
            row.status = IngestionStatus.PARTIAL
            row.approved_items_json = json.dumps(
                approved, ensure_ascii=False, default=str
            )
            row.db_reviewer_notes = body.notes
            row.db_reviewed_at = datetime.utcnow()
            session.commit()
            return {"id": row.id, "status": "partial", "saved": saved}

        else:
            raise HTTPException(400, f"잘못된 액션: {body.action}")
    finally:
        session.close()


@router.delete("/{ingestion_id}")
def delete_ingestion(ingestion_id: int):
    """대기열 항목 삭제."""
    session = get_session()
    try:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        session.delete(row)
        session.commit()
        return {"status": "deleted", "id": ingestion_id}
    finally:
        session.close()


# --- 내부 헬퍼 ---


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
        required = ["title", "url"]
        price_field = "price"
    else:
        required = ["name", "sale_price"]
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

# 한국어 마트명 → DB source 키 매핑
_STORE_NAME_MAP = {
    "이마트": "emart",
    "홈플러스": "homeplus",
    "롯데마트": "lottemart",
    "코스트코": "costco",
}


def _resolve_source(item: dict) -> str:
    """크롤러 항목에서 source 키를 결정 (한국어 → 영문 변환 포함)."""
    raw = (
        item.get("source")
        or item.get("_source")
        or item.get("store")
        or "mart_discount"
    )
    return _STORE_NAME_MAP.get(raw, raw)


# 크롤러 소스 → source_type 매핑
_SOURCE_TYPE_MAP = {
    "emart": "mart_crawl",
    "homeplus": "mart_crawl",
    "lottemart": "mart_crawl",
    "costco": "mart_crawl",
    "ppomppu": "community_deal",
    "fmkorea": "community_deal",
    "clien": "community_deal",
    "government": "baseline",
    "mart_regular": "baseline",
}


def _ensure_product(session, name: str, crawler_source: str | None = None) -> int:
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
        return product.id

    # Determine source_type from crawler source
    source_type = _SOURCE_TYPE_MAP.get(crawler_source, "unknown") if crawler_source else "unknown"

    new_product = Product(name=name, unit="개", source_type=source_type)
    session.add(new_product)
    session.flush()

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
    except Exception:
        pass

    return new_product.id


def _insert_items(session, items: list[dict], schema_type: str) -> int:
    """승인된 항목을 최종 DB 테이블에 삽입."""
    saved = 0
    for item in items:
        try:
            if schema_type == "HotdealPost":
                product_name = item.get("title", "")
                hotdeal_source = item.get("source_community", "hotdeal")
                pid = _ensure_product(session, product_name, crawler_source=hotdeal_source)
                row = HotdealPrice(
                    product_id=pid,
                    price=float(item.get("price", 0)),
                    source=hotdeal_source,
                    source_url=item.get("url", ""),
                    title=product_name,
                    crawled_at=datetime.utcnow(),
                )
            else:
                source = _resolve_source(item)
                if source in ("government", "mart_regular"):
                    product_name = item.get("name", "")
                    pid = _ensure_product(session, product_name, crawler_source=source)
                    row = BaselinePrice(
                        product_id=pid,
                        price=float(
                            item.get("sale_price") or item.get("price", 0)
                        ),
                        source=source,
                        unit=item.get("unit", ""),
                        recorded_at=datetime.utcnow(),
                        region=item.get("region"),
                    )
                else:
                    # 마트 할인 데이터 → DiscountHistory
                    product_name = item.get("name", "")
                    pid = _ensure_product(session, product_name, crawler_source=source)
                    row = DiscountHistory(
                        product_id=pid,
                        price=float(
                            item.get("sale_price") or item.get("price", 0)
                        ),
                        original_price=item.get("original_price"),
                        discount_rate=item.get("discount_percent")
                            or item.get("discount_rate"),
                        source=source,
                        source_url=item.get("detail_url")
                            or item.get("source_url", ""),
                        crawled_at=datetime.utcnow(),
                        raw_data={
                            "image_url": item.get("image_url", ""),
                            "event_name": item.get("event_name", ""),
                            "unit": item.get("unit", ""),
                            "category": item.get("category", ""),
                            "product_name": product_name,
                            "store": item.get("store", ""),
                        },
                    )
            session.add(row)
            saved += 1
        except Exception:
            continue
    return saved
