"""Read-only external hotdeal feed uploaded from local crawling."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _BACKEND_ROOT / "storage" / "external_hotdeals.sqlite"


def _json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def _relative_time(value) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
        if seconds < 60:
            return "방금"
        if seconds < 3600:
            return f"{seconds // 60}분 전"
        if seconds < 86400:
            return f"{seconds // 3600}시간 전"
        return f"{seconds // 86400}일 전"
    except ValueError:
        return str(value)


class ExternalHotdealStore:
    def __init__(self, path: str | Path | None = None):
        configured = str(path or os.getenv("WALLETSAVIOR_EXTERNAL_HOTDEAL_DB", "")).strip()
        self.path = (
            Path(configured).expanduser()
            if configured
            else _DEFAULT_DB
        ).resolve()

    def available(self) -> bool:
        return self.path.is_file()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        connection = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro",
            uri=True,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _serialize(row: sqlite3.Row | dict) -> dict:
        data = dict(row)
        return {
            "id": int(data["id"]),
            "hotdeal_id": int(data["id"]),
            "product_id": None,
            "title": data.get("title") or "",
            "source": data.get("source_site") or "other",
            "source_site": data.get("source_site") or "other",
            "source_native_id": data.get("source_native_id"),
            "url": data.get("url") or "",
            "price": data.get("price"),
            "origPrice": data.get("original_price"),
            "original_price": data.get("original_price"),
            "discount_rate": data.get("discount_rate"),
            "time": _relative_time(data.get("posted_at") or data.get("fetched_at")),
            "posted_at": str(data.get("posted_at") or ""),
            "expires_at": str(data.get("expires_at") or ""),
            "cat": data.get("category_raw") or "",
            "category": data.get("category_raw") or "",
            "shop_name": data.get("shop_name") or "",
            "tags": _json_list(data.get("tags")),
            "views": 0,
            "comments": 0,
            "thumb": None,
            "is_verified": True,
            "fetched_at": str(data.get("fetched_at") or ""),
        }

    def list_hotdeals(
        self,
        *,
        category: str | None = None,
        source: str | None = None,
        sort: str = "recent",
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        if not self.available():
            return []

        clauses = ["is_active=1"]
        params: list[object] = []
        if source:
            clauses.append("source_site=?")
            params.append(source)
        if category and category != "all":
            clauses.append("COALESCE(category_raw, '') LIKE ?")
            params.append(f"%{category}%")

        order = "COALESCE(posted_at, fetched_at) DESC, id DESC"
        if sort == "price_asc":
            order = "price IS NULL, price ASC, COALESCE(posted_at, fetched_at) DESC"
        elif sort == "discount":
            order = "discount_rate IS NULL, discount_rate DESC, COALESCE(posted_at, fetched_at) DESC"

        params.extend([max(1, min(per_page, 100)), max(0, (page - 1) * per_page)])
        sql = (
            "SELECT * FROM hotdeal_posts WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY {order} LIMIT ? OFFSET ?"
        )
        with self.connection() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._serialize(row) for row in rows]

    def get_hotdeal(self, hotdeal_id: int) -> dict | None:
        if not self.available():
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM hotdeal_posts WHERE id=? AND is_active=1",
                (hotdeal_id,),
            ).fetchone()
        return self._serialize(row) if row else None

    def sources(self) -> list[str]:
        if not self.available():
            return []
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT DISTINCT source_site FROM hotdeal_posts "
                "WHERE is_active=1 ORDER BY source_site"
            ).fetchall()
        return [str(row[0]) for row in rows if row[0]]
