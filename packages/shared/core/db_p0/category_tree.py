"""P0#12 — category_set version + remap 모델 + admin override 활성화.

db-FINAL §2-1 / §7-1.
운영 화면(P1)이 아니라 모델/트랜잭션이 P0.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class CategorySetStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class RemapKind(str, Enum):
    ONE_TO_ONE = "one_to_one"
    SPLIT = "split"
    MERGE = "merge"
    UNMAPPED = "unmapped"


class CategorySet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    version_label: str
    status: CategorySetStatus = CategorySetStatus.DRAFT
    activated_at: Optional[datetime] = None


class CategoryRemap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Optional[int] = None
    from_set_version: str
    to_set_version: str
    from_category_id: str
    to_category_id: Optional[str] = None
    mapping_kind: RemapKind
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    decided_by: str = "auto"   # auto|manual|ai_suggested


def activate_category_set(
    sets: list[CategorySet],
    target_id: int,
    remaps: list[CategoryRemap],
    *,
    admin_override: bool = False,
    now: Optional[datetime] = None,
) -> tuple[list[CategorySet], list[CategoryRemap]]:
    """단일 트랜잭션 활성 swap. unmapped 존재 시 admin_override=False면 거부.

    admin_override=True면 미분류 처리 큐 자동 생성 흐름으로 진행(§2-1).
    반환 첫번째: 새 set 목록(상태 갱신 후), 두번째: unmapped 항목들(미분류 큐 시드).
    """
    now = now or datetime.now(timezone.utc)
    target = next((s for s in sets if s.id == target_id), None)
    if target is None:
        raise ValueError(f"target set not found: {target_id}")
    if target.status == CategorySetStatus.ACTIVE:
        raise ValueError("target already active")

    unmapped = [r for r in remaps if r.mapping_kind == RemapKind.UNMAPPED]
    if unmapped and not admin_override:
        raise ValueError(
            f"{len(unmapped)} unmapped categories — admin_override required "
            "(미분류 처리 큐 자동 생성으로 진행됨)"
        )

    new_sets: list[CategorySet] = []
    for s in sets:
        if s.id == target_id:
            new_sets.append(s.model_copy(update={
                "status": CategorySetStatus.ACTIVE,
                "activated_at": now,
            }))
        elif s.status == CategorySetStatus.ACTIVE:
            new_sets.append(s.model_copy(update={"status": CategorySetStatus.ARCHIVED}))
        else:
            new_sets.append(s)

    return new_sets, unmapped
