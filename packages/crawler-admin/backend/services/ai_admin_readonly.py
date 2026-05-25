"""ai_admin_readonly.py — ai-admin control DB 읽기 전용 접근 서비스.

목적:
    raw-batch export 시 ai-admin control DB의 raw_crawl_records를 읽어
    miss 항목을 추출한다.

읽기 전용 원칙:
    이 모듈은 ai-admin DB에 절대 쓰지 않는다.

패키지 충돌 회피:
    ai-admin ORM 모델을 직접 import하지 않고 raw SQLAlchemy text 쿼리를 사용한다.
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_AI_ADMIN_ENGINE_LOCK = Lock()
_ai_admin_engine: Optional[Engine] = None


def _get_ai_admin_engine() -> Engine:
    """ai-admin control DB 엔진 싱글턴. 첫 호출 시 config.AI_ADMIN_DATABASE_URL로 생성."""
    global _ai_admin_engine
    if _ai_admin_engine is None:
        with _AI_ADMIN_ENGINE_LOCK:
            if _ai_admin_engine is None:
                import config

                url = config.AI_ADMIN_DATABASE_URL
                connect_args = (
                    {"check_same_thread": False} if url.startswith("sqlite") else {}
                )
                _ai_admin_engine = create_engine(url, connect_args=connect_args)
    return _ai_admin_engine


def reset_ai_admin_engine(new_engine: Optional[Engine] = None) -> None:
    """테스트에서 ai-admin 엔진을 교체하거나 초기화할 때 사용.

    new_engine=None이면 기존 엔진 dispose() 후 None으로 재설정.
    new_engine이 지정되면 그 엔진으로 교체.
    """
    global _ai_admin_engine
    with _AI_ADMIN_ENGINE_LOCK:
        if _ai_admin_engine is not None and new_engine is None:
            _ai_admin_engine.dispose()
        _ai_admin_engine = new_engine


def get_ai_admin_session() -> Iterator[Session]:
    """FastAPI 의존성 — ai-admin control DB 읽기 전용 세션 주입.

    테스트에서는 app.dependency_overrides[get_ai_admin_session]으로 교체 가능.
    """
    engine = _get_ai_admin_engine()
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_records_by_batch_ids(
    session: Session,
    batch_ids: list[str],
    include_all: bool = False,
) -> list[dict[str, Any]]:
    """지정한 batch_id 목록에 속하는 raw_crawl_records 조회.

    Args:
        session: ai-admin control DB 세션
        batch_ids: 조회할 배치 ID 목록
        include_all: True이면 모든 records, False이면 batch_ids 필터 적용

    Returns:
        raw_crawl_record 행들의 dict 리스트
        (raw_record_id, batch_id, source_name, raw_title, raw_price,
         crawled_at, raw_payload)
    """
    if not batch_ids and not include_all:
        return []

    columns = [
        "raw_record_id", "batch_id", "source_name",
        "raw_title", "raw_price", "crawled_at", "raw_payload",
    ]

    if include_all or not batch_ids:
        rows = session.execute(
            text(
                "SELECT raw_record_id, batch_id, source_name, "
                "raw_title, raw_price, crawled_at, raw_payload "
                "FROM raw_crawl_records ORDER BY crawled_at ASC"
            )
        ).fetchall()
    else:
        _BATCH = 900
        rows = []
        for i in range(0, len(batch_ids), _BATCH):
            chunk = batch_ids[i : i + _BATCH]
            placeholders = ", ".join(f":b{j}" for j in range(len(chunk)))
            params = {f"b{j}": b for j, b in enumerate(chunk)}
            chunk_rows = session.execute(
                text(
                    f"SELECT raw_record_id, batch_id, source_name, "
                    f"raw_title, raw_price, crawled_at, raw_payload "
                    f"FROM raw_crawl_records "
                    f"WHERE batch_id IN ({placeholders}) "
                    f"ORDER BY crawled_at ASC"
                ),
                params,
            ).fetchall()
            rows.extend(chunk_rows)

    import json as _json

    result = []
    for row in rows:
        d = dict(zip(columns, row))
        # raw_payload: SQLite에서 문자열로 오면 파싱
        if isinstance(d.get("raw_payload"), str):
            try:
                d["raw_payload"] = _json.loads(d["raw_payload"])
            except Exception:
                d["raw_payload"] = {}
        elif d.get("raw_payload") is None:
            d["raw_payload"] = {}
        # crawled_at → ISO 문자열
        v = d.get("crawled_at")
        if v is not None and hasattr(v, "isoformat"):
            d["crawled_at"] = v.isoformat()
        elif v is not None:
            d["crawled_at"] = str(v)
        result.append(d)
    return result
