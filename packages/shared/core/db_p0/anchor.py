"""P0#7 — 도매 anchor 3-layer + freshness_decay + lineage.

db-FINAL §2-5. lineage_group으로 같은 원천 재가공 중복 weight 방지.
parser 깨짐과 진짜 소스 중단을 failure_kind로 구분.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from enum import Enum
from typing import Iterable, Optional

from pydantic import BaseModel, Field, ConfigDict


class SourceClass(str, Enum):
    WHOLESALE = "wholesale"
    RETAIL_MARKETPLACE = "retail_marketplace"
    OVERSEAS_DIRECT = "overseas_direct"
    WAREHOUSE_BULK = "warehouse_bulk"
    MANUAL_ADMIN = "manual_admin"


class FailureKind(str, Enum):
    NETWORK = "network"
    PARSER = "parser"
    AUTH = "auth"
    EMPTY = "empty"


class SourceStatus(str, Enum):
    ACTIVE = "active"
    STALE = "stale"
    DEAD = "dead"


class WholesaleBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    source_code: str
    source_class: SourceClass
    source_lineage_group: str
    commodity_key: str
    observed_date: date
    observed_at_utc: datetime
    unit_price_krw: float = Field(gt=0)
    unit_basis: str
    region_hint: Optional[str] = None
    raw_payload: Optional[dict] = None
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WholesaleSourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_code: str
    display_name: str
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    failure_kind: Optional[FailureKind] = None
    consecutive_fails: int = 0
    freshness_days: int = 0
    confidence_weight: float = Field(ge=0.0, le=1.0, default=1.0)
    status: SourceStatus = SourceStatus.ACTIVE


class CategoryFreshnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str
    half_life_days: int = Field(ge=1, default=30)


def _decay(age_days: float, half_life_days: int) -> float:
    """exponential half-life. 신선식품은 7일, 가공식품은 30일 (§2-5 카테고리별 half-life)."""
    if age_days <= 0:
        return 1.0
    return math.pow(0.5, age_days / half_life_days)


def effective_anchor(
    baselines: Iterable[WholesaleBaseline],
    statuses: dict[str, WholesaleSourceStatus],
    half_life_days: int,
    *,
    as_of: Optional[datetime] = None,
) -> Optional[tuple[float, bool]]:
    """다중 소스 가중 평균 + freshness decay. 같은 lineage_group은 한 표.

    반환: (anchor_price_krw, is_stale). 가용 신호가 0이면 None.
    is_stale=True면 UI는 fallback 메시지("도매 anchor 오래됨")를 띄우되 기능은 살린다.
    """
    now = as_of or datetime.now(timezone.utc)

    # lineage_group별로 가장 신선한 1건만 남긴다 (중복 weight 방지).
    lineage_best: dict[str, WholesaleBaseline] = {}
    for b in baselines:
        prev = lineage_best.get(b.source_lineage_group)
        if prev is None or b.observed_at_utc > prev.observed_at_utc:
            lineage_best[b.source_lineage_group] = b

    if not lineage_best:
        return None

    num = 0.0
    den = 0.0
    all_stale = True
    for b in lineage_best.values():
        st = statuses.get(b.source_code)
        weight = st.confidence_weight if st else 1.0
        if st and st.status == SourceStatus.DEAD:
            continue
        age = (now - b.observed_at_utc).total_seconds() / 86400.0
        d = _decay(age, half_life_days)
        w = weight * d
        if w <= 0:
            continue
        num += b.unit_price_krw * w
        den += w
        # half-life 2배 이내면 fresh로 간주
        if age <= half_life_days * 2:
            all_stale = False

    if den == 0:
        return None
    return (num / den, all_stale)
