"""인증 서비스 — JWT 토큰 생성/검증 + 비밀번호 해싱"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
import logging

logger = logging.getLogger(__name__)

# --- JWT Secret 설정 ---
_DEFAULT_DEV_SECRET = "dev-secret-key-change-in-production"
SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEFAULT_DEV_SECRET)
_ENV = os.getenv("ENV", "development").lower()

if _ENV == "production":
    if not SECRET_KEY or SECRET_KEY == _DEFAULT_DEV_SECRET:
        raise RuntimeError(
            "FATAL: JWT_SECRET_KEY environment variable is required in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(SECRET_KEY) < 32:
        raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters (256 bits)")
elif SECRET_KEY == _DEFAULT_DEV_SECRET:
    logger.warning(
        "⚠️  Using default JWT secret — set JWT_SECRET_KEY env var before deploying"
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """비밀번호 해싱"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """비밀번호 검증"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """JWT 액세스 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict) -> str:
    """JWT 리프레시 토큰 생성"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """JWT 토큰 디코딩 및 검증"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def create_token_pair(user_id: int, email: str, role: str) -> dict:
    """액세스 + 리프레시 토큰 쌍 생성"""
    token_data = {"sub": str(user_id), "email": email, "role": role}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
