"""Persist hotdeal reports through the injected main DB storage."""
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


class HotdealReportStore:
    def __init__(self, storage):
        self._session_factory = getattr(storage, "SessionLocal", None)
        if self._session_factory is None:
            raise RuntimeError("main DB session factory is unavailable")

    def report(self, hotdeal_id: int, user_id: int, reason: str) -> dict | None:
        now = datetime.utcnow()
        with self._session_factory() as session:
            exists = session.execute(
                text("SELECT id FROM hotdeal_prices WHERE id = :hotdeal_id"),
                {"hotdeal_id": hotdeal_id},
            ).first()
            if exists is None:
                return None

            current = session.execute(
                text(
                    "SELECT id, status FROM hotdeal_reports "
                    "WHERE hotdeal_id = :hotdeal_id AND user_id = :user_id"
                ),
                {"hotdeal_id": hotdeal_id, "user_id": user_id},
            ).first()
            if current is not None:
                session.execute(
                    text(
                        "UPDATE hotdeal_reports SET reason = :reason, status = 'open', "
                        "updated_at = :updated_at, resolved_at = NULL WHERE id = :id"
                    ),
                    {"reason": reason, "updated_at": now, "id": current.id},
                )
                session.commit()
                return {"id": int(current.id), "status": "open", "updated": True}

            try:
                session.execute(
                    text(
                        "INSERT INTO hotdeal_reports "
                        "(hotdeal_id, user_id, reason, status, created_at, updated_at) "
                        "VALUES (:hotdeal_id, :user_id, :reason, 'open', :created_at, :updated_at)"
                    ),
                    {
                        "hotdeal_id": hotdeal_id,
                        "user_id": user_id,
                        "reason": reason,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                session.commit()
            except IntegrityError:
                # 같은 사용자의 동시 중복 신고는 하나로 수렴시킨다.
                session.rollback()

            row = session.execute(
                text(
                    "SELECT id, status FROM hotdeal_reports "
                    "WHERE hotdeal_id = :hotdeal_id AND user_id = :user_id"
                ),
                {"hotdeal_id": hotdeal_id, "user_id": user_id},
            ).first()
            if row is None:
                raise RuntimeError("hotdeal report was not persisted")
            return {"id": int(row.id), "status": row.status, "updated": False}
