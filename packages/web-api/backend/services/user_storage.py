"""Persistent public accounts stored only in web-api's accounts.sqlite."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


class PublicUserStoreError(RuntimeError):
    pass


_UNSET = object()


class PublicUserStore:
    def __init__(self, db_storage: Any):
        if db_storage is None or not hasattr(db_storage, "SessionLocal"):
            raise PublicUserStoreError("public user database is unavailable")
        self.SessionLocal = db_storage.SessionLocal

    @staticmethod
    def _role(value) -> str:
        raw = str(getattr(value, "value", value) or "user").lower()
        return raw.rsplit(".", 1)[-1]

    @classmethod
    def _serialize(cls, row, *, include_password: bool = False) -> dict:
        data = dict(row)
        preferences = data.get("preferences")
        if isinstance(preferences, str) and preferences:
            try:
                preferences = json.loads(preferences)
            except Exception:
                preferences = None
        payload = {
            "id": int(data["id"]),
            "email": data["email"],
            "nickname": data["nickname"],
            "role": cls._role(data.get("role")),
            "profile_image_url": data.get("profile_image"),
            "bio": data.get("bio"),
            "preferences": preferences if isinstance(preferences, dict) else None,
            "is_active": bool(data.get("is_active")),
            "is_deleted": bool(data.get("is_deleted")),
            "created_at": str(data.get("created_at") or ""),
            "updated_at": str(data.get("updated_at") or "") or None,
            "deleted_at": str(data.get("deleted_at") or "") or None,
        }
        if include_password:
            payload["hashed_password"] = data.get("hashed_password")
        return payload

    def _get(self, clause: str, params: dict, include_password: bool = False):
        with self.SessionLocal() as session:
            row = session.execute(
                text(f"SELECT * FROM users WHERE {clause} LIMIT 1"), params
            ).mappings().first()
        return self._serialize(row, include_password=include_password) if row else None

    def get_by_id(self, user_id: int, *, include_password: bool = False):
        return self._get("id=:value", {"value": int(user_id)}, include_password)

    def get_by_email(self, email: str, *, include_password: bool = False):
        return self._get(
            "lower(email)=:value",
            {"value": email.strip().lower()},
            include_password,
        )

    def create_password_user(self, *, email: str, nickname: str, hashed_password: str) -> dict:
        email = email.strip().lower()
        nickname = nickname.strip()
        now = datetime.utcnow().isoformat()
        with self.SessionLocal() as session:
            if session.execute(text("SELECT 1 FROM users WHERE email=:v"), {"v": email}).first():
                raise PublicUserStoreError("email_exists")
            if session.execute(text("SELECT 1 FROM users WHERE nickname=:v"), {"v": nickname}).first():
                raise PublicUserStoreError("nickname_exists")
            try:
                session.execute(text(
                    "INSERT INTO users "
                    "(email,nickname,hashed_password,role,is_active,is_deleted,created_at,updated_at) "
                    "VALUES (:email,:nickname,:password,'user',1,0,:now,:now)"
                ), {"email": email, "nickname": nickname, "password": hashed_password, "now": now})
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if session.execute(text("SELECT 1 FROM users WHERE email=:v"), {"v": email}).first():
                    raise PublicUserStoreError("email_exists") from exc
                if session.execute(text("SELECT 1 FROM users WHERE nickname=:v"), {"v": nickname}).first():
                    raise PublicUserStoreError("nickname_exists") from exc
                raise PublicUserStoreError("account_create_conflict") from exc
            user_id = int(session.execute(
                text("SELECT id FROM users WHERE email=:email"), {"email": email}
            ).scalar_one())
        return self.get_by_id(user_id)

    def ensure_demo_user(self, *, email: str, nickname: str) -> dict:
        existing = self.get_by_email(email)
        if existing:
            return existing
        candidate = nickname.strip()
        with self.SessionLocal() as session:
            suffix = 2
            while session.execute(text("SELECT 1 FROM users WHERE nickname=:v"), {"v": candidate}).first():
                candidate = f"{nickname}_{suffix}"
                suffix += 1
        return self.create_password_user(email=email, nickname=candidate, hashed_password=None)

    def update_profile(
        self, user_id: int, *, nickname=_UNSET, bio=_UNSET,
        profile_image_url=_UNSET, preferences=_UNSET,
    ):
        updates, params = [], {"id": int(user_id), "updated_at": datetime.utcnow().isoformat()}
        if nickname is not _UNSET:
            value = str(nickname).strip()
            with self.SessionLocal() as session:
                duplicate = session.execute(
                    text("SELECT 1 FROM users WHERE nickname=:v AND id<>:id"),
                    {"v": value, "id": int(user_id)},
                ).first()
            if duplicate:
                raise PublicUserStoreError("nickname_exists")
            updates.append("nickname=:nickname"); params["nickname"] = value
        if bio is not _UNSET:
            updates.append("bio=:bio"); params["bio"] = bio
        if profile_image_url is not _UNSET:
            updates.append("profile_image=:profile_image"); params["profile_image"] = profile_image_url
        if preferences is not _UNSET:
            updates.append("preferences=:preferences")
            params["preferences"] = json.dumps(preferences, ensure_ascii=False) if preferences is not None else None
        if not updates:
            return self.get_by_id(user_id)
        updates.append("updated_at=:updated_at")
        with self.SessionLocal() as session:
            result = session.execute(
                text(f"UPDATE users SET {', '.join(updates)} WHERE id=:id"), params
            )
            session.commit()
            if not result.rowcount:
                return None
        return self.get_by_id(user_id)

    def soft_delete(self, user_id: int):
        now = datetime.utcnow().isoformat()
        with self.SessionLocal() as session:
            result = session.execute(text(
                "UPDATE users SET is_active=0,is_deleted=1,deleted_at=:now,updated_at=:now WHERE id=:id"
            ), {"now": now, "id": int(user_id)})
            session.commit()
            if not result.rowcount:
                return None
        return self.get_by_id(user_id)

    def upsert_oauth_user(
        self, *, provider: str, provider_user_id: str, email: str | None,
        nickname: str | None, profile_image_url: str | None,
    ) -> dict:
        provider = provider.lower()
        if provider not in {"google", "kakao", "naver"}:
            raise PublicUserStoreError("unsupported_provider")
        provider_user_id = str(provider_user_id)
        real_email = (email or "").strip().lower()
        stored_email = real_email or f"{provider}-{provider_user_id}@oauth.walletsavior.local"
        now = datetime.utcnow().isoformat()

        with self.SessionLocal() as session:
            account = session.execute(text(
                "SELECT user_id FROM oauth_accounts WHERE provider=:p AND provider_user_id=:pid"
            ), {"p": provider, "pid": provider_user_id}).mappings().first()
            user_id = int(account["user_id"]) if account else None
            if user_id is None:
                row = session.execute(
                    text("SELECT id FROM users WHERE email=:email"), {"email": stored_email}
                ).first()
                user_id = int(row.id) if row else None
            if user_id is None:
                base = (nickname or "").strip() or f"{provider}_{provider_user_id}"
                candidate, suffix = base, 2
                while session.execute(text("SELECT 1 FROM users WHERE nickname=:v"), {"v": candidate}).first():
                    candidate = f"{base}_{suffix}"; suffix += 1
                session.execute(text(
                    "INSERT INTO users "
                    "(email,nickname,role,profile_image,is_active,is_deleted,created_at,updated_at) "
                    "VALUES (:email,:nickname,'user',:image,1,0,:now,:now)"
                ), {"email": stored_email, "nickname": candidate, "image": profile_image_url, "now": now})
                user_id = int(session.execute(
                    text("SELECT id FROM users WHERE email=:email"), {"email": stored_email}
                ).scalar_one())
            if not account:
                try:
                    session.execute(text(
                        "INSERT INTO oauth_accounts "
                        "(user_id,provider,provider_user_id,created_at) VALUES (:uid,:p,:pid,:now)"
                    ), {"uid": user_id, "p": provider, "pid": provider_user_id, "now": now})
                except IntegrityError as exc:
                    # A concurrent OAuth callback may have linked this provider id first.
                    # rollback() also removes a user we created earlier in this transaction,
                    # so always re-read the winning link instead of keeping the stale user_id.
                    session.rollback()
                    winner = session.execute(text(
                        "SELECT user_id FROM oauth_accounts WHERE provider=:p AND provider_user_id=:pid"
                    ), {"p": provider, "pid": provider_user_id}).mappings().first()
                    if winner is None:
                        raise PublicUserStoreError("oauth_link_conflict") from exc
                    user_id = int(winner["user_id"])
            if profile_image_url:
                session.execute(
                    text("UPDATE users SET profile_image=:image,updated_at=:now WHERE id=:id"),
                    {"image": profile_image_url, "now": now, "id": user_id},
                )
            session.commit()
        return self.get_by_id(user_id)
