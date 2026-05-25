"""rd3-pipe-silent-gap-fix — 크롤 아티팩트를 ai-admin /api/ingest/raw-records/label 로 replay.

목적: 코스트코 OCC v0.6.0 처럼 _standalone_ 스크립트가 만든 JSON 아티팩트(예:
.walletsavior-live-validation/rd2-costco-playwright/run-*.json)는 orchestrator 를 거치지
않아 raw_crawl_records 에 0건으로 흡수된다. 이 CLI 로 사후 replay 하면 동일한 silent-drop
가드(records_sent vs records_stored 비교 + wire log)를 통과시킬 수 있다.

사용 예:
    py -3 packages/crawler-admin/backend/tools/forward_crawl_artifact_to_ai_admin.py \\
        --artifact .walletsavior-live-validation/rd2-costco-playwright/run-XYZ.json \\
        --items-path runs[].items \\
        --source-name costco --crawler-name costco_crawler \\
        --schema-type mart_discount \\
        --ai-admin-base-url http://localhost:8003 --provider-id google-dev

JSON 구조가 마트마다 다르므로 --items-path 로 어디서 items 리스트를 뽑을지 명시한다.
('runs[].items' = runs 배열의 각 원소의 items 를 모두 concat)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_items(payload: Any, path: str) -> list[dict]:
    cur: Any = payload
    parts = [p for p in path.split(".") if p]
    out: list[dict] = []
    for part in parts:
        if part.endswith("[]"):
            key = part[:-2]
            if key:
                cur = cur[key] if isinstance(cur, dict) else None
            if not isinstance(cur, list):
                return []
            # Flatten remaining path across list elements.
            remaining = ".".join(parts[parts.index(part) + 1 :])
            if not remaining:
                for el in cur:
                    if isinstance(el, list):
                        out.extend(x for x in el if isinstance(x, dict))
                    elif isinstance(el, dict):
                        out.append(el)
                return out
            for el in cur:
                out.extend(_load_items(el, remaining))
            return out
        cur = cur.get(part) if isinstance(cur, dict) else None
    if isinstance(cur, list):
        return [x for x in cur if isinstance(x, dict)]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifact", required=True, help="path to crawl JSON artifact")
    parser.add_argument("--items-path", required=True, help="dotted path to items, supports [] for list flatten")
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--crawler-name", required=True)
    parser.add_argument("--schema-type", default="mart_discount")
    parser.add_argument("--ai-admin-base-url", required=True)
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--wire-log", default=None, help="optional override for forward wire log path")
    parser.add_argument("--dry-run", action="store_true", help="only print item count, don't POST")
    args = parser.parse_args(argv)

    backend = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(backend))
    sys.path.insert(0, str(backend.parent.parent / "shared"))

    payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    items = _load_items(payload, args.items_path)
    print(f"loaded items: {len(items)} from {args.artifact} (path={args.items_path})")
    if args.dry_run or not items:
        return 0

    if args.wire_log:
        os.environ["WALLETSAVIOR_CRAWL_FORWARD_WIRE_LOG_PATH"] = args.wire_log

    from pipeline.ai_export import RawExportError, forward_raw_records_to_ai_admin

    try:
        result = forward_raw_records_to_ai_admin(
            items,
            ai_admin_base_url=args.ai_admin_base_url,
            provider_id=args.provider_id,
            source_name=args.source_name,
            crawler_name=args.crawler_name,
            schema_type=args.schema_type,
            api_key=args.api_key,
        )
    except RawExportError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(
        {
            "records_sent": result["records_sent"],
            "records_accepted": result["records_accepted"],
            "drop_count": result["drop_count"],
            "batches_sent": result["batches_sent"],
            "wire_log_path": result.get("wire_log_path"),
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0 if result["drop_count"] == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
