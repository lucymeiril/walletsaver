"""폐기된 ai-admin 자동전송 환경변수가 실행 경로를 되살리지 못하는지 검증한다."""
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
    reg.register(
        _StubPlugin(
            name="costco_crawler",
            mart_kind="costco",
            items=[{"name": f"item-{i}", "sale_price": 1000 + i} for i in range(3)],
        )
    )
    return reg


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
    """과거 환경변수가 남아 있어도 네트워크 전송 코드는 호출되지 않아야 한다."""
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_URL", "http://legacy-ai-admin.invalid")
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_PROVIDER", "legacy-provider")
    monkeypatch.setenv("WALLETSAVIOR_AI_ADMIN_FORWARD_API_KEY", "legacy-key")

    import pipeline.ai_export as ai_export
    import urllib.request

    def fail_if_forwarded(*args, **kwargs):
        raise AssertionError("legacy ai-admin forwarding must not be called")

    monkeypatch.setattr(ai_export, "forward_raw_records_to_ai_admin", fail_if_forwarded)
    monkeypatch.setattr(urllib.request, "urlopen", fail_if_forwarded)

    run_id = trigger_run("costco_crawler", store=fresh_store, registry=registry_with_plugin)
    run = fresh_store.get_run(run_id)

    assert run["status"] == "success"
    assert all("ai_admin" not in line.lower() for line in run["log_lines"])
