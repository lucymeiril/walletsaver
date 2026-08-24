"""Route public product reads to a derived SQLite snapshot.

The current web API still has low-volume private/write features (favorites,
alerts, hotdeal voting, etc.) that belong to the main application store. Product
catalog, category, mart-price and price-history reads are safe to serve from the
public snapshot instead. This proxy keeps the existing route surface intact
while enforcing that split at the storage boundary.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from storage.db import DBStorage


class PublicSnapshotStorage(DBStorage):
    """DBStorage-compatible reader that can never write the public snapshot.

    NullPool is deliberate: on Windows the db-admin process publishes snapshots
    with ``os.replace``. Holding pooled SQLite file handles in the web process
    can prevent that atomic replacement. Every request therefore releases its
    connection fully when the SQLAlchemy Session closes.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).resolve()
        path = self.db_path.as_posix()
        database_url = f"sqlite:///file:{path}?mode=ro&uri=true"
        self.engine = create_engine(
            database_url,
            echo=False,
            connect_args={"timeout": 30, "check_same_thread": False},
            poolclass=NullPool,
            pool_pre_ping=True,
        )

        @event.listens_for(self.engine, "connect")
        def _set_snapshot_pragmas(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA query_only=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        self._session_factory = sessionmaker(bind=self.engine)
        self.SessionLocal = scoped_session(self._session_factory)


class SplitStorage:
    """Delegate selected public reads to ``public`` and everything else to main.

    If the web process starts before the first snapshot exists, ``public`` may
    initially be ``None``. The proxy lazily attaches as soon as the configured
    file appears, so a first-run server restart is not required.
    """

    PUBLIC_READ_METHODS = frozenset(
        {
            "get_products",
            "get_product_detail",
            "search_products",
            "get_mart_deals",
            "get_price_history",
            "get_price_compare",
        }
    )

    def __init__(
        self,
        *,
        main: Any,
        public: Any | None,
        public_db_path: str | Path | None = None,
    ) -> None:
        self.main = main
        self.public = public
        self.public_db_path = Path(public_db_path).resolve() if public_db_path else None
        self._public_lock = threading.Lock()

    def _public_target(self):
        if self.public is not None:
            return self.public
        path = self.public_db_path
        if path is None or not path.is_file():
            return None
        with self._public_lock:
            if self.public is None and path.is_file():
                self.public = PublicSnapshotStorage(path)
        return self.public

    @property
    def SessionLocal(self):
        """Direct category/product ORM reads in products.py prefer the public DB."""
        target = self._public_target() or self.main
        return getattr(target, "SessionLocal", None)

    @property
    def public_enabled(self) -> bool:
        return self._public_target() is not None

    def __getattr__(self, name: str):
        if name in self.PUBLIC_READ_METHODS:
            public = self._public_target()
            if public is not None:
                public_attr = getattr(public, name, None)
                if public_attr is not None:
                    return public_attr
        return getattr(self.main, name)
