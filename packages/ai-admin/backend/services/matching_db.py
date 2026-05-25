"""matching_db.py — db-admin matching_entries 읽기 전용 접근 서비스.

목적:
    외부 분류 export 파이프라인에서 raw_crawl_records의 match_key hit 여부를 판단.

"miss만 export" 원칙:
    이 모듈은 hit 여부 확인만 하며 hit_count/last_used_at을 절대 갱신하지 않는다.
    bulk_lookup_hit_keys()가 반환하지 않은 키가 export 대상이다.

패키지 충돌 회피:
    ai-admin과 db-admin 모두 storage/ 패키지를 가진다. 이름 충돌을 피하기 위해
    db-admin ORM 모델을 직접 import하지 않고 raw SQLAlchemy text 쿼리를 사용한다.
"""
from __future__ import annotations

from threading import Lock
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_MATCHING_ENGINE_LOCK = Lock()
_matching_engine: Optional[Engine] = None


def _get_matching_engine() -> Engine:
    """db-admin matching DB 엔진 싱글턴. 첫 호출 시 settings.DB_ADMIN_DATABASE_URL로 생성."""
    global _matching_engine
    if _matching_engine is None:
        with _MATCHING_ENGINE_LOCK:
            if _matching_engine is None:
                from config import settings

                url = settings.DB_ADMIN_DATABASE_URL
                connect_args = (
                    {"check_same_thread": False} if url.startswith("sqlite") else {}
                )
                _matching_engine = create_engine(url, connect_args=connect_args)
    return _matching_engine


def reset_matching_engine(new_engine: Optional[Engine] = None) -> None:
    """테스트에서 matching DB 엔진을 교체하거나 초기화할 때 사용.

    new_engine=None 이면 기존 엔진을 dispose() 하고 None으로 재설정한다.
    new_engine이 지정되면 기존 엔진 대신 이것을 사용한다.
    """
    global _matching_engine
    with _MATCHING_ENGINE_LOCK:
        if _matching_engine is not None and new_engine is None:
            _matching_engine.dispose()
        _matching_engine = new_engine


def get_matching_session() -> Iterator[Session]:
    """FastAPI 의존성 — matching DB (db-admin) 세션 주입.

    테스트에서는 app.dependency_overrides[get_matching_session]으로 교체 가능.
    """
    engine = _get_matching_engine()
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def bulk_lookup_hit_keys(session: Session, match_keys: list[str]) -> set[str]:
    """match_key 목록 중 matching_entries에 존재하는(hit) 키 집합을 반환.

    읽기 전용 — hit_count, last_used_at을 갱신하지 않는다.
    "miss만 export" 원칙: 이 함수가 반환하지 않은 키가 외부 분류 export 대상이다.

    SQLite IN 절 제한(999개) 대응을 위해 900개씩 배치 처리한다.
    """
    if not match_keys:
        return set()

    _BATCH = 900
    hit_keys: set[str] = set()

    for i in range(0, len(match_keys), _BATCH):
        chunk = match_keys[i : i + _BATCH]
        # named placeholder: :k0, :k1, ... (SQLite/Postgres 모두 호환)
        placeholders = ", ".join(f":k{j}" for j in range(len(chunk)))
        params = {f"k{j}": k for j, k in enumerate(chunk)}
        rows = session.execute(
            text(
                f"SELECT match_key FROM matching_entries "
                f"WHERE match_key IN ({placeholders})"
            ),
            params,
        ).fetchall()
        for row in rows:
            hit_keys.add(row[0])

    return hit_keys
