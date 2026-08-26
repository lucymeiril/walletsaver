"""Persistent public-account access through the main WalletSavior database.

The public API already receives a DBStorage instance backed by walletguardian.db.
This adapter intentionally reuses that session factory and the existing db-admin
SQLAlchemy models instead of creating another user schema. Community content is
stored separately in board.sqlite; its community_users rows are only mirrors of
these authoritative user ids.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PublicUserStoreError(RuntimeError):
    pass


_UNSET = object()


@dataclass
class PublicUserStore:
    db_storage: Any

    def __post_init__(self) -> None:
        if self.db_storage is None or not hasattr(self.db_storage, "SessionLocal"):
            raise PublicUserStoreError("public user database is unavailable")
        self.SessionLocal = self.db_storage.SessionLocal

    @staticmethod
    def _models():
        # web-api loads db-admin's storage.db before route imports. Keep this
        # import lazy so direct module imports fail cleanly instead of creating
        # a second, mismatched model registry.
        from storage.models import OAuthAccount, OAuthProvider, User, UserRole

        return User, UserRole, OAuthAccount, OAuthProvider

    @staticmethod
    def _role_value(role: Any) -> str:
        return getattr(role, "value", role) or "user"

    @classmethod
    def _serialize(cls, user: Any, *, include_password: bool = False) -> dict:
        payload = {
            "id": int(user.id),
            "email": user.email,
            "nickname": user.nickname,
            "role": cls._role_value(user.role),
            "profile_image_url": user.profile_image,
            "bio": user.bio,
            "preferences": user.preferences if isinstance(user.preferences, dict) else None,
            "is_active": bool(user.is_active),
            "is_deleted": bool(user.is_deleted),
            "created_at": user.created_at.isoformat() if user.created_at else "",
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            "deleted_at": user.deleted_at.isoformat() if user.deleted_at else None,
        }
        if include_password:
            payload["hashed_password"] = user.hashed_password
        return payload

    def get_by_id(self, user_id: int, *, include_password: bool = False) -> dict | None:
        User, _, _, _ = self._models()
        with self.SessionLocal() as session:
            user = session.get(User, int(user_id))
            return self._serialize(user, include_password=include_password) if user else None

    def get_by_email(self, email: str, *, include_password: bool = False) -> dict | None:
        User, _, _, _ = self._models()
        normalized = email.strip().lower()
        with self.SessionLocal() as session:
            user = session.query(User).filter(User.email == normalized).first()
            return self._serialize(user, include_password=include_password) if user else None

    def create_password_user(self, *, email: str, nickname: str, hashed_password: str) -> dict:
        User, UserRole, _, _ = self._models()
        normalized = email.strip().lower()
        nickname = nickname.strip()
        with self.SessionLocal() as session:
            if session.query(User).filter(User.email == normalized).first():
                raise PublicUserStoreError("email_exists")
            if session.query(User).filter(User.nickname == nickname).first():
                raise PublicUserStoreError("nickname_exists")
            user = User(
                email=normalized,
                nickname=nickname,
                hashed_password=hashed_password,
                role=UserRole.USER,
                is_active=True,
                is_deleted=False,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return self._serialize(user)

    def ensure_demo_user(self, *, email: str, nickname: str) -> dict:
        User, UserRole, _, _ = self._models()
        normalized = email.strip().lower()
        with self.SessionLocal() as session:
            user = session.query(User).filter(User.email == normalized).first()
            if user is None:
                candidate = nickname.strip()
                suffix = 2
                while session.query(User).filter(User.nickname == candidate).first():
                    candidate = f"{nickname}_{suffix}"
                    suffix += 1
                user = User(
                    email=normalized,
                    nickname=candidate,
                    hashed_password=None,
                    role=UserRole.USER,
                    is_active=True,
                    is_deleted=False,
                )
                session.add(user)
                session.commit()
                session.refresh(user)
            return self._serialize(user)

    def update_profile(
        self,
        user_id: int,
        *,
        nickname: Any = _UNSET,
        bio: Any = _UNSET,
        profile_image_url: Any = _UNSET,
        preferences: Any = _UNSET,
    ) -> dict | None:
        from datetime import datetime

        User, _, _, _ = self._models()
        with self.SessionLocal() as session:
            user = session.get(User, int(user_id))
            if user is None:
                return None
            if nickname is not _UNSET:
                normalized_nickname = str(nickname).strip()
                duplicate = session.query(User).filter(
                    User.nickname == normalized_nickname,
                    User.id != user.id,
                ).first()
                if duplicate:
                    raise PublicUserStoreError("nickname_exists")
                user.nickname = normalized_nickname
            if bio is not _UNSET:
                user.bio = bio
            if profile_image_url is not _UNSET:
                user.profile_image = profile_image_url
            if preferences is not _UNSET:
                user.preferences = preferences
            user.updated_at = datetime.utcnow()
            session.commit()
            session.refresh(user)
            return self._serialize(user)

    def soft_delete(self, user_id: int) -> dict | None:
        from datetime import datetime

        User, _, _, _ = self._models()
        with self.SessionLocal() as session:
            user = session.get(User, int(user_id))
            if user is None:
                return None
            now = datetime.utcnow()
            user.is_active = False
            user.is_deleted = True
            user.deleted_at = now
            user.updated_at = now
            session.commit()
            session.refresh(user)
            return self._serialize(user)

    def upsert_oauth_user(
        self,
        *,
        provider: str,
        provider_user_id: str,
        email: str | None,
        nickname: str | None,
        profile_image_url: str | None,
    ) -> dict:
        User, UserRole, OAuthAccount, OAuthProvider = self._models()
        try:
            provider_enum = OAuthProvider(provider)
        except ValueError as exc:
            raise PublicUserStoreError("unsupported_provider") from exc

        provider_user_id = str(provider_user_id)
        real_email = (email or "").strip().lower()
        stored_email = real_email or f"{provider}-{provider_user_id}@oauth.walletsavior.local"

        with self.SessionLocal() as session:
            account = session.query(OAuthAccount).filter(
                OAuthAccount.provider == provider_enum,
                OAuthAccount.provider_user_id == provider_user_id,
            ).first()
            user = account.user if account else None

            if user is None and real_email:
                user = session.query(User).filter(User.email == real_email).first()
            if user is None and not real_email:
                user = session.query(User).filter(User.email == stored_email).first()

            if user is None:
                base_nickname = (nickname or "").strip() or f"{provider}_{provider_user_id}"
                candidate = base_nickname
                suffix = 2
                while session.query(User).filter(User.nickname == candidate).first():
                    candidate = f"{base_nickname}_{suffix}"
                    suffix += 1
                user = User(
                    email=stored_email,
                    nickname=candidate,
                    hashed_password=None,
                    role=UserRole.USER,
                    profile_image=profile_image_url,
                    is_active=True,
                    is_deleted=False,
                )
                session.add(user)
                session.flush()

            if account is None:
                account = OAuthAccount(
                    user_id=user.id,
                    provider=provider_enum,
                    provider_user_id=provider_user_id,
                    access_token=None,
                    refresh_token=None,
                )
                session.add(account)

            if real_email and user.email.endswith("@oauth.walletsavior.local"):
                email_owner = session.query(User).filter(
                    User.email == real_email,
                    User.id != user.id,
                ).first()
                if email_owner is None:
                    user.email = real_email
            if profile_image_url:
                user.profile_image = profile_image_url

            session.commit()
            session.refresh(user)
            return self._serialize(user)
