"""rd3-pipe-silent-gap-fix — 오케스트레이터 → ai-admin 자동 forward 회귀 테스트.

기존에는 RawBatch.items 가 _persist_run_result 에서 버려졌다. 환경변수가 설정된 경우
forward_raw_records_to_ai_admin 으로 자동 전달되고, silent drop 시 run 이 partial 로
강등되며 failure_reasons 에 ai_admin_forward_failed 항목이 누적되는지 확인한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from services.crawl_orchestrator import (
    OrchestratorStore,
    PluginRegistry,
    RawBatch,
    reset_run_store_for_tests,
    trigger_run,
)


@dataclass
class _StubPlugin:
    name: str
    mart_kind: str
    items: list[dict]

    @property
    def display_name(self) -> str:
        return self.name

    def supports_targeted_search(self, query: str) -> bool:
        return False

    async def crawl(self, targets=None):
        return RawBatch(
            plugin_name=self.name,
            items=list(self.items),
            items_found=len(self.items),
            items_saved=len(self.items),
        )


@pytest.fixture()
def fresh_store(tmp_path):
    store = OrchestratorStore(db_path=str(tmp_path / "orch.db"))
    reset_run_store_for_tests(store)
    yield store


@pytest.fixture()
def registry_with_plugin():
    reg = PluginRegistry()
    plugin = _StubPlugin(
        name="costco_crawler",
        mart_kind="costco",
        items=[{"name": f"item-{i}", "sale_price": 1000 + i} for i in range(3)],
    )
    reg.register(plugin)
    return reg, plugin


def test_no_forward_env_vars_means_no_auto_forward(monkeypatch, fresh_store, registry_with_plugin):
    """환경변수가 없으면 기존처럼 forward 호출 없이 success 만 기록한다."""
    monkeypatch.delenv("WALLETSAVIOR_AI_ADMIN_FORWARD_URL", raising=False)
    monkeypatch.delenv("WALLETSAVIOR_AI_ADMIN_FORWARD_PROVIDER", raising=False)
    reg, _ = registry_with_plugin
    run_id = trigger_run("costco_crawler", store=fresh_store, registry=reg)
    run = fresh_store.get_run(run_id)
    assert run["status"] == "success"
    assert all("ai_admin_forward" not in l for l in run["log_lines"])


def test_auto_forward_records_success_in_log_when_accepted(monkeypatch, fresh_store, registry_with_plugin, tmp_path):
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_URL", "http://ai-admin.test")
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_PROVIDER", "google-dev")
    monkeypatch.setenv("WALLETSAVIOR_CRAWL_FORWARD_WIRE_LOG_PATH", str(tmp_path / "wire.jsonl"))

    # Patch http_post via monkeypatching forward function used by orchestrator.
    import pipeline.ai_export as ai_export

    def fake_post(url, payload, headers, timeout_seconds):
        return 200, {"raw_batch_id": "ai", "records_stored": len(payload["records"])}

    real = ai_export.forward_raw_records_to_ai_admin

    def patched(items, **kwargs):
        kwargs.setdefault("http_post", fake_post)
        return real(items, **kwargs)

    monkeypatch.setattr(ai_export, "forward_raw_records_to_ai_admin", patched)
    # services/crawl_orchestrator.py imports lazily inside the helper, so it picks up the patch.

    reg, _ = registry_with_plugin
    run_id = trigger_run("costco_crawler", store=fresh_store, registry=reg)
    run = fresh_store.get_run(run_id)
    assert run["status"] == "success"
    assert any("ai_admin_forward: sent=3 accepted=3 drop=0" in l for l in run["log_lines"])


def test_auto_forward_silent_drop_marks_run_partial(monkeypatch, fresh_store, registry_with_plugin):
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_URL", "http://ai-admin.test")
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_PROVIDER", "google-dev")

    import pipeline.ai_export as ai_export

    def fake_post(url, payload, headers, timeout_seconds):
        # 모든 행 drop — 코스트코 0건 시나리오 재현.
        return 200, {"raw_batch_id": "ai-drop", "records_stored": 0}

    real = ai_export.forward_raw_records_to_ai_admin

    def patched(items, **kwargs):
        kwargs.setdefault("http_post", fake_post)
        return real(items, **kwargs)

    monkeypatch.setattr(ai_export, "forward_raw_records_to_ai_admin", patched)

    reg, _ = registry_with_plugin
    run_id = trigger_run("costco_crawler", store=fresh_store, registry=reg)
    run = fresh_store.get_run(run_id)
    # silent drop 검출 시 run 은 partial 로 강등되고 ai_admin_forward_failed 사유가 남는다.
    assert run["status"] == "partial"
    assert any("ai_admin_forward_failed" in r for r in run["failure_reasons"])
    assert any("ai_admin_silent_drop" in r for r in run["failure_reasons"])
