"""Match monitor API — cumulative ProductMatch/LearnedKnowledge stats and per-run history."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.deps import get_db_session

router = APIRouter(prefix="/api/match-monitor", tags=["match-monitor"])


@router.get("/cumulative")
def get_cumulative(session: Session = Depends(get_db_session)):
    """Cumulative ProductMatch/LearnedKnowledge stats."""
    from storage.repositories import (
        LearnedKnowledgeRepository,
        ProductMatchStoreRepository,
    )

    pm_repo = ProductMatchStoreRepository(session)
    lk_repo = LearnedKnowledgeRepository(session)

    return {
        "product_match": {
            "total": pm_repo.count_all(),
            "by_status": pm_repo.count_by_status(),
            "by_source": pm_repo.count_by_source(),
        },
        "learned_knowledge": {
            "total": lk_repo.count_all(),
            "by_type": lk_repo.count_by_type(),
            "success_count_distribution": lk_repo.success_count_distribution(),
        },
    }


@router.get("/runs")
def get_runs(n: int = 20, session: Session = Depends(get_db_session)):
    """Recent N labeling runs with per-run stats."""
    from storage.repositories import LabelingRunLogRepository

    repo = LabelingRunLogRepository(session)
    runs = repo.list_recent(limit=max(1, min(n, 200)))
    return {"runs": runs, "total": repo.count()}
