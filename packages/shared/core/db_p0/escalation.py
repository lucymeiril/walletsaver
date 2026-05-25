"""P0#4 — escalation claim/version으로 동시 관리자 처리 충돌 방지.

db-FINAL §2-8. resolve API는
    WHERE id=? AND resolved_at IS NULL AND version=?
1행 갱신 패턴. 실패 시 "이미 다른 관리자(@X)가 처리함" UI 분기.
claim 기본 +15분, 만료 cron 자동 해제.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


CLAIM_TTL_MINUTES = 15


class ProductReviewQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    payload_json: dict
    version: int = Field(default=0, ge=0)
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    claim_expires_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    resolver_user_id: Optional[str] = None
    resolution_json: Optional[dict] = None


class EscalationVersionConflict(RuntimeError):
    """다른 관리자가 먼저 resolve 했다는 신호 — UI는 누가 처리했는지 표시."""


class EscalationClaimExpired(RuntimeError):
    """claim TTL 만료 후 resolve 시도. 다시 claim 받으라는 신호."""


def claim_item(
    item: ProductReviewQueueItem,
    user_id: str,
    *,
    now: Optional[datetime] = None,
) -> ProductReviewQueueItem:
    """claim 발급. 다른 사람이 활성 claim 중이면 거부.

    같은 유저가 재발급하면 TTL만 갱신한다(refresh 패턴).
    """
    now = now or datetime.now(timezone.utc)
    if item.resolved_at is not None:
        raise EscalationVersionConflict(f"already resolved by {item.resolver_user_id}")

    active = (
        item.claimed_by is not None
        and item.claim_expires_at is not None
        and item.claim_expires_at > now
        and item.claimed_by != user_id
    )
    if active:
        raise EscalationVersionConflict(f"claimed by {item.claimed_by}")

    return item.model_copy(update={
        "claimed_by": user_id,
        "claimed_at": now,
        "claim_expires_at": now + timedelta(minutes=CLAIM_TTL_MINUTES),
        "version": item.version + 1,
    })


def resolve_item(
    item: ProductReviewQueueItem,
    user_id: str,
    expected_version: int,
    resolution: dict,
    *,
    now: Optional[datetime] = None,
) -> ProductReviewQueueItem:
    """optimistic version 비교 + claim TTL 확인 + 1트랜잭션 resolve."""
    now = now or datetime.now(timezone.utc)
    if item.resolved_at is not None:
        raise EscalationVersionConflict(f"already resolved by {item.resolver_user_id}")
    if item.version != expected_version:
        raise EscalationVersionConflict(
            f"version mismatch: stored={item.version} expected={expected_version}"
        )
    if item.claimed_by != user_id:
        raise EscalationVersionConflict(f"not claimed by {user_id} (claimed_by={item.claimed_by})")
    if item.claim_expires_at is None or item.claim_expires_at <= now:
        raise EscalationClaimExpired(f"claim expired at {item.claim_expires_at}")

    return item.model_copy(update={
        "resolved_at": now,
        "resolver_user_id": user_id,
        "resolution_json": resolution,
        "version": item.version + 1,
    })
