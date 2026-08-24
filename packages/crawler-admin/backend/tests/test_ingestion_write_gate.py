from __future__ import annotations

import asyncio
import time

import pytest

from pipeline import ingestion_write_gate as gate


@pytest.mark.asyncio
async def test_ingestion_write_gate_serializes_concurrent_posts(monkeypatch):
    monkeypatch.setenv("INGESTION_WRITE_MIN_INTERVAL_SECONDS", "0")
    gate._loop_states.clear()

    active = 0
    max_active = 0

    async def fake_post(label: str):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return label

    results = await asyncio.gather(
        gate.run_ingestion_post(fake_post, "a"),
        gate.run_ingestion_post(fake_post, "b"),
        gate.run_ingestion_post(fake_post, "c"),
    )

    assert results == ["a", "b", "c"]
    assert max_active == 1


@pytest.mark.asyncio
async def test_ingestion_write_gate_applies_global_spacing(monkeypatch):
    monkeypatch.setenv("INGESTION_WRITE_MIN_INTERVAL_SECONDS", "0.03")
    gate._loop_states.clear()

    started: list[float] = []

    async def fake_post():
        started.append(time.monotonic())
        return "ok"

    await gate.run_ingestion_post(fake_post)
    await gate.run_ingestion_post(fake_post)

    assert started[1] - started[0] >= 0.02


def test_gate_targets_only_pending_ingestion_collection():
    assert gate._is_ingestion_submit_url("http://localhost:8002/api/ingestions") is True
    assert gate._is_ingestion_submit_url("http://localhost:8002/api/ingestions/") is True
    assert gate._is_ingestion_submit_url("http://localhost:8002/api/ingestions?x=1") is True
    assert gate._is_ingestion_submit_url("http://localhost:8002/api/ingestions/42") is False
    assert gate._is_ingestion_submit_url("http://localhost:8002/api/prices/bulk") is False
