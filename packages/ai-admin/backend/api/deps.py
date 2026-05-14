"""FastAPI 공용 의존성 — DB 세션 주입.

테스트에서는 `app.dependency_overrides[get_db_session]`로 in-memory DB 세션을
주입할 수 있다.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from storage.database import get_default_database


def get_db_session() -> Iterator[Session]:
    db = get_default_database()
    session = db.session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
