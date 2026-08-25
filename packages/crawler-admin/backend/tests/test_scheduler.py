"""Current schedule API contracts backed by OrchestratorStore."""
from __future__ import annotations

import pytest

import api.routes.schedules as routes
from services.crawl_orchestrator import OrchestratorStore


@pytest.fixture
def store(monkeypatch):
    current = OrchestratorStore(":memory:")
    monkeypatch.setattr(routes.orch, "get_run_store", lambda: current)
    return current


@pytest.mark.asyncio
async def test_schedule_crud_uses_orchestrator_store(store):
    created = await routes.create_schedule(
        routes.ScheduleCreate(crawler_name="emart", cron="0 7 * * *")
    )
    schedule_id = created["id"]

    assert created["crawlerId"] == "emart"
    assert created["crawlerName"] == "이마트"
    assert created["cron"] == "0 7 * * *"
    assert store.get_schedule(schedule_id)["plugin_name"] == "emart"

    listed = await routes.list_schedules()
    assert [row["id"] for row in listed["schedules"]] == [schedule_id]

    updated = await routes.update_schedule(
        schedule_id,
        routes.ScheduleUpdate(cron="0 9 * * *"),
    )
    assert updated["cron"] == "0 9 * * *"

    toggled = await routes.toggle_schedule(
        schedule_id,
        routes.ScheduleToggle(enabled=False),
    )
    assert toggled["enabled"] is False
    assert store.get_schedule(schedule_id)["enabled"] is False

    deleted = await routes.delete_schedule(schedule_id)
    assert deleted["status"] == "removed"
    assert store.get_schedule(schedule_id) is None


@pytest.mark.asyncio
async def test_legacy_crawler_name_still_resolves_to_new_schedule_id(store):
    schedule_id = store.create_schedule(
        plugin_name="homeplus",
        cron_expr="0 7 * * 1",
        enabled=True,
    )

    updated = await routes.update_schedule(
        "homeplus",
        routes.ScheduleUpdate(cron="0 8 * * 1"),
    )

    assert updated["id"] == schedule_id
    assert store.get_schedule(schedule_id)["cron_expr"] == "0 8 * * 1"


@pytest.mark.asyncio
async def test_schedule_tick_delegates_to_current_orchestrator(monkeypatch):
    monkeypatch.setattr(routes, "_ensure_current_plugins_registered", lambda: None)
    monkeypatch.setattr(
        routes.orch,
        "run_due_schedules",
        lambda: [{"status": "success", "run_id": "run_test"}],
    )

    result = await routes._run_due_once()

    assert result == [{"status": "success", "run_id": "run_test"}]
