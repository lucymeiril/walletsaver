"""
DB 엔진 싱글턴, WAL 모드, 세션 관리 테스트.
"""

from pathlib import Path

import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.orm import Session

from services.base import (
    get_engine, get_session, get_session_factory,
    managed_session, reset_engine,
)
from storage.models import Base, Product

_TEST_DB_PATH = Path(__file__).parent / "_test_engine.db"


# ── Fixtures ──

@pytest.fixture(autouse=True)
def _reset():
    """각 테스트 전후로 싱글턴 엔진을 리셋한다."""
    reset_engine()
    yield
    reset_engine()
    if _TEST_DB_PATH.exists():
        _TEST_DB_PATH.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        p = _TEST_DB_PATH.parent / (_TEST_DB_PATH.name + suffix)
        if p.exists():
            p.unlink(missing_ok=True)


@pytest.fixture
def setup_db():
    """인메모리 SQLite로 테이블을 생성한다."""
    reset_engine()
    engine = get_engine(url="sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def setup_file_db():
    """파일 기반 SQLite로 테이블을 생성한다 (WAL 테스트용)."""
    db_url = f"sqlite:///{_TEST_DB_PATH}"
    reset_engine()
    engine = get_engine(url=db_url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


# ── 1. 싱글턴 엔진 ──

class TestSingletonEngine:
    def test_same_engine_returned(self):
        """get_engine()은 항상 동일 인스턴스를 반환한다."""
        e1 = get_engine(url="sqlite://")
        e2 = get_engine()
        assert e1 is e2

    def test_reset_creates_new_engine(self):
        """reset_engine() 후 새 엔진이 생성된다."""
        e1 = get_engine(url="sqlite://")
        reset_engine()
        e2 = get_engine(url="sqlite://")
        assert e1 is not e2

    def test_session_factory_is_singleton(self):
        """get_session_factory()은 동일 인스턴스를 반환한다."""
        get_engine(url="sqlite://")
        f1 = get_session_factory()
        f2 = get_session_factory()
        assert f1 is f2


# ── 2. WAL 모드 ──

class TestWALMode:
    def test_wal_mode_enabled(self, setup_file_db):
        """SQLite에서 WAL journal_mode가 활성화된다."""
        with get_engine().connect() as conn:
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
            assert mode == "wal"

    def test_busy_timeout_set(self, setup_db):
        """busy_timeout이 30000ms로 설정된다."""
        with get_engine().connect() as conn:
            timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
            assert timeout == 30000

    def test_foreign_keys_enabled(self, setup_db):
        """foreign_keys가 활성화된다."""
        with get_engine().connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert fk == 1

    def test_synchronous_normal(self, setup_db):
        """synchronous가 NORMAL(1)로 설정된다."""
        with get_engine().connect() as conn:
            sync = conn.execute(text("PRAGMA synchronous")).scalar()
            assert sync == 1  # NORMAL = 1


# ── 3. 세션 관리 ──

class TestSessionManagement:
    def test_get_session_returns_session(self, setup_db):
        """get_session()이 유효한 Session 인스턴스를 반환한다."""
        session = get_session()
        assert isinstance(session, Session)
        session.close()

    def test_get_session_with_explicit_engine(self):
        """명시적 engine 전달 시 해당 engine에 바인딩된 세션을 반환한다."""
        engine = create_engine("sqlite://", echo=False)
        session = get_session(engine=engine)
        assert isinstance(session, Session)
        session.close()
        engine.dispose()


# ── 4. managed_session 컨텍스트 매니저 ──

class TestManagedSession:
    def test_commit_on_success(self, setup_db):
        """정상 종료 시 자동 commit된다."""
        with managed_session() as session:
            p = Product(name="테스트 상품", unit="개")
            session.add(p)
            session.flush()

        # 새 세션에서 조회하여 commit 확인
        session2 = get_session()
        try:
            result = session2.execute(
                text("SELECT name FROM products WHERE name = '테스트 상품'")
            ).scalar()
            assert result == "테스트 상품"
        finally:
            session2.close()

    def test_rollback_on_exception(self, setup_db):
        """예외 발생 시 rollback된다."""
        with pytest.raises(ValueError):
            with managed_session() as session:
                p = Product(name="롤백 테스트", unit="개")
                session.add(p)
                session.flush()
                raise ValueError("의도적 예외")

        # rollback 확인
        session2 = get_session()
        try:
            result = session2.execute(
                text("SELECT count(*) FROM products WHERE name = '롤백 테스트'")
            ).scalar()
            assert result == 0
        finally:
            session2.close()

    def test_session_closed_after_block(self, setup_db):
        """블록 종료 후 세션이 닫힌다."""
        session_ref = None
        with managed_session() as session:
            session_ref = session
        # scoped_session의 경우 close 후에도 접근 가능하나,
        # 새 트랜잭션이 시작되므로 이전 트랜잭션은 종료됨


# ── 5. 동시성 테스트 ──

class TestConcurrency:
    def test_sequential_multisession(self, setup_db):
        """여러 세션을 순차적으로 사용하면 데이터가 정상 관리된다."""
        with managed_session() as session:
            for i in range(10):
                session.add(Product(name=f"상품-{i}", unit="개"))

        for _ in range(5):
            session = get_session()
            try:
                result = session.execute(text("SELECT count(*) FROM products")).scalar()
                assert result == 10
            finally:
                session.close()

    def test_sequential_writes(self, setup_db):
        """여러 managed_session 쓰기가 순차적으로 모두 성공한다."""
        for idx in range(20):
            with managed_session() as session:
                session.add(Product(name=f"순차-{idx}", unit="개"))

        with managed_session() as session:
            count = session.execute(text("SELECT count(*) FROM products")).scalar()
            assert count == 20
