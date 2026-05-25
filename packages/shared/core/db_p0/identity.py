"""P0#1 — stable_id + redirect 분리.

db-FINAL §2-2 / §S-3 Q4.

핵심 의도:
    - SHA1 fingerprint는 brand/name/pack 변경 시 자유롭게 진화한다.
    - 외부 노출 키는 영구 불변의 stable_id (ULID-like) 하나뿐.
    - canonical merge/split/fingerprint bump 시에는 redirect 테이블에 from→to 만 박고
      기존 stable_id가 가리키는 모든 외부 링크가 깨지지 않게 한다.
    - 모든 외부 조회는 resolver 의무 통과(체인 깊이 8 한도, cycle 금지).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Optional

from pydantic import BaseModel, Field, ConfigDict


class CanonicalStatus(str, Enum):
    ACTIVE = "active"
    MERGED = "merged"
    SPLIT = "split"
    DEAD = "dead"


class RedirectReason(str, Enum):
    MERGE = "merge"
    SPLIT = "split"
    BRAND_ALIAS_RULE = "brand_alias_rule"
    FINGERPRINT_VERSION_BUMP = "fingerprint_version_bump"
    MANUAL = "manual"


# resolver 안정성을 보장하기 위한 하드 상한 — §S-3 Q4.2
MAX_REDIRECT_DEPTH = 8


def new_stable_id() -> str:
    """ULID-like 영구 불변 식별자. 외부 노출용."""
    # 시간 prefix + 랜덤 — 사람이 봐도 시간 순서가 대충 잡힘.
    ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    rand = secrets.token_hex(8)
    return f"{ts:013x}{rand}"


def compute_fingerprint(
    brand_norm: str,
    name_core: str,
    pack_qty: float,
    pack_unit: str,
    fp_version: int,
) -> str:
    """SHA1(brand|name|pack_qty|pack_unit|fp_version).

    fp_version을 포함하므로 산식 변경 시 자연스럽게 새 fingerprint가 나오고
    기존 stable_id는 redirect로 이관된다. (§2-2 fingerprint 자유 진화)
    """
    payload = f"{brand_norm}|{name_core}|{pack_qty}|{pack_unit}|{fp_version}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


class CanonicalProductIdentity(BaseModel):
    """canonical_product_identity 테이블 모델."""

    model_config = ConfigDict(extra="forbid")

    stable_id: str = Field(min_length=8, description="외부 영구 불변 PK")
    current_fingerprint: str = Field(min_length=40, max_length=40)
    fingerprint_version: int = Field(ge=1, default=1)
    merged_into: Optional[str] = None
    split_from: Optional[str] = None
    status: CanonicalStatus = CanonicalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CanonicalIdRedirect(BaseModel):
    """canonical_id_redirect 테이블 모델."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    reason: RedirectReason
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by_user_id: Optional[str] = None


class RedirectCycleError(ValueError):
    """redirect 추가 시 cycle 발생 — INSERT 거부 (§2-2 resolver 계약)."""


class RedirectDepthExceeded(ValueError):
    """resolve 시 체인이 MAX_REDIRECT_DEPTH 초과 — 데이터 모순 신호."""


class RedirectResolver:
    """in-memory resolver. 실제 운영에서는 DB-backed 구현이 같은 인터페이스를 만족하면 된다.

    의도적으로 단순 dict 기반으로 둔다 — snapshot 빌더와 web-api가 똑같이 가져다 쓰는
    *함수형* 계약을 노출하는 것이 P0의 본체다.
    """

    def __init__(self) -> None:
        # from_id -> to_id
        self._edges: dict[str, str] = {}

    def add(self, redirect: CanonicalIdRedirect) -> None:
        """체인 cycle/depth 검증 후 추가."""
        if redirect.from_id == redirect.to_id:
            raise RedirectCycleError(f"self-loop: {redirect.from_id}")

        # to_id 쪽에서 from_id로 다시 돌아오는 경로가 있으면 cycle.
        # 가상으로 추가한 뒤 resolve를 끝까지 돌려본다.
        prev = self._edges.get(redirect.from_id)
        self._edges[redirect.from_id] = redirect.to_id
        try:
            self.resolve(redirect.from_id)
        except RedirectCycleError:
            if prev is None:
                self._edges.pop(redirect.from_id, None)
            else:
                self._edges[redirect.from_id] = prev
            raise
        except RedirectDepthExceeded:
            # depth 초과는 데이터 누적의 결과이므로 추가 자체는 허용하되 호출자에게 알린다.
            if prev is None:
                self._edges.pop(redirect.from_id, None)
            else:
                self._edges[redirect.from_id] = prev
            raise

    def bulk_load(self, redirects: Iterable[CanonicalIdRedirect]) -> None:
        for r in redirects:
            self.add(r)

    def resolve(self, stable_id: str) -> str:
        """terminal id 반환. cycle/depth 초과 시 명시적 에러."""
        seen: set[str] = set()
        current = stable_id
        for _ in range(MAX_REDIRECT_DEPTH + 1):
            nxt = self._edges.get(current)
            if nxt is None:
                return current
            if nxt in seen or nxt == stable_id:
                raise RedirectCycleError(f"cycle through {stable_id} -> {nxt}")
            seen.add(current)
            current = nxt
        raise RedirectDepthExceeded(
            f"redirect chain from {stable_id} exceeds {MAX_REDIRECT_DEPTH}"
        )

    def __contains__(self, stable_id: str) -> bool:
        return stable_id in self._edges
