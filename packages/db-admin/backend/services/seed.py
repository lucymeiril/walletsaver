"""기본 관리자 계정 시딩 — 최초 실행 시 admin 사용자가 없으면 생성."""

import logging

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

            admin = User(
                email=DEFAULT_ADMIN_EMAIL,
                hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
                nickname=DEFAULT_ADMIN_NICKNAME,
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(admin)
        logger.info(
            "Seed: created default admin account (%s)", DEFAULT_ADMIN_EMAIL
        )
    except Exception as exc:
        logger.warning("Seed: failed to create default admin — %s", exc)
