"""
prompt/rulepack 거버넌스 서비스.

AI가 prompt를 직접 바꾸면 장기간 축적한 지식이 망가질 수 있다. 이 서비스는
draft -> review -> active -> rollback 흐름을 코드처럼 엄격하게 관리한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts.control_plane import PromptPackContract, PromptPackStatus


class PromptPackRepository(Protocol):
    def get(self, pack_id: str, version: str) -> PromptPackContract | None:
        """특정 prompt/rulepack 버전을 조회한다."""

    def list_versions(self, pack_id: str) -> list[PromptPackContract]:
        """pack_id의 모든 버전을 반환한다."""

    def save(self, pack: PromptPackContract) -> None:
        """prompt/rulepack을 저장한다."""


@dataclass(frozen=True)
class PromptPackDiff:
    """UI에서 변경 내용을 검토하기 위한 최소 diff 정보."""

    pack_id: str
    from_version: str
    to_version: str
    added_lines: list[str]
    removed_lines: list[str]


class PromptGovernanceService:
    def __init__(self, repository: PromptPackRepository):
        self.repository = repository

    def submit_draft(self, pack: PromptPackContract) -> None:
        if pack.status != PromptPackStatus.DRAFT:
            raise ValueError("New prompt/rulepack submissions must start as draft")
        self._ensure_unique(pack.pack_id, pack.version)
        self.repository.save(pack)

    def request_review(self, pack_id: str, version: str) -> PromptPackContract:
        pack = self._require(pack_id, version)
        if pack.status != PromptPackStatus.DRAFT:
            raise ValueError("Only draft prompt/rulepacks can enter review")
        updated = pack.model_copy(update={"status": PromptPackStatus.IN_REVIEW})
        self.repository.save(updated)
        return updated

    def activate(self, pack_id: str, version: str, approved_by: str) -> PromptPackContract:
        pack = self._require(pack_id, version)
        if pack.status != PromptPackStatus.IN_REVIEW:
            raise ValueError("Only in-review prompt/rulepacks can be activated")

        for existing in self.repository.list_versions(pack_id):
            if existing.status == PromptPackStatus.ACTIVE:
                self.repository.save(existing.model_copy(update={"status": PromptPackStatus.DEPRECATED}))

        updated = pack.model_copy(
            update={
                "status": PromptPackStatus.ACTIVE,
                "approved_by": approved_by,
            },
        )
        self.repository.save(updated)
        return updated

    def rollback(self, pack_id: str, target_version: str, requested_by: str) -> PromptPackContract:
        target = self._require(pack_id, target_version)
        if target.status not in {PromptPackStatus.DEPRECATED, PromptPackStatus.ACTIVE}:
            raise ValueError("Rollback target must be an active or deprecated prompt/rulepack")

        for existing in self.repository.list_versions(pack_id):
            if existing.status == PromptPackStatus.ACTIVE:
                self.repository.save(existing.model_copy(update={"status": PromptPackStatus.ROLLED_BACK}))

        restored = target.model_copy(
            update={
                "status": PromptPackStatus.ACTIVE,
                "approved_by": requested_by,
                "backup_of_version": target.version,
                "changelog": f"Rollback activated from version {target.version}",
            },
        )
        self.repository.save(restored)
        return restored

    def diff(self, pack_id: str, from_version: str, to_version: str) -> PromptPackDiff:
        before = self._require(pack_id, from_version)
        after = self._require(pack_id, to_version)
        before_lines = before.content.splitlines()
        after_lines = after.content.splitlines()
        before_set = set(before_lines)
        after_set = set(after_lines)
        return PromptPackDiff(
            pack_id=pack_id,
            from_version=from_version,
            to_version=to_version,
            added_lines=[line for line in after_lines if line not in before_set],
            removed_lines=[line for line in before_lines if line not in after_set],
        )

    def _require(self, pack_id: str, version: str) -> PromptPackContract:
        pack = self.repository.get(pack_id, version)
        if pack is None:
            raise KeyError(f"Prompt/rulepack not found: {pack_id}@{version}")
        return pack

    def _ensure_unique(self, pack_id: str, version: str) -> None:
        if self.repository.get(pack_id, version) is not None:
            raise ValueError(f"Prompt/rulepack already exists: {pack_id}@{version}")
