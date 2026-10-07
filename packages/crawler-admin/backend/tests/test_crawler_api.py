"""Focused API regressions for the current crawler-admin runtime."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes import crawlers as crawler_routes
from services import crawl_orchestrator as orch
from audit import AuditEventType
from pipeline.pipeline import PipelineResult


@pytest.mark.parametrize("configured,explicit,expected", [
    (None, None, "default"),
    ("  /separated/demo/orchestrator.db  ", None, "/separated/demo/orchestrator.db"),
    ("  ", None, "default"),
    ("/separated/demo/orchestrator.db", "/explicit/orchestrator.db", "/explicit/orchestrator.db"),
])
def test_orchestrator_store_external_path_selector(monkeypatch, configured, explicit, expected):
    if configured is None:
        monkeypatch.delenv("WALLETSAVIOR_ORCHESTRATOR_DB", raising=False)
    else:
        monkeypatch.setenv("WALLETSAVIOR_ORCHESTRATOR_DB", configured)
    # Selecting the runtime location must not require creating a real management DB.
    monkeypatch.setattr(orch.OrchestratorStore, "_init_schema", lambda self: None)
    store = orch.OrchestratorStore(explicit)
    assert store.db_path == (orch._DEFAULT_DB_PATH if expected == "default" else expected)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "false")
    monkeypatch.setenv("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", "1")
    orch.reset_run_store_for_tests(orch.OrchestratorStore(":memory:"))
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_health_reports_current_service(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "crawler-admin"
    assert data["status"] in {"ok", "degraded"}


def test_list_crawlers_exposes_four_current_marts(client):
    response = client.get("/api/crawlers")
    assert response.status_code == 200
    data = response.json()
    rows = data.get("crawlers", [])
    names = {row.get("name") for row in rows}
    assert {"emart", "homeplus", "lottemart", "costco"}.issubset(names)


def test_unknown_crawler_routes_return_not_found(client):
    assert client.get("/api/crawlers/nonexistent/status").status_code == 404
    assert client.post("/api/crawlers/nonexistent/run").status_code == 404


def test_emart_category_endpoints_only_run_allowlisted_ids(client, monkeypatch):
    async def fake_run_and_store(crawler_id, pipeline, *, crawl_method="crawl"):
        crawler = crawler_routes._require_crawler(crawler_id)
        crawler._selected_category_request = None
        await crawler_routes.release_crawler_slot(crawler_id)

    monkeypatch.setattr(crawler_routes, "_run_and_store", fake_run_and_store)

    listed = client.get("/api/crawlers/emart/categories")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["crawler_id"] == "emart"
    assert payload["count"] == 29
    assert any(row["category_hint"] == "우유/유제품" for row in payload["categories"])

    rejected = client.post(
        "/api/crawlers/emart/run-category",
        json={"category_id": "not-allowlisted"},
    )
    assert rejected.status_code == 404

    selected = payload["categories"][0]
    started = client.post(
        "/api/crawlers/emart/run-category",
        json={"category_id": selected["category_id"]},
    )
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["category"]["category_id"] == selected["category_id"]


def test_category_request_bodies_reach_route_validation(client):
    lotte = client.post(
        "/api/crawlers/lottemart/run-category",
        json={"query": "not-allowlisted"},
    )

    assert lotte.status_code == 404
    assert "롯데마트 카테고리" in lotte.json()["detail"]
    schema = client.app.openapi()
    assert "/api/crawlers/emart/run-category" in schema["paths"]
    assert "/api/crawlers/lottemart/run-category" in schema["paths"]


def test_orchestrator_rejects_unknown_schedule_plugin(client):
    response = client.post(
        "/api/v1/schedules",
        json={"plugin_name": "nonexistent", "cron_expr": "0 8 * * *"},
    )
    assert response.status_code == 404


def test_orchestrator_rejects_invalid_cron(client):
    response = client.post(
        "/api/v1/schedules",
        json={"plugin_name": "emart", "cron_expr": "not a cron"},
    )
    assert response.status_code == 400


def test_orchestrator_schedule_crud_uses_current_api(client):
    created = client.post(
        "/api/v1/schedules",
        json={"plugin_name": "emart", "cron_expr": "0 8 * * *"},
    )
    assert created.status_code == 201
    schedule = created.json()
    schedule_id = schedule["id"]
    assert schedule["plugin_name"] == "emart"
    assert schedule["cron_timezone"] == "UTC"
    assert schedule["cron_dialect"] == "unix"
    assert schedule["stored_timezone_provenance"] == "not_recorded"

    listed = client.get("/api/v1/schedules")
    assert listed.status_code == 200
    assert any(row["id"] == schedule_id for row in listed.json()["schedules"])

    updated = client.patch(
        f"/api/v1/schedules/{schedule_id}",
        json={"cron_expr": "0 9 * * *", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["cron_expr"] == "0 9 * * *"
    assert updated.json()["enabled"] is False

    deleted = client.delete(f"/api/v1/schedules/{schedule_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True


@pytest.mark.parametrize("cron,now,due", [
    ("0 7 * * 1", "2026-10-05T07:00:00+00:00", True),  # Unix Monday
    ("0 7 * * 1", "2026-10-06T08:00:00+00:00", False),
    ("0 7 * * 0", "2026-10-04T07:00:00+00:00", True),
    ("0 7 * * 7", "2026-10-04T07:00:00+00:00", True),
    ("0 7 * * 1-5", "2026-10-10T08:00:00+00:00", False),
    ("0 7 6 * 1", "2026-10-05T07:00:00+00:00", True),  # Unix date OR weekday
])
def test_schedule_unix_weekday_due_uses_explicit_utc(cron, now, due):
    from datetime import datetime
    clock = datetime.fromisoformat(now)
    schedule = {"enabled": True, "cron_expr": cron}
    assert orch._schedule_is_due(schedule, clock, None) is due
    assert orch._schedule_is_due(schedule, clock.replace(tzinfo=None), None) is due


def test_schedule_legacy_naive_clock_and_exact_fire_are_not_repeated():
    from datetime import datetime, timezone
    last = orch._parse_iso("2026-10-05T07:00:00")
    assert last == datetime(2026, 10, 5, 7, tzinfo=timezone.utc)
    weekly = {"enabled": True, "cron_expr": "0 7 * * 1"}
    assert not orch._schedule_is_due(weekly, datetime(2026, 10, 5, 7, 0, 30), last)
    assert orch._schedule_is_due(weekly, datetime(2026, 10, 12, 7), last)
    interval = {"enabled": True, "interval_hours": 168}
    assert not orch._schedule_is_due(interval, datetime(2026, 10, 12, 6, 59), last)
    assert orch._schedule_is_due(interval, datetime(2026, 10, 12, 7), last)


@pytest.mark.parametrize("owner_state,recovered", [
    ("dead", True), ("pid_reused", True), ("live", False),
    ("foreign", False), ("unmarked", False), ("access_denied", False),
])
def test_schedule_restart_recovers_only_confirmed_dead_owner(tmp_path, monkeypatch, owner_state, recovered):
    import json
    import socket
    import psutil
    from datetime import datetime, timezone
    from services import orchestrator_dispatch as dispatch

    owner = {"hostname": socket.gethostname(), "pid": 123456, "process_started_at": 100.0}
    if owner_state == "foreign":
        owner["hostname"] = "different-host"
    marker = [] if owner_state == "unmarked" else [orch._OWNER_PREFIX + json.dumps(owner)]
    monkeypatch.setattr(orch, "_owner_log", lambda: marker)
    path = str(tmp_path / "orchestrator.sqlite")
    first = orch.OrchestratorStore(path)
    sid = first.create_schedule("lottemart", interval_hours=168)
    run_id = first.create_run("lottemart", schedule_id=sid)
    first.update_run_status(run_id, "running", items_found=2, items_saved=1, finished=False)
    reopened = orch.OrchestratorStore(path)

    def process(pid):
        assert pid == 123456
        if owner_state == "dead":
            raise psutil.NoSuchProcess(pid)
        if owner_state == "access_denied":
            raise psutil.AccessDenied(pid)
        return MagicMock(create_time=lambda: 101.0 if owner_state == "pid_reused" else 100.0,
                         status=lambda: psutil.STATUS_RUNNING)
    monkeypatch.setattr(psutil, "Process", process)
    summary = reopened.recover_abandoned_runs()
    assert summary == {"recovered": int(recovered), "held_running": int(not recovered)}
    row = reopened.get_run(run_id)
    assert row["status"] == ("failed" if recovered else "running")
    assert (row["items_found"], row["items_saved"]) == (2, 1)
    if recovered:
        assert "runtime_owner_exited_before_completion" in row["failure_reasons"]
    assert reopened.get_schedule(sid)["interval_hours"] == 168
    assert reopened.recover_abandoned_runs()["recovered"] == 0
    submit = MagicMock()
    monkeypatch.setattr(dispatch, "_submit", submit)
    if not recovered:
        # Even an overdue job with unknown/active owner is not dispatched again.
        registry = orch.PluginRegistry()
        from types import SimpleNamespace
        registry.register(SimpleNamespace(name="lottemart"))
        dispatch.dispatch_due_schedules(datetime(2099, 1, 1, tzinfo=timezone.utc), store=reopened, registry=registry)
        submit.assert_not_called()


def test_schedule_claim_rechecks_due_and_running_atomically(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    path = str(tmp_path / "orchestrator.sqlite")
    stores = [orch.OrchestratorStore(path), orch.OrchestratorStore(path)]
    sid = stores[0].create_schedule("lottemart", cron_expr="0 7 * * 1")
    now = datetime(2026, 10, 5, 7, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda store: store.claim_due_schedule(sid, "lottemart", now), stores))
    claimed = [value for value in ids if value]
    assert len(claimed) == 1
    row = stores[0].get_run(claimed[0])
    assert orch._recorded_owner(row["log_lines"])["pid"] > 0
    assert row["started_at"] == now.isoformat()
    stores[0].update_run_status(claimed[0], "success", items_found=1, items_saved=1)
    assert stores[1].claim_due_schedule(sid, "lottemart", now) is None
    assert stores[1].claim_due_schedule(sid, "lottemart", datetime(2026, 10, 12, 7, tzinfo=timezone.utc))


def test_schedule_startup_recovery_precedes_loop_without_crawling(monkeypatch):
    from api.routes import orchestrator as routes
    store = MagicMock()
    store.recover_abandoned_runs.return_value = {"recovered": 1, "held_running": 1}
    monkeypatch.setattr(orch, "get_run_store", lambda: store)
    monkeypatch.setattr(routes, "_schedule_task", None)
    monkeypatch.delenv("WALLETSAVIOR_DISABLE_SCHEDULE_LOOP", raising=False)
    async def wait_only():
        await asyncio.Event().wait()
    monkeypatch.setattr(routes, "_schedule_loop", wait_only)
    async def exercise():
        await routes._start_schedule_loop()
        assert routes.schedule_loop_running()
        assert routes.schedule_loop_state()["startup_recovery"] == {"recovered": 1, "held_running": 1}
        await routes._stop_schedule_loop()
    asyncio.run(exercise())
    store.recover_abandoned_runs.assert_called_once()


def test_schedule_health_does_not_call_failing_ticks_healthy(client, monkeypatch):
    from api.routes import orchestrator as routes
    orch.get_run_store().create_schedule("lottemart", cron_expr="0 7 * * 1")
    monkeypatch.setattr(routes, "_schedule_last_error", "TypeError")
    monkeypatch.setattr(routes, "schedule_loop_running", lambda: True)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["reason"] == "scheduler_tick_failed"


def test_logs_endpoint_returns_list_contract(client):
    response = client.get("/api/logs?limit=10&status=success")
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)


def test_logs_endpoint_reads_canonical_orchestrator_runs(client):
    store = orch.get_run_store()
    run_id = store.create_run("emart", triggered_by="manual")
    store.update_run_status(
        run_id,
        status="success",
        items_found=4,
        items_saved=3,
    )

    response = client.get("/api/logs?job_id=emart&status=success")

    assert response.status_code == 200
    [entry] = response.json()["logs"]
    assert entry["job_id"] == "emart"
    assert entry["run_id"] == run_id
    assert entry["result"]["items_found"] == 4
    assert entry["result"]["items_saved"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,saved", [("failed", 0), ("partial_failure", 1), ("success", 2)])
async def test_pipeline_result_audit_retains_failure_outcome_without_runtime_writes(monkeypatch, status, saved):
    result = PipelineResult(crawler_name="synthetic", status=status, items_found=2, items_valid=2, items_saved=saved)
    pipeline = MagicMock(run_crawler=AsyncMock(return_value=result))
    audit = MagicMock()
    history = MagicMock()
    release = AsyncMock()
    monkeypatch.setattr(crawler_routes, "_crawl_results", {})
    monkeypatch.setattr(crawler_routes, "get_semaphore", lambda: asyncio.Semaphore(1))
    monkeypatch.setattr(crawler_routes, "release_crawler_slot", release)
    monkeypatch.setattr(crawler_routes, "_append_run_history", history)
    monkeypatch.setattr(crawler_routes, "audit_log", audit)
    await crawler_routes._run_and_store("synthetic", pipeline)
    assert crawler_routes._crawl_results["synthetic"]["status"] == status
    assert crawler_routes._crawl_results["synthetic"]["items_saved"] == saved
    assert audit.call_args.args[0] == (AuditEventType.CRAWL_COMPLETED if status == "success" else AuditEventType.CRAWL_FAILED)
    assert audit.call_args.kwargs["result"] == ("success" if status == "success" else "error")
    assert audit.call_args.kwargs["detail"]["status"] == status
    history.assert_called_once_with("synthetic", status, result.duration)
    release.assert_awaited_once_with("synthetic")


@pytest.mark.parametrize('source_url', [None, 'https://lottemartzetta.com/products/OS8801114119426/details'])
def test_bounded_lotte_run_uses_existing_pipeline_without_live_transport(monkeypatch, source_url):
    from starlette.requests import Request
    captured = []
    worker = AsyncMock()
    monkeypatch.setattr(crawler_routes, '_require_crawler', lambda name: MagicMock())
    monkeypatch.setattr(crawler_routes, '_get_pipeline', lambda: 'existing_pipeline')
    monkeypatch.setattr(crawler_routes, 'acquire_crawler_slot', AsyncMock(return_value=True))
    monkeypatch.setattr(crawler_routes, 'audit_log', MagicMock())
    monkeypatch.setattr(crawler_routes, '_crawl_results', {})
    monkeypatch.setattr(crawler_routes, '_run_and_store', worker)
    monkeypatch.setattr(crawler_routes.asyncio, 'create_task', lambda coroutine: captured.append(coroutine))
    async def run():
        body = crawler_routes.CrawlerRunRequest(source_url=source_url) if source_url else None
        response = await crawler_routes.run_crawler.__wrapped__('lottemart', Request({'type': 'http'}), body)
        await captured.pop()
        return response
    response = asyncio.run(run())
    expected = {} if source_url is None else {'crawl_method': 'crawl_incremental', 'crawl_kwargs': {'source_url': source_url}, 'max_attempts': 1}
    worker.assert_awaited_once_with('lottemart', 'existing_pipeline', **expected)
    assert response.get('source_url') == source_url
    assert crawler_routes._crawl_results['lottemart'].get('source_url') == source_url


@pytest.mark.parametrize('url', [
    'https://example.test/products/OS8801114119426/details',
    'http://lottemartzetta.com/products/OS8801114119426/details',
    'https://user@lottemartzetta.com/products/OS8801114119426/details',
    'https://lottemartzetta.com/products/OS8801114119426/details?token=x',
    'https://lottemartzetta.com/products/OS8801114119426/details#x',
    'https://lottemartzetta.com/products/OS123/details',
])
def test_bounded_lotte_run_rejects_noncanonical_source_before_transport(url):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        crawler_routes.CrawlerRunRequest(source_url=url)


def test_bounded_source_rejects_other_crawler_before_slot(monkeypatch):
    from starlette.requests import Request
    from fastapi import HTTPException
    acquire = AsyncMock()
    monkeypatch.setattr(crawler_routes, 'acquire_crawler_slot', acquire)
    with pytest.raises(HTTPException) as error:
        asyncio.run(crawler_routes.run_crawler.__wrapped__('homeplus', Request({'type': 'http'}),
            crawler_routes.CrawlerRunRequest(source_url='https://lottemartzetta.com/products/OS8801114119426/details')))
    assert error.value.status_code == 400
    acquire.assert_not_awaited()


def test_bounded_run_retains_selected_url_in_existing_job_history(monkeypatch):
    source_url = 'https://lottemartzetta.com/products/OS8801114119426/details'
    result = PipelineResult(crawler_name='lottemart', status='failed', items_found=0, items_valid=0, items_saved=0)
    pipeline = MagicMock(run_crawler=AsyncMock(return_value=result))
    history = MagicMock()
    monkeypatch.setattr(crawler_routes, '_crawl_results', {})
    monkeypatch.setattr(crawler_routes, 'get_semaphore', lambda: asyncio.Semaphore(1))
    monkeypatch.setattr(crawler_routes, 'release_crawler_slot', AsyncMock())
    monkeypatch.setattr(crawler_routes, '_append_run_history', history)
    monkeypatch.setattr(crawler_routes, 'audit_log', MagicMock())
    asyncio.run(crawler_routes._run_and_store('lottemart', pipeline,
        crawl_method='crawl_incremental', crawl_kwargs={'source_url': source_url}, max_attempts=1))
    assert crawler_routes._crawl_results['lottemart']['source_url'] == source_url
    history.assert_called_once_with('lottemart', 'failed', result.duration, source_url=source_url)
    assert pipeline.run_crawler.await_args.kwargs['max_attempts'] == 1


@pytest.mark.parametrize('configured,expected', [
    ({}, 'http://localhost:8002/api/ingestions'),
    ({'DB_ADMIN_URL': 'http://127.0.0.1:28102/'}, 'http://127.0.0.1:28102/api/ingestions'),
    ({'INGESTION_API_URL': 'http://127.0.0.1:28102/api/ingestions', 'DB_ADMIN_URL': 'http://localhost:8002'}, 'http://127.0.0.1:28102/api/ingestions'),
    ({'DB_ADMIN_INGESTION_URL': ' http://127.0.0.1:29102/custom/intake/ ', 'INGESTION_API_URL': 'http://127.0.0.1:28102/api/ingestions', 'DB_ADMIN_URL': 'http://localhost:8002'}, 'http://127.0.0.1:29102/custom/intake/'),
    ({'DB_ADMIN_INGESTION_URL': '  ', 'INGESTION_API_URL': 'http://127.0.0.1:28102/api/ingestions'}, 'http://127.0.0.1:28102/api/ingestions'),
    ({'DB_ADMIN_INGESTION_URL': '', 'INGESTION_API_URL': ' ', 'DB_ADMIN_URL': ' http://127.0.0.1:28102/ '}, 'http://127.0.0.1:28102/api/ingestions'),
    ({'DB_ADMIN_INGESTION_URL': ' ', 'INGESTION_API_URL': '', 'DB_ADMIN_URL': ' '}, 'http://localhost:8002/api/ingestions'),
])
def test_review_proxy_locator_uses_explicit_or_same_intake_target(monkeypatch, configured, expected):
    from api.routes import ingestion as proxy
    for name in ['DB_ADMIN_INGESTION_URL', 'INGESTION_API_URL', 'DB_ADMIN_URL']:
        monkeypatch.delenv(name, raising=False)
    for name, value in configured.items():
        monkeypatch.setenv(name, value)
    assert proxy._resolve_db_admin_ingestion_url() == expected


def test_review_proxy_locator_drives_existing_list_and_detail_without_new_intake(monkeypatch):
    from api.routes import ingestion as proxy
    monkeypatch.delenv('DB_ADMIN_INGESTION_URL', raising=False)
    monkeypatch.setenv('INGESTION_API_URL', 'http://127.0.0.1:28102/api/ingestions')
    monkeypatch.setattr(proxy, 'DB_ADMIN_URL', proxy._resolve_db_admin_ingestion_url())
    forward = AsyncMock(return_value={'id': 17, 'status': 'pending'})
    monkeypatch.setattr(proxy, '_proxy', forward)
    response = asyncio.run(proxy.list_ingestions(status='pending', crawler_name='lottemart', limit=50, offset=0))
    assert response == {'id': 17, 'status': 'pending'}
    forward.assert_awaited_once_with('get', 'http://127.0.0.1:28102/api/ingestions',
        params={'limit': 50, 'offset': 0, 'status': 'pending', 'crawler_name': 'lottemart'})
    forward.reset_mock()
    asyncio.run(proxy.get_ingestion(17))
    forward.assert_awaited_once_with('get', 'http://127.0.0.1:28102/api/ingestions/17')
