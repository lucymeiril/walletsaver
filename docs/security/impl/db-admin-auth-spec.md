# DB Admin — Authentication, Authorization & CORS Implementation Spec

> **Created**: 2025-07-20
> **Scope**: `packages/db-admin/backend/` and `packages/db-admin/frontend/src/`
> **Addresses**: Code Audit Issues #1, #2, #3 · Architecture Audit Issues #1, #2, #3, #6
> **Goal**: Add API key authentication, RBAC, restricted CORS, and inter-service auth — without breaking existing functionality.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [File Inventory](#2-file-inventory)
3. [Step 1 — Configuration & Environment Variables](#3-step-1--configuration--environment-variables)
4. [Step 2 — CORS Restriction](#4-step-2--cors-restriction)
5. [Step 3 — Auth Dependencies (Middleware)](#5-step-3--auth-dependencies-middleware)
6. [Step 4 — Apply Auth to All Route Files](#6-step-4--apply-auth-to-all-route-files)
7. [Step 5 — Inter-Service API Key for Crawlers](#7-step-5--inter-service-api-key-for-crawlers)
8. [Step 6 — Frontend Changes](#8-step-6--frontend-changes)
9. [Step 7 — Seed Admin User & API Keys](#9-step-7--seed-admin-user--api-keys)
10. [Test Plan](#10-test-plan)
11. [Migration & Rollback](#11-migration--rollback)

---

## 1. Architecture Overview

```
┌─────────────┐  Authorization: Bearer <JWT>   ┌──────────────────────────────┐
│  Frontend   │ ─────────────────────────────► │  FastAPI Backend (:8002)      │
│  (:5175)    │                                │                              │
│  React+Vite │ ◄───────────────────────────── │  CORS: localhost:5175 only   │
└─────────────┘                                │                              │
                                               │  ┌────────────────────────┐  │
┌─────────────┐  X-API-Key: <service-key>      │  │ auth.py (NEW)          │  │
│  Crawler    │ ─────────────────────────────► │  │  verify_api_key()      │  │
│  Pipeline   │   POST /api/ingestions         │  │  verify_jwt()          │  │
│             │                                │  │  require_role(admin)   │  │
└─────────────┘                                │  └────────────────────────┘  │
                                               └──────────────────────────────┘
```

### Authentication Strategy

We use a **dual-mode** approach:
- **JWT tokens** for human users (frontend admin panel)
- **Static API keys** for service-to-service calls (crawler → db-admin)

Both modes are validated via a single `get_current_identity()` dependency that checks `Authorization: Bearer <JWT>` first, then falls back to `X-API-Key: <key>`.

### Role Hierarchy

| Role | Code | Can Read | Can Write | Can Delete | Can Reset |
|------|------|----------|-----------|------------|-----------|
| `viewer` | `UserRole.USER` | ✅ | ❌ | ❌ | ❌ |
| `moderator` | `UserRole.MODERATOR` | ✅ | ✅ | ❌ | ❌ |
| `admin` | `UserRole.ADMIN` | ✅ | ✅ | ✅ | ✅ |
| `service` | (API key) | ingestion only | ingestion only | ❌ | ❌ |

---

## 2. File Inventory

### New Files to Create

| File | Purpose |
|------|---------|
| `backend/api/auth.py` | JWT + API key verification, RBAC dependencies |
| `backend/api/routes/auth_routes.py` | `/api/auth/login`, `/api/auth/me`, `/api/auth/refresh` |
| `backend/scripts/create_admin.py` | CLI script to seed an admin user |
| `frontend/src/api/authClient.js` | Auth-aware fetch wrapper |
| `frontend/src/pages/Login/LoginPage.jsx` | Login form |
| `frontend/src/hooks/useAuth.js` | Auth state hook (token storage, logout) |
| `frontend/src/components/AuthGuard.jsx` | Route guard wrapper |

### Existing Files to Modify

| File | Change |
|------|--------|
| `backend/config.py` | Add `JWT_SECRET`, `CORS_ORIGINS`, `SERVICE_API_KEYS` settings |
| `backend/requirements.txt` | Add `python-jose[cryptography]`, `passlib[bcrypt]` |
| `backend/api/app.py` | Restrict CORS, register auth routes |
| `backend/api/routes/admin.py` | Add `Depends(require_admin)` to all endpoints |
| `backend/api/routes/products.py` | Add auth dependencies per endpoint |
| `backend/api/routes/categories.py` | Add auth dependencies per endpoint |
| `backend/api/routes/keywords.py` | Add auth dependencies per endpoint |
| `backend/api/routes/prices.py` | Add auth dependencies per endpoint |
| `backend/api/routes/analytics.py` | Add auth dependencies per endpoint |
| `backend/api/routes/dashboard.py` | Add `Depends(require_viewer)` |
| `backend/api/routes/ingestion.py` | Add service key auth for POST, viewer auth for GET |
| `frontend/src/api/client.js` | Inject `Authorization` header from stored token |
| `frontend/src/App.jsx` | Add login route + `AuthGuard` wrapper |
| `packages/crawler-admin/backend/pipeline/pipeline.py` | Add `X-API-Key` header to HTTP requests |

---

## 3. Step 1 — Configuration & Environment Variables

### File: `backend/config.py`

Replace the entire file with:

```python
"""DB 관리 백엔드 설정 — SQLite 기본, 환경변수로 PostgreSQL 전환 가능"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

_default_db = f"sqlite:///{BASE_DIR / 'walletguardian.db'}"

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", _default_db)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    API_PORT: int = int(os.getenv("DB_ADMIN_PORT", "8002"))

    # ── Connection Pool 설정 ──
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", "5"))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", "10"))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", "30"))
    DB_POOL_RECYCLE: int = int(os.getenv("DB_POOL_RECYCLE", "1800"))

    # ── Auth 설정 (NEW) ──
    JWT_SECRET: str = os.getenv("JWT_SECRET", "CHANGE-ME-IN-PRODUCTION-32-chars!")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("JWT_ACCESS_EXPIRE_MIN", "60"))
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "7"))

    # ── CORS 설정 (NEW) ──
    # Comma-separated list of allowed origins
    CORS_ALLOWED_ORIGINS: list[str] = [
        o.strip()
        for o in os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5175,http://127.0.0.1:5175,http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if o.strip()
    ]

    # ── Service API Keys (NEW) ──
    # Format: "key1:role1,key2:role2" — e.g. "crawlerkey123:service,websitekey456:viewer"
    # In production, generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    SERVICE_API_KEYS: dict[str, str] = {}

    def __init__(self):
        raw_keys = os.getenv("SERVICE_API_KEYS", "")
        if raw_keys:
            for pair in raw_keys.split(","):
                pair = pair.strip()
                if ":" in pair:
                    key, role = pair.rsplit(":", 1)
                    self.SERVICE_API_KEYS[key.strip()] = role.strip()

settings = Settings()
```

### Environment Variables (`.env` or system)

```bash
# Required for production — generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET=your-production-secret-at-least-32-characters

# CORS origins (comma-separated)
CORS_ALLOWED_ORIGINS=http://localhost:5175,http://127.0.0.1:5175

# Service API keys: "key:role,key:role"
# Generate keys: python -c "import secrets; print(secrets.token_urlsafe(32))"
SERVICE_API_KEYS=crawler_emart_Abc123xyz:service,crawler_coupang_Def456uvw:service
```

---

## 4. Step 2 — CORS Restriction

### File: `backend/api/app.py`

**Change the CORS middleware block (lines 17-23):**

Replace:
```python
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

With:
```python
    from config import settings as _settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )
```

**Also register the auth router** by adding after the existing router imports (around line 32):

```python
    from api.routes.auth_routes import router as auth_router
    # ... existing include_router calls ...
    app.include_router(auth_router, prefix="/api")
```

The `/health` endpoint (line 45-47) remains public — no auth needed.

### Full `app.py` After Changes

```python
"""DB 관리 API 팩토리"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware


def create_app() -> FastAPI:
    from config import settings as _settings

    app = FastAPI(
        title="WalletSavior DB 관리",
        description="데이터베이스 관리 API",
        version="0.1.0",
    )

    app.add_middleware(GZipMiddleware, minimum_size=500)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_settings.CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    from api.routes.products import router as products_router
    from api.routes.prices import router as prices_router
    from api.routes.categories import router as categories_router
    from api.routes.keywords import router as keywords_router
    from api.routes.analytics import router as analytics_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.admin import router as admin_router
    from api.routes.auth_routes import router as auth_router

    app.include_router(products_router, prefix="/api")
    app.include_router(prices_router, prefix="/api")
    app.include_router(categories_router, prefix="/api")
    app.include_router(keywords_router, prefix="/api")
    app.include_router(analytics_router, prefix="/api")
    app.include_router(dashboard_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")
    app.include_router(ingestion_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "db-admin"}

    return app
```

---

## 5. Step 3 — Auth Dependencies (Middleware)

### New File: `backend/api/auth.py`

This is the core authentication module. It provides reusable FastAPI dependencies.

```python
"""Authentication & authorization dependencies for DB Admin API.

Usage in route files:
    from api.auth import require_viewer, require_moderator, require_admin, require_service

    @router.get("/items")
    def list_items(identity: dict = Depends(require_viewer)):
        ...

    @router.post("/items")
    def create_item(identity: dict = Depends(require_moderator)):
        ...

    @router.delete("/items/{id}")
    def delete_item(identity: dict = Depends(require_admin)):
        ...
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

from config import settings

logger = logging.getLogger(__name__)

# ── Password hashing ──
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT token creation ──

def create_access_token(user_id: int, email: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Identity resolution (JWT or API key) ──

# Optional bearer — allows None when no Authorization header is present
_optional_bearer = HTTPBearer(auto_error=False)

async def get_current_identity(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
    x_api_key: Optional[str] = Header(None),
) -> dict:
    """Resolve the caller's identity from JWT bearer token or X-API-Key header.

    Returns a dict:
        {"id": int|str, "email": str, "role": str, "auth_type": "jwt"|"api_key"}

    Raises 401 if neither auth method provides a valid identity.
    """
    # 1) Try JWT bearer token
    if credentials and credentials.credentials:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "액세스 토큰이 아닙니다.")
        return {
            "id": int(payload["sub"]),
            "email": payload.get("email", ""),
            "role": payload.get("role", "user"),
            "auth_type": "jwt",
        }

    # 2) Try static API key
    if x_api_key:
        role = settings.SERVICE_API_KEYS.get(x_api_key)
        if role:
            return {
                "id": f"service:{x_api_key[:8]}",
                "email": "service-account",
                "role": role,
                "auth_type": "api_key",
            }
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 API 키입니다.")

    # 3) No credentials provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="인증이 필요합니다. Authorization 헤더 또는 X-API-Key를 제공하세요.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ── Role-based dependencies ──

ROLE_HIERARCHY = {"user": 0, "viewer": 0, "service": 1, "moderator": 2, "admin": 3}

def _require_min_role(min_role: str):
    """Factory: returns a FastAPI dependency that enforces a minimum role level."""
    min_level = ROLE_HIERARCHY.get(min_role, 0)

    async def _checker(identity: dict = Depends(get_current_identity)) -> dict:
        caller_level = ROLE_HIERARCHY.get(identity["role"], 0)
        if caller_level < min_level:
            logger.warning(
                "Access denied: user=%s role=%s required=%s",
                identity.get("email"), identity["role"], min_role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"'{min_role}' 이상의 권한이 필요합니다. 현재 권한: '{identity['role']}'",
            )
        return identity

    return _checker

# Pre-built dependencies — import these in route files
require_viewer = _require_min_role("viewer")        # any authenticated user
require_service = _require_min_role("service")      # service accounts + moderator + admin
require_moderator = _require_min_role("moderator")  # moderator + admin
require_admin = _require_min_role("admin")           # admin only
```

---

### New File: `backend/api/routes/auth_routes.py`

```python
"""Authentication endpoints: login, token refresh, current user info."""

import logging
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Depends, status

from api.auth import (
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_identity,
)
from services.base import get_session
from storage.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest):
    """Authenticate with email + password, return JWT tokens."""
    session = get_session()
    try:
        user = session.query(User).filter(User.email == body.email).first()
        if not user or not user.hashed_password:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "이메일 또는 비밀번호가 올바르지 않습니다.")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "비활성화된 계정입니다.")

        access = create_access_token(user.id, user.email, user.role.value)
        refresh = create_refresh_token(user.id)

        logger.info("[AUTH] login success: user=%s role=%s", user.email, user.role.value)
        return TokenResponse(access_token=access, refresh_token=refresh)
    finally:
        session.close()


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(body: RefreshRequest):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    payload = decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "리프레시 토큰이 아닙니다.")

    user_id = int(payload["sub"])
    session = get_session()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        if not user or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않은 사용자입니다.")

        access = create_access_token(user.id, user.email, user.role.value)
        refresh = create_refresh_token(user.id)
        return TokenResponse(access_token=access, refresh_token=refresh)
    finally:
        session.close()


@router.get("/me")
def get_me(identity: dict = Depends(get_current_identity)):
    """Return the currently authenticated user's profile."""
    if identity["auth_type"] == "api_key":
        return {"id": identity["id"], "role": identity["role"], "auth_type": "api_key"}

    session = get_session()
    try:
        user = session.query(User).filter(User.id == identity["id"]).first()
        if not user:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "사용자를 찾을 수 없습니다.")
        return {
            "id": user.id,
            "email": user.email,
            "nickname": user.nickname,
            "role": user.role.value,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
    finally:
        session.close()
```

---

## 6. Step 4 — Apply Auth to All Route Files

### Auth Dependency Mapping Per Endpoint

Every route file needs two changes:
1. **Import** the appropriate dependency from `api.auth`
2. **Add** `identity: dict = Depends(require_xxx)` to each endpoint function signature

Below is the exact mapping for each file.

---

### File: `backend/api/routes/admin.py`

**All endpoints → `require_admin`** (most destructive operations)
Exception: `GET /data-summary` → `require_moderator` (read-only summary)

Add at top (after existing imports):
```python
from fastapi import APIRouter, HTTPException, Depends
from api.auth import require_admin, require_moderator
```

Modify each endpoint signature:

```python
# GET /admin/data-summary  — moderator can view
@router.get("/data-summary")
def data_summary(identity: dict = Depends(require_moderator)):
    ...

# POST /admin/reset-source  — admin only
@router.post("/reset-source")
def reset_source(body: ResetSourceRequest, identity: dict = Depends(require_admin)):
    ...

# POST /admin/reset-products  — admin only
@router.post("/reset-products")
def reset_products(body: ResetProductsRequest, identity: dict = Depends(require_admin)):
    ...

# POST /admin/reset-all  — admin only
@router.post("/reset-all")
def reset_all(body: ResetAllRequest, identity: dict = Depends(require_admin)):
    ...
```

Update logger.warning calls to include user identity:
```python
logger.warning(
    "[ADMIN] reset-source by user=%s: source=%s discount=%d baseline=%d hotdeal=%d",
    identity.get("email"), src, discount_del, baseline_del, hotdeal_del,
)
```

---

### File: `backend/api/routes/products.py`

Add import:
```python
from fastapi import APIRouter, HTTPException, Query, Depends
from api.auth import require_viewer, require_moderator, require_admin
```

Endpoint mapping:

| Endpoint | Dependency |
|----------|------------|
| `GET /products/` (list) | `require_viewer` |
| `GET /products/stats` | `require_viewer` |
| `GET /products/{id}` | `require_viewer` |
| `GET /products/{id}/history` | `require_viewer` |
| `GET /products/{id}/comparison` | `require_viewer` |
| `GET /products/{id}/similar` | `require_viewer` |
| `POST /products/` (create) | `require_moderator` |
| `PUT /products/{id}` (update) | `require_moderator` |
| `DELETE /products/{id}` | `require_admin` |
| `POST /products/bulk-delete` | `require_admin` |
| `POST /products/bulk-category` | `require_moderator` |

Example for one endpoint:
```python
@router.get("/")
def list_products(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    # ... existing params ...
    identity: dict = Depends(require_viewer),
):
    ...
```

---

### File: `backend/api/routes/categories.py`

Add import:
```python
from fastapi import APIRouter, HTTPException, Depends
from api.auth import require_viewer, require_moderator, require_admin
```

| Endpoint | Dependency |
|----------|------------|
| `GET /categories/` | `require_viewer` |
| `GET /categories/{id}/products` | `require_viewer` |
| `GET /categories/{id}/product-count` | `require_viewer` |
| `POST /categories/` | `require_moderator` |
| `PUT /categories/{id}` | `require_moderator` |
| `PUT /categories/{id}/move` | `require_moderator` |
| `DELETE /categories/{id}` | `require_admin` |

---

### File: `backend/api/routes/keywords.py`

Add import:
```python
from fastapi import APIRouter, HTTPException, Query, Depends
from api.auth import require_viewer, require_moderator, require_admin
```

| Endpoint | Dependency |
|----------|------------|
| `GET /keywords/` | `require_viewer` |
| `GET /keywords/stats` | `require_viewer` |
| `GET /keywords/search` | `require_viewer` |
| `GET /keywords/popular` | `require_viewer` |
| `POST /keywords/` | `require_moderator` |
| `PUT /keywords/{id}` | `require_moderator` |
| `DELETE /keywords/{id}` | `require_admin` |
| `POST /keywords/bulk-delete` | `require_admin` |

---

### File: `backend/api/routes/prices.py`

Add import:
```python
from fastapi import APIRouter, HTTPException, Query, Depends
from api.auth import require_viewer, require_moderator, require_admin
```

| Endpoint | Dependency |
|----------|------------|
| `GET /prices/stats` | `require_viewer` |
| `GET /prices/product/{id}` | `require_viewer` |
| `GET /prices/tier-config` | `require_viewer` |
| `POST /prices/tier-config` | `require_admin` |
| `GET /prices/outliers` | `require_viewer` |
| `POST /prices/outliers/{id}/whitelist` | `require_moderator` |
| `GET /prices/outliers/{id}/distribution` | `require_viewer` |
| `GET /prices/history` | `require_viewer` |
| `GET /prices/tier-preview` | `require_viewer` |
| `GET /prices/export` | `require_moderator` |
| `POST /prices/bulk` | `require_moderator` |

---

### File: `backend/api/routes/analytics.py`

Add import:
```python
from fastapi import APIRouter, HTTPException, Query, Depends
from api.auth import require_viewer, require_moderator
```

| Endpoint | Dependency |
|----------|------------|
| All `GET` endpoints | `require_viewer` |
| `GET /analytics/export/*` | `require_moderator` |
| `POST /analytics/duplicates` | `require_viewer` |
| `POST /analytics/outliers/{id}/action` | `require_moderator` |

---

### File: `backend/api/routes/dashboard.py`

Add import:
```python
from fastapi import APIRouter, Depends
from api.auth import require_viewer
```

| Endpoint | Dependency |
|----------|------------|
| `GET /dashboard/stats` | `require_viewer` |

---

### File: `backend/api/routes/ingestion.py`

This file needs **dual auth** — service keys for crawler submissions, viewer/moderator for admin review.

Add import:
```python
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from api.auth import require_viewer, require_moderator, get_current_identity
```

| Endpoint | Dependency |
|----------|------------|
| `POST /api/ingestions` (submit) | `get_current_identity` (service or moderator) |
| `GET /api/ingestions` (list) | `require_viewer` |
| `GET /api/ingestions/stats` | `require_viewer` |
| `GET /api/ingestions/{id}` | `require_viewer` |
| `POST /api/ingestions/{id}/db-review` | `require_moderator` |
| `POST /api/ingestions/bulk-approve` | `require_moderator` |

For the `POST /api/ingestions` submit endpoint, add validation that the caller is either a service account or at least moderator:

```python
@router.post("")
def submit_ingestion(body: IngestionSubmit, identity: dict = Depends(get_current_identity)):
    # Allow service accounts and moderator+ roles
    if identity["role"] not in ("service", "moderator", "admin"):
        raise HTTPException(403, "크롤러 서비스 또는 관리자 권한이 필요합니다.")
    ...
```

---

## 7. Step 5 — Inter-Service API Key for Crawlers

### File: `packages/crawler-admin/backend/pipeline/pipeline.py`

The crawler pipeline currently sends plain HTTP POST to `INGESTION_API_URL`. Add the `X-API-Key` header.

**Change 1**: Add environment variable for the API key (near line 42):

```python
INGESTION_API_URL = os.getenv(
    "INGESTION_API_URL", "http://localhost:8002/api/ingestions"
)
INGESTION_API_KEY = os.getenv("INGESTION_API_KEY", "")
```

**Change 2**: In the `_store_to_ingestion` method (around line 335-337), add the header:

Find:
```python
            resp = await client.post(INGESTION_API_URL, json=payload)
```

Replace with:
```python
            headers = {}
            if INGESTION_API_KEY:
                headers["X-API-Key"] = INGESTION_API_KEY
            resp = await client.post(INGESTION_API_URL, json=payload, headers=headers)
```

### Crawler Environment Variable

```bash
# Set in crawler-admin's .env or docker-compose environment
INGESTION_API_KEY=crawler_emart_Abc123xyz
```

This key must match one of the entries in db-admin's `SERVICE_API_KEYS` env var.

---

## 8. Step 6 — Frontend Changes

### File: `frontend/src/api/client.js`

Add token injection to ALL fetch calls. This is the minimal-change approach — modify the helper functions to auto-attach the stored token.

Replace the existing file content with:

```javascript
const API_BASE = '/api';

// ── Token storage ──
const TOKEN_KEY = 'db_admin_access_token';
const REFRESH_KEY = 'db_admin_refresh_token';

export function getStoredToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getStoredRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function storeTokens(access, refresh) {
  localStorage.setItem(TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

// ── Auth headers ──
function authHeaders(extra = {}) {
  const token = getStoredToken();
  const headers = { ...extra };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// ── Response handler (with auto-logout on 401) ──
const json = async (r) => {
  if (r.status === 401) {
    // Try refresh once
    const refreshed = await tryRefreshToken();
    if (!refreshed) {
      clearTokens();
      window.location.href = '/login';
      throw new Error('인증이 만료되었습니다.');
    }
    // The caller should retry — for simplicity, redirect
    window.location.reload();
    throw new Error('토큰 갱신 중...');
  }
  const data = await r.json();
  if (!r.ok) {
    const msg = data.detail || data.message || `HTTP ${r.status}`;
    const err = new Error(msg);
    err.status = r.status;
    throw err;
  }
  return data;
};

async function tryRefreshToken() {
  const refresh = getStoredRefreshToken();
  if (!refresh) return false;
  try {
    const r = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!r.ok) return false;
    const data = await r.json();
    storeTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    return false;
  }
}

// ── Fetch wrappers with auth ──
const getJson = (url) =>
  fetch(url, { headers: authHeaders() }).then(json);

const postJson = (url, data) =>
  fetch(url, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(data),
  }).then(json);

const putJson = (url, data) =>
  fetch(url, {
    method: 'PUT',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(data),
  }).then(json);

const del = (url) =>
  fetch(url, {
    method: 'DELETE',
    headers: authHeaders(),
  }).then(json);

// ── Auth API (no auth header needed for login) ──
export const authApi = {
  login: (email, password) =>
    fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }).then(async (r) => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      storeTokens(data.access_token, data.refresh_token);
      return data;
    }),
  me: () => getJson(`${API_BASE}/auth/me`),
  logout: () => { clearTokens(); },
};

// ── Existing API (unchanged signatures, now with auth headers) ──
export const api = {
  // Products
  getProducts: (params) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return getJson(`${API_BASE}/products/${qs}`);
  },
  getProduct: (id) => getJson(`${API_BASE}/products/${id}`),
  getProductStats: () => getJson(`${API_BASE}/products/stats`),
  getProductHistory: (id, days = 30) => getJson(`${API_BASE}/products/${id}/history?days=${days}`),
  getProductComparison: (id) => getJson(`${API_BASE}/products/${id}/comparison`),
  getProductSimilar: (id, limit = 10) => getJson(`${API_BASE}/products/${id}/similar?limit=${limit}`),
  createProduct: (data) => postJson(`${API_BASE}/products/`, data),
  updateProduct: (id, data) => putJson(`${API_BASE}/products/${id}`, data),
  deleteProduct: (id) => del(`${API_BASE}/products/${id}`),
  bulkDeleteProducts: (ids) => postJson(`${API_BASE}/products/bulk-delete`, { ids }),
  bulkUpdateCategory: (ids, categoryId) => postJson(`${API_BASE}/products/bulk-category`, { ids, category_id: categoryId }),
  // Categories
  getCategories: () => getJson(`${API_BASE}/categories/`),
  createCategory: (data) => postJson(`${API_BASE}/categories/`, data),
  updateCategory: (id, data) => putJson(`${API_BASE}/categories/${id}`, data),
  deleteCategory: (id) => del(`${API_BASE}/categories/${id}`),
  moveCategory: (id, newParentId) => putJson(`${API_BASE}/categories/${id}/move`, { new_parent_id: newParentId }),
  getCategoryProducts: (id) => getJson(`${API_BASE}/categories/${id}/products`),
  getCategoryProductCount: (id) => getJson(`${API_BASE}/categories/${id}/product-count`),
  // Keywords
  getKeywords: (params) => {
    const qs = params ? `?${new URLSearchParams(params)}` : '';
    return getJson(`${API_BASE}/keywords/${qs}`);
  },
  getKeywordStats: () => getJson(`${API_BASE}/keywords/stats`),
  searchKeywords: (q) => getJson(`${API_BASE}/keywords/search?q=${encodeURIComponent(q)}`),
  getPopularKeywords: () => getJson(`${API_BASE}/keywords/popular`),
  createKeyword: (data) => postJson(`${API_BASE}/keywords/`, data),
  updateKeyword: (id, data) => putJson(`${API_BASE}/keywords/${id}`, data),
  deleteKeyword: (id) => del(`${API_BASE}/keywords/${id}`),
  bulkDeleteKeywords: (ids) => postJson(`${API_BASE}/keywords/bulk-delete`, ids ? { ids } : {}),
  // Analytics
  getQualityReport: () => getJson(`${API_BASE}/analytics/quality-report`),
  getSummary: () => getJson(`${API_BASE}/analytics/summary`),
  getPriceTrends: (productIds, days = 30) => {
    const params = new URLSearchParams();
    productIds.forEach(id => params.append('product_ids', id));
    params.set('days', days);
    return getJson(`${API_BASE}/analytics/price-trends?${params}`);
  },
  getSourceStatsDetail: () => getJson(`${API_BASE}/analytics/source-stats`),
  searchProducts: (q) => getJson(`${API_BASE}/analytics/products/search?q=${encodeURIComponent(q)}`),
  getSourceDistribution: () => getJson(`${API_BASE}/analytics/source-distribution`),
  getCategoryDistribution: () => getJson(`${API_BASE}/analytics/category-distribution`),
  getDailyTrend: (days = 30) => getJson(`${API_BASE}/analytics/daily-trend?days=${days}`),
  getDataQualitySummary: () => getJson(`${API_BASE}/analytics/data-quality-summary`),
  outlierAction: (id, action, newPrice) => postJson(`${API_BASE}/analytics/outliers/${id}/action`, { action, new_price: newPrice }),
  getSourceTypes: () => getJson(`${API_BASE}/analytics/source-types`),
  // Dashboard
  getDashboardStats: () => getJson(`${API_BASE}/dashboard/stats`),
  // Prices
  getPriceStats: () => getJson(`${API_BASE}/prices/stats`),
  getProductPrices: (id, days = 90) => getJson(`${API_BASE}/prices/product/${id}?days=${days}`),
  getTierConfig: () => getJson(`${API_BASE}/prices/tier-config`),
  saveTierConfig: (tiers) => postJson(`${API_BASE}/prices/tier-config`, { tiers }),
  getGlobalOutliers: (limit = 20) => getJson(`${API_BASE}/prices/outliers?limit=${limit}`),
  getPriceHistory: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return getJson(`${API_BASE}/prices/history?${qs}`);
  },
  whitelistOutlier: (id) => postJson(`${API_BASE}/prices/outliers/${id}/whitelist`, {}),
  getTierPreview: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return getJson(`${API_BASE}/prices/tier-preview?${qs}`);
  },
  getOutlierDistribution: (productId, days = 90) =>
    getJson(`${API_BASE}/prices/outliers/${productId}/distribution?days=${days}`),
  // Ingestions
  getIngestions: (params) => getJson(`${API_BASE}/ingestions?${new URLSearchParams(params)}`),
  getIngestion: (id) => getJson(`${API_BASE}/ingestions/${id}`),
  reviewIngestion: (id, data) => postJson(`${API_BASE}/ingestions/${id}/db-review`, data),
  bulkApproveIngestions: (ids, reviewer, notes) => postJson(`${API_BASE}/ingestions/bulk-approve`, { ids, reviewer, notes }),
  getIngestionStats: () => getJson(`${API_BASE}/ingestions/stats`),
  // Admin
  getDataSummary: () => getJson(`${API_BASE}/admin/data-summary`),
  resetSource: (source, confirm) => postJson(`${API_BASE}/admin/reset-source`, { source, confirm }),
  resetProducts: (confirm) => postJson(`${API_BASE}/admin/reset-products`, { confirm }),
  resetAll: (confirm) => postJson(`${API_BASE}/admin/reset-all`, { confirm }),
};
```

### New File: `frontend/src/pages/Login/LoginPage.jsx`

```jsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../../api/client';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await authApi.login(email, password);
      navigate('/');
    } catch (err) {
      setError(err.message || '로그인에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      minHeight: '100vh', background: 'var(--bg1, #f5f5f5)',
    }}>
      <form onSubmit={handleSubmit} style={{
        background: 'var(--bg2, #fff)', padding: '2rem', borderRadius: '8px',
        boxShadow: '0 2px 8px rgba(0,0,0,0.1)', width: '100%', maxWidth: '400px',
      }}>
        <h2 style={{ marginBottom: '1.5rem', textAlign: 'center' }}>DB Admin 로그인</h2>
        {error && (
          <div style={{ color: 'red', marginBottom: '1rem', textAlign: 'center' }}>{error}</div>
        )}
        <div style={{ marginBottom: '1rem' }}>
          <label style={{ display: 'block', marginBottom: '0.25rem' }}>이메일</label>
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            required autoFocus
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ccc' }}
          />
        </div>
        <div style={{ marginBottom: '1.5rem' }}>
          <label style={{ display: 'block', marginBottom: '0.25rem' }}>비밀번호</label>
          <input
            type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            required
            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #ccc' }}
          />
        </div>
        <button type="submit" disabled={loading} style={{
          width: '100%', padding: '0.75rem', borderRadius: '4px',
          background: 'var(--primary, #2563eb)', color: '#fff', border: 'none',
          cursor: loading ? 'wait' : 'pointer', fontSize: '1rem',
        }}>
          {loading ? '로그인 중...' : '로그인'}
        </button>
      </form>
    </div>
  );
}
```

### New File: `frontend/src/components/AuthGuard.jsx`

```jsx
import { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { getStoredToken, authApi, clearTokens } from '../api/client';

export default function AuthGuard({ children }) {
  const [checking, setChecking] = useState(true);
  const [authed, setAuthed] = useState(false);
  const location = useLocation();

  useEffect(() => {
    const token = getStoredToken();
    if (!token) {
      setAuthed(false);
      setChecking(false);
      return;
    }
    // Verify token is still valid
    authApi.me()
      .then(() => setAuthed(true))
      .catch(() => {
        clearTokens();
        setAuthed(false);
      })
      .finally(() => setChecking(false));
  }, [location.pathname]);

  if (checking) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '40vh' }}>
        인증 확인 중...
      </div>
    );
  }

  if (!authed) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}
```

### File: `frontend/src/App.jsx` (modify)

Replace the entire file with:

```jsx
import { Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import AdminLayout from './layouts/AdminLayout';
import AuthGuard from './components/AuthGuard';

const LoginPage          = lazy(() => import('./pages/Login/LoginPage'));
const Dashboard          = lazy(() => import('./pages/Dashboard/Dashboard'));
const Products           = lazy(() => import('./pages/Products/Products'));
const Prices             = lazy(() => import('./pages/Prices/Prices'));
const ClassificationPage = lazy(() => import('./pages/Classification/ClassificationPage'));
const Analytics          = lazy(() => import('./pages/Analytics/Analytics'));
const InboxPage          = lazy(() => import('./pages/Inbox/InboxPage'));

function Loader() {
  return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', minHeight:'40vh', color:'var(--text3)' }}>
      로딩 중...
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<Loader />}>
      <Routes>
        {/* Public route */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected routes */}
        <Route element={<AuthGuard><AdminLayout /></AuthGuard>}>
          <Route path="/"               element={<Dashboard />} />
          <Route path="/inbox"          element={<InboxPage />} />
          <Route path="/products"       element={<Products />} />
          <Route path="/prices"         element={<Prices />} />
          <Route path="/classification" element={<ClassificationPage />} />
          <Route path="/categories"     element={<Navigate to="/classification" replace />} />
          <Route path="/keywords"       element={<Navigate to="/classification" replace />} />
          <Route path="/analytics"      element={<Analytics />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
```

---

## 9. Step 7 — Seed Admin User & API Keys

### New File: `backend/scripts/create_admin.py`

Run with: `cd packages/db-admin/backend && python -m scripts.create_admin`

```python
"""Create an admin user for the DB Admin panel.

Usage:
    python -m scripts.create_admin
    python -m scripts.create_admin --email admin@example.com --password secret123 --nickname Admin
"""

import argparse
import sys
import os

# Ensure the backend package is importable
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
```

### Backend `__init__.py` for scripts

Create `backend/scripts/__init__.py` (empty file):
```python
```

---

### File: `backend/requirements.txt`

Add the new dependencies:

```
# DB Admin Backend
fastapi>=0.115.0
uvicorn>=0.34.0
sqlalchemy>=2.0.0
alembic>=1.14.0
psycopg2-binary>=2.9.0
pydantic>=2.0
redis>=5.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
```

---

## 10. Test Plan

### Manual Test Cases

#### TC-1: Unauthenticated request → 401
```bash
# Before: returns 200
# After: returns 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/api/products/
# Expected: 401
```

#### TC-2: Login with valid credentials → 200 + tokens
```bash
curl -s -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@walletsavior.local","password":"admin1234"}'
# Expected: {"access_token":"...","refresh_token":"...","token_type":"bearer"}
```

#### TC-3: Login with invalid credentials → 401
```bash
curl -s -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@walletsavior.local","password":"wrong"}'
# Expected: 401
```

#### TC-4: Authenticated GET with JWT → 200
```bash
TOKEN=$(curl -s -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@walletsavior.local","password":"admin1234"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  http://localhost:8002/api/products/
# Expected: 200
```

#### TC-5: Viewer cannot delete → 403
```bash
# Create a viewer user first, then try:
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -X DELETE http://localhost:8002/api/products/1
# Expected: 403
```

#### TC-6: Admin can reset → 200
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8002/api/admin/reset-source \
  -d '{"source":"test","confirm":"DELETE_TEST"}'
# Expected: 200
```

#### TC-7: Service API key can submit ingestion → 200
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: crawler_emart_Abc123xyz" \
  -H "Content-Type: application/json" \
  -X POST http://localhost:8002/api/ingestions \
  -d '{"crawler_name":"emart","items":[]}'
# Expected: 200
```

#### TC-8: Invalid API key → 401
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: invalid-key" \
  -X GET http://localhost:8002/api/products/
# Expected: 401
```

#### TC-9: CORS blocks unknown origin
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Origin: http://evil.example.com" \
  -X OPTIONS http://localhost:8002/api/products/
# Expected: No Access-Control-Allow-Origin in response for evil origin
```

#### TC-10: CORS allows localhost:5175
```bash
curl -s -D - -o /dev/null \
  -H "Origin: http://localhost:5175" \
  -H "Access-Control-Request-Method: GET" \
  -X OPTIONS http://localhost:8002/api/products/
# Expected: Access-Control-Allow-Origin: http://localhost:5175
```

#### TC-11: Health endpoint remains public
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/health
# Expected: 200 (no auth required)
```

#### TC-12: Token refresh works
```bash
curl -s -X POST http://localhost:8002/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH_TOKEN\"}"
# Expected: 200 + new tokens
```

### Automated Test (pytest)

Create `backend/tests/test_auth.py`:

```python
"""Auth middleware integration tests."""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app
from api.auth import hash_password, create_access_token
from services.base import get_session
from storage.models import User, UserRole


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def admin_token():
    session = get_session()
    try:
        user = session.query(User).filter(User.email == "test_admin@test.com").first()
        if not user:
            user = User(
                email="test_admin@test.com",
                hashed_password=hash_password("testpass"),
                nickname="TestAdmin",
                role=UserRole.ADMIN,
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        return create_access_token(user.id, user.email, user.role.value)
    finally:
        session.close()


class TestAuthMiddleware:
    def test_unauthenticated_returns_401(self, client):
        r = client.get("/api/products/")
        assert r.status_code == 401

    def test_health_is_public(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_login_success(self, client, admin_token):
        r = client.post("/api/auth/login", json={
            "email": "test_admin@test.com",
            "password": "testpass",
        })
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_wrong_password(self, client):
        r = client.post("/api/auth/login", json={
            "email": "test_admin@test.com",
            "password": "wrong",
        })
        assert r.status_code == 401

    def test_authenticated_request(self, client, admin_token):
        r = client.get("/api/products/", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200

    def test_get_me(self, client, admin_token):
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200
        assert r.json()["role"] == "admin"
```

---

## 11. Migration & Rollback

### Step-by-Step Deployment Order

1. **Install dependencies** (non-breaking):
   ```bash
   cd packages/db-admin/backend
   pip install python-jose[cryptography] passlib[bcrypt]
   ```

2. **Add config changes** (`config.py`) — old code still works since new fields have defaults.

3. **Create `api/auth.py`** and `api/routes/auth_routes.py` — new files, no impact on existing routes.

4. **Create admin user** (run once):
   ```bash
   cd packages/db-admin/backend
   python -m scripts.create_admin --email admin@walletsavior.local --password <secure-password>
   ```

5. **Update `api/app.py`** — CORS restriction + auth router registration. **This is the breaking change for CORS.** Test that the frontend still works at `localhost:5175`.

6. **Update route files one at a time** — Add `Depends(require_xxx)` to each file. Deploy and test each file individually:
   - Start with `admin.py` (highest risk endpoints)
   - Then `ingestion.py` (inter-service)
   - Then `products.py`, `categories.py`, `keywords.py`
   - Then `prices.py`, `analytics.py`, `dashboard.py`

7. **Update frontend** — Deploy `client.js` changes, `LoginPage`, `AuthGuard`, and `App.jsx` together. The frontend will now redirect to `/login` for unauthenticated users.

8. **Update crawler pipeline** — Add `INGESTION_API_KEY` env var and header to `pipeline.py`.

### Rollback Plan

If issues arise:
- **Quick rollback**: Remove `Depends(require_xxx)` from route endpoints — routes go back to public.
- **CORS rollback**: Set `CORS_ALLOWED_ORIGINS=*` env var (not recommended but instant).
- **Frontend rollback**: Remove `<AuthGuard>` wrapper from `App.jsx` — all pages accessible again.
- **Database**: No schema migrations needed. The `users` table already exists with `hashed_password` and `role` fields.

### Environment Variable Checklist

| Variable | Required | Default | Example |
|----------|----------|---------|---------|
| `JWT_SECRET` | **Yes (production)** | `CHANGE-ME-IN-PRODUCTION-32-chars!` | `a1b2c3d4e5f6...` (32+ chars) |
| `JWT_ACCESS_EXPIRE_MIN` | No | `60` | `30` |
| `JWT_REFRESH_EXPIRE_DAYS` | No | `7` | `14` |
| `CORS_ALLOWED_ORIGINS` | No | `http://localhost:5175,...` | `https://admin.example.com` |
| `SERVICE_API_KEYS` | **Yes (if crawlers run)** | `""` (empty = no service keys) | `key1:service,key2:service` |
| `INGESTION_API_KEY` | **Yes (crawler side)** | `""` | `key1` (must match db-admin) |

---

> **End of spec.** The implementation agent should be able to code each section directly from the code blocks above. The order in Section 11 ensures no downtime — each step is independently deployable and reversible.
