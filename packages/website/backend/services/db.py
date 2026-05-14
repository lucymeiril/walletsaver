"""DB session management for the website backend.

Provides managed_session and engine management that connects to the shared
walletguardian.db from db-admin. Re-implements the session pattern from
db-admin's services.base to avoid namespace collisions between packages.
"""
import os
import sys
import logging
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool, NullPool

logger = logging.getLogger(__name__)

# db-admin path for storage.models access
_db_admin_backend = str(Path(__file__).resolve().parents[3] / "db-admin" / "backend")
if _db_admin_backend not in sys.path:
    sys.path.insert(0, _db_admin_backend)

from storage.models import Base  # noqa: E402

_DEFAULT_DB_URL = f"sqlite:///{Path(_db_admin_backend) / 'walletguardian.db'}"

_engine = None
_session_factory = None
_ScopedSession = None


def get_engine(url: str | None = None):
    """싱글턴 엔진 — SQLite 기본, 테스트 시 :memory: 지원."""
    global _engine
    if _engine is not None:
        return _engine

    if url is None:
        url = os.getenv("DATABASE_URL", _DEFAULT_DB_URL)

    connect_args: dict = {}
    pool_kwargs: dict = {}
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        connect_args["check_same_thread"] = False
        is_memory = url in ("sqlite://", "sqlite:///:memory:")
        pool_kwargs["poolclass"] = StaticPool if is_memory else NullPool

    _engine = create_engine(url, echo=False, connect_args=connect_args, **pool_kwargs)

    if is_sqlite:
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    logger.info("Website DB engine created: %s", url.split("@")[-1])
    return _engine


def get_session_factory():
    global _session_factory, _ScopedSession
    if _ScopedSession is not None:
        return _ScopedSession
    engine = get_engine()
    _session_factory = sessionmaker(bind=engine)
    _ScopedSession = scoped_session(_session_factory)
    return _ScopedSession


def get_session(engine=None):
    if engine is not None:
        return sessionmaker(bind=engine)()
    factory = get_session_factory()
    return factory()


@contextmanager
def managed_session():
    """세션 컨텍스트 매니저 — commit/rollback/close 자동 처리."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine():
    """엔진 리셋 — 테스트 간 DB 교체 시 사용."""
    global _engine, _session_factory, _ScopedSession
    if _ScopedSession is not None:
        _ScopedSession.remove()
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _ScopedSession = None
