"""크롤 오케스트레이터 — Plugin 인터페이스, SQLite 영속 스토어, 스케줄/ad-hoc 실행기."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ── Plugin Protocol & 데이터 모델 ────────────────────────────────

@runtime_checkable
class CrawlerPlugin(Protocol):
    """크롤러 플러그인 어댑터 프로토콜."""

    @property
    def name(self) -> str: ...

    @property
    def mart_kind(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    def supports_targeted_search(self, query: str) -> bool: ...

    async def crawl(self, targets: list[str] | None = None) -> "RawBatch": ...


@dataclass
class RawBatch:
    plugin_name: str
    items: list[dict] = field(default_factory=list)
    items_found: int = 0
    items_saved: int = 0
    errors: list[str] = field(default_factory=list)
    partial: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ── Plugin Registry ──────────────────────────────────────────────

class PluginRegistry:
    """In-memory plugin registry."""

    def __init__(self) -> None:
        self._plugins: dict[str, CrawlerPlugin] = {}
        self._lock = threading.Lock()

    def register(self, plugin: CrawlerPlugin) -> None:
        with self._lock:
            self._plugins[plugin.name] = plugin
            logger.info("[PluginRegistry] registered %s", plugin.name)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._plugins.pop(name, None)

    def get(self, name: str) -> Optional[CrawlerPlugin]:
        return self._plugins.get(name)

    def list_all(self) -> list[CrawlerPlugin]:
        return list(self._plugins.values())

    def clear(self) -> None:
        with self._lock:
            self._plugins.clear()


_registry_singleton: Optional[PluginRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> PluginRegistry:
    global _registry_singleton
    with _registry_lock:
        if _registry_singleton is None:
            _registry_singleton = PluginRegistry()
        return _registry_singleton


# ── SQLite Orchestrator Store ────────────────────────────────────

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = str(_BACKEND_DIR / "orchestrator.db")


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


class OrchestratorStore:
    """SQLite 기반 영속 스토어 — 스케줄, 런, ad-hoc 요청."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._is_memory = db_path == ":memory:"
        if self._is_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        else:
            self._conn = None
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._is_memory:
            return self._conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS crawl_schedules (
                        id TEXT PRIMARY KEY,
                        plugin_name TEXT NOT NULL,
                        cron_expr TEXT,
                        interval_hours REAL,
                        target_categories TEXT,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS crawl_runs (
                        run_id TEXT PRIMARY KEY,
                        plugin_name TEXT NOT NULL,
                        schedule_id TEXT,
                        status TEXT NOT NULL DEFAULT 'running',
                        triggered_by TEXT NOT NULL DEFAULT 'schedule',
                        started_at TEXT NOT NULL,
                        finished_at TEXT,
                        items_found INTEGER NOT NULL DEFAULT 0,
                        items_saved INTEGER NOT NULL DEFAULT 0,
                        failure_reasons TEXT NOT NULL DEFAULT '[]',
                        log_lines TEXT NOT NULL DEFAULT '[]',
                        retried_from TEXT
                    );
                    CREATE TABLE IF NOT EXISTS crawl_requests (
                        request_id TEXT PRIMARY KEY,
                        plugin_name TEXT NOT NULL,
                        search_query TEXT,
                        canonical_id TEXT,
                        requested_by TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        run_id TEXT,
                        created_at TEXT NOT NULL,
                        result_preview TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_runs_plugin ON crawl_runs(plugin_name);
                    CREATE INDEX IF NOT EXISTS idx_runs_status ON crawl_runs(status);
                    """
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def create_schedule(
        self,
        plugin_name: str,
        cron_expr: Optional[str] = None,
        interval_hours: Optional[float] = None,
        target_categories: Optional[list[str]] = None,
        enabled: bool = True,
        schedule_id: Optional[str] = None,
    ) -> str:
        sid = schedule_id or f"sch_{uuid.uuid4().hex[:12]}"
        now = _now_iso()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO crawl_schedules (id, plugin_name, cron_expr, interval_hours, target_categories, enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        sid,
                        plugin_name,
                        cron_expr,
                        interval_hours,
                        json.dumps(target_categories or []),
                        1 if enabled else 0,
                        now,
                        now,
                    ),
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()
        return sid

    def list_schedules(self, plugin_name: Optional[str] = None, enabled_only: bool = False) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                q = "SELECT * FROM crawl_schedules"
                clauses = []
                params: list = []
                if plugin_name:
                    clauses.append("plugin_name = ?")
                    params.append(plugin_name)
                if enabled_only:
                    clauses.append("enabled = 1")
                if clauses:
                    q += " WHERE " + " AND ".join(clauses)
                q += " ORDER BY created_at DESC"
                rows = conn.execute(q, params).fetchall()
            finally:
                if not self._is_memory:
                    conn.close()
        return [self._schedule_row_to_dict(r) for r in rows]

    def get_schedule(self, schedule_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM crawl_schedules WHERE id = ?", (schedule_id,)
                ).fetchone()
            finally:
                if not self._is_memory:
                    conn.close()
        return self._schedule_row_to_dict(row) if row else None

    def update_schedule(self, schedule_id: str, **fields) -> Optional[dict]:
        if not fields:
            return self.get_schedule(schedule_id)
        allowed = {"cron_expr", "interval_hours", "target_categories", "enabled", "plugin_name"}
        sets = []
        params: list = []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "target_categories":
                v = json.dumps(v or [])
            elif k == "enabled":
                v = 1 if v else 0
            sets.append(f"{k} = ?")
            params.append(v)
        if not sets:
            return self.get_schedule(schedule_id)
        sets.append("updated_at = ?")
        params.append(_now_iso())
        params.append(schedule_id)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE crawl_schedules SET {', '.join(sets)} WHERE id = ?",
                    params,
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()
        return self.get_schedule(schedule_id)

    def delete_schedule(self, schedule_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM crawl_schedules WHERE id = ?", (schedule_id,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                if not self._is_memory:
                    conn.close()

    @staticmethod
    def _schedule_row_to_dict(row) -> dict:
        d = dict(row)
        d["enabled"] = bool(d.get("enabled"))
        try:
            d["target_categories"] = json.loads(d.get("target_categories") or "[]")
        except (ValueError, TypeError):
            d["target_categories"] = []
        return d

    def create_run(
        self,
        plugin_name: str,
        schedule_id: Optional[str] = None,
        triggered_by: str = "schedule",
        retried_from: Optional[str] = None,
    ) -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO crawl_runs (run_id, plugin_name, schedule_id, status, triggered_by, started_at, retried_from) VALUES (?, ?, ?, 'running', ?, ?, ?)",
                    (run_id, plugin_name, schedule_id, triggered_by, _now_iso(), retried_from),
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()
        return run_id

    def update_run_status(
        self,
        run_id: str,
        status: str,
        items_found: Optional[int] = None,
        items_saved: Optional[int] = None,
        failure_reasons: Optional[list[str]] = None,
        finished: bool = True,
    ) -> None:
        sets = ["status = ?"]
        params: list = [status]
        if items_found is not None:
            sets.append("items_found = ?")
            params.append(items_found)
        if items_saved is not None:
            sets.append("items_saved = ?")
            params.append(items_saved)
        if failure_reasons is not None:
            sets.append("failure_reasons = ?")
            params.append(json.dumps(failure_reasons))
        if finished:
            sets.append("finished_at = ?")
            params.append(_now_iso())
        params.append(run_id)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE crawl_runs SET {', '.join(sets)} WHERE run_id = ?",
                    params,
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def append_log(self, run_id: str, line: str) -> None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT log_lines FROM crawl_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
                if not row:
                    return
                try:
                    lines = json.loads(row["log_lines"] or "[]")
                except (ValueError, TypeError):
                    lines = []
                stamp = _now_iso()
                lines.append(f"[{stamp}] {line}")
                conn.execute(
                    "UPDATE crawl_runs SET log_lines = ? WHERE run_id = ?",
                    (json.dumps(lines), run_id),
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM crawl_runs WHERE run_id = ?", (run_id,)
                ).fetchone()
            finally:
                if not self._is_memory:
                    conn.close()
        return self._run_row_to_dict(row) if row else None

    def list_runs(
        self,
        plugin_name: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        page = max(1, int(page or 1))
        page_size = max(1, min(200, int(page_size or 20)))
        offset = (page - 1) * page_size
        clauses = []
        params: list = []
        if plugin_name:
            clauses.append("plugin_name = ?")
            params.append(plugin_name)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._lock:
            conn = self._connect()
            try:
                total = conn.execute(f"SELECT COUNT(*) AS c FROM crawl_runs{where}", params).fetchone()["c"]
                rows = conn.execute(
                    f"SELECT * FROM crawl_runs{where} ORDER BY started_at DESC LIMIT ? OFFSET ?",
                    (*params, page_size, offset),
                ).fetchall()
            finally:
                if not self._is_memory:
                    conn.close()
        return {
            "items": [self._run_row_to_dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    def last_run_for_plugin(self, plugin_name: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM crawl_runs WHERE plugin_name = ? ORDER BY started_at DESC LIMIT 1",
                    (plugin_name,),
                ).fetchone()
            finally:
                if not self._is_memory:
                    conn.close()
        return self._run_row_to_dict(row) if row else None

    def last_run_for_schedule(self, schedule_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM crawl_runs WHERE schedule_id = ? ORDER BY started_at DESC LIMIT 1",
                    (schedule_id,),
                ).fetchone()
            finally:
                if not self._is_memory:
                    conn.close()
        return self._run_row_to_dict(row) if row else None

    def find_retry_run(self, source_run_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM crawl_runs WHERE retried_from = ? AND status IN ('running','success','partial') ORDER BY started_at DESC LIMIT 1",
                    (source_run_id,),
                ).fetchone()
            finally:
                if not self._is_memory:
                    conn.close()
        return self._run_row_to_dict(row) if row else None

    @staticmethod
    def _run_row_to_dict(row) -> dict:
        d = dict(row)
        try:
            d["failure_reasons"] = json.loads(d.get("failure_reasons") or "[]")
        except (ValueError, TypeError):
            d["failure_reasons"] = []
        try:
            d["log_lines"] = json.loads(d.get("log_lines") or "[]")
        except (ValueError, TypeError):
            d["log_lines"] = []
        return d

    def create_request(
        self,
        plugin_name: str,
        search_query: Optional[str] = None,
        canonical_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> str:
        rid = f"req_{uuid.uuid4().hex[:12]}"
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO crawl_requests (request_id, plugin_name, search_query, canonical_id, requested_by, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                    (rid, plugin_name, search_query, canonical_id, requested_by, _now_iso()),
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()
        return rid

    def update_request(
        self,
        request_id: str,
        status: Optional[str] = None,
        run_id: Optional[str] = None,
        result_preview: Optional[Any] = None,
    ) -> Optional[dict]:
        sets = []
        params: list = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if run_id is not None:
            sets.append("run_id = ?")
            params.append(run_id)
        if result_preview is not None:
            sets.append("result_preview = ?")
            params.append(json.dumps(result_preview))
        if not sets:
            return self.get_request(request_id)
        params.append(request_id)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    f"UPDATE crawl_requests SET {', '.join(sets)} WHERE request_id = ?",
                    params,
                )
                conn.commit()
            finally:
                if not self._is_memory:
                    conn.close()
        return self.get_request(request_id)

    def get_request(self, request_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM crawl_requests WHERE request_id = ?", (request_id,)
                ).fetchone()
            finally:
                if not self._is_memory:
                    conn.close()
        if not row:
            return None
        d = dict(row)
        if d.get("result_preview"):
            try:
                d["result_preview"] = json.loads(d["result_preview"])
            except (ValueError, TypeError):
                pass
        return d


_store_singleton: Optional[OrchestratorStore] = None
_store_lock = threading.Lock()


def get_run_store() -> OrchestratorStore:
    """모듈 레벨 싱글톤 — 프로덕션 DB 핸들."""
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = OrchestratorStore()
        return _store_singleton


def reset_run_store_for_tests(store: Optional[OrchestratorStore] = None) -> OrchestratorStore:
    """테스트 전용 — 싱글톤을 새 인스턴스로 교체."""
    global _store_singleton
    with _store_lock:
        _store_singleton = store or OrchestratorStore(":memory:")
        return _store_singleton


def _maybe_run_async(coro):
    """이미 실행 중인 이벤트 루프가 있다면 새 루프에서 실행, 아니면 asyncio.run 사용."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result_box: dict = {}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            result_box["value"] = loop.run_until_complete(coro)
        except Exception as exc:  # pragma: no cover
            result_box["error"] = exc
        finally:
            loop.close()

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in result_box:
        raise result_box["error"]
    return result_box.get("value")


async def _invoke_plugin_crawl(plugin: CrawlerPlugin, targets: list[str] | None) -> RawBatch:
    """플러그인 crawl() 호출 — targets 인자를 받지 않는 어댑터도 지원."""
    try:
        sig = inspect.signature(plugin.crawl)
        if "targets" in sig.parameters:
            return await plugin.crawl(targets=targets)
        return await plugin.crawl()
    except TypeError:
        return await plugin.crawl()


def _persist_run_result(
    store: OrchestratorStore,
    run_id: str,
    batch: Optional[RawBatch],
    error: Optional[BaseException],
) -> dict:
    if error is not None:
        store.append_log(run_id, f"오류: {error!r}")
        store.update_run_status(
            run_id,
            status="failed",
            items_found=0,
            items_saved=0,
            failure_reasons=[str(error)],
        )
        return {"run_id": run_id, "status": "failed", "error": str(error)}

    assert batch is not None
    status = "success"
    if batch.errors and batch.items:
        status = "partial"
    elif batch.errors and not batch.items:
        status = "failed"
    if batch.partial:
        status = "partial"
    store.append_log(run_id, f"수집 {batch.items_found}건 / 저장 {batch.items_saved}건 / 오류 {len(batch.errors)}건")
    store.update_run_status(
        run_id,
        status=status,
        items_found=batch.items_found,
        items_saved=batch.items_saved,
        failure_reasons=list(batch.errors or []),
    )
    return {
        "run_id": run_id,
        "status": status,
        "items_found": batch.items_found,
        "items_saved": batch.items_saved,
        "errors": list(batch.errors or []),
    }


async def _execute_plugin_async(
    plugin: CrawlerPlugin,
    targets: list[str] | None,
    run_id: str,
    store: OrchestratorStore,
) -> dict:
    """플러그인을 실행하고 로컬 run 결과만 기록한다.

    외부 분류는 별도의 명시적 export/import 흐름에서 수행한다. 오케스트레이터는
    폐기된 live ai-admin 서버나 provider를 자동 호출하지 않는다.
    """
    store.append_log(run_id, f"플러그인 {plugin.name} 실행 시작")
    try:
        batch = await _invoke_plugin_crawl(plugin, targets)
        return _persist_run_result(store, run_id, batch, None)
    except Exception as exc:  # pragma: no cover - 예외 흐름은 테스트에서 패치로 검증
        logger.exception("[orchestrator] plugin %s failed", plugin.name)
        return _persist_run_result(store, run_id, None, exc)


def _execute_plugin_sync(
    plugin: CrawlerPlugin,
    targets: list[str] | None,
    run_id: str,
    store: OrchestratorStore,
) -> dict:
    return _maybe_run_async(_execute_plugin_async(plugin, targets, run_id, store))


def trigger_run(
    plugin_name: str,
    target_categories: list[str] | None = None,
    triggered_by: str = "manual",
    schedule_id: Optional[str] = None,
    store: Optional[OrchestratorStore] = None,
    registry: Optional[PluginRegistry] = None,
) -> str:
    """즉시 실행 — 실행 완료 후 run_id 반환."""
    store = store or get_run_store()
    registry = registry or get_registry()
    plugin = registry.get(plugin_name)
    if plugin is None:
        raise ValueError(f"플러그인을 찾을 수 없습니다: {plugin_name}")
    run_id = store.create_run(plugin_name, schedule_id=schedule_id, triggered_by=triggered_by)
    _execute_plugin_sync(plugin, target_categories, run_id, store)
    return run_id


def run_ad_hoc(
    plugin_name: str,
    search_query: Optional[str],
    canonical_id: Optional[str],
    requested_by: str,
    store: Optional[OrchestratorStore] = None,
    registry: Optional[PluginRegistry] = None,
) -> str:
    """Ad-hoc 수집 요청 — request_id 반환."""
    store = store or get_run_store()
    registry = registry or get_registry()
    plugin = registry.get(plugin_name)
    if plugin is None:
        raise ValueError(f"플러그인을 찾을 수 없습니다: {plugin_name}")
    request_id = store.create_request(
        plugin_name=plugin_name,
        search_query=search_query,
        canonical_id=canonical_id,
        requested_by=requested_by,
    )
    targets = [search_query] if search_query else None
    run_id = store.create_run(plugin_name, triggered_by="ad-hoc")
    store.update_request(request_id, status="running", run_id=run_id)
    result = _execute_plugin_sync(plugin, targets, run_id, store)
    final_status = "done" if result.get("status") in {"success", "partial"} else "failed"
    preview = {
        "status": result.get("status"),
        "items_found": result.get("items_found", 0),
        "items_saved": result.get("items_saved", 0),
        "errors": result.get("errors", []),
    }
    store.update_request(request_id, status=final_status, result_preview=preview)
    return request_id


def retry_run(
    run_id: str,
    store: Optional[OrchestratorStore] = None,
    registry: Optional[PluginRegistry] = None,
) -> str:
    """실패한 런을 재실행 — 멱등(이미 재시도된 경우 동일 run_id 반환)."""
    store = store or get_run_store()
    registry = registry or get_registry()
    source = store.get_run(run_id)
    if source is None:
        raise ValueError(f"run을 찾을 수 없습니다: {run_id}")
    existing = store.find_retry_run(run_id)
    if existing is not None:
        return existing["run_id"]
    plugin = registry.get(source["plugin_name"])
    if plugin is None:
        raise ValueError(f"플러그인을 찾을 수 없습니다: {source['plugin_name']}")
    new_run_id = store.create_run(
        plugin_name=source["plugin_name"],
        schedule_id=source.get("schedule_id"),
        triggered_by="retry",
        retried_from=run_id,
    )
    _execute_plugin_sync(plugin, None, new_run_id, store)
    return new_run_id


def _schedule_is_due(schedule: dict, now: datetime, last_started_at: Optional[datetime]) -> bool:
    """다음 실행 시각이 now 이전이면 due."""
    if not schedule.get("enabled"):
        return False
    interval = schedule.get("interval_hours")
    cron_expr = schedule.get("cron_expr")
    if interval is not None:
        try:
            interval = float(interval)
        except (TypeError, ValueError):
            interval = None
    if interval is not None:
        if interval <= 0:
            return True
        if last_started_at is None:
            return True
        return now >= last_started_at + timedelta(hours=interval)
    if cron_expr:
        try:
            from apscheduler.triggers.cron import CronTrigger
            trig = CronTrigger.from_crontab(cron_expr)
        except Exception:
            return False
        if last_started_at is None:
            prev = trig.get_next_fire_time(None, now - timedelta(days=1))
            return bool(prev and prev <= now)
        next_fire = trig.get_next_fire_time(None, last_started_at)
        return bool(next_fire and next_fire <= now)
    return False


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def run_due_schedules(
    now: Optional[datetime] = None,
    store: Optional[OrchestratorStore] = None,
    registry: Optional[PluginRegistry] = None,
) -> list[dict]:
    """활성 스케줄 중 도래한 것을 모두 실행 — 실행 결과 요약 리스트 반환."""
    now = now or datetime.utcnow()
    store = store or get_run_store()
    registry = registry or get_registry()
    summaries: list[dict] = []
    for sched in store.list_schedules(enabled_only=True):
        last = store.last_run_for_schedule(sched["id"])
        last_started = _parse_iso(last["started_at"]) if last else None
        if not _schedule_is_due(sched, now, last_started):
            continue
        plugin = registry.get(sched["plugin_name"])
        if plugin is None:
            summaries.append({
                "schedule_id": sched["id"],
                "plugin_name": sched["plugin_name"],
                "status": "skipped",
                "reason": "plugin_not_registered",
            })
            continue
        run_id = store.create_run(
            plugin_name=sched["plugin_name"],
            schedule_id=sched["id"],
            triggered_by="schedule",
        )
        result = _execute_plugin_sync(plugin, sched.get("target_categories") or None, run_id, store)
        summaries.append({"schedule_id": sched["id"], **result})
    return summaries
