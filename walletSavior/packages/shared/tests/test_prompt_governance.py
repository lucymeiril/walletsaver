"""prompt/rulepack 거버넌스 테스트."""

import pytest

from shared.core.contracts.ai_pipeline import AIWorkerRole
from shared.core.contracts.control_plane import PromptPackContract, PromptPackStatus
from shared.core.prompt_governance import PromptGovernanceService


class InMemoryPromptRepo:
    def __init__(self):
        self.packs = {}

    def get(self, pack_id: str, version: str):
        return self.packs.get((pack_id, version))

    def list_versions(self, pack_id: str):
        return [pack for (pid, _), pack in self.packs.items() if pid == pack_id]

    def save(self, pack: PromptPackContract):
        self.packs[(pack.pack_id, pack.version)] = pack


def make_pack(version: str, content: str, status=PromptPackStatus.DRAFT) -> PromptPackContract:
    return PromptPackContract(
        pack_id="classifier-default",
        role=AIWorkerRole.CLASSIFIER,
        version=version,
        status=status,
        content=content,
        created_by="prompt-ai",
    )


def test_prompt_pack_requires_review_before_activation():
    repo = InMemoryPromptRepo()
    service = PromptGovernanceService(repo)
    service.submit_draft(make_pack("1", "rule: classify pork"))

    with pytest.raises(ValueError, match="in-review"):
        service.activate("classifier-default", "1", approved_by="admin")

    service.request_review("classifier-default", "1")
    active = service.activate("classifier-default", "1", approved_by="admin")

    assert active.status == PromptPackStatus.ACTIVE
    assert active.approved_by == "admin"


def test_activating_new_version_deprecates_previous_active():
    repo = InMemoryPromptRepo()
    service = PromptGovernanceService(repo)
    service.submit_draft(make_pack("1", "old"))
    service.request_review("classifier-default", "1")
    service.activate("classifier-default", "1", approved_by="admin")
    service.submit_draft(make_pack("2", "new"))
    service.request_review("classifier-default", "2")

    service.activate("classifier-default", "2", approved_by="admin")

    assert repo.get("classifier-default", "1").status == PromptPackStatus.DEPRECATED
    assert repo.get("classifier-default", "2").status == PromptPackStatus.ACTIVE


def test_diff_reports_added_and_removed_lines():
    repo = InMemoryPromptRepo()
    service = PromptGovernanceService(repo)
    service.submit_draft(make_pack("1", "keep\nremove"))
    service.submit_draft(make_pack("2", "keep\nadd"))

    diff = service.diff("classifier-default", "1", "2")

    assert diff.added_lines == ["add"]
    assert diff.removed_lines == ["remove"]


def test_rollback_marks_current_active_and_restores_target():
    repo = InMemoryPromptRepo()
    service = PromptGovernanceService(repo)
    service.submit_draft(make_pack("1", "old"))
    service.request_review("classifier-default", "1")
    service.activate("classifier-default", "1", approved_by="admin")
    service.submit_draft(make_pack("2", "bad"))
    service.request_review("classifier-default", "2")
    service.activate("classifier-default", "2", approved_by="admin")

    restored = service.rollback("classifier-default", "1", requested_by="admin")

    assert restored.status == PromptPackStatus.ACTIVE
    assert repo.get("classifier-default", "2").status == PromptPackStatus.ROLLED_BACK
