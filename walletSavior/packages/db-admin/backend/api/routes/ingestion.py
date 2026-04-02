"""대기열(Pending Ingestion) API — 크롤 결과 수신, 검토, 승인/거부"""

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from services.base import get_session
from storage.models import (
    PendingIngestion,
    IngestionStatus,
    BaselinePrice,
    DiscountHistory,
    HotdealPrice,
    Product,
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


@router.post("", status_code=201)
def submit_ingestion(body: IngestionSubmit):
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
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """대기열 목록 조회 (summary)."""
    session = get_session()
    try:
        q = session.query(PendingIngestion)
        if status:
            q = q.filter(PendingIngestion.status == status)
        if crawler_name:
            q = q.filter(PendingIngestion.crawler_name == crawler_name)
        q = q.order_by(PendingIngestion.crawled_at.desc())
        total = q.count()
        rows = q.offset(offset).limit(limit).all()
        return {
            "total": total,
            "items": [
                {
                    "id": r.id,
                    "crawler_name": r.crawler_name,
                    "crawl_status": r.crawl_status,
                    "items_count": r.items_count,
                    "schema_type": r.schema_type,
                    "quality_score": r.quality_score,
                    "status": r.status.value
                    if hasattr(r.status, "value")
                    else r.status,
                    "crawled_at": r.crawled_at.isoformat()
                    if r.crawled_at
                    else None,
                    "duration_seconds": r.duration_seconds,
                }
                for r in rows
            ],
        }
    finally:
        session.close()


@router.get("/{ingestion_id}")
def get_ingestion(ingestion_id: int):
    """대기열 항목 상세 조회 — 항목 미리보기 포함."""
    session = get_session()
    try:
        row = session.get(PendingIngestion, ingestion_id)
        if not row:
            raise HTTPException(404, "대기열 항목을 찾을 수 없습니다")
        return {
            "id": row.id,
            "crawler_name": row.crawler_name,
            "crawl_status": row.crawl_status,
            "items_count": row.items_count,
            "schema_type": row.schema_type,
            "quality_score": row.quality_score,
            "status": row.status.value
            if hasattr(row.status, "value")
            else row.status,
            "crawled_at": row.crawled_at.isoformat() if row.crawled_at else None,
            "duration_seconds": row.duration_seconds,
            "items": json.loads(row.items_json) if row.items_json else [],
            "quality_details": row.quality_details,
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


def _ensure_product(session, name: str) -> int:
    """Product 레코드가 없으면 자동 생성하고 id를 반환."""
    if not name:
        return 1
    product = session.execute(
        select(Product).where(Product.name == name)
    ).scalar_one_or_none()
    if product:
        return product.id
    new_product = Product(name=name, unit="개")
    session.add(new_product)
    session.flush()
    return new_product.id


def _insert_items(session, items: list[dict], schema_type: str) -> int:
    """승인된 항목을 최종 DB 테이블에 삽입."""
    saved = 0
    for item in items:
        try:
            if schema_type == "HotdealPost":
                product_name = item.get("title", "")
                pid = _ensure_product(session, product_name)
                row = HotdealPrice(
                    product_id=pid,
                    price=float(item.get("price", 0)),
                    source=item.get("source_community", "hotdeal"),
                    source_url=item.get("url", ""),
                    title=product_name,
                    crawled_at=datetime.utcnow(),
                )
            else:
                source = _resolve_source(item)
                if source in ("government", "mart_regular"):
                    product_name = item.get("name", "")
                    pid = _ensure_product(session, product_name)
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
                    pid = _ensure_product(session, product_name)
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
