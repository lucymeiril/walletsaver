"""폐기된 ai-admin 자동전송 설정이 실행 경로를 되살리지 못하는지 검증한다."""
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
    registry = PluginRegistry()
    registry.register(
        _StubPlugin(
            name="costco_crawler",
            mart_kind="costco",
            items=[{"name": f"item-{i}", "sale_price": 1000 + i} for i in range(3)],
        )
    )
    return registry


def test_run_records_result_without_external_forwarding(fresh_store, registry_with_plugin):
    run_id = trigger_run("costco_crawler", store=fresh_store, registry=registry_with_plugin)
    run = fresh_store.get_run(run_id)

    assert run["status"] == "success"
    assert run["items_found"] == 3
    assert run["items_saved"] == 3
    assert all("ai_admin" not in line.lower() for line in run["log_lines"])


def test_legacy_ai_admin_env_vars_are_ignored(
    monkeypatch,
    fresh_store,
    registry_with_plugin,
):
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_URL", "http://legacy-ai-admin.invalid")
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_PROVIDER", "legacy-provider")
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_API_KEY", "legacy-key")

    import pipeline.ai_export as raw_handoff
    import urllib.request

    assert not hasattr(raw_handoff, "forward_raw_records_to_ai_admin")
    assert not hasattr(raw_handoff, "fetch_ai_admin_providers")

    def fail_if_network_called(*args, **kwargs):
        raise AssertionError("legacy forwarding must not make a network call")

    monkeypatch.setattr(urllib.request, "urlopen", fail_if_network_called)

    run_id = trigger_run("costco_crawler", store=fresh_store, registry=registry_with_plugin)
    run = fresh_store.get_run(run_id)

    assert run["status"] == "success"
    assert all("ai_admin" not in line.lower() for line in run["log_lines"])
