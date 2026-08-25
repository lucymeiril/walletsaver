"""Control-plane contracts for non-blocking orchestrator dispatch."""
from __future__ import annotations

import asyncio
import threading
import time

from services.crawl_orchestrator import OrchestratorStore, PluginRegistry, RawBatch
from services.orchestrator_dispatch import dispatch_run


class _BlockingPlugin:
    name = "blocking"
    mart_kind = "blocking"
    display_name = "Blocking"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def supports_targeted_search(self, query: str) -> bool:
        return False

    async def crawl(self, targets=None) -> RawBatch:
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        return RawBatch(
            plugin_name=self.name,
            items=[{"name": "fixture"}],
            items_found=1,
            items_saved=1,
        )


def test_dispatch_run_returns_before_crawl_finishes():
    store = OrchestratorStore(":memory:")
    registry = PluginRegistry()
    plugin = _BlockingPlugin()
    registry.register(plugin)

    run_id = dispatch_run("blocking", store=store, registry=registry)

    assert plugin.started.wait(timeout=1.0)
    running = store.get_run(run_id)
    assert running is not None
    assert running["status"] == "running"
    assert running["finished_at"] is None

    plugin.release.set()
    deadline = time.monotonic() + 2.0
    finished = running
    while time.monotonic() < deadline:
        finished = store.get_run(run_id)
        if finished and finished["status"] != "running":
            break
        time.sleep(0.01)

    assert finished is not None
    assert finished["status"] == "success"
    assert finished["items_found"] == 1
    assert finished["items_saved"] == 1
    assert finished["finished_at"] is not None
