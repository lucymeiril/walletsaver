"""서비스 공통 세션 헬퍼"""
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from storage.models import Base

import logging

logger = logging.getLogger("db.session")


@lru_cache(maxsize=1)
def get_engine(url=None):
    if url is None:
        from config import settings
        url = settings.DATABASE_URL
    connect_args = {}
    pool_kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        from sqlalchemy.pool import StaticPool
        pool_kwargs["poolclass"] = StaticPool
    else:
        from config import settings
        pool_kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
    engine = create_engine(url, echo=False, connect_args=connect_args, **pool_kwargs)

    # Set SQLite PRAGMAs on every new connection
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
            logger.debug("SQLite PRAGMAs set (WAL, busy_timeout=5000)")

    return engine


_SessionFactory = None


def get_session(engine=None) -> Session:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=engine or get_engine())
    return _SessionFactory()
