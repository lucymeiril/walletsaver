"""raw vs DB row-count gate API 라우트.

GET /api/raw_vs_db_gate?run_id={source_run_id}
    - source_run_id: RawCrawlBatch.batch_id 또는 root_batch_id 접두어.
    - 응답: services.raw_vs_db_gate.compare() 반환값 그대로 JSON.

GET /api/raw_vs_db_gate/summary?limit=20
    - 최근 N개 배치의 drop 요약 목록.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from api.deps import get_db_session
from services.raw_vs_db_gate import compare
from storage.models import RawCrawlBatch

router = APIRouter(prefix="/api/raw_vs_db_gate", tags=["raw-vs-db-gate"])


@router.get("")
def gate_check(
    run_id: str = Query(..., description="배치 ID 또는 root_batch_id"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """단일 배치의 raw vs DB row count 비교 결과를 반환한다.

    Examples:
        GET /api/raw_vs_db_gate?run_id=source-20240101T000000Z-abc12345
        GET /api/raw_vs_db_gate?run_id=raw-abc1234567890abc
    """
    if not run_id or not run_id.strip():
        raise HTTPException(status_code=422, detail="run_id is required")
    return compare(run_id.strip(), session)


@router.get("/summary")
def gate_summary(
    limit: int = Query(default=20, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """최근 N개 distinct root batch의 drop 요약 목록.

    batch_id에서 '-{3자리 숫자}' 접미사를 제거해 root batch를 추출한다.
    동적 마트 추가 시 코드 수정 없이 동작한다.
    """
    import re

    # 최근 배치 distinct batch_id 조회
    rows = session.execute(
        select(RawCrawlBatch.batch_id, RawCrawlBatch.source_name, RawCrawlBatch.created_at)
        .order_by(RawCrawlBatch.created_at.desc())
        .limit(limit * 5)  # 중복 제거 여유분
    ).all()

    seen: set[str] = set()
    root_ids: list[str] = []
    for row in rows:
        bid = row[0]
        # '-001', '-002' 접미사 제거해 root_batch_id 추출
        root = re.sub(r"-\d{3}$", "", bid)
        if root not in seen:
            seen.add(root)
            root_ids.append(root)
        if len(root_ids) >= limit:
            break

    items = []
    for rid in root_ids:
        result = compare(rid, session)
        items.append({
            "source_run_id": rid,
            "status": result["status"],
            "raw_count": result["raw_count"],
            "ai_raw_count": result["ai_raw_count"],
            "drop_pct": result["drop_pct"],
            "by_mart": result["by_mart"],
        })

    return {"items": items, "count": len(items)}
