"""Moderation access to the isolated web community SQLite database.

This module intentionally uses sqlite3 instead of importing the web-api ORM.
That avoids a second copy of the board model definitions while ensuring DB Admin
moderation reads and writes the exact same ``board.sqlite`` file as the public
web community API.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_BOARD_DB = _PROJECT_ROOT / "packages" / "web-api" / "backend" / "storage" / "board.sqlite"


def board_db_path() -> Path:
    configured = os.getenv("WALLETSAVIOR_BOARD_DB")
    return Path(configured).resolve() if configured else _DEFAULT_BOARD_DB.resolve()


@contextmanager
def _connection(*, write: bool = False):
    path = board_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
    try:
        _require_current_schema(connection)
        yield connection
        if write:
            connection.commit()
    except Exception:
        if write:
            connection.rollback()
        raise
    finally:
        connection.close()


def _require_current_schema(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('community_users','community_posts','community_comments','community_votes')"
    ).fetchall()
    names = {row[0] for row in rows}
    required = {
        "community_users",
        "community_posts",
        "community_comments",
        "community_votes",
    }
    if names != required:
        missing = sorted(required - names)
        raise RuntimeError(
            "community board schema is not initialized; start web-api once first "
            f"(missing: {', '.join(missing)})"
        )


def _post_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "post_type": row["post_type"],
        "author_id": row["author_id"],
        "author": row["author"],
        "category_id": row["category_id"],
        "custom_category": row["custom_category"],
        "product_id": None,
        "deal_price": row["deal_price"],
        "original_price": row["original_price"],
        "deal_url": row["deal_url"],
        "tags": [],
        "view_count": row["view_count"],
        "comment_count": row["comment_count"],
        "vote_count": row["vote_count"],
        "is_pinned": False,
        "is_deleted": bool(row["is_deleted"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_posts(
    *,
    status: str = "active",
    post_type: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    if status == "reported":
        return {
            "items": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 1,
            "note": "신고 테이블이 없어 신고된 게시글 필터는 아직 데이터가 없습니다.",
        }

    clauses: list[str] = []
    params: list[object] = []
    if status == "active":
        clauses.append("p.is_deleted = 0")
    elif status == "deleted":
        clauses.append("p.is_deleted = 1")
    if post_type:
        clauses.append("p.post_type = ?")
        params.append(post_type)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        clauses.append("(p.title LIKE ? ESCAPE '\\' OR p.content LIKE ? ESCAPE '\\' OR u.nickname LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern, pattern])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM community_posts p "
            "LEFT JOIN community_users u ON u.id = p.author_id "
            f"{where}",
            params,
        ).fetchone()[0]
        rows = connection.execute(
            "SELECT p.id, p.title, p.content, p.post_type, p.author_id, "
            "u.nickname AS author, p.category_id, p.custom_category, "
            "p.deal_price, p.original_price, p.deal_url, p.view_count, "
            "p.is_deleted, p.created_at, p.updated_at, "
            "(SELECT COUNT(*) FROM community_comments c WHERE c.post_id=p.id AND c.is_deleted=0) AS comment_count, "
            "(SELECT COUNT(*) FROM community_votes v WHERE v.post_id=p.id) AS vote_count "
            "FROM community_posts p "
            "LEFT JOIN community_users u ON u.id = p.author_id "
            f"{where} ORDER BY p.created_at DESC LIMIT ? OFFSET ?",
            [*params, per_page, (page - 1) * per_page],
        ).fetchall()

    return {
        "items": [_post_dict(row) for row in rows],
        "total": int(total),
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (int(total) + per_page - 1) // per_page),
    }


def get_post(post_id: int) -> dict | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT p.id, p.title, p.content, p.post_type, p.author_id, "
            "u.nickname AS author, p.category_id, p.custom_category, "
            "p.deal_price, p.original_price, p.deal_url, p.view_count, "
            "p.is_deleted, p.created_at, p.updated_at, "
            "(SELECT COUNT(*) FROM community_comments c WHERE c.post_id=p.id AND c.is_deleted=0) AS comment_count, "
            "(SELECT COUNT(*) FROM community_votes v WHERE v.post_id=p.id) AS vote_count "
            "FROM community_posts p LEFT JOIN community_users u ON u.id=p.author_id "
            "WHERE p.id=?",
            (post_id,),
        ).fetchone()
        if row is None:
            return None
        comments = connection.execute(
            "SELECT c.id, c.post_id, c.parent_id, c.content, c.author_id, "
            "u.nickname AS author, c.is_deleted, c.created_at "
            "FROM community_comments c "
            "LEFT JOIN community_users u ON u.id=c.author_id "
            "WHERE c.post_id=? ORDER BY c.created_at ASC, c.id ASC",
            (post_id,),
        ).fetchall()
    return {
        "post": _post_dict(row),
        "comments": [
            {
                "id": comment["id"],
                "post_id": comment["post_id"],
                "parent_id": comment["parent_id"],
                "content": comment["content"],
                "author_id": comment["author_id"],
                "author": comment["author"],
                "is_deleted": bool(comment["is_deleted"]),
                "created_at": comment["created_at"],
                "updated_at": comment["created_at"],
            }
            for comment in comments
        ],
    }


def set_post_deleted(post_id: int, deleted: bool) -> bool:
    with _connection(write=True) as connection:
        cursor = connection.execute(
            "UPDATE community_posts SET is_deleted=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (1 if deleted else 0, post_id),
        )
        return cursor.rowcount > 0


def set_comment_deleted(comment_id: int, deleted: bool) -> bool:
    with _connection(write=True) as connection:
        cursor = connection.execute(
            "UPDATE community_comments SET is_deleted=? WHERE id=?",
            (1 if deleted else 0, comment_id),
        )
        return cursor.rowcount > 0


def set_user_active(user_id: int, active: bool) -> dict | None:
    with _connection(write=True) as connection:
        cursor = connection.execute(
            "UPDATE community_users SET is_active=? WHERE id=?",
            (1 if active else 0, user_id),
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            "SELECT id, email, nickname, is_active FROM community_users WHERE id=?",
            (user_id,),
        ).fetchone()
    return {
        "id": row["id"],
        "email": row["email"],
        "nickname": row["nickname"],
        "is_active": bool(row["is_active"]),
    }
