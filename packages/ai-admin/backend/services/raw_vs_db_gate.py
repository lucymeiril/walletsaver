"""WalletSavior raw vs DB row-count gate (rd3-rawvsdb-gate).

역할:
    크롤러가 ai-admin으로 전송한 raw 레코드 수와 실제 DB에 적재된 레코드 수를
    비교하는 게이트.  코스트코 OCC 995×3건이 0건으로 흡수되는 silent gap을
    수치로 명시화하고, 임계치 초과 시 status=fail을 반환한다.

비교 단계:
    raw_count        : raw_crawl_batches.item_count 합계 (전송 신고 수)
    ai_raw_count     : raw_crawl_records 실제 저장 수
    match_count      : product_matches (같은 batch_id)
    canonical_count  : product_matches 중 distinct canonical_product_id
    publish_count    : ai_publish_records status='published'

status 결정:
    raw → ai_raw drop > THRESHOLD → fail  (silent gap 의심)
    그 외 → pass

임계치:
    기본 5%.  ENV WALLETSAVIOR_RAWVSDB_DROP_THRESHOLD 로 오버라이드.

batch_id 매칭 전략:
    1. batch_id = source_run_id (정확 일치)
    2. batch_id LIKE 'source_run_id-%' (멀티-배치 split 결과)
    두 조건을 OR로 합산한다.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from sqlalchemy import func, select, distinct, or_
from sqlalchemy.orm import Session

from storage.models import (
    AIPublishRecord,
    ProductMatch,
    RawCrawlBatch,
    RawCrawlRecord,
)

# ── 임계치 ────────────────────────────────────────────────────────────────────
_DEFAULT_DROP_THRESHOLD: float = 0.05
_THRESHOLD_ENV = "WALLETSAVIOR_RAWVSDB_DROP_THRESHOLD"


def get_threshold() -> float:
    """ENV 오버라이드를 반영한 현재 drop 임계치를 반환한다."""
    raw = os.environ.get(_THRESHOLD_ENV)
    if raw:
        try:
            v = float(raw)
            if 0.0 <= v <= 1.0:
                return v
        except (TypeError, ValueError):
            pass
    return _DEFAULT_DROP_THRESHOLD


# ── 핵심 함수 ─────────────────────────────────────────────────────────────────

def _batch_id_filter(source_run_id: str):
    """SQLAlchemy 컬럼 필터 — 정확 일치 또는 멀티-배치 prefix 매칭."""
    prefix_pattern = source_run_id + "-%"
    return or_(
        RawCrawlBatch.batch_id == source_run_id,
        RawCrawlBatch.batch_id.like(prefix_pattern),
    )


def _record_batch_filter(source_run_id: str):
    """RawCrawlRecord 용 batch_id 필터."""
    prefix_pattern = source_run_id + "-%"
    return or_(
        RawCrawlRecord.batch_id == source_run_id,
        RawCrawlRecord.batch_id.like(prefix_pattern),
    )


def _match_batch_filter(source_run_id: str):
    """ProductMatch 용 batch_id 필터."""
    prefix_pattern = source_run_id + "-%"
    return or_(
        ProductMatch.batch_id == source_run_id,
        ProductMatch.batch_id.like(prefix_pattern),
    )


def _publish_batch_filter(source_run_id: str):
    """AIPublishRecord 용 batch_id 필터."""
    prefix_pattern = source_run_id + "-%"
    return or_(
        AIPublishRecord.batch_id == source_run_id,
        AIPublishRecord.batch_id.like(prefix_pattern),
    )


def _safe_drop_pct(numerator: int, denominator: int) -> Optional[float]:
    """(denominator - numerator) / denominator. denominator=0 이면 None."""
    if denominator == 0:
        return None
    dropped = denominator - numerator
    return round(dropped / denominator, 4)


def compare(source_run_id: str, session: Session) -> dict[str, Any]:
    """raw_crawl_batches vs DB 레코드 수 비교 결과를 반환한다.

    Args:
        source_run_id: 비교할 배치 ID (root_batch_id 또는 단일 batch_id).
        session: ai-admin control DB SQLAlchemy 세션.

    Returns:
        {
            "source_run_id": str,
            "raw_count": int,          # RawCrawlBatch.item_count 합계
            "ai_raw_count": int,       # RawCrawlRecord 실제 저장 수
            "match_count": int,        # ProductMatch 수
            "canonical_count": int,    # distinct canonical_product_id
            "publish_count": int,      # AIPublishRecord status=published
            "drop_pct": float | None,  # raw→ai_raw 드롭 비율 (0~1)
            "threshold": float,        # 현재 임계치
            "status": "pass" | "fail", # drop_pct > threshold → fail
            "stages": list[dict],      # 단계별 드롭 비율 표
            "by_mart": dict,           # source_name별 세부 카운트
        }
    """
    threshold = get_threshold()

    # ── raw_count: RawCrawlBatch.item_count 합계 ──────────────────────────────
    raw_count_row = session.execute(
        select(func.coalesce(func.sum(RawCrawlBatch.item_count), 0))
        .where(_batch_id_filter(source_run_id))
    ).scalar()
    raw_count: int = int(raw_count_row or 0)

    # ── ai_raw_count: 실제 저장된 RawCrawlRecord 수 ──────────────────────────
    ai_raw_count_row = session.execute(
        select(func.count(RawCrawlRecord.raw_record_id))
        .where(_record_batch_filter(source_run_id))
    ).scalar()
    ai_raw_count: int = int(ai_raw_count_row or 0)

    # ── match_count: ProductMatch 수 ─────────────────────────────────────────
    match_count_row = session.execute(
        select(func.count(ProductMatch.match_id))
        .where(_match_batch_filter(source_run_id))
    ).scalar()
    match_count: int = int(match_count_row or 0)

    # ── canonical_count: distinct canonical_product_id ───────────────────────
    canonical_count_row = session.execute(
        select(func.count(distinct(ProductMatch.canonical_product_id)))
        .where(
            _match_batch_filter(source_run_id),
            ProductMatch.canonical_product_id.isnot(None),
        )
    ).scalar()
    canonical_count: int = int(canonical_count_row or 0)

    # ── publish_count: AIPublishRecord 중 published ───────────────────────────
    publish_count_row = session.execute(
        select(func.count(AIPublishRecord.raw_record_id))
        .where(
            _publish_batch_filter(source_run_id),
            AIPublishRecord.status == "published",
        )
    ).scalar()
    publish_count: int = int(publish_count_row or 0)

    # ── drop 비율 계산 ────────────────────────────────────────────────────────
    drop_pct = _safe_drop_pct(ai_raw_count, raw_count)

    # ── status 결정 ───────────────────────────────────────────────────────────
    if drop_pct is None:
        # raw_count=0 → 비교 불가, 데이터 없음
        status = "no_data"
    elif drop_pct > threshold:
        status = "fail"
    else:
        status = "pass"

    # ── 단계별 드롭 비율 표 ───────────────────────────────────────────────────
    stages = [
        {
            "stage": "raw→ai_raw",
            "in": raw_count,
            "out": ai_raw_count,
            "drop_pct": drop_pct,
            "alert": drop_pct is not None and drop_pct > threshold,
        },
        {
            "stage": "ai_raw→match",
            "in": ai_raw_count,
            "out": match_count,
            "drop_pct": _safe_drop_pct(match_count, ai_raw_count),
            "alert": False,
        },
        {
            "stage": "match→publish",
            "in": match_count,
            "out": publish_count,
            "drop_pct": _safe_drop_pct(publish_count, match_count),
            "alert": False,
        },
    ]

    # ── source_name(마트)별 세부 ──────────────────────────────────────────────
    by_mart = _by_mart(source_run_id, session)

    return {
        "source_run_id": source_run_id,
        "raw_count": raw_count,
        "ai_raw_count": ai_raw_count,
        "match_count": match_count,
        "canonical_count": canonical_count,
        "publish_count": publish_count,
        "drop_pct": drop_pct,
        "threshold": threshold,
        "status": status,
        "stages": stages,
        "by_mart": by_mart,
    }


def _by_mart(source_run_id: str, session: Session) -> dict[str, dict[str, int]]:
    """source_name(마트)별 raw_count / ai_raw_count 집계.

    동적 마트 추가 시 코드 수정 없이 동작한다 (쿼리가 source_name을 자동 열거).
    """
    # RawCrawlBatch 단위 raw_count
    batch_rows = session.execute(
        select(RawCrawlBatch.source_name, func.sum(RawCrawlBatch.item_count))
        .where(_batch_id_filter(source_run_id))
        .group_by(RawCrawlBatch.source_name)
    ).all()

    mart_raw: dict[str, int] = {row[0]: int(row[1] or 0) for row in batch_rows}

    # RawCrawlRecord 단위 ai_raw_count
    record_rows = session.execute(
        select(RawCrawlRecord.source_name, func.count(RawCrawlRecord.raw_record_id))
        .where(_record_batch_filter(source_run_id))
        .group_by(RawCrawlRecord.source_name)
    ).all()

    mart_ai_raw: dict[str, int] = {row[0]: int(row[1] or 0) for row in record_rows}

    all_marts = set(mart_raw) | set(mart_ai_raw)
    result: dict[str, dict[str, int]] = {}
    for mart in sorted(all_marts):
        rc = mart_raw.get(mart, 0)
        arc = mart_ai_raw.get(mart, 0)
        dp = _safe_drop_pct(arc, rc)
        result[mart] = {
            "raw_count": rc,
            "ai_raw_count": arc,
            "drop_pct": dp,
        }
    return result
