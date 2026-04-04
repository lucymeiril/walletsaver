"""
서비스 공통 세션 헬퍼 — 싱글턴 엔진 + scoped_session.

왜 싱글턴인가:
    create_engine()은 내부적으로 커넥션 풀을 생성한다.
    매 요청마다 새 엔진을 만들면 풀이 재사용되지 않아
    config.py의 DB_POOL_SIZE 등 설정이 무의미해진다.
    모듈 수준에서 한 번만 생성하고 재사용한다.
"""

import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.pool import StaticPool

from storage.models import Base

logger = logging.getLogger(__name__)

# ── 모듈-레벨 싱글턴 ──
_engine = None
_session_factory = None
_ScopedSession = None


def get_engine(url: str | None = None):
    """
    싱글턴 SQLAlchemy 엔진을 반환한다.

    첫 호출에서 엔진을 생성하고 이후 호출에서는 동일 인스턴스를 반환.
    SQLite: StaticPool + WAL 모드 + busy_timeout 5초
    PostgreSQL: QueuePool + pool_size/max_overflow/pool_recycle
    """
    global _engine
    if _engine is not None:
        return _engine

    if url is None:
        from config import settings
        url = settings.DATABASE_URL

    connect_args: dict = {}
    pool_kwargs: dict = {}
    is_sqlite = url.startswith("sqlite")

    if is_sqlite:
        connect_args["check_same_thread"] = False
        pool_kwargs["poolclass"] = StaticPool
    else:
        from config import settings
        pool_kwargs.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
            pool_pre_ping=True,
        )

    _engine = create_engine(
        url, echo=False, connect_args=connect_args, **pool_kwargs,
    )

    # ── SQLite 전용 PRAGMA 설정 ──
    if is_sqlite:
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # ── PostgreSQL statement timeout ──
    if not is_sqlite:
        @event.listens_for(_engine, "connect")
        def _set_pg_timeout(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET statement_timeout = '30s'")
            cursor.close()

    logger.info("Engine created: %s (pool=%s)", url.split("@")[-1], type(_engine.pool).__name__)
    return _engine


def get_session_factory():
    """scoped_session 팩토리를 반환한다 (스레드 안전)."""
    global _session_factory, _ScopedSession
    if _ScopedSession is not None:
        return _ScopedSession

    engine = get_engine()
    _session_factory = sessionmaker(bind=engine)
    _ScopedSession = scoped_session(_session_factory)
    return _ScopedSession


def get_session(engine=None) -> Session:
    """
    세션을 반환한다.

    하위 호환성을 위해 engine 파라미터를 유지하되,
    기본 호출 시 싱글턴 팩토리에서 세션을 생성한다.
    """
    if engine is not None:
        return sessionmaker(bind=engine)()

    factory = get_session_factory()
    return factory()


@contextmanager
def managed_session():
    """
    세션 컨텍스트 매니저 — commit/rollback/close를 자동 처리.

    사용법:
        with managed_session() as session:
            session.add(product)
            # commit은 블록 종료 시 자동 수행
            # 예외 발생 시 rollback 후 재발생
    """
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
    """
    엔진 및 세션 팩토리를 리셋한다.

    테스트에서 DB를 교체하거나 shutdown 시 사용.
    """
    global _engine, _session_factory, _ScopedSession
    if _ScopedSession is not None:
        _ScopedSession.remove()
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _ScopedSession = None
