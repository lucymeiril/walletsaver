# Website Privacy, Audit Logging & Hardening — Implementation Spec

> **Sub-project:** `packages/website`  
> **Stack:** FastAPI (Python) backend · React (Vite) frontend  
> **Source Audits:** `website-code-audit.md`, `website-arch-audit.md`  
> **Date:** 2025-07-16  

---

## Table of Contents

1. [User Data Privacy](#1-user-data-privacy)
2. [Audit Logging](#2-audit-logging)
3. [Bind Address Hardening](#3-bind-address-hardening)
4. [Config Security — Secrets to Environment Variables](#4-config-security)
5. [Frontend Security — localStorage & Zustand](#5-frontend-security)
6. [Community Moderation — Spam & Content Limits](#6-community-moderation)
7. [Test Cases](#7-test-cases)
8. [Environment Variable Reference](#8-environment-variable-reference)
9. [Rollout Order](#9-rollout-order)

---

## 1. User Data Privacy

**Audit refs:** Arch `User Data Privacy Assessment`, Code `M-09`

### 1.1 Data Minimization

**Current state:** The Zustand store persists purchase interests (`favorites`), search history (`recentSearches`), shopping habits (`shoppingList`), and financial targets (`priceAlerts`) into `localStorage`. The backend stores no analytics or tracking data beyond community content and auth state.

**Goal:** Only persist UI preferences client-side. Behavioral data stays in-memory or moves server-side behind authentication.

#### Changes

| # | File | Change |
|---|------|--------|
| 1a | `frontend/src/stores/appStore.js` (lines 142-149) | Remove `favorites`, `recentSearches`, `shoppingList`, `priceAlerts` from `partialize`. Keep only `theme` and `filterPreferences`. |
| 1b | `frontend/src/stores/appStore.js` | Add a one-time migration to clear legacy persisted sensitive data on load. |

**Before (`appStore.js:142-149`):**
```javascript
partialize: (state) => ({
    theme: state.theme,
    favorites: state.favorites,
    recentSearches: state.recentSearches,
    shoppingList: state.shoppingList,
    priceAlerts: state.priceAlerts,
    filterPreferences: state.filterPreferences,
}),
```

**After:**
```javascript
partialize: (state) => ({
    theme: state.theme,
    filterPreferences: state.filterPreferences,
    // favorites, recentSearches, shoppingList, priceAlerts
    // are kept in-memory only — not persisted to localStorage.
}),
version: 2,
migrate: (persisted, version) => {
    if (version < 2) {
        // Strip sensitive behavioral data from old persisted state
        const { favorites, recentSearches, shoppingList, priceAlerts, ...safe } = persisted;
        return safe;
    }
    return persisted;
},
```

### 1.2 PII Encryption at Rest (Post-DB-Migration Prep)

**Current state:** Users are stored in-memory (`auth.py:16-18`). When migrated to SQLite/PostgreSQL (per Code finding `H-11`), email addresses and OAuth tokens will be persisted in plaintext.

**Goal:** Encrypt PII fields (email, OAuth IDs) at rest using Fernet symmetric encryption.

#### Changes

| # | File | Change |
|---|------|--------|
| 2a | `backend/services/crypto_service.py` | **New file** — Fernet encryption wrapper |
| 2b | `backend/config.py` | Add `DATA_ENCRYPTION_KEY` env var |

**New file — `backend/services/crypto_service.py`:**
```python
"""
PII 필드 암호화 — Fernet 대칭 키 방식.
DB 마이그레이션 후 User 모델의 email, oauth_id 필드에 적용한다.
"""
import os
from cryptography.fernet import Fernet

_key = os.getenv("DATA_ENCRYPTION_KEY")
if not _key:
    import warnings
    warnings.warn(
        "DATA_ENCRYPTION_KEY not set — PII encryption disabled. "
        "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
        stacklevel=2,
    )
    _fernet = None
else:
    _fernet = Fernet(_key.encode() if isinstance(_key, str) else _key)


def encrypt_pii(plaintext: str) -> str:
    """Encrypt a PII string. Returns plaintext unchanged if key is not configured."""
    if not _fernet or not plaintext:
        return plaintext
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_pii(ciphertext: str) -> str:
    """Decrypt a PII string. Returns ciphertext unchanged if key is not configured."""
    if not _fernet or not ciphertext:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext  # Already plaintext or corrupt — return as-is
```

**Usage (post-DB-migration, in the User SQLAlchemy model):**
```python
from services.crypto_service import encrypt_pii, decrypt_pii

# On write:
user.email_encrypted = encrypt_pii(user_email)

# On read:
email = decrypt_pii(user.email_encrypted)
```

**Environment variable:**
```
DATA_ENCRYPTION_KEY=   # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 1.3 Account Deletion Endpoint

**Goal:** Users must be able to delete their account and all associated data (GDPR Right to Erasure).

#### Changes

| # | File | Change |
|---|------|--------|
| 3a | `backend/api/routes/auth.py` | Add `DELETE /api/auth/me` endpoint |

**New endpoint:**
```python
@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(user: dict = Depends(require_auth)):
    """계정 삭제 — 모든 사용자 데이터(게시글, 댓글, 투표) 삭제."""
    from api.routes.community import _SessionLocal, _use_db
    from models.community import PostModel, CommentModel, VoteModel

    if _use_db and _SessionLocal:
        with _SessionLocal() as session:
            # Delete votes, comments, posts in order (FK constraints)
            session.query(VoteModel).filter(VoteModel.user_id == user["id"]).delete()
            session.query(CommentModel).filter(CommentModel.author_id == user["id"]).delete()
            session.query(PostModel).filter(PostModel.author_id == user["id"]).delete()
            session.commit()

    # Remove from in-memory store
    email = user.get("email")
    if email and email in _users_db:
        del _users_db[email]

    audit_logger.info("account_deleted", extra={
        "user_id": user["id"],
        "ip": "redacted",  # Privacy: don't log IP on deletion
    })
    return Response(status_code=204)
```

---

## 2. Audit Logging

**Audit refs:** Code `M-06` (No Authentication Audit Logging), Arch `Phase 4` (Log review)

### 2.1 Logging Infrastructure

**Current state:** Scattered `logging.getLogger(__name__)` with no centralized config. No structured logging. No auth event logging.

**Goal:** Structured JSON audit log for security-relevant events, written to a dedicated file and stdout.

#### Changes

| # | File | Change |
|---|------|--------|
| 4a | `backend/services/audit_logger.py` | **New file** — Structured audit logger |
| 4b | `backend/api/app.py` | Initialize logging on startup |

**New file — `backend/services/audit_logger.py`:**
```python
"""
감사 로깅 — 보안 관련 이벤트 구조화 로깅.

모든 인증, 콘텐츠 변경, 관리자 작업을 JSON 형식으로 기록한다.
"""
import logging
import json
import os
from datetime import datetime, timezone
from typing import Optional


_LOG_DIR = os.getenv("AUDIT_LOG_DIR", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "audit.jsonl")


class _JsonFormatter(logging.Formatter):
    """한 줄 JSON 로그 포매터."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "module": record.module,
        }
        # Merge extra fields (ip, user_id, action, etc.)
        for key in ("user_id", "email", "ip", "action", "resource",
                     "resource_id", "detail", "status", "provider"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False)


def setup_audit_logging() -> logging.Logger:
    """감사 로거 초기화 — 앱 시작 시 한 번 호출."""
    os.makedirs(_LOG_DIR, exist_ok=True)

    logger = logging.getLogger("audit")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        # File handler — append JSONL
        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setFormatter(_JsonFormatter())
        logger.addHandler(fh)

        # Console handler — same JSON format for log aggregators
        ch = logging.StreamHandler()
        ch.setFormatter(_JsonFormatter())
        logger.addHandler(ch)

    return logger


# Module-level singleton
audit_logger = setup_audit_logging()


# --- Convenience helpers ---

def log_auth_event(
    action: str,
    *,
    user_id: Optional[int] = None,
    email: Optional[str] = None,
    ip: Optional[str] = None,
    status: str = "success",
    detail: Optional[str] = None,
    provider: Optional[str] = None,
):
    """
    인증 이벤트 기록.

    Actions: login, login_failed, register, logout, token_refresh,
             token_refresh_failed, oauth_login, oauth_callback,
             oauth_failed, password_change, account_deleted
    """
    audit_logger.info(action, extra={
        "user_id": user_id,
        "email": email,
        "ip": ip,
        "action": action,
        "status": status,
        "detail": detail,
        "provider": provider,
    })


def log_content_event(
    action: str,
    *,
    user_id: int,
    resource: str,
    resource_id: Optional[int] = None,
    ip: Optional[str] = None,
    detail: Optional[str] = None,
):
    """
    콘텐츠 변경 이벤트 기록.

    Actions: post_created, post_updated, post_deleted,
             comment_created, comment_deleted,
             vote_cast, vote_removed,
             report_submitted
    """
    audit_logger.info(action, extra={
        "user_id": user_id,
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "ip": ip,
        "detail": detail,
    })


def log_admin_event(
    action: str,
    *,
    admin_id: int,
    ip: Optional[str] = None,
    resource: Optional[str] = None,
    resource_id: Optional[int] = None,
    detail: Optional[str] = None,
):
    """
    관리자 작업 이벤트 기록.

    Actions: admin_login, user_banned, post_removed,
             crawler_triggered, config_changed
    """
    audit_logger.warning(action, extra={
        "user_id": admin_id,
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "ip": ip,
        "detail": detail,
    })
```

### 2.2 Auth Route Instrumentation

| # | File | Location | Audit call |
|---|------|----------|------------|
| 5a | `backend/api/routes/auth.py` | `register()` success (after line 44) | `log_auth_event("register", user_id=user["id"], email=data.email, ip=request.client.host)` |
| 5b | `backend/api/routes/auth.py` | `register()` — add `request: Request` param | Import `Request` from FastAPI |
| 5c | `backend/api/routes/auth.py` | `login()` success (after line 53) | `log_auth_event("login", user_id=user["id"], email=data.email, ip=request.client.host)` |
| 5d | `backend/api/routes/auth.py` | `login()` failure (line 52 HTTPException) | `log_auth_event("login_failed", email=data.email, ip=request.client.host, status="failed")` |
| 5e | `backend/api/routes/auth.py` | `refresh()` success | `log_auth_event("token_refresh", user_id=int(payload["sub"]), ip=request.client.host)` |
| 5f | `backend/api/routes/auth.py` | `refresh()` failure | `log_auth_event("token_refresh_failed", ip=request.client.host, status="failed")` |
| 5g | `backend/api/routes/auth.py` | `oauth_callback()` success | `log_auth_event("oauth_callback", user_id=user["id"], email=user_info.email, ip=request.client.host, provider=provider)` |
| 5h | `backend/api/routes/auth.py` | `oauth_callback()` failure | `log_auth_event("oauth_failed", ip=request.client.host, status="failed", provider=provider, detail=str(e))` |

**Exact code changes for `auth.py`:**

Add at top of file:
```python
from fastapi import APIRouter, HTTPException, status, Request
from services.audit_logger import log_auth_event
```

Modify `register`:
```python
@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, request: Request):
    # ... existing logic ...
    _users_db[data.email] = user
    _next_id += 1

    log_auth_event("register", user_id=user["id"], email=data.email,
                   ip=request.client.host if request.client else "unknown")
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    return TokenResponse(**tokens)
```

Modify `login`:
```python
@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request):
    user = _users_db.get(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        log_auth_event("login_failed", email=data.email,
                       ip=request.client.host if request.client else "unknown",
                       status="failed")
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    log_auth_event("login", user_id=user["id"], email=data.email,
                   ip=request.client.host if request.client else "unknown")
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    return TokenResponse(**tokens)
```

Modify `refresh`:
```python
@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: TokenRefresh, request: Request):
    payload = decode_token(data.refresh_token)
    if not payload or payload.get("type") != "refresh":
        log_auth_event("token_refresh_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed")
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    log_auth_event("token_refresh", user_id=int(payload["sub"]),
                   ip=request.client.host if request.client else "unknown")
    tokens = create_token_pair(int(payload["sub"]), payload["email"], payload["role"])
    return TokenResponse(**tokens)
```

Modify `oauth_callback`:
```python
@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, request: Request):
    global _next_id
    try:
        token_data = await exchange_code_for_token(provider, code)
        user_info = await get_user_info(provider, token_data["access_token"])
        # ... existing user lookup/creation ...

        log_auth_event("oauth_callback", user_id=user["id"], email=user_info.email,
                       ip=request.client.host if request.client else "unknown",
                       provider=provider)
        tokens = create_token_pair(user["id"], user["email"], user["role"])
        return RedirectResponse(url=f"...")
    except Exception as e:
        log_auth_event("oauth_failed",
                       ip=request.client.host if request.client else "unknown",
                       status="failed", provider=provider, detail=str(e))
        raise HTTPException(status_code=400, detail=f"OAuth 인증 실패: {str(e)}")
```

### 2.3 Community Route Instrumentation

| # | File | Location | Audit call |
|---|------|----------|------------|
| 6a | `backend/api/routes/community.py` | `create_post()` after `session.commit()` | `log_content_event("post_created", user_id=user["id"], resource="post", resource_id=post.id, ip=request.client.host)` |
| 6b | `backend/api/routes/community.py` | `create_comment()` after `session.commit()` | `log_content_event("comment_created", user_id=user["id"], resource="comment", resource_id=comment.id, ip=request.client.host)` |
| 6c | `backend/api/routes/community.py` | `vote_post()` after `session.commit()` | `log_content_event("vote_cast", user_id=user["id"], resource="vote", resource_id=post_id, detail=body.vote_type)` |
| 6d | `backend/api/routes/community.py` | `delete_post()` | `log_content_event("post_deleted", user_id=user["id"], resource="post", resource_id=post_id)` |
| 6e | `backend/api/routes/community.py` | `delete_comment()` | `log_content_event("comment_deleted", user_id=user["id"], resource="comment", resource_id=comment_id)` |

**Exact code — add at top of `community.py`:**
```python
from fastapi import Request
from services.audit_logger import log_content_event
```

**Add `request: Request` as parameter to `create_post`, `create_comment`, and all state-changing endpoints.**

### 2.4 Hotdeal Route Instrumentation

| # | File | Location | Audit call |
|---|------|----------|------------|
| 7a | `backend/api/routes/hotdeals.py` | `vote_hotdeal()` after success | `log_content_event("vote_cast", user_id=0, resource="hotdeal_vote", resource_id=hotdeal_id, ip=client_ip)` |
| 7b | `backend/api/routes/hotdeals.py` | `report_hotdeal()` after success | `log_content_event("report_submitted", user_id=0, resource="hotdeal_report", resource_id=hotdeal_id, ip=client_ip, detail=reason[:200])` |
| 7c | `backend/api/routes/hotdeals.py` | `add_hotdeal_comment()` | `log_content_event("comment_created", user_id=0, resource="hotdeal_comment", resource_id=hotdeal_id, ip=client_ip)` |
| 7d | `backend/api/routes/hotdeals.py` | `delete_hotdeal_comment()` | `log_content_event("comment_deleted", user_id=0, resource="hotdeal_comment", resource_id=comment_id, ip=client_ip)` |

### 2.5 Admin Actions Instrumentation

| # | File | Location | Audit call |
|---|------|----------|------------|
| 8a | `backend/api/routes/crawlers.py` | Crawler trigger endpoints (after adding auth) | `log_admin_event("crawler_triggered", admin_id=user["id"], resource="crawler", detail=name, ip=request.client.host)` |

### 2.6 Log Rotation & Retention

**New file — `backend/logging_config.py`:**
```python
"""
로깅 설정 — 앱 시작 시 main.py에서 호출.
"""
import logging
import logging.handlers
import os

def configure_logging():
    """루트 로거 설정 — 콘솔 + 파일 로테이션."""
    log_dir = os.getenv("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)

    # Root logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Console
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root.addHandler(console)

    # Rotating file (10 MB, keep 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    root.addHandler(file_handler)
```

**Update `backend/main.py` — add before `app = create_app()`:**
```python
from logging_config import configure_logging
configure_logging()
```

### 2.7 Audit Log Output Format

Each line in `logs/audit.jsonl` is a self-contained JSON object:
```json
{"ts":"2025-07-16T14:30:00+00:00","level":"INFO","event":"login","module":"audit_logger","user_id":42,"email":"user@example.com","ip":"127.0.0.1","action":"login","status":"success"}
{"ts":"2025-07-16T14:30:05+00:00","level":"INFO","event":"login_failed","module":"audit_logger","email":"attacker@evil.com","ip":"192.168.1.100","action":"login_failed","status":"failed"}
{"ts":"2025-07-16T14:31:00+00:00","level":"INFO","event":"post_created","module":"audit_logger","user_id":42,"action":"post_created","resource":"post","resource_id":15,"ip":"127.0.0.1"}
```

---

## 3. Bind Address Hardening

**Audit refs:** Arch `MEDIUM-07`, Code `L-02`

### 3.1 Change Default Bind from `0.0.0.0` to `127.0.0.1`

**Current state:** `backend/config.py:46` — `API_HOST = os.getenv("API_HOST", "0.0.0.0")`  
**Risk:** Binds to all network interfaces by default, exposing the dev server to the local network.

#### Changes

| # | File | Line | Change |
|---|------|------|--------|
| 9a | `backend/config.py` | 46 | Change default from `"0.0.0.0"` to `"127.0.0.1"` |

**Before:**
```python
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
```

**After:**
```python
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")
```

**Docker override:** In `docker-compose.yml` and `docker-compose.dev.yml`, set:
```yaml
environment:
  - API_HOST=0.0.0.0   # Required inside container to accept connections from Docker network
```

**Production override:** When deploying behind a reverse proxy (nginx), keep `127.0.0.1` and let nginx handle external traffic.

---

## 4. Config Security

**Audit refs:** Code `C-04` (Hardcoded JWT Secret), `L-03` (Database URL Credentials), Arch `CRITICAL-04`, `LOW-01`

### 4.1 JWT Secret — Fail on Missing

| # | File | Line | Change |
|---|------|------|--------|
| 10a | `backend/services/auth_service.py` | 9 | Remove fallback default; crash at startup |

**Before (`auth_service.py:9`):**
```python
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
```

**After:**
```python
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "FATAL: JWT_SECRET_KEY environment variable is required. "
        "Generate one: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )
```

### 4.2 Database URL — Fail on Missing (Production)

| # | File | Line | Change |
|---|------|------|--------|
| 11a | `backend/config.py` | 17 | Remove hardcoded credentials from default |

**Before:**
```python
DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/wallet_guardian")
```

**After:**
```python
_DEFAULT_DB = f"sqlite:///{BASE_DIR / 'walletguardian.db'}"
DATABASE_URL: str = os.getenv("DATABASE_URL", _DEFAULT_DB)
```

This removes hardcoded PostgreSQL credentials from source code. The default falls back to the local SQLite database (which the project already uses). In production, `DATABASE_URL` must be set explicitly.

### 4.3 OAuth Secrets — Validate at Startup

| # | File | Change |
|---|------|--------|
| 12a | `backend/services/oauth_service.py` | Add startup validation for OAuth client IDs/secrets when providers are used |

**Add at module level (after `OAuthConfig` class, around line 59):**
```python
def validate_oauth_config(provider: str) -> None:
    """OAuth 설정 검증 — 빈 client_id/client_secret 시 명확한 에러."""
    config = OAuthConfig.get(provider)
    if not config["client_id"] or not config["client_secret"]:
        raise ValueError(
            f"OAuth provider '{provider}' requires {provider.upper()}_CLIENT_ID "
            f"and {provider.upper()}_CLIENT_SECRET environment variables."
        )
```

**Use in `get_oauth_login_url`:**
```python
def get_oauth_login_url(provider: str) -> str:
    validate_oauth_config(provider)  # Fail early with clear message
    config = OAuthConfig.get(provider)
    # ... rest of function
```

### 4.4 OAuth Redirect Base — Require Env Var for Production

| # | File | Line | Change |
|---|------|------|--------|
| 13a | `backend/services/oauth_service.py` | 61 | Keep default for dev, log warning |

**After:**
```python
REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")
if REDIRECT_BASE == "http://localhost:8000":
    import warnings
    warnings.warn(
        "OAUTH_REDIRECT_BASE is using localhost default. "
        "Set OAUTH_REDIRECT_BASE for production deployment.",
        stacklevel=2,
    )
```

### 4.5 CORS Origins — Environment Variable

| # | File | Line | Change |
|---|------|------|--------|
| 14a | `backend/api/app.py` | 35-46 | Read origins from `CORS_ORIGINS` env var |

**Before:**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**After:**
```python
_DEFAULT_ORIGINS = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### 4.6 Complete Environment Variable List (New)

Add to `backend/.env.example`:
```env
# === Required ===
JWT_SECRET_KEY=                    # python -c "import secrets; print(secrets.token_urlsafe(64))"

# === Database ===
DATABASE_URL=sqlite:///walletguardian.db   # Or postgresql://...

# === Server ===
API_HOST=127.0.0.1                 # Use 0.0.0.0 inside Docker
API_PORT=8000
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# === OAuth (optional — required only if OAuth login is enabled) ===
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
KAKAO_CLIENT_ID=
KAKAO_CLIENT_SECRET=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
OAUTH_REDIRECT_BASE=http://localhost:8000  # Must be HTTPS in production

# === API Keys (optional) ===
KAMIS_API_KEY=
KAMIS_API_ID=
OPINET_API_KEY=
KOSIS_API_KEY=

# === PII Encryption (optional — recommended for production) ===
DATA_ENCRYPTION_KEY=               # python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# === Logging ===
AUDIT_LOG_DIR=logs
LOG_DIR=logs
```

---

## 5. Frontend Security

**Audit refs:** Code `C-02` (JWT in localStorage), `M-09` (Sensitive data in localStorage)

### 5.1 Remove JWT Tokens from localStorage

**Current state:** `access_token` and `refresh_token` stored in `localStorage` at multiple locations.

**Goal:** Move tokens to `httpOnly` cookies set by the backend. The frontend never touches raw token values.

> **Note:** This is a coordinated backend + frontend change. It is listed here for completeness but requires the token-to-cookie migration (Code `C-02` fix) to be implemented first. Section 5.1 defines the **frontend half** of that migration.

#### Phase A — Immediate (Reduce Exposure)

Until the full cookie migration is done, reduce what's stored:

| # | File | Change |
|---|------|--------|
| 15a | `frontend/src/services/api.js` | Use `sessionStorage` instead of `localStorage` for `access_token` (cleared on tab close) |
| 15b | `frontend/src/services/authService.js` | Same — `sessionStorage` for `refresh_token` |

**api.js changes:**
```javascript
// Before:
this.token = localStorage.getItem('access_token');
// After:
this.token = sessionStorage.getItem('access_token');

// Before:
localStorage.setItem('access_token', token);
// After:
sessionStorage.setItem('access_token', token);

// Before:
localStorage.removeItem('access_token');
// After:
sessionStorage.removeItem('access_token');
```

**authService.js changes:**
```javascript
// Before:
localStorage.setItem('refresh_token', data.refresh_token);
// After:
sessionStorage.setItem('refresh_token', data.refresh_token);

// Before:
localStorage.removeItem('refresh_token');
// After:
sessionStorage.removeItem('refresh_token');
```

**Also add a cleanup for old localStorage tokens (run once on import):**
```javascript
// api.js — top of file, after imports
// One-time migration: clear legacy localStorage tokens
if (localStorage.getItem('access_token')) {
    sessionStorage.setItem('access_token', localStorage.getItem('access_token'));
    localStorage.removeItem('access_token');
}
if (localStorage.getItem('refresh_token')) {
    sessionStorage.setItem('refresh_token', localStorage.getItem('refresh_token'));
    localStorage.removeItem('refresh_token');
}
```

#### Phase B — Full Cookie Migration (Backend + Frontend)

This is the complete solution (requires backend changes from the auth hardening spec):

**Backend — set cookies on login/refresh responses:**
```python
# auth.py — in login() and register()
response = JSONResponse(content={"token_type": "bearer", "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60})
response.set_cookie(
    key="access_token",
    value=tokens["access_token"],
    httponly=True,
    secure=True,       # Requires HTTPS
    samesite="strict",
    max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    path="/api",
)
response.set_cookie(
    key="refresh_token",
    value=tokens["refresh_token"],
    httponly=True,
    secure=True,
    samesite="strict",
    max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    path="/api/auth/refresh",  # Only sent to refresh endpoint
)
return response
```

**Frontend — remove all token storage, rely on automatic cookie sending:**
```javascript
// api.js — fetch calls include credentials
const response = await fetch(url, {
    ...options,
    credentials: 'include',  // Send cookies
    // Remove Authorization header — cookies handle auth
});
```

### 5.2 Secure Zustand Persist

**Current state:** `wallet-savior-store` persists to `localStorage` with no encryption or integrity check.

#### Changes (already covered in Section 1.1)

Summary of `appStore.js` changes:
1. **Reduce persisted fields** — only `theme` and `filterPreferences`
2. **Add version + migrate** — strips old sensitive data on upgrade
3. **Add storage encryption (optional hardening):**

```javascript
import { persist, createJSONStorage } from 'zustand/middleware';

// Optional: encrypt localStorage for defense-in-depth
const secureStorage = {
    getItem: (name) => {
        const raw = localStorage.getItem(name);
        if (!raw) return null;
        try {
            return JSON.parse(atob(raw));  // Basic obfuscation (not encryption)
        } catch {
            return JSON.parse(raw);  // Fallback for non-encoded
        }
    },
    setItem: (name, value) => {
        localStorage.setItem(name, btoa(JSON.stringify(value)));
    },
    removeItem: (name) => localStorage.removeItem(name),
};
```

> **Note:** True client-side encryption is impossible (the key must be in JS). The obfuscation prevents casual inspection. The real fix is to not persist sensitive data at all (Section 1.1).

---

## 6. Community Moderation

**Audit refs:** Arch `MEDIUM-03` (Guest posts without moderation), Code `H-07`, `H-01`, `C-09`

### 6.1 Content Length Limits (Pydantic Schemas)

| # | File | Change |
|---|------|--------|
| 16a | `backend/api/schemas/community.py` | Add field constraints to `PostCreate` |
| 16b | `backend/api/schemas/community.py` | Add field constraints to `CommentCreate` |
| 16c | `backend/api/schemas/community.py` | Add field constraints to `VoteRequest` |

**Before (`PostCreate`):**
```python
class PostCreate(BaseModel):
    title: str
    content: str
    post_type: PostType = PostType.FREE
    category: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    url: Optional[str] = None
    images: Optional[list] = None
```

**After:**
```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional
import re

class PostCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    content: str = Field(..., min_length=1, max_length=50_000)
    post_type: PostType = PostType.FREE
    category: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0, le=100_000_000)
    original_price: Optional[float] = Field(None, ge=0, le=100_000_000)
    url: Optional[str] = Field(None, max_length=2048)
    images: Optional[list[str]] = Field(None, max_length=10)

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, v):
        if v and not re.match(r'^https?://', v):
            raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다")
        return v

    @field_validator("images")
    @classmethod
    def validate_images(cls, v):
        if v:
            for img_url in v:
                if not isinstance(img_url, str):
                    raise ValueError("이미지 URL은 문자열이어야 합니다")
                if len(img_url) > 500_000:  # ~375KB base64
                    raise ValueError("이미지 데이터가 너무 큽니다 (최대 500KB)")
        return v
```

**Before (`CommentCreate`):**
```python
class CommentCreate(BaseModel):
    content: str
    parent_id: Optional[int] = None
```

**After:**
```python
class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5_000)
    parent_id: Optional[int] = None
```

**Before (`VoteRequest`):**
```python
class VoteRequest(BaseModel):
    vote_type: str  # "hot" or "not"
```

**After:**
```python
from enum import Enum

class VoteType(str, Enum):
    HOT = "hot"
    NOT = "not"

class VoteRequest(BaseModel):
    vote_type: VoteType
```

### 6.2 Hotdeal Endpoints — Pydantic Models for Raw `request.json()`

**Audit ref:** Code `M-10`

| # | File | Change |
|---|------|--------|
| 17a | `backend/api/schemas/hotdeals.py` | **New file** — Pydantic models for hotdeal endpoints |
| 17b | `backend/api/routes/hotdeals.py` | Replace `request.json()` with Pydantic models |

**New file — `backend/api/schemas/hotdeals.py`:**
```python
"""핫딜 관련 요청 스키마"""
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class HotdealVoteType(str, Enum):
    HOT = "hot"
    NOT = "not"


class HotdealVoteRequest(BaseModel):
    vote_type: HotdealVoteType = HotdealVoteType.HOT


class HotdealReportRequest(BaseModel):
    reason: str = Field("", max_length=1000)


class HotdealCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    author: str = Field("익명", max_length=50)
```

**Update `hotdeals.py` — vote endpoint:**
```python
from api.schemas.hotdeals import HotdealVoteRequest, HotdealReportRequest, HotdealCommentCreate

@router.post("/{hotdeal_id}/vote")
async def vote_hotdeal(request: Request, hotdeal_id: int, body: HotdealVoteRequest):
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(f"vote:{client_ip}"):
        raise HTTPException(status_code=429, detail="Too many requests")
    # Use body.vote_type instead of manual parsing
    # ...
```

### 6.3 Basic Spam Prevention

| # | File | Change |
|---|------|--------|
| 18a | `backend/services/spam_filter.py` | **New file** — Simple spam detection |

**New file — `backend/services/spam_filter.py`:**
```python
"""
스팸 필터 — 커뮤니티 콘텐츠 기본 스팸 방지.

규칙 기반 필터: 중복 제출 방지, 링크 스팸, 반복 문자 감지.
"""
import re
import time
from collections import defaultdict
from typing import Optional


# Per-user submission tracking (user_id → list of timestamps)
_submission_times: dict[int, list[float]] = defaultdict(list)
_SUBMISSION_WINDOW = 60  # seconds
_MAX_SUBMISSIONS_PER_WINDOW = 5


class SpamCheckResult:
    def __init__(self, is_spam: bool, reason: Optional[str] = None):
        self.is_spam = is_spam
        self.reason = reason


def check_rate(user_id: int) -> SpamCheckResult:
    """사용자별 제출 속도 확인."""
    now = time.time()
    times = _submission_times[user_id]
    times = [t for t in times if now - t < _SUBMISSION_WINDOW]
    _submission_times[user_id] = times

    if len(times) >= _MAX_SUBMISSIONS_PER_WINDOW:
        return SpamCheckResult(True, "너무 빠르게 작성하고 있습니다. 잠시 후 다시 시도해주세요.")

    times.append(now)
    return SpamCheckResult(False)


def check_content(text: str) -> SpamCheckResult:
    """콘텐츠 스팸 패턴 확인."""
    if not text or not text.strip():
        return SpamCheckResult(True, "내용을 입력해주세요.")

    # Excessive links (>5 URLs in a single post)
    url_count = len(re.findall(r'https?://\S+', text))
    if url_count > 5:
        return SpamCheckResult(True, "링크가 너무 많습니다. 최대 5개까지 허용됩니다.")

    # Repeated characters (e.g., "aaaaaaaaaa" — 10+ same char)
    if re.search(r'(.)\1{9,}', text):
        return SpamCheckResult(True, "반복 문자가 너무 많습니다.")

    # Very short content that is likely spam
    stripped = re.sub(r'\s+', '', text)
    if len(stripped) < 2:
        return SpamCheckResult(True, "내용이 너무 짧습니다.")

    return SpamCheckResult(False)


def check_spam(user_id: int, title: str, content: str) -> SpamCheckResult:
    """게시글 스팸 종합 검사."""
    # Rate check
    rate_result = check_rate(user_id)
    if rate_result.is_spam:
        return rate_result

    # Title check
    title_result = check_content(title)
    if title_result.is_spam:
        return SpamCheckResult(True, f"제목: {title_result.reason}")

    # Content check
    content_result = check_content(content)
    if content_result.is_spam:
        return content_result

    return SpamCheckResult(False)


def check_comment_spam(user_id: int, content: str) -> SpamCheckResult:
    """댓글 스팸 검사."""
    rate_result = check_rate(user_id)
    if rate_result.is_spam:
        return rate_result

    return check_content(content)
```

### 6.4 Integrate Spam Filter into Community Routes

| # | File | Change |
|---|------|--------|
| 19a | `backend/api/routes/community.py` | Add spam check before post creation |
| 19b | `backend/api/routes/community.py` | Add spam check before comment creation |

**In `create_post()` — add after auth check, before DB write:**
```python
from services.spam_filter import check_spam, check_comment_spam

@router.post("")
async def create_post(body: PostCreate, request: Request, user: dict = Depends(get_current_user)):
    if not user:
        user = {"id": 0, "email": "guest@wallet.local", "nickname": "게스트", "role": "guest"}

    # Spam check
    spam_result = check_spam(user["id"], body.title, body.content)
    if spam_result.is_spam:
        raise HTTPException(status_code=429, detail=spam_result.reason)

    # ... existing DB logic ...
```

**In `create_comment()` — add before DB write:**
```python
@router.post("/{post_id}/comments")
async def create_comment(post_id: int, body: CommentCreate, request: Request, user: dict = Depends(require_auth)):
    # Spam check
    spam_result = check_comment_spam(user["id"], body.content)
    if spam_result.is_spam:
        raise HTTPException(status_code=429, detail=spam_result.reason)

    # ... existing DB logic ...
```

### 6.5 Guest Post Restrictions

**Audit ref:** Code `H-07`

**Option A (Recommended): Require authentication for all community posts.**

```python
# community.py — change create_post
@router.post("")
async def create_post(body: PostCreate, request: Request, user: dict = Depends(require_auth)):
    # Remove guest fallback entirely — require_auth will return 401 if not authenticated
    # ... existing DB logic ...
```

**Option B (If guest posts are a requirement): Add stricter guest limits.**

```python
@router.post("")
async def create_post(body: PostCreate, request: Request, user: dict = Depends(get_current_user)):
    if not user:
        user = {"id": 0, "email": "guest@wallet.local", "nickname": "게스트", "role": "guest"}
        # Stricter rate limit for guests: 2 posts per 10 minutes
        guest_spam = check_rate_strict(user_id=0, window=600, max_count=2)
        if guest_spam.is_spam:
            raise HTTPException(status_code=429, detail="게스트 작성 제한: 10분당 2개까지 가능합니다.")
```

---

## 7. Test Cases

### 7.1 Config Security Tests

**File:** `backend/tests/test_config_security.py`

```python
"""설정 보안 테스트 — 환경 변수 검증."""
import os
import pytest


class TestJWTSecretRequired:
    """JWT_SECRET_KEY 미설정 시 시작 실패 확인."""

    def test_missing_jwt_secret_raises(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            # Force reimport to trigger validation
            import importlib
            import services.auth_service
            importlib.reload(services.auth_service)

    def test_jwt_secret_set_succeeds(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-at-least-32-chars-long-for-security")
        import importlib
        import services.auth_service
        importlib.reload(services.auth_service)
        assert services.auth_service.SECRET_KEY == "test-secret-at-least-32-chars-long-for-security"


class TestBindAddress:
    """기본 바인드 주소 확인."""

    def test_default_bind_is_localhost(self, monkeypatch):
        monkeypatch.delenv("API_HOST", raising=False)
        import importlib
        import config
        importlib.reload(config)
        assert config.API_HOST == "127.0.0.1"

    def test_docker_override_accepted(self, monkeypatch):
        monkeypatch.setenv("API_HOST", "0.0.0.0")
        import importlib
        import config
        importlib.reload(config)
        assert config.API_HOST == "0.0.0.0"


class TestDatabaseURL:
    """DATABASE_URL에 하드코딩된 자격증명 없음 확인."""

    def test_default_db_url_has_no_credentials(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        import importlib
        import config
        importlib.reload(config)
        assert "user:password" not in config.DATABASE_URL
        assert "sqlite" in config.DATABASE_URL
```

### 7.2 Audit Logging Tests

**File:** `backend/tests/test_audit_logging.py`

```python
"""감사 로깅 테스트."""
import json
import logging
import pytest
from services.audit_logger import (
    log_auth_event, log_content_event, log_admin_event, audit_logger
)


@pytest.fixture
def capture_audit_logs(caplog):
    """감사 로그 캡처 픽스처."""
    with caplog.at_level(logging.INFO, logger="audit"):
        yield caplog


class TestAuthAuditLogging:
    """인증 이벤트 감사 로그 검증."""

    def test_login_success_logged(self, capture_audit_logs):
        log_auth_event("login", user_id=1, email="test@test.com", ip="127.0.0.1")
        assert any("login" in r.message for r in capture_audit_logs.records)

    def test_login_failure_logged(self, capture_audit_logs):
        log_auth_event("login_failed", email="bad@test.com", ip="10.0.0.1", status="failed")
        records = [r for r in capture_audit_logs.records if "login_failed" in r.message]
        assert len(records) == 1
        assert records[0].status == "failed"

    def test_register_logged(self, capture_audit_logs):
        log_auth_event("register", user_id=5, email="new@test.com", ip="127.0.0.1")
        records = [r for r in capture_audit_logs.records if "register" in r.message]
        assert len(records) == 1
        assert records[0].user_id == 5

    def test_oauth_callback_logged(self, capture_audit_logs):
        log_auth_event("oauth_callback", user_id=3, email="o@test.com",
                       ip="127.0.0.1", provider="google")
        records = [r for r in capture_audit_logs.records if "oauth_callback" in r.message]
        assert len(records) == 1
        assert records[0].provider == "google"


class TestContentAuditLogging:
    """콘텐츠 이벤트 감사 로그 검증."""

    def test_post_created_logged(self, capture_audit_logs):
        log_content_event("post_created", user_id=1, resource="post", resource_id=10, ip="127.0.0.1")
        records = [r for r in capture_audit_logs.records if "post_created" in r.message]
        assert len(records) == 1
        assert records[0].resource_id == 10

    def test_comment_created_logged(self, capture_audit_logs):
        log_content_event("comment_created", user_id=2, resource="comment", resource_id=20)
        assert any("comment_created" in r.message for r in capture_audit_logs.records)

    def test_vote_logged(self, capture_audit_logs):
        log_content_event("vote_cast", user_id=1, resource="vote", resource_id=5, detail="hot")
        records = [r for r in capture_audit_logs.records if "vote_cast" in r.message]
        assert len(records) == 1
        assert records[0].detail == "hot"


class TestAdminAuditLogging:
    """관리자 이벤트 감사 로그 검증."""

    def test_admin_action_logged_at_warning(self, capture_audit_logs):
        log_admin_event("crawler_triggered", admin_id=1, resource="crawler", detail="ppomppu")
        records = [r for r in capture_audit_logs.records if "crawler_triggered" in r.message]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
```

### 7.3 Spam Filter Tests

**File:** `backend/tests/test_spam_filter.py`

```python
"""스팸 필터 테스트."""
import pytest
from services.spam_filter import check_content, check_spam, check_comment_spam, _submission_times


@pytest.fixture(autouse=True)
def clear_rate_state():
    """각 테스트 전 속도 제한 상태 초기화."""
    _submission_times.clear()
    yield
    _submission_times.clear()


class TestContentCheck:
    """콘텐츠 스팸 패턴 감지."""

    def test_normal_content_passes(self):
        result = check_content("이것은 정상적인 게시글 내용입니다.")
        assert not result.is_spam

    def test_empty_content_blocked(self):
        result = check_content("")
        assert result.is_spam

    def test_whitespace_only_blocked(self):
        result = check_content("   \n\t  ")
        assert result.is_spam

    def test_excessive_links_blocked(self):
        text = "Visit " + " ".join(f"http://spam{i}.com" for i in range(6))
        result = check_content(text)
        assert result.is_spam
        assert "링크" in result.reason

    def test_five_links_allowed(self):
        text = "Links: " + " ".join(f"http://site{i}.com" for i in range(5))
        result = check_content(text)
        assert not result.is_spam

    def test_repeated_chars_blocked(self):
        result = check_content("aaaaaaaaaa")
        assert result.is_spam
        assert "반복" in result.reason

    def test_short_repeated_chars_ok(self):
        result = check_content("aaabbbccc 정상")
        assert not result.is_spam


class TestRateLimit:
    """사용자별 제출 속도 제한."""

    def test_normal_rate_allowed(self):
        for _ in range(4):
            result = check_spam(user_id=100, title="제목", content="내용입니다 정상 게시글")
            assert not result.is_spam

    def test_burst_rate_blocked(self):
        for i in range(5):
            check_spam(user_id=200, title=f"제목{i}", content="내용입니다 정상 게시글")
        result = check_spam(user_id=200, title="제목6", content="내용입니다 정상 게시글")
        assert result.is_spam
        assert "빠르게" in result.reason

    def test_different_users_independent(self):
        for _ in range(5):
            check_spam(user_id=300, title="제목", content="내용입니다 정상 게시글")
        result = check_spam(user_id=301, title="제목", content="내용입니다 정상 게시글")
        assert not result.is_spam


class TestCommentSpam:
    """댓글 스팸 검사."""

    def test_normal_comment_passes(self):
        result = check_comment_spam(user_id=1, content="좋은 정보 감사합니다!")
        assert not result.is_spam

    def test_empty_comment_blocked(self):
        result = check_comment_spam(user_id=1, content="")
        assert result.is_spam
```

### 7.4 Content Length Validation Tests

**File:** `backend/tests/test_schema_validation.py`

```python
"""스키마 유효성 검사 테스트."""
import pytest
from pydantic import ValidationError
from api.schemas.community import PostCreate, CommentCreate, PostType


class TestPostCreateValidation:
    """PostCreate 스키마 유효성 검사."""

    def test_valid_post(self):
        post = PostCreate(title="정상 제목", content="정상 내용입니다.", post_type=PostType.FREE)
        assert post.title == "정상 제목"

    def test_title_too_short(self):
        with pytest.raises(ValidationError, match="min_length"):
            PostCreate(title="a", content="내용", post_type=PostType.FREE)

    def test_title_too_long(self):
        with pytest.raises(ValidationError, match="max_length"):
            PostCreate(title="가" * 201, content="내용", post_type=PostType.FREE)

    def test_content_too_long(self):
        with pytest.raises(ValidationError, match="max_length"):
            PostCreate(title="제목", content="가" * 50_001, post_type=PostType.FREE)

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError, match="ge"):
            PostCreate(title="제목", content="내용", post_type=PostType.HOTDEAL, price=-100)

    def test_javascript_url_rejected(self):
        with pytest.raises(ValidationError, match="http"):
            PostCreate(title="제목", content="내용", post_type=PostType.FREE, url="javascript:alert(1)")

    def test_valid_url_accepted(self):
        post = PostCreate(title="제목", content="내용", post_type=PostType.FREE, url="https://example.com")
        assert post.url == "https://example.com"

    def test_too_many_images_rejected(self):
        with pytest.raises(ValidationError, match="max_length"):
            PostCreate(
                title="제목", content="내용", post_type=PostType.FREE,
                images=[f"https://img{i}.com/a.jpg" for i in range(11)]
            )


class TestCommentCreateValidation:
    """CommentCreate 스키마 유효성 검사."""

    def test_valid_comment(self):
        c = CommentCreate(content="정상 댓글입니다.")
        assert c.content == "정상 댓글입니다."

    def test_empty_comment_rejected(self):
        with pytest.raises(ValidationError, match="min_length"):
            CommentCreate(content="")

    def test_comment_too_long(self):
        with pytest.raises(ValidationError, match="max_length"):
            CommentCreate(content="가" * 5_001)
```

### 7.5 Frontend Tests

**File:** `frontend/src/stores/__tests__/appStore.test.js`

```javascript
import { describe, it, expect, beforeEach } from 'vitest';

describe('appStore persistence', () => {
    beforeEach(() => {
        localStorage.clear();
        sessionStorage.clear();
    });

    it('should NOT persist favorites to localStorage', () => {
        // After using the store, localStorage should not contain favorites
        const stored = localStorage.getItem('wallet-savior-store');
        if (stored) {
            const parsed = JSON.parse(stored);
            expect(parsed.state).not.toHaveProperty('favorites');
            expect(parsed.state).not.toHaveProperty('recentSearches');
            expect(parsed.state).not.toHaveProperty('shoppingList');
            expect(parsed.state).not.toHaveProperty('priceAlerts');
        }
    });

    it('should persist only theme and filterPreferences', () => {
        const stored = localStorage.getItem('wallet-savior-store');
        if (stored) {
            const parsed = JSON.parse(stored);
            const keys = Object.keys(parsed.state || {});
            const allowed = ['theme', 'filterPreferences'];
            keys.forEach(k => expect(allowed).toContain(k));
        }
    });
});

describe('token storage', () => {
    it('should NOT have access_token in localStorage', () => {
        expect(localStorage.getItem('access_token')).toBeNull();
    });

    it('should NOT have refresh_token in localStorage', () => {
        expect(localStorage.getItem('refresh_token')).toBeNull();
    });
});
```

### 7.6 PII Encryption Tests

**File:** `backend/tests/test_crypto_service.py`

```python
"""PII 암호화 테스트."""
import os
import pytest


class TestCryptoService:
    """encrypt_pii / decrypt_pii 라운드 트립 검증."""

    def test_roundtrip_with_key(self, monkeypatch):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", key)

        import importlib
        import services.crypto_service as cs
        importlib.reload(cs)

        encrypted = cs.encrypt_pii("user@example.com")
        assert encrypted != "user@example.com"
        assert cs.decrypt_pii(encrypted) == "user@example.com"

    def test_passthrough_without_key(self, monkeypatch):
        monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)

        import importlib
        import services.crypto_service as cs
        importlib.reload(cs)

        assert cs.encrypt_pii("plaintext") == "plaintext"
        assert cs.decrypt_pii("plaintext") == "plaintext"

    def test_empty_string(self, monkeypatch):
        from cryptography.fernet import Fernet
        monkeypatch.setenv("DATA_ENCRYPTION_KEY", Fernet.generate_key().decode())

        import importlib
        import services.crypto_service as cs
        importlib.reload(cs)

        assert cs.encrypt_pii("") == ""
        assert cs.decrypt_pii("") == ""
```

---

## 8. Environment Variable Reference

Complete list of environment variables introduced or changed by this spec:

| Variable | Required | Default | Section | Purpose |
|----------|----------|---------|---------|---------|
| `JWT_SECRET_KEY` | ✅ Yes | *none — crashes* | §4.1 | JWT signing key |
| `DATABASE_URL` | No | `sqlite:///walletguardian.db` | §4.2 | Database connection |
| `API_HOST` | No | `127.0.0.1` | §3.1 | Server bind address |
| `API_PORT` | No | `8000` | existing | Server port |
| `CORS_ORIGINS` | No | localhost dev origins | §4.5 | Allowed CORS origins (comma-separated) |
| `GOOGLE_CLIENT_ID` | No | `""` | §4.3 | Google OAuth |
| `GOOGLE_CLIENT_SECRET` | No | `""` | §4.3 | Google OAuth |
| `KAKAO_CLIENT_ID` | No | `""` | §4.3 | Kakao OAuth |
| `KAKAO_CLIENT_SECRET` | No | `""` | §4.3 | Kakao OAuth |
| `NAVER_CLIENT_ID` | No | `""` | existing | Naver API/OAuth |
| `NAVER_CLIENT_SECRET` | No | `""` | existing | Naver API/OAuth |
| `OAUTH_REDIRECT_BASE` | No | `http://localhost:8000` | §4.4 | OAuth redirect base URL |
| `DATA_ENCRYPTION_KEY` | No | *disabled* | §1.2 | Fernet key for PII encryption |
| `AUDIT_LOG_DIR` | No | `logs` | §2.1 | Audit log file directory |
| `LOG_DIR` | No | `logs` | §2.6 | Application log directory |

---

## 9. Rollout Order

### Phase 1 — Config Hardening (Day 1, ~2 hours)

| Step | Section | Risk | Effort |
|------|---------|------|--------|
| 1 | §4.1 — JWT secret fail-on-missing | Breaking if env not set | 15 min |
| 2 | §4.2 — Database URL safe default | Non-breaking | 10 min |
| 3 | §3.1 — Bind address `127.0.0.1` | Breaking in Docker (needs override) | 10 min |
| 4 | §4.5 — CORS from env var | Non-breaking | 15 min |
| 5 | §4.6 — Create `.env.example` | Non-breaking | 15 min |
| 6 | §4.3 — OAuth validation | Non-breaking (warns, doesn't block) | 15 min |

**Pre-requisite:** Generate and set `JWT_SECRET_KEY` in all `.env` files before deploying.

### Phase 2 — Audit Logging (Day 1–2, ~3 hours)

| Step | Section | Risk | Effort |
|------|---------|------|--------|
| 7 | §2.1 — Create `audit_logger.py` | Non-breaking | 30 min |
| 8 | §2.6 — Create `logging_config.py` | Non-breaking | 15 min |
| 9 | §2.2 — Instrument auth routes | Non-breaking (adds logging only) | 45 min |
| 10 | §2.3 — Instrument community routes | Non-breaking | 30 min |
| 11 | §2.4 — Instrument hotdeal routes | Non-breaking | 30 min |

### Phase 3 — Content Validation & Moderation (Day 2–3, ~3 hours)

| Step | Section | Risk | Effort |
|------|---------|------|--------|
| 12 | §6.1 — Pydantic field constraints | May reject previously valid large inputs | 45 min |
| 13 | §6.2 — Hotdeal Pydantic models | Breaking change to hotdeal API | 30 min |
| 14 | §6.3 — Create `spam_filter.py` | Non-breaking | 30 min |
| 15 | §6.4 — Integrate spam filter | May rate-limit fast users | 30 min |
| 16 | §6.5 — Guest post restriction | Breaking if guests should post | 15 min |

### Phase 4 — Frontend Security (Day 3–4, ~2 hours)

| Step | Section | Risk | Effort |
|------|---------|------|--------|
| 17 | §5.1A — sessionStorage for tokens | Users logged out on tab close | 30 min |
| 18 | §5.2/§1.1 — Zustand persist reduction | Users lose saved favorites (one-time) | 30 min |

### Phase 5 — Privacy & Encryption (Day 5+, ~2 hours)

| Step | Section | Risk | Effort |
|------|---------|------|--------|
| 19 | §1.2 — Create `crypto_service.py` | Non-breaking (opt-in) | 30 min |
| 20 | §1.3 — Account deletion endpoint | Non-breaking | 45 min |

### Phase 6 — Full Cookie Migration (Future sprint, ~8 hours)

| Step | Section | Risk | Effort |
|------|---------|------|--------|
| 21 | §5.1B — Backend cookie-based auth | Major breaking change | 4 hours |
| 22 | §5.1B — Frontend cookie integration | Coordinated with backend | 4 hours |

---

## Files Changed Summary

### New Files

| File | Section | Purpose |
|------|---------|---------|
| `backend/services/audit_logger.py` | §2.1 | Structured audit logging |
| `backend/services/crypto_service.py` | §1.2 | PII field encryption |
| `backend/services/spam_filter.py` | §6.3 | Community spam prevention |
| `backend/logging_config.py` | §2.6 | Centralized logging config |
| `backend/api/schemas/hotdeals.py` | §6.2 | Pydantic models for hotdeal endpoints |
| `backend/.env.example` | §4.6 | Environment variable reference |
| `backend/tests/test_config_security.py` | §7.1 | Config security tests |
| `backend/tests/test_audit_logging.py` | §7.2 | Audit logging tests |
| `backend/tests/test_spam_filter.py` | §7.3 | Spam filter tests |
| `backend/tests/test_schema_validation.py` | §7.4 | Schema validation tests |
| `backend/tests/test_crypto_service.py` | §7.6 | PII encryption tests |

### Modified Files

| File | Section | Change |
|------|---------|--------|
| `backend/config.py` | §3.1, §4.2 | Bind address default, DB URL safe default |
| `backend/main.py` | §2.6 | Initialize logging |
| `backend/services/auth_service.py` | §4.1 | JWT secret fail-on-missing |
| `backend/services/oauth_service.py` | §4.3, §4.4 | OAuth config validation |
| `backend/api/app.py` | §4.5 | CORS from env var |
| `backend/api/routes/auth.py` | §2.2, §1.3 | Audit logging, account deletion |
| `backend/api/routes/community.py` | §2.3, §6.4, §6.5 | Audit logging, spam filter, guest restriction |
| `backend/api/routes/hotdeals.py` | §2.4, §6.2 | Audit logging, Pydantic models |
| `backend/api/schemas/community.py` | §6.1 | Field length constraints |
| `frontend/src/stores/appStore.js` | §1.1, §5.2 | Reduce persisted fields |
| `frontend/src/services/api.js` | §5.1 | sessionStorage migration |
| `frontend/src/services/authService.js` | §5.1 | sessionStorage migration |

### Dependencies to Add

| Package | File | Section |
|---------|------|---------|
| `cryptography` | `backend/requirements.txt` | §1.2 (PII encryption) |

---

*End of implementation spec.*
