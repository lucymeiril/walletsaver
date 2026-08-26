"""카테고리 ID 검증 게이트 — category_tree.yaml 기반.

역할:
    카테고리 마이그레이션/검증 진입점에서 category_id를 검증한다.
    - category_tree.yaml에 있는 ID → 통과 (is_valid=True)
    - legacy_id_migration.yaml에 있는 ID → 마이그 후 통과 (was_migrated=True)
    - 그 외 → escalation 큐 전달 (is_valid=False, escalated=True)

절대 규칙:
    - 새 카테고리가 필요하면 escalation 큐로 → 관리자 승인 흐름 (immutable 강제 X)
    - 거부 시 동적 차단(예외 발생)이 아닌 큐 전달 + 플래그 반환
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .category_mapper import load_tree

_MIGRATION_FILE = Path(__file__).parent.parent / "data" / "category_mappings" / "legacy_id_migration.yaml"

# ── reason codes ────────────────────────────────────────────────
REASON_EMPTY_INPUT = "EMPTY_CATEGORY_ID"
REASON_MIGRATED = "MIGRATED_LEGACY_ID"
REASON_ESCALATED = "ESCALATED_UNKNOWN_CATEGORY_ID"


@dataclass
class CategoryGateResult:
    """validate_category_id()의 결과 DTO."""
    is_valid: bool
    canonical_id: Optional[str]
    was_migrated: bool
    escalated: bool
    original_id: str
    reason: Optional[str] = None


# ── escalation queue (in-process; consumer가 flush) ─────────────
_escalation_queue: list[dict] = []


def get_escalation_queue() -> list[dict]:
    """현재 escalation 큐의 사본을 반환한다."""
    return list(_escalation_queue)


def clear_escalation_queue() -> None:
    """큐 초기화 (테스트용 / flush 후 호출)."""
    _escalation_queue.clear()


# ── migration map 로딩 ──────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_migration_map() -> dict[str, str]:
    """legacy_id_migration.yaml 로드: {old_id → tree_node_id}."""
    if not _MIGRATION_FILE.exists():
        return {}
    with open(_MIGRATION_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("mappings", {}) or {}


def reload_migration_map() -> None:
    """migration map 캐시 무효화 (파일 갱신 후 호출)."""
    _load_migration_map.cache_clear()


# ── 핵심 API ────────────────────────────────────────────────────

def validate_category_id(
    category_id: str | None,
    context: str | None = None,
) -> CategoryGateResult:
    """
    category_id를 tree 기준으로 검증한다.

    1. category_tree.yaml 직접 매칭 → is_valid=True
    2. legacy_id_migration.yaml 매핑 → is_valid=True, was_migrated=True
    3. 그 외 → escalation 큐 등록, is_valid=False, escalated=True

    Parameters
    ----------
    category_id : 검증할 ID 문자열
    context     : escalation 큐에 기록될 출처 정보 (선택)

    Returns
    -------
    CategoryGateResult
    """
    raw = str(category_id or "").strip()
    if not raw:
        return CategoryGateResult(
            is_valid=False,
            canonical_id=None,
            was_migrated=False,
            escalated=False,
            original_id=raw,
            reason=REASON_EMPTY_INPUT,
        )

    tree = load_tree()

    # 1) 직접 매칭
    if tree.get(raw) is not None:
        return CategoryGateResult(
            is_valid=True,
            canonical_id=raw,
            was_migrated=False,
            escalated=False,
            original_id=raw,
        )

    # 2) migration map
    migration = _load_migration_map()
    migrated_id = migration.get(raw)
    if migrated_id and tree.get(migrated_id) is not None:
        return CategoryGateResult(
            is_valid=True,
            canonical_id=migrated_id,
            was_migrated=True,
            escalated=False,
            original_id=raw,
            reason=REASON_MIGRATED,
        )

    # 3) 미등록 → escalation
    _escalation_queue.append({"original_id": raw, "context": context})
    return CategoryGateResult(
        is_valid=False,
        canonical_id=None,
        was_migrated=False,
        escalated=True,
        original_id=raw,
        reason=REASON_ESCALATED,
    )


def migrate_category_id(category_id: str | None) -> tuple[str | None, bool]:
    """
    ID를 tree ID로 변환한다.

    Returns
    -------
    (canonical_id_or_None, was_migrated)
    """
    result = validate_category_id(category_id)
    if result.is_valid:
        return result.canonical_id, result.was_migrated
    return None, False


def is_valid_tree_category(category_id: str | None) -> bool:
    """category_tree.yaml에 존재하거나 migration 가능한 ID이면 True."""
    return validate_category_id(category_id).is_valid


def canonical_tree_id(category_id: str | None) -> str | None:
    """검증/변환 후 canonical tree ID를 반환한다. 미등록이면 None."""
    return validate_category_id(category_id).canonical_id
