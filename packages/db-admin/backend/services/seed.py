"""기본 관리자 계정 시딩 — 최초 실행 시 admin 사용자가 없으면 생성."""

import logging
import os

from storage.models import User, UserRole
from api.auth import hash_password
from services.base import managed_session

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "admin@walletsavior.com"
DEFAULT_ADMIN_PASSWORD = "admin1234!"
DEFAULT_ADMIN_NICKNAME = "관리자"


def seed_default_admin() -> None:
    """admin 사용자가 없으면 기본 관리자 계정을 생성한다."""
    try:
        with managed_session() as session:
            existing = (
                session.query(User)
                .filter(User.role == UserRole.ADMIN)
                .first()
            )
            if existing:
                logger.debug("Seed: admin user already exists (id=%s)", existing.id)
                return

            # Public team demos supply their own values; ordinary startup keeps
            # the existing defaults and never changes an already-seeded admin.
            admin_email = os.getenv("DB_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL).strip()
            admin_password = os.getenv("DB_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
            if not admin_email or not admin_password:
                raise ValueError("Initial admin email/password must not be empty")
            admin = User(
                email=admin_email,
                hashed_password=hash_password(admin_password),
                nickname=DEFAULT_ADMIN_NICKNAME,
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin)
        logger.info(
            "Seed: created default admin account (%s)", admin_email
        )
    except Exception as exc:
        logger.warning("Seed: failed to create default admin — %s", exc)
