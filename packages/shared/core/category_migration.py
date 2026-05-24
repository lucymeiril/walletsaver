"""카테고리 ID 마이그레이션 실행기.

역할:
    기존 데이터(한글/정수/dot-notation)의 category_id를
    category_tree.yaml 공식 ID로 일괄 변환한다.
    매핑 불가 항목은 escalation 큐로 기록한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .category_id_gate import (
    clear_escalation_queue,
    get_escalation_queue,
    validate_category_id,
)


@dataclass
class MigrationStats:
    """마이그레이션 결과 통계."""
    total: int = 0
    already_valid: int = 0
    migrated: int = 0
    escalated: int = 0
    empty: int = 0

    def as_table(self) -> str:
        lines = [
            "┌─────────────────────────────────┬───────┐",
            "│ 항목                            │   수  │",
            "├─────────────────────────────────┼───────┤",
            f"│ 전체                            │ {self.total:5d} │",
            f"│ 이미 유효한 tree ID              │ {self.already_valid:5d} │",
            f"│ 마이그 성공 (legacy → tree)      │ {self.migrated:5d} │",
            f"│ escalation 큐 이관              │ {self.escalated:5d} │",
            f"│ 빈 ID (skip)                    │ {self.empty:5d} │",
            "└─────────────────────────────────┴───────┘",
        ]
        return "\n".join(lines)


def migrate_category_ids(
    records: Iterable[dict[str, Any]],
    category_key: str = "category_id",
    context: str | None = None,
) -> tuple[list[dict[str, Any]], MigrationStats]:
    """
    레코드 목록의 category_id를 일괄 변환한다.

    Parameters
    ----------
    records      : category_id 필드를 가진 dict 목록
    category_key : category_id를 담은 키 이름 (기본: "category_id")
    context      : escalation 큐에 남길 출처 문자열

    Returns
    -------
    (변환된 레코드 목록, MigrationStats)
    변환된 레코드는 새 dict 복사본이며 원본을 수정하지 않는다.
    """
    stats = MigrationStats()
    output: list[dict[str, Any]] = []

    for record in records:
        stats.total += 1
        old_id = record.get(category_key)
        result = validate_category_id(old_id, context=context)

        new_record = dict(record)

        if not str(old_id or "").strip():
            stats.empty += 1
        elif result.is_valid and not result.was_migrated:
            stats.already_valid += 1
        elif result.is_valid and result.was_migrated:
            stats.migrated += 1
            new_record[category_key] = result.canonical_id
            new_record["_category_migration_original"] = old_id
        else:
            stats.escalated += 1
            new_record["_category_escalated"] = True
            new_record["_category_escalation_reason"] = result.reason

        output.append(new_record)

    return output, stats
