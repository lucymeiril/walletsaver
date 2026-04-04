"""Create an admin user for the DB Admin panel.

Usage:
    py -m scripts.create_admin
    py -m scripts.create_admin --email admin@example.com --password secret123
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.auth import hash_password
from services.base import get_session
from storage.models import User, UserRole


def create_admin_user(email: str, password: str, nickname: str):
    session = get_session()
    try:
        existing = session.query(User).filter(User.email == email).first()
        if existing:
            print(f"User {email} already exists (role={existing.role.value}). Updating to admin...")
            existing.hashed_password = hash_password(password)
            existing.role = UserRole.ADMIN
            existing.is_active = True
            session.commit()
            print(f"Updated: {email} → admin")
            return

        user = User(
            email=email,
            hashed_password=hash_password(password),
            nickname=nickname,
            role=UserRole.ADMIN,
            is_active=True,
        )
        session.add(user)
        session.commit()
        print(f"Created admin user: {email} (nickname={nickname})")
    finally:
        session.close()


def generate_service_key():
    """Print a random service API key."""
    import secrets
    key = secrets.token_urlsafe(32)
    print(f"\nGenerated service API key: {key}")
    print(f"Add to SERVICE_API_KEYS env var as: {key}:service")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create DB Admin user")
    parser.add_argument("--email", default="admin@walletsavior.local")
    parser.add_argument("--password", default="admin1234")
    parser.add_argument("--nickname", default="관리자")
    parser.add_argument("--gen-key", action="store_true", help="Generate a service API key")
    args = parser.parse_args()

    create_admin_user(args.email, args.password, args.nickname)

    if args.gen_key:
        generate_service_key()
