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
_REQUIRED_SNAPSHOT_TABLES = {"hotdeal_posts", "snapshot_meta"}

# category_raw is intentionally preserved from the crawler.  The public API,
# however, exposes stable category keys to the frontend.  Keep that translation
# here instead of teaching crawler/db-admin about web UI category names.
_CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "food": ("food", "식품"),
    "electronics": ("electronics", "전자제품", "전자", "가전", "디지털"),
    "living": ("living", "생활", "리빙"),
    "fashion": ("fashion", "패션"),
    "beauty": ("beauty", "뷰티"),
    "travel": ("travel", "여행"),
    "etc": ("etc", "기타"),
}


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


def _like_contains(value: str) -> str:
    escaped = (
        str(value)
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{escaped}%"


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

    def health(self) -> dict:
        """Return non-fatal diagnostics for the optional external-hotdeal snapshot."""
        if not self.available():
            return {
                "ok": False,
                "available": False,
                "path": str(self.path),
                "reason": "snapshot_not_found",
            }

        try:
            with self.connection() as connection:
                quick_check = connection.execute("PRAGMA quick_check").fetchone()
                if not quick_check or quick_check[0] != "ok":
                    return {
                        "ok": False,
                        "available": True,
                        "path": str(self.path),
                        "reason": "quick_check_failed",
                        "detail": str(quick_check[0] if quick_check else "no result"),
                    }

                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                missing = sorted(_REQUIRED_SNAPSHOT_TABLES - tables)
                if missing:
                    return {
                        "ok": False,
                        "available": True,
                        "path": str(self.path),
                        "reason": "missing_tables",
                        "missing_tables": missing,
                    }

                meta = connection.execute(
                    "SELECT revision, built_at FROM snapshot_meta WHERE id=1"
                ).fetchone()
                if not meta:
                    return {
                        "ok": False,
                        "available": True,
                        "path": str(self.path),
                        "reason": "metadata_missing",
                    }

                row_count = int(
                    connection.execute("SELECT COUNT(*) FROM hotdeal_posts").fetchone()[0]
                )
                return {
                    "ok": True,
                    "available": True,
                    "path": str(self.path),
                    "revision": meta["revision"],
                    "built_at": meta["built_at"],
                    "row_count": row_count,
                }
        except (OSError, sqlite3.Error) as exc:
            return {
                "ok": False,
                "available": True,
                "path": str(self.path),
                "reason": "snapshot_unreadable",
                "detail": str(exc),
            }

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

    @staticmethod
    def _filters(
        category: str | None,
        source: str | None,
        query: str | None = None,
    ) -> tuple[list[str], list[object]]:
        clauses = ["is_active=1"]
        params: list[object] = []
        if source:
            clauses.append("source_site=?")
            params.append(source)
        if category and category != "all":
            category_text = str(category).strip()
            aliases = _CATEGORY_ALIASES.get(category_text.lower(), (category_text,))
            category_clauses = [
                "LOWER(COALESCE(category_raw, '')) LIKE LOWER(?) ESCAPE '\\'"
                for _ in aliases
            ]
            clauses.append("(" + " OR ".join(category_clauses) + ")")
            params.extend(_like_contains(alias) for alias in aliases)
        query_text = str(query or "").strip()
        if query_text:
            pattern = _like_contains(query_text)
            clauses.append(
                "(LOWER(COALESCE(title, '')) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(COALESCE(shop_name, '')) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(COALESCE(source_site, '')) LIKE LOWER(?) ESCAPE '\\' "
                "OR LOWER(COALESCE(category_raw, '')) LIKE LOWER(?) ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern, pattern])
        return clauses, params

    def count_hotdeals(
        self,
        *,
        category: str | None = None,
        source: str | None = None,
        query: str | None = None,
    ) -> int:
        if not self.available():
            return 0
        clauses, params = self._filters(category, source, query)
        with self.connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM hotdeal_posts WHERE " + " AND ".join(clauses),
                params,
            ).fetchone()
        return int(row[0]) if row else 0

    def list_hotdeals(
        self,
        *,
        category: str | None = None,
        source: str | None = None,
        query: str | None = None,
        sort: str = "recent",
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        if not self.available():
            return []

        clauses, params = self._filters(category, source, query)

        order = "COALESCE(posted_at, fetched_at) DESC, id DESC"
        if sort in {"price_asc", "priceAsc"}:
            order = "price IS NULL, price ASC, COALESCE(posted_at, fetched_at) DESC"
        elif sort == "discount":
            order = "discount_rate IS NULL, discount_rate DESC, COALESCE(posted_at, fetched_at) DESC"

        per_page = max(1, min(int(per_page or 20), 100))
        page = max(1, int(page or 1))
        params.extend([per_page, (page - 1) * per_page])
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
