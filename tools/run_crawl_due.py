#!/usr/bin/env python3
"""외부 스케줄러(작업스케줄러/cron)에서 호출 가능한 크롤 실행 CLI.

Usage:
    py -3 tools/run_crawl_due.py [--plugin emart] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# crawler-admin/backend 디렉터리를 sys.path에 추가
_BACKEND = Path(__file__).resolve().parent.parent / "packages" / "crawler-admin" / "backend"
_SHARED = Path(__file__).resolve().parent.parent / "packages" / "shared"
for p in (str(_BACKEND), str(_SHARED)):
    if p not in sys.path:
        sys.path.insert(0, p)


def _register_plugins() -> None:
    for mod_name in ("emart", "homeplus", "lottemart", "costco"):
        try:
            mod = __import__(f"crawlers.marts.{mod_name}.plugin", fromlist=["register"])
            mod.register()
        except Exception as exc:
            print(f"[warn] plugin {mod_name} register failed: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="도래한 크롤 스케줄을 실행합니다.")
    parser.add_argument("--plugin", help="특정 플러그인만 실행")
    parser.add_argument("--dry-run", action="store_true", help="실제 실행 없이 대상만 출력")
    args = parser.parse_args()

    _register_plugins()

    from services.crawl_orchestrator import (
        get_registry,
        get_run_store,
        run_due_schedules,
        _schedule_is_due,
        _parse_iso,
    )

    store = get_run_store()
    registry = get_registry()
    now = datetime.utcnow()

    schedules = store.list_schedules(plugin_name=args.plugin, enabled_only=True)
    if args.dry_run:
        due = []
        for s in schedules:
            last = store.last_run_for_schedule(s["id"])
            last_started = _parse_iso(last["started_at"]) if last else None
            if _schedule_is_due(s, now, last_started):
                due.append(s)
        print(json.dumps({"due_count": len(due), "schedules": due}, ensure_ascii=False, indent=2))
        return 0

    # 특정 플러그인만일 경우 임시 필터 — run_due_schedules는 모두 보지만,
    # 미등록 플러그인은 skipped로 표시되므로 결과를 후필터링
    summaries = run_due_schedules(now=now, store=store, registry=registry)
    if args.plugin:
        summaries = [s for s in summaries if s.get("plugin_name") == args.plugin]
    print(json.dumps({"executed": summaries}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
