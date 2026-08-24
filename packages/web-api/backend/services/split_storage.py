"""Route public product reads to a derived SQLite snapshot.

The current web API still has low-volume private/write features (favorites,
alerts, hotdeal voting, etc.) that belong to the main application store. Product
catalog, category, mart-price and price-history reads are safe to serve from the
public snapshot instead. This proxy keeps the existing route surface intact
while enforcing that split at the storage boundary.
"""
from __future__ import annotations

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
        path = Path(db_path).resolve().as_posix()
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
    """Delegate selected public reads to ``public`` and everything else to main."""

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

    def __init__(self, *, main: Any, public: Any | None) -> None:
        self.main = main
        self.public = public

    @property
    def SessionLocal(self):
        """Direct category/product ORM reads in products.py use the public DB."""
        target = self.public or self.main
        return getattr(target, "SessionLocal", None)

    @property
    def public_enabled(self) -> bool:
        return self.public is not None

    def __getattr__(self, name: str):
        if name in self.PUBLIC_READ_METHODS and self.public is not None:
            public_attr = getattr(self.public, name, None)
            if public_attr is not None:
                return public_attr
        return getattr(self.main, name)
