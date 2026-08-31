"""Server-owned account SQLite database for web-api.

This schema intentionally contains only user-owned writable state. Product and
price data live in replaceable read-only snapshots and are referenced by numeric
product_id without cross-file foreign keys.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import scoped_session, sessionmaker


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ACCOUNT_DB = _BACKEND_ROOT / "storage" / "accounts.sqlite"


class AccountDatabase:
    def __init__(self, path: str | Path | None = None):
        configured = str(path or os.getenv("WALLETSAVIOR_ACCOUNT_DB", "")).strip()
        self.path = (
            Path(configured).expanduser()
            if configured
            else _DEFAULT_ACCOUNT_DB
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
            cursor.execute("PRAGMA foreign_keys=ON")
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
        statements = (
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                hashed_password TEXT,
                nickname TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL DEFAULT 'user',
                profile_image TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                bio TEXT,
                preferences TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS oauth_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                access_token TEXT,
                refresh_token TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(provider, provider_user_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, product_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS price_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id TEXT NOT NULL,
                target_price REAL NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, product_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cart_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id INTEGER,
                item_name TEXT NOT NULL,
                item_price REAL NOT NULL,
                item_image_url TEXT,
                store_name TEXT,
                source_url TEXT,
                original_price REAL,
                discount_rate REAL,
                category TEXT,
                quantity INTEGER NOT NULL DEFAULT 1,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_cart_items_user
            ON cart_items(user_id, added_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS wishlist_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                product_id INTEGER,
                item_name TEXT NOT NULL,
                target_price REAL,
                item_image_url TEXT,
                store_name TEXT,
                category TEXT,
                price_at_add REAL,
                current_price REAL,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notify_on_drop INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_wishlist_items_user
            ON wishlist_items(user_id, added_at)
            """,
            """
            CREATE TABLE IF NOT EXISTS user_activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                activity_type TEXT NOT NULL,
                target_type TEXT,
                target_id TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS ix_user_activities_user
            ON user_activities(user_id, created_at)
            """,
        )
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))

    def close(self) -> None:
        self.SessionLocal.remove()
        self.engine.dispose()
