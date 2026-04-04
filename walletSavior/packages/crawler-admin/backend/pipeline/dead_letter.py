"""Dead-letter queue — local file fallback for failed ingestion attempts.

On store/ingestion failure, records are written to a JSONL file under
``data/dead_letter/``. A background sweep can replay them later.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DLQ_DIR = Path(os.getenv(
    "DLQ_DIR",
    str(Path(__file__).resolve().parent.parent / "data" / "dead_letter"),
))


def write_dead_letter(
    records: list[dict[str, Any]],
    *,
    crawler_name: str = "unknown",
    target: str = "store",
    error_msg: str = "",
) -> Path:
    """Persist *records* to a timestamped JSONL file and return its path."""
    _DLQ_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    filename = f"{crawler_name}_{target}_{ts}.jsonl"
    path = _DLQ_DIR / filename

    envelope = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "crawler_name": crawler_name,
        "target": target,
        "error": error_msg,
        "record_count": len(records),
        "records": records,
    }

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(envelope, ensure_ascii=False, default=str))

    logger.warning(
        "[DLQ] wrote %d records → %s (target=%s, error=%s)",
        len(records), path, target, error_msg,
    )
    return path


def list_dead_letters() -> list[Path]:
    """Return all pending dead-letter files, oldest first."""
    if not _DLQ_DIR.exists():
        return []
    return sorted(_DLQ_DIR.glob("*.jsonl"))


def read_dead_letter(path: Path) -> dict[str, Any]:
    """Read a single dead-letter file."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.loads(fh.read())


def remove_dead_letter(path: Path) -> None:
    """Delete a dead-letter file after successful replay."""
    path.unlink(missing_ok=True)
