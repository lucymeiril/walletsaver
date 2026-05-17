"""Auth utilities: password hashing, sessions, and FastAPI dependencies."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from storage.board_models import SessionRow, User, get_board_db

SESSION_COOKIE = "ws_session"
SESSION_TTL_HOURS = 24


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.utcnow()


def create_session(db: Session, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    expires = (_now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    row = SessionRow(token_hash=token_hash, user_id=user_id, expires_at=expires)
    db.add(row)
    db.commit()
    return token


def get_user_by_token(db: Session, token: str) -> Optional[User]:
    if not token:
        return None
    token_hash = _hash_token(token)
    row = db.get(SessionRow, token_hash)
    if not row:
        return None
    try:
        exp = datetime.fromisoformat(row.expires_at)
    except Exception:
        return None
    if exp < _now():
        db.delete(row)
        db.commit()
        return None
    # sliding expiry
    row.expires_at = (_now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
    db.commit()
    user = db.get(User, row.user_id)
    if user is None or user.banned_at:
        return None
    return user


def delete_session(db: Session, token: str) -> None:
    if not token:
        return
    th = _hash_token(token)
    row = db.get(SessionRow, th)
    if row:
        db.delete(row)
        db.commit()


def get_current_user(
    request: Request, db: Session = Depends(get_board_db)
) -> Optional[User]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return get_user_by_token(db, token)


def require_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="auth_required"
        )
    return user


def require_mod(user: User = Depends(require_user)) -> User:
    if user.role not in ("moderator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="mod_required"
        )
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin_required"
        )
    return user
