"""SQLAlchemy 엔진/세션 팩토리.

기본은 로컬 SQLite 파일이며, `AI_CONTROL_DATABASE_URL` 환경변수로 Postgres 등
다른 DB를 지정할 수 있다. 테이블 정의는 SQLite와 Postgres 모두에서 동작하도록
JSON/Text/DateTime/Integer/String 만 사용한다.
"""
from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    """엔진 + 세션 팩토리 묶음. 테스트에서는 in-memory URL과 함께 새로 생성한다."""

    def __init__(self, url: str, *, echo: bool = False, future: bool = True) -> None:
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self.url = url
        self.engine: Engine = create_engine(
            url,
            echo=echo,
            future=future,
            connect_args=connect_args,
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=future,
        )

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def session(self) -> Session:
        return self._session_factory()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """commit/rollback 자동 처리하는 세션 컨텍스트."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


_default_db: Optional[Database] = None
_default_db_lock = Lock()


def create_database(url: str, *, create_tables: bool = True) -> Database:
    db = Database(url)
    if create_tables:
        db.create_all()
    return db


def get_default_database() -> Database:
    """프로세스 내 기본 control DB 인스턴스. 설정의 URL을 사용한다."""
    global _default_db
    if _default_db is None:
        with _default_db_lock:
            if _default_db is None:
                from config import settings

                _default_db = create_database(settings.CONTROL_DATABASE_URL)
    return _default_db


def reset_default_database() -> None:
    """테스트에서 환경변수를 바꾼 뒤 기본 DB를 다시 만들기 위해 사용한다."""
    global _default_db
    with _default_db_lock:
        if _default_db is not None:
            _default_db.dispose()
        _default_db = None
