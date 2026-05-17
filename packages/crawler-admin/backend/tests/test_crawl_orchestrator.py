"""F1 오케스트레이터 TDD 테스트."""
from __future__ import annotations

import asyncio
import os

import pytest

from services.crawl_orchestrator import (
    OrchestratorStore,
    PluginRegistry,
    RawBatch,
    reset_run_store_for_tests,
    run_due_schedules,
    run_ad_hoc,
    retry_run,
    trigger_run,
)


# ── Mock 플러그인 ────────────────────────────────────────────────

class _MockPlugin:
    def __init__(self, name: str = "mockmart", batch_factory=None, raises=None):
        self._name = name
        self._batch_factory = batch_factory
        self._raises = raises
        self.call_count = 0
        self.last_targets = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def mart_kind(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._name.title()

    def supports_targeted_search(self, query: str) -> bool:
        return True

    async def crawl(self, targets=None) -> RawBatch:
        self.call_count += 1
        self.last_targets = targets
        if self._raises is not None:
            raise self._raises
        if self._batch_factory is not None:
            return self._batch_factory(self.call_count)
        return RawBatch(plugin_name=self._name, items=[{"x": 1}], items_found=1, items_saved=1)


@pytest.fixture
def store() -> OrchestratorStore:
    s = OrchestratorStore(":memory:")
    reset_run_store_for_tests(s)
    return s


@pytest.fixture
def registry() -> PluginRegistry:
    return PluginRegistry()


# ── 1. Plugin registry ─────────────────────────────────────────

def test_plugin_registry_register_and_lookup(registry):
    plugin = _MockPlugin("mockmart")
    registry.register(plugin)
    assert registry.get("mockmart") is plugin
    assert registry.get("missing") is None
    assert plugin in registry.list_all()


# ── 2. Schedule due judgment ───────────────────────────────────

def test_run_due_schedules_picks_up_interval_zero(store, registry):
    plugin = _MockPlugin("mockmart")
    registry.register(plugin)
    store.create_schedule(plugin_name="mockmart", interval_hours=0, enabled=True)

    summaries = run_due_schedules(store=store, registry=registry)

    assert len(summaries) == 1
    assert summaries[0]["status"] in {"success", "partial"}
    assert plugin.call_count == 1
    # 영속화 확인
    runs = store.list_runs()["items"]
    assert len(runs) == 1
    assert runs[0]["status"] == "success"


def test_run_due_schedules_skips_disabled(store, registry):
    plugin = _MockPlugin("mockmart")
    registry.register(plugin)
    store.create_schedule(plugin_name="mockmart", interval_hours=0, enabled=False)
    summaries = run_due_schedules(store=store, registry=registry)
    assert summaries == []
    assert plugin.call_count == 0


# ── 3. Partial failure → partial status ────────────────────────

def test_partial_failure_marks_run_as_partial(store, registry):
    def factory(_n):
        return RawBatch(
            plugin_name="mockmart",
            items=[{"a": 1}, {"a": 2}],
            items_found=3,
            items_saved=2,
            errors=["one_failed"],
            partial=True,
        )

    plugin = _MockPlugin("mockmart", batch_factory=factory)
    registry.register(plugin)

    run_id = trigger_run("mockmart", store=store, registry=registry)
    run = store.get_run(run_id)
    assert run["status"] == "partial"
    assert run["items_saved"] == 2
    assert run["items_found"] == 3
    assert "one_failed" in run["failure_reasons"]


# ── 4. Ad-hoc request → plugin called → result queued ─────────

def test_ad_hoc_request_executes_and_persists(store, registry):
    plugin = _MockPlugin("mockmart")
    registry.register(plugin)

    rid = run_ad_hoc(
        plugin_name="mockmart",
        search_query="우유",
        canonical_id="canon-1",
        requested_by="tester",
        store=store,
        registry=registry,
    )
    req = store.get_request(rid)
    assert req is not None
    assert req["status"] == "done"
    assert req["run_id"] is not None
    assert req["search_query"] == "우유"
    # 플러그인이 검색어를 targets로 받았는지
    assert plugin.last_targets == ["우유"]
    # run_id로 run row가 있어야 함
    run = store.get_run(req["run_id"])
    assert run is not None
    assert run["status"] == "success"


# ── 5. Idempotent retry ────────────────────────────────────────

def test_retry_run_is_idempotent(store, registry):
    # 첫 실행은 실패하도록 — call_count 1번만 실패
    def factory(n):
        if n == 1:
            return RawBatch(plugin_name="mockmart", items=[], items_found=0,
                            items_saved=0, errors=["boom"], partial=False)
        return RawBatch(plugin_name="mockmart", items=[{"x": 1}], items_found=1, items_saved=1)

    plugin = _MockPlugin("mockmart", batch_factory=factory)
    registry.register(plugin)

    initial_run_id = trigger_run("mockmart", store=store, registry=registry)
    initial = store.get_run(initial_run_id)
    assert initial["status"] == "failed"

    new_run_id_1 = retry_run(initial_run_id, store=store, registry=registry)
    new_run_id_2 = retry_run(initial_run_id, store=store, registry=registry)

    # 멱등성: 같은 retry run_id가 반환되어야 한다
    assert new_run_id_1 == new_run_id_2
    # 총 run 개수: original + 1 retry = 2
    runs = store.list_runs()["items"]
    assert len(runs) == 2
    # retry는 성공해야 함
    retried = store.get_run(new_run_id_1)
    assert retried["status"] == "success"
    assert retried["retried_from"] == initial_run_id
