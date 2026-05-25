"""db_admin_readonly.py — db-admin DB 읽기 전용 접근 서비스.

목적:
    raw-batch export 시 컨텍스트 파일 생성에 필요한 데이터를 db-admin DB에서 읽는다.
    - matching_entries: LLM이 기존 매칭 패턴 학습용
    - categories: LLM 분류 참조용 트리
    - keywords: 자동완성/검색 어휘 사전

읽기 전용 원칙:
    이 모듈은 db-admin DB에 절대 쓰지 않는다.
    bulk_lookup_hit_keys() 도 hit_count/last_used_at 갱신을 하지 않는다.

패키지 충돌 회피:
    db-admin ORM 모델을 직접 import하지 않고 raw SQLAlchemy text 쿼리를 사용한다.
"""
from __future__ import annotations

from threading import Lock
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_DB_ADMIN_ENGINE_LOCK = Lock()
_db_admin_engine: Optional[Engine] = None


def _get_db_admin_engine() -> Engine:
    """db-admin DB 엔진 싱글턴. 첫 호출 시 config.DB_ADMIN_DATABASE_URL로 생성."""
    global _db_admin_engine
    if _db_admin_engine is None:
        with _DB_ADMIN_ENGINE_LOCK:
            if _db_admin_engine is None:
                import config

                url = config.DB_ADMIN_DATABASE_URL
                connect_args = (
                    {"check_same_thread": False} if url.startswith("sqlite") else {}
                )
                _db_admin_engine = create_engine(url, connect_args=connect_args)
    return _db_admin_engine


def reset_db_admin_engine(new_engine: Optional[Engine] = None) -> None:
    """테스트에서 db-admin 엔진을 교체하거나 초기화할 때 사용.

    new_engine=None이면 기존 엔진 dispose() 후 None으로 재설정.
    new_engine이 지정되면 그 엔진으로 교체.
    """
    global _db_admin_engine
    with _DB_ADMIN_ENGINE_LOCK:
        if _db_admin_engine is not None and new_engine is None:
            _db_admin_engine.dispose()
        _db_admin_engine = new_engine


def get_db_admin_session() -> Iterator[Session]:
    """FastAPI 의존성 — db-admin 읽기 전용 세션 주입.

    테스트에서는 app.dependency_overrides[get_db_admin_session]으로 교체 가능.
    """
    engine = _get_db_admin_engine()
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


def bulk_lookup_hit_keys(session: Session, match_keys: list[str]) -> set[str]:
    """match_key 목록 중 matching_entries에 존재하는(hit) 키 집합을 반환.

    읽기 전용 — hit_count, last_used_at을 갱신하지 않는다.
    SQLite IN 절 제한(999개) 대응을 위해 900개씩 배치 처리한다.
    """
    if not match_keys:
        return set()

    _BATCH = 900
    hit_keys: set[str] = set()

    for i in range(0, len(match_keys), _BATCH):
        chunk = match_keys[i : i + _BATCH]
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


def get_all_matching_entries(session: Session) -> list[dict]:
    """matching_entries 전량 조회.

    LLM이 기존 매칭 패턴을 학습할 수 있도록 context/matching_entries.jsonl 생성에 사용.
    """
    rows = session.execute(
        text(
            "SELECT id, match_key, brand, name_core, pack_qty, pack_unit, "
            "canonical_product_id, category_id, keyword_ids, confidence, source, "
            "created_at, updated_at, last_used_at, hit_count, notes "
            "FROM matching_entries ORDER BY id"
        )
    ).fetchall()
    columns = [
        "id", "match_key", "brand", "name_core", "pack_qty", "pack_unit",
        "canonical_product_id", "category_id", "keyword_ids", "confidence",
        "source", "created_at", "updated_at", "last_used_at", "hit_count", "notes",
    ]
    result = []
    for row in rows:
        d = dict(zip(columns, row))
        # keyword_ids: JSON 문자열인 경우 파싱
        if isinstance(d.get("keyword_ids"), str):
            import json
            try:
                d["keyword_ids"] = json.loads(d["keyword_ids"])
            except Exception:
                pass
        # datetime 필드 → ISO 문자열
        for dt_col in ("created_at", "updated_at", "last_used_at"):
            v = d.get(dt_col)
            if v is not None and hasattr(v, "isoformat"):
                d[dt_col] = v.isoformat()
            elif v is not None:
                d[dt_col] = str(v)
        result.append(d)
    return result


def get_all_categories(session: Session) -> list[dict]:
    """categories 전량 조회.

    LLM이 분류 시 참조할 수 있도록 context/categories.yaml 생성에 사용.
    """
    rows = session.execute(
        text(
            "SELECT id, name, parent_id, depth, sort_order, icon, is_active "
            "FROM categories ORDER BY depth, sort_order, id"
        )
    ).fetchall()
    columns = ["id", "name", "parent_id", "depth", "sort_order", "icon", "is_active"]
    return [dict(zip(columns, row)) for row in rows]


def get_all_keywords(session: Session) -> list[dict]:
    """keywords 전량 조회.

    LLM이 자동완성/검색 어휘를 참조할 수 있도록 context/keywords.yaml 생성에 사용.
    """
    rows = session.execute(
        text(
            "SELECT id, word, synonyms, category_id, search_count, is_active "
            "FROM keywords ORDER BY search_count DESC, word"
        )
    ).fetchall()
    columns = ["id", "word", "synonyms", "category_id", "search_count", "is_active"]
    result = []
    for row in rows:
        d = dict(zip(columns, row))
        if isinstance(d.get("synonyms"), str):
            import json
            try:
                d["synonyms"] = json.loads(d["synonyms"])
            except Exception:
                pass
        result.append(d)
    return result
