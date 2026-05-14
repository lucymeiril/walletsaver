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
from sqlalchemy import inspect, text
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
        self._ensure_provider_config_columns()
        self._ensure_product_match_columns()

    def _ensure_provider_config_columns(self) -> None:
        """Add operator-tunable provider limit columns to existing local DBs."""
        defaults = {
            "max_provider_calls_per_minute": "INTEGER NOT NULL DEFAULT 5",
            "max_provider_calls_per_day": "INTEGER NOT NULL DEFAULT 300",
            "provider_retry_max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "provider_retry_min_delay_seconds": "FLOAT NOT NULL DEFAULT 10.0",
            "provider_retry_max_delay_seconds": "FLOAT NOT NULL DEFAULT 60.0",
        }
        inspector = inspect(self.engine)
        if "provider_configs" not in inspector.get_table_names():
            return
        existing = {column["name"] for column in inspector.get_columns("provider_configs")}
        with self.engine.begin() as connection:
            for column_name, column_type in defaults.items():
                if column_name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE provider_configs ADD COLUMN {column_name} {column_type}")
                    )
            connection.execute(
                text(
                    "UPDATE provider_configs "
                    "SET min_request_interval_seconds = 12.0 "
                    "WHERE min_request_interval_seconds < 12.0"
                )
            )

    def _ensure_product_match_columns(self) -> None:
        """Add strict source-specific match columns to existing local control DBs."""
        defaults = {
            "target_type": "VARCHAR(40) NOT NULL DEFAULT 'canonical_product'",
            "target_id": "VARCHAR(120)",
            "allowed_title_patterns": "JSON NOT NULL DEFAULT '[]'",
            "normalized_title_variants": "JSON NOT NULL DEFAULT '[]'",
            "blocked_title_patterns": "JSON NOT NULL DEFAULT '[]'",
            "package_signature": "VARCHAR(255)",
            "package_signature_required": "BOOLEAN NOT NULL DEFAULT 1",
            "source_product_id_history": "JSON NOT NULL DEFAULT '[]'",
            "approved_by": "VARCHAR(120)",
            "approved_at": "DATETIME",
            "version": "INTEGER NOT NULL DEFAULT 1",
            "is_active": "BOOLEAN NOT NULL DEFAULT 1",
            "disabled_reason": "TEXT",
        }
        inspector = inspect(self.engine)
        if "product_matches" not in inspector.get_table_names():
            return
        existing = {column["name"] for column in inspector.get_columns("product_matches")}
        with self.engine.begin() as connection:
            for column_name, column_type in defaults.items():
                if column_name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE product_matches ADD COLUMN {column_name} {column_type}")
                    )

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
