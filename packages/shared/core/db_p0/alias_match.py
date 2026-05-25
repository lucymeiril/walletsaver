"""P0#3, #11, #17, #18 — alias availability + match_candidate_log + community signal.

db-FINAL §2-6 / §6-5 / §6-6.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class AvailabilityStatus(str, Enum):
    ACTIVE = "active"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"
    UNKNOWN = "unknown"


class BrandAliasStatus(str, Enum):
    SUGGESTED = "suggested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ROLLBACK = "rollback"


class MartSkuAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    mart: str
    mart_item_id: str   # UNIQUE(mart, mart_item_id) DB 제약 별도
    stable_id: str
    availability_status: AvailabilityStatus = AvailabilityStatus.ACTIVE
    last_success_seen_at: Optional[datetime] = None
    last_missing_seen_at: Optional[datetime] = None
    consecutive_miss_count: int = 0


# §2-6 룰: 7일 miss → out_of_stock, 30일 → discontinued 후보 escalation.
OOS_DAYS = 7
DISCONTINUED_DAYS = 30


def bump_alias_observation(
    alias: MartSkuAlias,
    *,
    seen: bool,
    now: Optional[datetime] = None,
) -> MartSkuAlias:
    """crawler ingest 후 호출. availability 라벨 전이 규칙을 한곳에서 강제."""
    now = now or datetime.now(timezone.utc)
    if seen:
        return alias.model_copy(update={
            "availability_status": AvailabilityStatus.ACTIVE,
            "last_success_seen_at": now,
            "consecutive_miss_count": 0,
        })

    miss = alias.consecutive_miss_count + 1
    last_seen = alias.last_success_seen_at
    days_since = (now - last_seen).total_seconds() / 86400.0 if last_seen else miss * 1.0

    if days_since >= DISCONTINUED_DAYS:
        new_status = AvailabilityStatus.DISCONTINUED
    elif days_since >= OOS_DAYS:
        new_status = AvailabilityStatus.OUT_OF_STOCK
    else:
        new_status = alias.availability_status

    return alias.model_copy(update={
        "availability_status": new_status,
        "last_missing_seen_at": now,
        "consecutive_miss_count": miss,
    })


class BrandAlias(BaseModel):
    """suggested/approved/rejected/rollback — AI 자동 학습은 suggested까지만."""

    model_config = ConfigDict(extra="forbid")

    alias: str
    canonical_brand: str
    status: BrandAliasStatus = BrandAliasStatus.SUGGESTED
    evidence_json: dict = Field(default_factory=dict)
    affected_count_at_approval: Optional[int] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    applies_from_fingerprint_version: Optional[int] = None


class MatchCandidateLog(BaseModel):
    """request_id idempotent + bot_like 표식 + hot 90일 후 archive (§6-6)."""

    model_config = ConfigDict(extra="forbid")

    request_id: str
    post_draft_id: Optional[str] = None
    post_id: Optional[str] = None
    caller_id: str
    bot_like: bool = False
    query_payload_json: dict
    candidates_json: list[dict]
    selected_stable_id: Optional[str] = None
    rejected_reasons_json: Optional[list[str]] = None
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    archived: bool = False


class CommunityPriceSignal(BaseModel):
    """verdict_version delta pull (§S-3 Q4.5)."""

    model_config = ConfigDict(extra="forbid")

    stable_id: str
    post_id: str
    verdict_hot_count: int = 0
    verdict_not_hot_count: int = 0
    verdict_neutral_count: int = 0
    verdict_version: int = 0
    last_pulled_at: Optional[datetime] = None
    dispute_flag: bool = False


def pull_community_delta(
    cached: dict[tuple[str, str], CommunityPriceSignal],
    incoming: list[CommunityPriceSignal],
) -> list[CommunityPriceSignal]:
    """incoming 중 verdict_version이 cached보다 큰 것만 반환.

    cached[(stable_id, post_id)] -> 마지막으로 본 signal.
    web-api의 community pull endpoint에서 가져온 결과를 db-admin이 흡수할 때 사용.
    canonical 재매칭(stable_id 변경)이 발생하면 web-api가 보내는 incoming의 stable_id가
    바뀌므로, 호출자는 redirect resolver로 old→new 이관 이벤트를 함께 처리해야 한다.
    """
    out: list[CommunityPriceSignal] = []
    for sig in incoming:
        key = (sig.stable_id, sig.post_id)
        prev = cached.get(key)
        if prev is None or sig.verdict_version > prev.verdict_version:
            out.append(sig)
    return out
