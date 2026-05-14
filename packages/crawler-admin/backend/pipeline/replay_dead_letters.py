"""Dead letter 복구 — 인증 수정 후 실패한 레코드를 DB-Admin에 다시 전송.

Usage:
    py -m pipeline.replay_dead_letters            # replay all
    py -m pipeline.replay_dead_letters --dry-run   # preview only
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import httpx

# Allow running as ``python -m pipeline.replay_dead_letters`` from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.db_admin_auth import get_db_admin_auth  # noqa: E402
from pipeline.dead_letter import (  # noqa: E402
    list_dead_letters,
    read_dead_letter,
    remove_dead_letter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

INGESTION_API_URL = os.getenv(
    "INGESTION_API_URL", "http://localhost:8002/api/ingestions"
)
DB_ADMIN_API_URL = os.getenv(
    "DB_ADMIN_API_URL", "http://localhost:8002/api/prices/bulk"
)


async def _send_with_retry(
    client: httpx.AsyncClient,
    auth: Any,
    url: str,
    payload: dict | list,
) -> httpx.Response:
    """POST with automatic 401 retry."""
    headers = await auth.get_headers()
    resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code == 401:
        headers = await auth.handle_401()
        resp = await client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    return resp


async def replay_all(dry_run: bool = False) -> dict:
    """Replay all dead letter files. Returns summary dict."""
    files = list_dead_letters()
    if not files:
        logger.info("No dead letter files to replay.")
        return {"total": 0, "success": 0, "failed": 0}

    auth = get_db_admin_auth()
    results: dict[str, Any] = {
        "total": len(files),
        "success": 0,
        "failed": 0,
        "details": [],
    }

    for path in files:
        envelope = read_dead_letter(path)
        target = envelope.get("target", "store")
        records = envelope.get("records", [])
        crawler_name = envelope.get("crawler_name", "unknown")

        logger.info(
            "[Replay] %s: %d records (target=%s, crawler=%s)",
            path.name, len(records), target, crawler_name,
        )

        if dry_run:
            results["details"].append({
                "file": path.name,
                "status": "dry_run",
                "records": len(records),
            })
            continue

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if target == "ingestion":
                    payload = {
                        "crawler_name": crawler_name,
                        "crawl_status": "replayed",
                        "items": records,
                        "schema_type": envelope.get("schema_type", "DiscountItem"),
                    }
                    await _send_with_retry(client, auth, INGESTION_API_URL, payload)
                else:
                    await _send_with_retry(client, auth, DB_ADMIN_API_URL, records)

            remove_dead_letter(path)
            results["success"] += 1
            results["details"].append({
                "file": path.name,
                "status": "success",
                "records": len(records),
            })
            logger.info("[Replay] ✓ %s replayed (%d records)", path.name, len(records))
        except Exception as exc:
            results["failed"] += 1
            results["details"].append({
                "file": path.name,
                "status": "failed",
                "error": str(exc),
            })
            logger.error("[Replay] ✗ %s failed: %s", path.name, exc)

    logger.info(
        "[Replay] Done: %d total, %d success, %d failed",
        results["total"], results["success"], results["failed"],
    )
    return results


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    result = asyncio.run(replay_all(dry_run=dry))
    print(json.dumps(result, indent=2, ensure_ascii=False))
