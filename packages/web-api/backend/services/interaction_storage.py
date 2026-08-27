"""Server-owned interaction SQLite database for external hotdeals."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import scoped_session, sessionmaker


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_INTERACTION_DB = _BACKEND_ROOT / "storage" / "interactions.sqlite"


class InteractionDatabase:
    def __init__(self, path: str | Path | None = None):
        configured = str(path or os.getenv("WALLETSAVIOR_INTERACTION_DB", "")).strip()
        self.path = (
            Path(configured).expanduser()
            if configured
            else _DEFAULT_INTERACTION_DB
        ).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{self.path.as_posix()}",
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine, "connect")
        def _configure_sqlite(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

        with self.engine.begin() as connection:
            connection.execute(text("PRAGMA journal_mode=WAL"))

        self.SessionLocal = scoped_session(
            sessionmaker(bind=self.engine, expire_on_commit=False)
        )
        self.initialize()

    def initialize(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                """
                CREATE TABLE IF NOT EXISTS external_hotdeal_votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hotdeal_id INTEGER NOT NULL,
                    identity_key TEXT NOT NULL,
                    vote_type TEXT NOT NULL CHECK(vote_type IN ('hot', 'not')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(hotdeal_id, identity_key)
                )
                """
            ))
            connection.execute(text(
                """
                CREATE INDEX IF NOT EXISTS ix_external_hotdeal_votes_hotdeal
                ON external_hotdeal_votes(hotdeal_id, vote_type)
                """
            ))
            connection.execute(text(
                """
                CREATE TABLE IF NOT EXISTS external_hotdeal_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hotdeal_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT,
                    UNIQUE(hotdeal_id, user_id)
                )
                """
            ))
            connection.execute(text(
                """
                CREATE TABLE IF NOT EXISTS external_hotdeal_comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    hotdeal_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            ))
            connection.execute(text(
                """
                CREATE INDEX IF NOT EXISTS ix_external_hotdeal_comments_hotdeal
                ON external_hotdeal_comments(hotdeal_id, created_at, id)
                """
            ))
            connection.execute(text(
                """
                CREATE INDEX IF NOT EXISTS ix_external_hotdeal_comments_user
                ON external_hotdeal_comments(user_id, created_at)
                """
            ))

    def vote_counts(self, hotdeal_id: int) -> tuple[int, int]:
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT vote_type, COUNT(*) AS count "
                    "FROM external_hotdeal_votes WHERE hotdeal_id=:hotdeal_id "
                    "GROUP BY vote_type"
                ),
                {"hotdeal_id": hotdeal_id},
            ).mappings().all()
        counts = {row["vote_type"]: int(row["count"]) for row in rows}
        return counts.get("hot", 0), counts.get("not", 0)

    def clear_vote(self, hotdeal_id: int, identity_key: str) -> dict:
        """Remove the caller's vote without needing the previous vote type."""
        with self.SessionLocal() as session:
            session.execute(
                text(
                    "DELETE FROM external_hotdeal_votes "
                    "WHERE hotdeal_id=:hotdeal_id AND identity_key=:identity_key"
                ),
                {"hotdeal_id": hotdeal_id, "identity_key": identity_key},
            )
            session.commit()
        hot, not_ = self.vote_counts(hotdeal_id)
        return {"votes_hot": hot, "votes_not": not_, "user_vote": None}

    def toggle_vote(self, hotdeal_id: int, vote_type: str, identity_key: str) -> dict:
        now = datetime.utcnow().isoformat()
        with self.SessionLocal() as session:
            existing = session.execute(
                text(
                    "SELECT id, vote_type FROM external_hotdeal_votes "
                    "WHERE hotdeal_id=:hotdeal_id AND identity_key=:identity_key"
                ),
                {"hotdeal_id": hotdeal_id, "identity_key": identity_key},
            ).mappings().first()

            if existing and existing["vote_type"] == vote_type:
                session.execute(
                    text("DELETE FROM external_hotdeal_votes WHERE id=:id"),
                    {"id": existing["id"]},
                )
                user_vote = None
            elif existing:
                session.execute(
                    text(
                        "UPDATE external_hotdeal_votes "
                        "SET vote_type=:vote_type, updated_at=:updated_at WHERE id=:id"
                    ),
                    {
                        "vote_type": vote_type,
                        "updated_at": now,
                        "id": existing["id"],
                    },
                )
                user_vote = vote_type
            else:
                session.execute(
                    text(
                        "INSERT INTO external_hotdeal_votes "
                        "(hotdeal_id, identity_key, vote_type, created_at, updated_at) "
                        "VALUES (:hotdeal_id, :identity_key, :vote_type, :created_at, :updated_at)"
                    ),
                    {
                        "hotdeal_id": hotdeal_id,
                        "identity_key": identity_key,
                        "vote_type": vote_type,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                user_vote = vote_type
            session.commit()

        hot, not_ = self.vote_counts(hotdeal_id)
        return {"votes_hot": hot, "votes_not": not_, "user_vote": user_vote}

    def comment_count(self, hotdeal_id: int) -> int:
        with self.SessionLocal() as session:
            return int(session.execute(
                text(
                    "SELECT COUNT(*) FROM external_hotdeal_comments "
                    "WHERE hotdeal_id=:hotdeal_id"
                ),
                {"hotdeal_id": int(hotdeal_id)},
            ).scalar_one())

    def list_comments(self, hotdeal_id: int) -> list[dict]:
        with self.SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT id, hotdeal_id, user_id, author, content, created_at, updated_at "
                    "FROM external_hotdeal_comments "
                    "WHERE hotdeal_id=:hotdeal_id "
                    "ORDER BY created_at ASC, id ASC"
                ),
                {"hotdeal_id": int(hotdeal_id)},
            ).mappings().all()
        return [dict(row) for row in rows]

    def add_comment(self, hotdeal_id: int, user_id: int, author: str, content: str) -> dict:
        now = datetime.utcnow().isoformat()
        with self.SessionLocal() as session:
            session.execute(
                text(
                    "INSERT INTO external_hotdeal_comments "
                    "(hotdeal_id, user_id, author, content, created_at, updated_at) "
                    "VALUES (:hotdeal_id, :user_id, :author, :content, :now, :now)"
                ),
                {
                    "hotdeal_id": int(hotdeal_id),
                    "user_id": int(user_id),
                    "author": str(author).strip() or "사용자",
                    "content": str(content).strip(),
                    "now": now,
                },
            )
            comment_id = int(session.execute(text("SELECT last_insert_rowid()")).scalar_one())
            session.commit()
        return {
            "id": comment_id,
            "hotdeal_id": int(hotdeal_id),
            "user_id": int(user_id),
            "author": str(author).strip() or "사용자",
            "content": str(content).strip(),
            "created_at": now,
            "updated_at": now,
        }

    def delete_comment(self, hotdeal_id: int, comment_id: int, user_id: int) -> str:
        """Delete one comment if it belongs to the authenticated user."""
        with self.SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT user_id FROM external_hotdeal_comments "
                    "WHERE id=:comment_id AND hotdeal_id=:hotdeal_id"
                ),
                {"comment_id": int(comment_id), "hotdeal_id": int(hotdeal_id)},
            ).mappings().first()
            if row is None:
                return "not_found"
            if int(row["user_id"]) != int(user_id):
                return "forbidden"
            session.execute(
                text(
                    "DELETE FROM external_hotdeal_comments "
                    "WHERE id=:comment_id AND hotdeal_id=:hotdeal_id"
                ),
                {"comment_id": int(comment_id), "hotdeal_id": int(hotdeal_id)},
            )
            session.commit()
        return "deleted"

    def report(self, hotdeal_id: int, user_id: int, reason: str) -> dict:
        now = datetime.utcnow().isoformat()
        with self.SessionLocal() as session:
            row = session.execute(
                text(
                    "SELECT id FROM external_hotdeal_reports "
                    "WHERE hotdeal_id=:hotdeal_id AND user_id=:user_id"
                ),
                {"hotdeal_id": hotdeal_id, "user_id": user_id},
            ).mappings().first()
            if row:
                report_id = int(row["id"])
                session.execute(
                    text(
                        "UPDATE external_hotdeal_reports "
                        "SET reason=:reason, status='open', updated_at=:updated_at, resolved_at=NULL "
                        "WHERE id=:id"
                    ),
                    {"reason": reason, "updated_at": now, "id": report_id},
                )
                updated = True
            else:
                session.execute(
                    text(
                        "INSERT INTO external_hotdeal_reports "
                        "(hotdeal_id, user_id, reason, status, created_at, updated_at) "
                        "VALUES (:hotdeal_id, :user_id, :reason, 'open', :created_at, :updated_at)"
                    ),
                    {
                        "hotdeal_id": hotdeal_id,
                        "user_id": user_id,
                        "reason": reason,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                report_id = int(session.execute(
                    text(
                        "SELECT id FROM external_hotdeal_reports "
                        "WHERE hotdeal_id=:hotdeal_id AND user_id=:user_id"
                    ),
                    {"hotdeal_id": hotdeal_id, "user_id": user_id},
                ).scalar_one())
                updated = False
            session.commit()
        return {"id": report_id, "status": "open", "updated": updated}

    def close(self) -> None:
        self.SessionLocal.remove()
        self.engine.dispose()
