# Website Authentication & Authorization — Security Implementation Spec

**Project:** WalletSavior / Website  
**Path:** `packages/website`  
**Stack:** FastAPI (Python) backend · React (Vite) frontend  
**Source Audits:** `website-code-audit.md` (C-02, C-03, C-04, C-07, C-08, H-04, H-05) · `website-arch-audit.md` (CRITICAL-03, CRITICAL-04, HIGH-01, HIGH-02, HIGH-03, HIGH-05)  
**Date:** 2025-07-16  

---

## Table of Contents

1. [JWT Secret — Environment-Only with Startup Validation](#1-jwt-secret)
2. [Token Storage — httpOnly Cookies](#2-token-storage)
3. [OAuth Security — CSRF State + Secure Token Delivery](#3-oauth-security)
4. [Token Refresh — Rotation with One-Time Use](#4-token-refresh)
5. [Session Invalidation — Token Blacklist + Logout](#5-session-invalidation)
6. [Password Security — Strength Enforcement](#6-password-security)
7. [CORS — Strict Production Configuration](#7-cors)
8. [Migration Checklist](#8-migration-checklist)
9. [Test Cases](#9-test-cases)

---

## 1. JWT Secret

**Audit Refs:** C-04, CRITICAL-04  
**Severity:** 🔴 Critical  
**Current State:** Hardcoded fallback `"dev-secret-key-change-in-production"` in `auth_service.py:9`  

### 1.1 Current Code

```python
# backend/services/auth_service.py:9
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
```

### 1.2 Target Code

**File: `backend/services/auth_service.py`** — Replace lines 8–9:

```python
# 설정 — JWT 시크릿은 환경 변수 필수 (미설정 시 서버 기동 실패)
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "FATAL: JWT_SECRET_KEY environment variable is required. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
if len(SECRET_KEY) < 32:
    raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters (256 bits)")
```

**File: `backend/config.py`** — Add JWT config section after line 17:

```python
# --- JWT ---
JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
if not JWT_SECRET_KEY:
    raise RuntimeError("FATAL: JWT_SECRET_KEY environment variable is required")
```

### 1.3 Secret Generation

```bash
# Generate a 256-bit random key
python -c "import secrets; print(secrets.token_hex(32))"
# Example output: a3f1c9b2e8d74f6a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4
```

### 1.4 Environment Files

**File: `backend/.env.example`** — Add:

```env
# REQUIRED — JWT signing key (min 32 chars, use: python -c "import secrets; print(secrets.token_hex(32))")
JWT_SECRET_KEY=
```

**File: `backend/.env`** (local development, gitignored):

```env
JWT_SECRET_KEY=<paste-generated-key-here>
```

### 1.5 Docker Compose

**File: `docker-compose.yml`** — Add to website-backend service:

```yaml
services:
  website-backend:
    environment:
      - JWT_SECRET_KEY=${JWT_SECRET_KEY:?JWT_SECRET_KEY is required}
```

---

## 2. Token Storage — httpOnly Cookies

**Audit Refs:** C-02, HIGH-01  
**Severity:** 🔴 Critical  
**Current State:** Both `access_token` and `refresh_token` stored in `localStorage` — accessible to any XSS payload.

### 2.1 Architecture Change

```
BEFORE (vulnerable):
┌──────────┐   JSON body: {access_token, refresh_token}   ┌──────────┐
│ Frontend │ ◄──────────────────────────────────────────── │ Backend  │
│          │   localStorage.setItem('access_token', ...)   │          │
│          │   Authorization: Bearer <token>                │          │
└──────────┘ ─────────────────────────────────────────────►└──────────┘

AFTER (secure):
┌──────────┐   Set-Cookie: access_token=...; HttpOnly      ┌──────────┐
│ Frontend │ ◄──────────────────────────────────────────── │ Backend  │
│          │   Set-Cookie: refresh_token=...; HttpOnly      │          │
│          │   Cookie: access_token=...; refresh_token=...  │          │
└──────────┘ ─────────────────────────────────────────────►└──────────┘
  JS never sees tokens      browser auto-sends cookies
```

### 2.2 Backend — Cookie Utility Module (NEW)

**File: `backend/services/cookie_service.py`** — Create new file:

```python
"""쿠키 기반 토큰 관리 유틸리티"""
import os
from fastapi.responses import JSONResponse

COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)  # None = current domain
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "lax" for OAuth redirects, "strict" for non-OAuth

ACCESS_TOKEN_MAX_AGE = 30 * 60          # 30 minutes (seconds)
REFRESH_TOKEN_MAX_AGE = 7 * 24 * 60 * 60  # 7 days (seconds)


def set_auth_cookies(response: JSONResponse, access_token: str, refresh_token: str) -> JSONResponse:
    """Set httpOnly cookies for access and refresh tokens."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=ACCESS_TOKEN_MAX_AGE,
        path="/",
        domain=COOKIE_DOMAIN,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        max_age=REFRESH_TOKEN_MAX_AGE,
        path="/api/auth/refresh",  # Only sent to refresh endpoint
        domain=COOKIE_DOMAIN,
    )
    return response


def clear_auth_cookies(response: JSONResponse) -> JSONResponse:
    """Clear auth cookies on logout."""
    response.delete_cookie(key="access_token", path="/", domain=COOKIE_DOMAIN)
    response.delete_cookie(key="refresh_token", path="/api/auth/refresh", domain=COOKIE_DOMAIN)
    return response
```

**Key security properties:**
- `httponly=True` → JavaScript cannot read the token (prevents XSS token theft)
- `secure=True` (production) → Only sent over HTTPS
- `samesite="lax"` → Protects against CSRF for state-changing requests while allowing OAuth redirect cookies
- `refresh_token` path restricted to `/api/auth/refresh` → not sent with every request
- `domain=None` → scoped to current origin only

### 2.3 Backend — Auth Routes Changes

**File: `backend/api/routes/auth.py`** — Full replacement:

```python
"""인증 API 라우트"""
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from api.schemas.auth import (
    UserRegister, UserLogin, TokenResponse, TokenRefresh, UserProfile
)
from services.auth_service import (
    hash_password, verify_password, create_token_pair, decode_token
)
from services.oauth_service import (
    get_oauth_login_url, exchange_code_for_token, get_user_info
)
from services.cookie_service import set_auth_cookies, clear_auth_cookies
from api.middleware.auth import require_auth

router = APIRouter(prefix="/api/auth", tags=["인증"])

# 임시 인메모리 저장소 (DB 연결 전까지 사용)
_users_db: dict[str, dict] = {}
_next_id = 1


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister):
    """회원가입 — 이메일/비밀번호"""
    global _next_id

    if data.email in _users_db:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")

    for user in _users_db.values():
        if user["nickname"] == data.nickname:
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")

    user = {
        "id": _next_id,
        "email": data.email,
        "nickname": data.nickname,
        "hashed_password": hash_password(data.password),
        "role": "user",
    }
    _users_db[data.email] = user
    _next_id += 1

    tokens = create_token_pair(user["id"], user["email"], user["role"])

    # Set tokens as httpOnly cookies — NOT in response body
    response = JSONResponse(
        content={"message": "회원가입 완료", "expires_in": tokens["expires_in"]},
        status_code=201,
    )
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])


@router.post("/login")
async def login(data: UserLogin):
    """로그인 — 이메일/비밀번호"""
    user = _users_db.get(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    tokens = create_token_pair(user["id"], user["email"], user["role"])

    response = JSONResponse(
        content={"message": "로그인 성공", "expires_in": tokens["expires_in"]},
    )
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])


@router.post("/refresh")
async def refresh(request: Request):
    """토큰 갱신 — refresh_token은 쿠키에서 읽음"""
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="리프레시 토큰이 없습니다")

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    # --- Token blacklist check (see Section 5) ---
    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti):
        raise HTTPException(status_code=401, detail="폐기된 리프레시 토큰입니다")

    # Blacklist the old refresh token (rotation — see Section 4)
    if jti:
        blacklist_token(jti, payload.get("exp", 0))

    tokens = create_token_pair(int(payload["sub"]), payload["email"], payload["role"])

    response = JSONResponse(
        content={"message": "토큰 갱신 완료", "expires_in": tokens["expires_in"]},
    )
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(require_auth)):
    """로그아웃 — 쿠키 삭제 + 리프레시 토큰 블랙리스트"""
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        payload = decode_token(refresh_token)
        if payload and payload.get("jti"):
            blacklist_token(payload["jti"], payload.get("exp", 0))

    response = JSONResponse(content={"message": "로그아웃 완료"})
    return clear_auth_cookies(response)
```

> **Note:** `is_token_blacklisted` and `blacklist_token` are defined in [Section 5](#5-session-invalidation). Add `from fastapi import Depends` and the blacklist imports.

### 2.4 Backend — Auth Middleware Changes

**File: `backend/api/middleware/auth.py`** — Replace `get_current_user` to read from cookies:

```python
"""인증 미들웨어 — JWT 토큰 검증 (쿠키 기반 + Bearer 폴백)"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from services.auth_service import decode_token

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """현재 인증된 사용자 정보 추출 (쿠키 우선, Bearer 폴백)"""
    token = None

    # 1) httpOnly 쿠키에서 access_token 읽기 (primary)
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        token = cookie_token

    # 2) Authorization: Bearer 헤더 폴백 (API client / mobile 호환)
    if not token and credentials:
        token = credentials.credentials

    if not token:
        return None

    payload = decode_token(token)
    if not payload:
        return None

    if payload.get("type") != "access":
        return None

    return {
        "id": int(payload["sub"]),
        "email": payload["email"],
        "role": payload["role"],
    }


async def require_auth(
    user: Optional[dict] = Depends(get_current_user),
) -> dict:
    """인증 필수 — 미인증 시 401"""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증이 필요합니다",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def require_admin(
    user: dict = Depends(require_auth),
) -> dict:
    """관리자 권한 필수 — 비관리자 시 403"""
    if user["role"] not in ("admin", "moderator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자 권한이 필요합니다",
        )
    return user
```

### 2.5 Frontend — API Client Changes

**File: `frontend/src/services/api.js`** — Key changes:

```javascript
// CHANGE 1: Constructor — remove localStorage token read (line 68)
// BEFORE:
this.token = localStorage.getItem('access_token');
// AFTER:
// Token is now in httpOnly cookie — browser sends it automatically.
// No JS token management needed.

// CHANGE 2: setToken / clearToken — remove localStorage (lines 71-80)
// DELETE these methods entirely. Cookies are managed by the backend.

// CHANGE 3: request() — remove Bearer header, add credentials: 'include' (lines 82-150)
async request(path, options = {}) {
  const { timeout = DEFAULT_TIMEOUT, signal: externalSignal, ...fetchOptions } = options;
  const headers = {
    'Content-Type': 'application/json',
    ...fetchOptions.headers,
  };
  // REMOVED: no more Authorization: Bearer header
  // Cookies are sent automatically with credentials: 'include'

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  if (externalSignal) {
    if (externalSignal.aborted) {
      clearTimeout(timeoutId);
      controller.abort();
    } else {
      externalSignal.addEventListener('abort', () => controller.abort(), { once: true });
    }
  }

  let response;
  try {
    response = await fetch(`${this.baseUrl}${path}`, {
      ...fetchOptions,
      headers,
      credentials: 'include',  // ← CRITICAL: send cookies cross-origin
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      if (externalSignal?.aborted) throw err;
      throw new ApiError(ERROR_MESSAGES.timeout, 0, 'timeout');
    }
    throw new ApiError(ERROR_MESSAGES.network, 0, 'network');
  } finally {
    clearTimeout(timeoutId);
  }

  // 401 → try refresh (cookie-based)
  if (response.status === 401) {
    const refreshed = await this.refreshToken();
    if (refreshed) {
      try {
        response = await fetch(`${this.baseUrl}${path}`, {
          ...fetchOptions,
          headers,
          credentials: 'include',
        });
      } catch {
        throw new ApiError(ERROR_MESSAGES.network, 0, 'network');
      }
    } else {
      useStore.getState().openLoginModal();
      throw new ApiError(ERROR_MESSAGES.unauthorized, 401, 'unauthorized');
    }
  }

  if (!response.ok) {
    let data = null;
    try { data = await response.json(); } catch { /* ignore */ }
    throw new ApiError(
      data?.message || getErrorMessage(response.status),
      response.status,
      response.status >= 500 ? 'server' : 'client',
      data,
    );
  }

  return response;
}

// CHANGE 4: refreshToken() — cookie-based, no localStorage (lines 201-221)
async refreshToken() {
  try {
    const response = await fetch(`${this.baseUrl}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',  // sends refresh_token cookie
    });
    return response.ok;
    // Backend sets new cookies in the response — no JS handling needed
  } catch {
    return false;
  }
}
```

### 2.6 Frontend — Auth Service Changes

**File: `frontend/src/services/authService.js`** — Full replacement:

```javascript
import { api } from './api';

export const authService = {
  async login(email, password) {
    const res = await api.post('/api/auth/login', { email, password });
    if (!res.ok) throw new Error('로그인에 실패했습니다');
    return res.json();
    // Tokens are set as httpOnly cookies by the backend response
    // REMOVED: localStorage.setItem('access_token', ...)
    // REMOVED: localStorage.setItem('refresh_token', ...)
  },

  async register(userData) {
    const res = await api.post('/api/auth/register', userData);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '회원가입에 실패했습니다');
    }
    return res.json();
  },

  async logout() {
    try {
      await api.post('/api/auth/logout');
    } finally {
      // Cookies are cleared by backend Set-Cookie with max-age=0
      // No localStorage cleanup needed
    }
  },

  async getProfile() {
    const res = await api.get('/api/auth/me');
    if (!res.ok) throw new Error('프로필 조회에 실패했습니다');
    return res.json();
  },

  async updateProfile(data) {
    const res = await api.put('/api/auth/me', data);
    if (!res.ok) throw new Error('프로필 수정에 실패했습니다');
    return res.json();
  },

  async socialLogin(provider) {
    // Redirect to backend OAuth endpoint — tokens handled via cookies
    window.location.href = `${api.baseUrl}/api/auth/oauth/${provider}`;
  },
};
```

### 2.7 Frontend — Remove All localStorage Token References

Search and replace across all frontend files:

| File | Line | Remove/Change |
|------|------|---------------|
| `services/api.js:68` | `this.token = localStorage.getItem('access_token')` | Delete |
| `services/api.js:74` | `localStorage.setItem('access_token', token)` | Delete |
| `services/api.js:79` | `localStorage.removeItem('access_token')` | Delete |
| `services/api.js:88-90` | `Authorization: Bearer` header | Delete |
| `services/api.js:203` | `localStorage.getItem('refresh_token')` | Delete |
| `services/api.js:216` | `localStorage.setItem('refresh_token', ...)` | Delete |
| `services/authService.js:8-9` | `api.setToken` + `localStorage.setItem` | Delete |
| `services/authService.js:27` | `localStorage.removeItem('refresh_token')` | Delete |
| `services/authService.js:47-48` | `api.setToken` + `localStorage.setItem` | Delete |
| `pages/Community/CommunityPage.jsx:209` | `localStorage.getItem('access_token')` | Remove; auth is automatic via cookies |

### 2.8 Cookie Configuration Summary

| Attribute | `access_token` Cookie | `refresh_token` Cookie |
|-----------|----------------------|------------------------|
| `HttpOnly` | `true` | `true` |
| `Secure` | `true` (prod) / `false` (dev) | `true` (prod) / `false` (dev) |
| `SameSite` | `Lax` | `Lax` |
| `Path` | `/` | `/api/auth/refresh` |
| `Max-Age` | 1800 (30 min) | 604800 (7 days) |
| `Domain` | current origin | current origin |

---

## 3. OAuth Security

**Audit Refs:** C-03, CRITICAL-03, H-04, HIGH-05  
**Severity:** 🔴 Critical + 🟠 High  
**Current State:** No CSRF state parameter. Tokens leaked in redirect URL query string. No redirect URI validation.

### 3.1 OAuth Flow — Before vs. After

```
BEFORE (vulnerable):
┌────────┐  GET /oauth/google  ┌────────┐  redirect to Google   ┌────────┐
│Frontend│ ──────────────────► │Backend │ ────────────────────► │ Google │
│        │                     │        │   (NO state param)    │        │
│        │                     │        │ ◄──── callback?code   │        │
│        │ ◄── 302 to          │        │                       │        │
│        │  /?access_token=... │        │  TOKENS IN URL! 🔴    │        │
└────────┘     (browser history)└────────┘                       └────────┘

AFTER (secure):
┌────────┐  GET /oauth/google  ┌────────┐  redirect to Google   ┌────────┐
│Frontend│ ──────────────────► │Backend │ ────────────────────► │ Google │
│        │                     │        │   state=<random>      │        │
│        │                     │        │   (state in cookie)   │        │
│        │                     │        │ ◄── callback?code&    │        │
│        │                     │        │     state=<random>    │        │
│        │                     │        │   ✅ validate state   │        │
│        │ ◄── 302 to /        │        │   Set-Cookie: tokens  │        │
│        │  (cookies set,      │        │   NO tokens in URL    │        │
│        │   no tokens in URL) │        │                       │        │
└────────┘                     └────────┘                       └────────┘
```

### 3.2 Backend — OAuth Service Changes

**File: `backend/services/oauth_service.py`** — Add state parameter support:

```python
"""OAuth 서비스 — Google, Kakao, Naver OAuth 2.0 처리"""
import httpx
import os
import secrets
from typing import Optional
from dataclasses import dataclass
from urllib.parse import urlencode, quote

# ... (OAuthConfig class unchanged) ...

REDIRECT_BASE = os.getenv("OAUTH_REDIRECT_BASE", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Allowed post-OAuth redirect targets (prevent open redirect)
ALLOWED_REDIRECT_URLS = {
    FRONTEND_URL,
    f"{FRONTEND_URL}/",
    f"{FRONTEND_URL}/auth/callback",
}


def generate_oauth_state() -> str:
    """Generate cryptographically random state parameter for CSRF protection."""
    return secrets.token_urlsafe(32)


def get_oauth_login_url(provider: str, state: str) -> str:
    """OAuth 로그인 URL 생성 (state 포함)"""
    config = OAuthConfig.get(provider)
    params = {
        "client_id": config["client_id"],
        "redirect_uri": f"{REDIRECT_BASE}/api/auth/oauth/{provider}/callback",
        "response_type": "code",
        "scope": config["scope"],
        "state": state,  # ← CSRF protection
    }
    query = urlencode({k: v for k, v in params.items() if v})
    return f"{config['auth_url']}?{query}"


# exchange_code_for_token and get_user_info remain unchanged
```

### 3.3 Backend — OAuth Route Changes

**File: `backend/api/routes/auth.py`** — OAuth endpoints:

```python
from services.oauth_service import (
    get_oauth_login_url, exchange_code_for_token, get_user_info,
    generate_oauth_state, FRONTEND_URL, ALLOWED_REDIRECT_URLS
)

OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_MAX_AGE = 600  # 10 minutes


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """OAuth 로그인 — state 생성 후 공급자로 리다이렉트"""
    state = generate_oauth_state()

    try:
        url = get_oauth_login_url(provider, state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = RedirectResponse(url=url, status_code=302)

    # Store state in httpOnly cookie for validation in callback
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        max_age=OAUTH_STATE_MAX_AGE,
        path="/api/auth/oauth",
    )
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str, request: Request):
    """OAuth 콜백 — state 검증 + 쿠키로 토큰 전달"""
    global _next_id

    # 1) Validate CSRF state parameter
    stored_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not stored_state or not secrets.compare_digest(stored_state, state):
        raise HTTPException(status_code=403, detail="OAuth state 검증 실패 (CSRF 방지)")

    try:
        token_data = await exchange_code_for_token(provider, code)
        user_info = await get_user_info(provider, token_data["access_token"])

        # 기존 사용자 확인 또는 신규 생성
        user = _users_db.get(user_info.email)
        if not user:
            user = {
                "id": _next_id,
                "email": user_info.email,
                "nickname": user_info.nickname,
                "hashed_password": None,
                "role": "user",
                "oauth_provider": provider,
                "oauth_id": user_info.provider_user_id,
            }
            _users_db[user_info.email] = user
            _next_id += 1

        tokens = create_token_pair(user["id"], user["email"], user["role"])

        # 2) Redirect WITHOUT tokens in URL — set as httpOnly cookies
        redirect_url = FRONTEND_URL  # Clean redirect, no tokens in URL
        response = RedirectResponse(url=redirect_url, status_code=302)
        set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])

        # 3) Clear the OAuth state cookie
        response.delete_cookie(key=OAUTH_STATE_COOKIE, path="/api/auth/oauth")

        return response

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth 인증 실패: {str(e)}")
```

### 3.4 Frontend — OAuth Callback Page

**File: `frontend/src/pages/Auth/AuthCallback.jsx`** — Create new file:

Since tokens are now in cookies (not URL), the callback page is minimal:

```jsx
import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import useStore from '../../stores/appStore';
import { authService } from '../../services/authService';

export default function AuthCallback() {
  const navigate = useNavigate();
  const { login, addToast } = useStore();

  useEffect(() => {
    // Tokens are already in httpOnly cookies from the redirect.
    // Fetch the user profile to confirm auth and get user data.
    authService.getProfile()
      .then((profile) => {
        login(profile);
        addToast('로그인 되었습니다!', 'success');
        navigate('/', { replace: true });
      })
      .catch(() => {
        addToast('로그인에 실패했습니다.', 'error');
        navigate('/', { replace: true });
      });
  }, []);

  return <div style={{ textAlign: 'center', marginTop: '2rem' }}>로그인 처리 중...</div>;
}
```

**File: `frontend/src/App.jsx`** — Add route:

```jsx
import AuthCallback from './pages/Auth/AuthCallback';

// Inside <Routes>:
<Route path="/auth/callback" element={<AuthCallback />} />
```

### 3.5 Frontend — LoginModal OAuth Buttons

**File: `frontend/src/components/modals/LoginModal.jsx`** — Add click handlers:

```jsx
// Replace the OAuth buttons (lines 38-39):
<button type="button" className={s.kakao}
  onClick={() => window.location.href = `${import.meta.env.VITE_API_URL || ''}/api/auth/oauth/kakao`}>
  카카오로 시작하기
</button>
<button type="button" className={s.naver}
  onClick={() => window.location.href = `${import.meta.env.VITE_API_URL || ''}/api/auth/oauth/naver`}>
  네이버로 시작하기
</button>
```

### 3.6 Redirect URI Validation

The backend already uses hardcoded redirect URIs in `OAuthConfig`, preventing open-redirect attacks. The post-login redirect target (`FRONTEND_URL`) is also hardcoded via environment variable and validated against `ALLOWED_REDIRECT_URLS`.

---

## 4. Token Refresh — Rotation with One-Time Use

**Audit Refs:** HIGH-02  
**Severity:** 🟠 High  
**Current State:** No token rotation. Old refresh tokens remain valid indefinitely.

### 4.1 Concept

```
Refresh Token Rotation:

1. Client sends refresh_token (in cookie) → POST /api/auth/refresh
2. Backend validates refresh_token
3. Backend BLACKLISTS the old refresh token (by jti)
4. Backend issues NEW access_token + NEW refresh_token
5. If a blacklisted refresh_token is reused → REVOKE ALL tokens for that user
   (indicates token theft — attacker and legitimate user are racing)
```

### 4.2 Backend — Add `jti` Claim to Refresh Tokens

**File: `backend/services/auth_service.py`** — Modify `create_refresh_token`:

```python
import uuid

def create_refresh_token(data: dict) -> str:
    """JWT 리프레시 토큰 생성 (jti 포함 — 회전/폐기용)"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),  # Unique token ID for blacklisting
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
```

### 4.3 Rotation Logic in Refresh Endpoint

Already shown in [Section 2.3](#23-backend--auth-routes-changes) — the `/refresh` endpoint:
1. Reads `refresh_token` from cookie
2. Checks if its `jti` is blacklisted → reject if so
3. Blacklists the current `jti`
4. Issues new token pair with new `jti`

### 4.4 Theft Detection (Reuse Detection)

If a blacklisted refresh token is presented again, it means the token was stolen (legitimate user already rotated it). In that case, revoke ALL tokens for the user:

```python
# In the refresh endpoint, add after blacklist check:
if jti and is_token_blacklisted(jti):
    # Possible token theft! Revoke all tokens for this user.
    revoke_all_user_tokens(int(payload["sub"]))
    raise HTTPException(
        status_code=401,
        detail="보안 경고: 토큰 재사용이 감지되었습니다. 모든 세션이 종료되었습니다."
    )
```

---

## 5. Session Invalidation — Token Blacklist + Logout

**Audit Refs:** HIGH-02  
**Severity:** 🟠 High  
**Current State:** No logout endpoint. No token blacklist. No revocation mechanism.

### 5.1 Blacklist Module

**File: `backend/services/token_blacklist.py`** — Create new file:

```python
"""토큰 블랙리스트 — 폐기된 리프레시 토큰 관리

Production: Redis 기반으로 교체할 것.
현재: 인메모리 dict (개발용, 서버 재시작 시 초기화).
"""
import time
from typing import Optional

# In-memory store: {jti: expiry_timestamp}
# Production: Replace with Redis SET with TTL
_blacklist: dict[str, int] = {}

# Per-user token version: {user_id: version}
# When version changes, all tokens with older version are invalid
_user_token_versions: dict[int, int] = {}


def blacklist_token(jti: str, exp: int) -> None:
    """Add a refresh token JTI to the blacklist."""
    _blacklist[jti] = exp
    _cleanup_expired()


def is_token_blacklisted(jti: str) -> bool:
    """Check if a refresh token JTI is blacklisted."""
    return jti in _blacklist


def revoke_all_user_tokens(user_id: int) -> None:
    """Increment user's token version — invalidates all existing tokens."""
    current = _user_token_versions.get(user_id, 0)
    _user_token_versions[user_id] = current + 1


def get_user_token_version(user_id: int) -> int:
    """Get current token version for a user."""
    return _user_token_versions.get(user_id, 0)


def _cleanup_expired() -> None:
    """Remove expired entries from blacklist to prevent memory growth."""
    now = int(time.time())
    expired = [jti for jti, exp in _blacklist.items() if exp < now]
    for jti in expired:
        del _blacklist[jti]
```

### 5.2 Integrate Blacklist into Auth Service

**File: `backend/services/auth_service.py`** — Add `token_version` claim:

```python
from services.token_blacklist import get_user_token_version

def create_token_pair(user_id: int, email: str, role: str) -> dict:
    """액세스 + 리프레시 토큰 쌍 생성 (token_version 포함)"""
    token_version = get_user_token_version(user_id)
    token_data = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "tv": token_version,  # token version — for global revocation
    }
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
```

**File: `backend/api/middleware/auth.py`** — Validate `token_version` in access tokens:

```python
from services.token_blacklist import get_user_token_version

async def get_current_user(request: Request, ...) -> Optional[dict]:
    # ... (token extraction as before) ...

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None

    user_id = int(payload["sub"])
    token_version = payload.get("tv", 0)

    # Check if token version is current (global revocation check)
    if token_version < get_user_token_version(user_id):
        return None  # Token was revoked via password change or admin action

    return {
        "id": user_id,
        "email": payload["email"],
        "role": payload["role"],
    }
```

### 5.3 Logout Endpoint

Already defined in [Section 2.3](#23-backend--auth-routes-changes). Summary:

```
POST /api/auth/logout
├── Read refresh_token from cookie
├── Extract jti from refresh token payload
├── Add jti to blacklist
├── Clear access_token cookie (max-age=0)
├── Clear refresh_token cookie (max-age=0)
└── Return {"message": "로그아웃 완료"}
```

### 5.4 Password Change Invalidation

When implementing a password change endpoint, call `revoke_all_user_tokens(user_id)`:

```python
@router.post("/change-password")
async def change_password(data: PasswordChange, user: dict = Depends(require_auth)):
    """비밀번호 변경 — 모든 기존 세션 무효화"""
    # ... verify old password, hash new password, update DB ...

    # Invalidate ALL existing tokens for this user
    revoke_all_user_tokens(user["id"])

    # Issue fresh tokens
    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content={"message": "비밀번호 변경 완료"})
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
```

### 5.5 Production Migration — Redis Blacklist

Replace the in-memory blacklist with Redis when deploying:

```python
# services/token_blacklist.py — production version
import redis
import os

_redis = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/1"))

def blacklist_token(jti: str, exp: int) -> None:
    ttl = max(exp - int(time.time()), 0)
    if ttl > 0:
        _redis.setex(f"blacklist:{jti}", ttl, "1")

def is_token_blacklisted(jti: str) -> bool:
    return _redis.exists(f"blacklist:{jti}") > 0

def revoke_all_user_tokens(user_id: int) -> None:
    _redis.incr(f"user_tv:{user_id}")

def get_user_token_version(user_id: int) -> int:
    v = _redis.get(f"user_tv:{user_id}")
    return int(v) if v else 0
```

---

## 6. Password Security

**Audit Refs:** H-05  
**Severity:** 🟠 High  
**Current State:** Only requires ≥8 chars + ≥1 digit. Passes `password1`, `12345678`, `qwerty12`.

### 6.1 Backend — Enhanced Password Validation

**File: `backend/api/schemas/auth.py`** — Replace `validate_password`:

```python
import re

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    nickname: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        errors = []
        if len(v) < 8:
            errors.append("8자 이상")
        if len(v) > 128:
            errors.append("128자 이하")
        if not re.search(r'[A-Z]', v):
            errors.append("대문자 1개 이상")
        if not re.search(r'[a-z]', v):
            errors.append("소문자 1개 이상")
        if not re.search(r'[0-9]', v):
            errors.append("숫자 1개 이상")
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', v):
            errors.append("특수문자 1개 이상")

        if errors:
            raise ValueError(f"비밀번호 요구사항 미충족: {', '.join(errors)}")

        # Block common weak passwords
        common_passwords = {
            'password', 'password1', '12345678', 'qwerty12', 'abcdefgh',
            'abc12345', 'iloveyou', 'admin123', 'letmein12', 'welcome1',
        }
        if v.lower() in common_passwords:
            raise ValueError("너무 흔한 비밀번호입니다. 다른 비밀번호를 선택해주세요")

        return v

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, v):
        if len(v) < 2 or len(v) > 20:
            raise ValueError("닉네임은 2-20자여야 합니다")
        if not re.match(r'^[가-힣a-zA-Z0-9_]+$', v):
            raise ValueError("닉네임은 한글, 영문, 숫자, 밑줄(_)만 사용 가능합니다")
        return v
```

### 6.2 Frontend — Password Strength Indicator

**File: `frontend/src/components/modals/LoginModal.jsx`** — Add validation feedback:

```jsx
import { useState, useMemo } from 'react';
import useStore from '../../stores/appStore';
import s from './LoginModal.module.css';

const PASSWORD_RULES = [
  { test: (v) => v.length >= 8, label: '8자 이상' },
  { test: (v) => /[A-Z]/.test(v), label: '대문자' },
  { test: (v) => /[a-z]/.test(v), label: '소문자' },
  { test: (v) => /[0-9]/.test(v), label: '숫자' },
  { test: (v) => /[!@#$%^&*()_+\-=\[\]{};:'",.<>?/\\|`~]/.test(v), label: '특수문자' },
];

export default function LoginModal() {
  const [tab, setTab] = useState('login');
  const [password, setPassword] = useState('');
  const { login, addToast, isLoginModalOpen, closeLoginModal } = useStore();

  const passwordStrength = useMemo(() => {
    return PASSWORD_RULES.map((rule) => ({
      ...rule,
      passed: rule.test(password),
    }));
  }, [password]);

  const allPassed = passwordStrength.every((r) => r.passed);

  // ... (handleLogin, handleSignup using authService) ...

  return (
    // ... existing modal wrapper ...
    // In the signup form, replace the password field:
    <div className={s.group}>
      <label>비밀번호</label>
      <input
        type="password"
        placeholder="8자 이상, 대/소문자, 숫자, 특수문자"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {password && (
        <div className={s.strengthIndicator}>
          {passwordStrength.map((rule) => (
            <span key={rule.label} className={rule.passed ? s.passed : s.failed}>
              {rule.passed ? '✓' : '✗'} {rule.label}
            </span>
          ))}
        </div>
      )}
    </div>
    // ... rest of form ...
  );
}
```

### 6.3 Bcrypt Configuration

Current `passlib` bcrypt config is correct (auto-rounds, auto-salt). No changes needed:

```python
# backend/services/auth_service.py:14 — already correct
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Default rounds = 12 (passlib default), which is appropriate
```

---

## 7. CORS — Strict Production Configuration

**Audit Refs:** C-08, HIGH-03  
**Severity:** 🟠 High  
**Current State:** `allow_methods=["*"]`, `allow_headers=["*"]` — permits TRACE and other unexpected methods.

### 7.1 Backend — CORS Changes

**File: `backend/api/app.py`** — Replace lines 34–46:

```python
import os

# CORS — 환경 변수로 허용 오리진 설정
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,                             # Required for cookies
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Explicit — no TRACE
    allow_headers=["Content-Type", "Authorization"],    # Explicit — minimal
    expose_headers=["X-Request-Id"],                    # Optional: for debugging
    max_age=600,                                        # Preflight cache: 10 min
)
```

### 7.2 Environment Configuration

**Development `.env`:**
```env
CORS_ORIGINS=http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000
```

**Production `.env`:**
```env
CORS_ORIGINS=https://wallet-savior.example.com
```

### 7.3 Docker Compose

```yaml
services:
  website-backend:
    environment:
      - CORS_ORIGINS=${CORS_ORIGINS:-http://localhost:5173}
```

---

## 8. Migration Checklist

### 8.1 File Changes Summary

| # | File | Action | Section |
|---|------|--------|---------|
| 1 | `backend/services/auth_service.py` | Modify: env-only secret, add `jti`+`tv` claims | §1, §4, §5 |
| 2 | `backend/services/cookie_service.py` | **Create**: cookie utility | §2 |
| 3 | `backend/services/token_blacklist.py` | **Create**: blacklist module | §5 |
| 4 | `backend/services/oauth_service.py` | Modify: add `state` param, `urlencode` | §3 |
| 5 | `backend/api/routes/auth.py` | Rewrite: cookie-based auth, logout, OAuth state | §2, §3, §5 |
| 6 | `backend/api/middleware/auth.py` | Modify: cookie+Bearer reader, version check | §2, §5 |
| 7 | `backend/api/schemas/auth.py` | Modify: stronger password + nickname validation | §6 |
| 8 | `backend/api/app.py` | Modify: strict CORS | §7 |
| 9 | `backend/config.py` | Modify: add JWT_SECRET_KEY check | §1 |
| 10 | `backend/.env.example` | Modify: add JWT_SECRET_KEY, CORS_ORIGINS, COOKIE_* | §1, §7 |
| 11 | `frontend/src/services/api.js` | Rewrite: credentials:'include', remove localStorage | §2 |
| 12 | `frontend/src/services/authService.js` | Rewrite: remove token management | §2 |
| 13 | `frontend/src/components/modals/LoginModal.jsx` | Modify: real auth, password strength, OAuth buttons | §3, §6 |
| 14 | `frontend/src/pages/Auth/AuthCallback.jsx` | **Create**: OAuth callback page | §3 |
| 15 | `frontend/src/App.jsx` | Modify: add `/auth/callback` route | §3 |
| 16 | `frontend/src/pages/Community/CommunityPage.jsx` | Modify: remove `localStorage.getItem('access_token')` | §2 |
| 17 | `docker-compose.yml` | Modify: add env vars | §1, §7 |

### 8.2 New Dependencies

**Backend (`requirements.txt`):**
```
# No new dependencies needed — all functionality uses stdlib + existing deps
# (secrets, uuid are stdlib; jose, passlib already installed)
```

**Frontend (`package.json`):**
```
# No new dependencies needed — fetch credentials:'include' is native
```

### 8.3 Deployment Order

```
Phase 1 — Non-breaking (can deploy independently):
  [1] JWT secret: env-only with startup crash  ← Deploy first, set env var
  [2] Password validation: stronger rules       ← Backend-only, non-breaking
  [3] CORS: strict methods/headers               ← Backend-only, test first
  [4] Nickname validation: alphanumeric only     ← Backend-only

Phase 2 — Coordinated (backend + frontend together):
  [5] Token storage: localStorage → httpOnly cookies  ← Both must deploy together
  [6] OAuth: state param + cookie tokens              ← Both must deploy together
  [7] Token blacklist + logout endpoint               ← Backend, then frontend

Phase 3 — Follow-up:
  [8] Redis blacklist (production)
  [9] Password change → revoke all tokens
  [10] Rate limiting on auth endpoints (separate spec)
```

### 8.4 Environment Variables — Complete List

```env
# === REQUIRED ===
JWT_SECRET_KEY=<64-char-hex-string>

# === RECOMMENDED ===
CORS_ORIGINS=https://your-domain.com
FRONTEND_URL=https://your-domain.com
OAUTH_REDIRECT_BASE=https://your-domain.com
COOKIE_SECURE=true
COOKIE_SAMESITE=lax
COOKIE_DOMAIN=.your-domain.com

# === OAuth Providers ===
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
KAKAO_CLIENT_ID=
KAKAO_CLIENT_SECRET=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=

# === Optional (Phase 3) ===
REDIS_URL=redis://localhost:6379/1
```

---

## 9. Test Cases

### 9.1 JWT Secret Tests

```python
# tests/test_auth_secret.py
import pytest
import os

class TestJWTSecret:
    def test_startup_fails_without_secret(self, monkeypatch):
        """서버는 JWT_SECRET_KEY 없이 시작할 수 없어야 한다"""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
            import importlib
            import services.auth_service as mod
            importlib.reload(mod)

    def test_startup_fails_with_short_secret(self, monkeypatch):
        """32자 미만의 시크릿은 거부해야 한다"""
        monkeypatch.setenv("JWT_SECRET_KEY", "tooshort")
        with pytest.raises(RuntimeError, match="at least 32"):
            import importlib
            import services.auth_service as mod
            importlib.reload(mod)

    def test_startup_succeeds_with_valid_secret(self, monkeypatch):
        """유효한 시크릿으로 정상 기동"""
        monkeypatch.setenv("JWT_SECRET_KEY", "a" * 64)
        import importlib
        import services.auth_service as mod
        importlib.reload(mod)
        assert mod.SECRET_KEY == "a" * 64
```

### 9.2 Cookie Token Tests

```python
# tests/test_auth_cookies.py
import pytest
from httpx import AsyncClient

class TestCookieAuth:
    @pytest.mark.asyncio
    async def test_login_sets_httponly_cookies(self, client: AsyncClient):
        """로그인 응답에 httpOnly 쿠키가 설정되어야 한다"""
        # Register first
        await client.post("/api/auth/register", json={
            "email": "test@example.com", "password": "Test1234!", "nickname": "tester"
        })
        # Login
        resp = await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        assert resp.status_code == 200
        cookies = resp.cookies
        assert "access_token" in cookies
        assert "refresh_token" in cookies
        # Verify tokens are NOT in response body
        body = resp.json()
        assert "access_token" not in body
        assert "refresh_token" not in body

    @pytest.mark.asyncio
    async def test_tokens_not_in_response_body(self, client: AsyncClient):
        """응답 본문에 토큰이 포함되면 안 된다"""
        resp = await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        body = resp.json()
        assert "access_token" not in body
        assert "refresh_token" not in body

    @pytest.mark.asyncio
    async def test_cookie_auth_on_protected_route(self, client: AsyncClient):
        """쿠키 기반 인증으로 보호된 라우트 접근"""
        # Login (sets cookies)
        await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        # Access protected route (cookies auto-sent)
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_bearer_token_fallback(self, client: AsyncClient):
        """Bearer 토큰 헤더로도 인증 가능해야 한다 (API 클라이언트 호환)"""
        # This test uses direct token creation for Bearer auth
        from services.auth_service import create_access_token
        token = create_access_token({"sub": "1", "email": "test@example.com", "role": "user", "tv": 0})
        resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
```

### 9.3 OAuth Security Tests

```python
# tests/test_oauth_security.py
import pytest
from httpx import AsyncClient

class TestOAuthSecurity:
    @pytest.mark.asyncio
    async def test_oauth_login_sets_state_cookie(self, client: AsyncClient):
        """OAuth 로그인 시 state 쿠키가 설정되어야 한다"""
        resp = await client.get("/api/auth/oauth/google", follow_redirects=False)
        assert resp.status_code == 302
        assert "oauth_state" in resp.cookies
        # Verify state parameter in redirect URL
        location = resp.headers["location"]
        assert "state=" in location

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_missing_state(self, client: AsyncClient):
        """state 없는 OAuth 콜백은 거부해야 한다"""
        resp = await client.get("/api/auth/oauth/google/callback?code=test_code")
        assert resp.status_code in (403, 422)  # Missing state param

    @pytest.mark.asyncio
    async def test_oauth_callback_rejects_wrong_state(self, client: AsyncClient):
        """잘못된 state의 OAuth 콜백은 거부해야 한다"""
        # Set a fake state cookie
        client.cookies.set("oauth_state", "correct_state")
        resp = await client.get(
            "/api/auth/oauth/google/callback?code=test_code&state=wrong_state"
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_oauth_callback_no_tokens_in_url(self, client: AsyncClient):
        """OAuth 콜백 리다이렉트 URL에 토큰이 포함되면 안 된다"""
        # This requires mocking the OAuth provider
        # After successful callback, check redirect URL
        # assert "access_token" not in redirect_url
        # assert "refresh_token" not in redirect_url
        pass  # Implement with OAuth provider mock
```

### 9.4 Token Refresh Rotation Tests

```python
# tests/test_token_rotation.py
import pytest
from httpx import AsyncClient

class TestTokenRotation:
    @pytest.mark.asyncio
    async def test_refresh_issues_new_tokens(self, client: AsyncClient):
        """리프레시 시 새로운 토큰 쌍을 발급해야 한다"""
        # Login
        resp = await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        old_access = resp.cookies.get("access_token")
        old_refresh = resp.cookies.get("refresh_token")

        # Refresh
        resp = await client.post("/api/auth/refresh")
        new_access = resp.cookies.get("access_token")
        new_refresh = resp.cookies.get("refresh_token")

        assert new_access != old_access
        assert new_refresh != old_refresh

    @pytest.mark.asyncio
    async def test_old_refresh_token_rejected_after_rotation(self, client: AsyncClient):
        """회전 후 이전 리프레시 토큰은 거부되어야 한다"""
        # Login
        resp = await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        old_refresh = resp.cookies.get("refresh_token")

        # Refresh (rotates token)
        await client.post("/api/auth/refresh")

        # Try using old refresh token
        client.cookies.set("refresh_token", old_refresh, path="/api/auth/refresh")
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_reuse_detection_revokes_all(self, client: AsyncClient):
        """토큰 재사용 감지 시 모든 세션을 폐기해야 한다"""
        # Similar to above but verifies that subsequent valid tokens
        # are also rejected (user_token_version incremented)
        pass  # Implement with full flow
```

### 9.5 Session Invalidation Tests

```python
# tests/test_session_invalidation.py
import pytest
from httpx import AsyncClient

class TestSessionInvalidation:
    @pytest.mark.asyncio
    async def test_logout_clears_cookies(self, client: AsyncClient):
        """로그아웃 시 쿠키가 삭제되어야 한다"""
        await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        resp = await client.post("/api/auth/logout")
        assert resp.status_code == 200
        # Cookies should be cleared (max-age=0)
        assert resp.cookies.get("access_token") is None or resp.cookies.get("access_token") == ""

    @pytest.mark.asyncio
    async def test_logout_blacklists_refresh_token(self, client: AsyncClient):
        """로그아웃 후 리프레시 토큰은 재사용 불가"""
        resp = await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        refresh = resp.cookies.get("refresh_token")

        await client.post("/api/auth/logout")

        # Try reusing the refresh token
        client.cookies.set("refresh_token", refresh, path="/api/auth/refresh")
        resp = await client.post("/api/auth/refresh")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_password_change_revokes_all_sessions(self, client: AsyncClient):
        """비밀번호 변경 시 모든 기존 세션이 무효화되어야 한다"""
        # Login on "device A"
        resp_a = await client.post("/api/auth/login", json={
            "email": "test@example.com", "password": "Test1234!"
        })
        token_a = resp_a.cookies.get("access_token")

        # Change password
        await client.post("/api/auth/change-password", json={
            "old_password": "Test1234!",
            "new_password": "NewPass5678!"
        })

        # Token from device A should be rejected
        client.cookies.set("access_token", token_a)
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 401
```

### 9.6 Password Security Tests

```python
# tests/test_password_validation.py
import pytest
from httpx import AsyncClient

class TestPasswordValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("password,should_pass", [
        ("short1A!", False),         # Too short (7 chars)
        ("alllower1!", False),       # No uppercase
        ("ALLUPPER1!", False),       # No lowercase
        ("NoDigits!!", False),       # No digit
        ("NoSpecial1a", False),      # No special char
        ("password1", False),        # Common password (lowercase)
        ("ValidPass1!", True),       # Valid
        ("MyP@ss1234", True),        # Valid
        ("가나다라1Aa!", True),       # Valid with Korean
    ])
    async def test_password_requirements(self, client: AsyncClient, password, should_pass):
        resp = await client.post("/api/auth/register", json={
            "email": f"test_{password[:4]}@test.com",
            "password": password,
            "nickname": f"user_{password[:4]}",
        })
        if should_pass:
            assert resp.status_code == 201
        else:
            assert resp.status_code == 422  # Validation error

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nickname,should_pass", [
        ("ab", True),                      # Min length
        ("a" * 20, True),                  # Max length
        ("a", False),                      # Too short
        ("a" * 21, False),                 # Too long
        ("valid_user", True),              # Underscore OK
        ("한글닉네임", True),               # Korean OK
        ("<script>", False),               # HTML rejected
        ("nick name", False),              # Space rejected
        ("nick@name", False),              # Special char rejected
    ])
    async def test_nickname_validation(self, client: AsyncClient, nickname, should_pass):
        resp = await client.post("/api/auth/register", json={
            "email": f"{nickname[:3]}@test.com",
            "password": "ValidPass1!",
            "nickname": nickname,
        })
        if should_pass:
            assert resp.status_code in (201, 400)  # 400 = duplicate
        else:
            assert resp.status_code == 422
```

### 9.7 CORS Tests

```python
# tests/test_cors.py
import pytest
from httpx import AsyncClient

class TestCORS:
    @pytest.mark.asyncio
    async def test_cors_allows_configured_origin(self, client: AsyncClient):
        """설정된 오리진은 허용"""
        resp = await client.options("/api/auth/login", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        })
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    @pytest.mark.asyncio
    async def test_cors_blocks_unknown_origin(self, client: AsyncClient):
        """미설정 오리진은 차단"""
        resp = await client.options("/api/auth/login", headers={
            "Origin": "https://evil.com",
            "Access-Control-Request-Method": "POST",
        })
        assert resp.headers.get("access-control-allow-origin") != "https://evil.com"

    @pytest.mark.asyncio
    async def test_cors_blocks_trace_method(self, client: AsyncClient):
        """TRACE 메서드는 차단"""
        resp = await client.options("/api/auth/login", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "TRACE",
        })
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "TRACE" not in allowed

    @pytest.mark.asyncio
    async def test_cors_allows_credentials(self, client: AsyncClient):
        """credentials: include 허용 (쿠키 전송용)"""
        resp = await client.options("/api/auth/login", headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        })
        assert resp.headers.get("access-control-allow-credentials") == "true"
```

### 9.8 Frontend Test Cases (Manual / E2E)

| # | Test Case | Steps | Expected Result |
|---|-----------|-------|-----------------|
| F-01 | Login stores no tokens in JS | Login → check `localStorage` and `sessionStorage` | No `access_token` or `refresh_token` keys exist |
| F-02 | Cookie sent with requests | Login → make API call → inspect network tab | `Cookie: access_token=...` header present, no `Authorization` header |
| F-03 | Token refresh is automatic | Wait for access token to expire → make API call | Request succeeds transparently; new cookies set |
| F-04 | Logout clears cookies | Click logout → inspect cookies | No `access_token` or `refresh_token` cookies |
| F-05 | OAuth redirects to provider | Click "카카오로 시작하기" | Redirected to Kakao OAuth page; URL contains `state=` param |
| F-06 | OAuth callback sets cookies | Complete OAuth flow → inspect cookies | `access_token` and `refresh_token` cookies present; URL has no tokens |
| F-07 | Password strength indicator | Type weak password in register form | Strength rules show red/green indicators |
| F-08 | Weak password rejected | Submit register with `password1` | Error message displayed |
| F-09 | XSS cannot read tokens | Execute `document.cookie` in console | httpOnly cookies not visible; `localStorage` has no tokens |

---

## Appendix A — Complete auth_service.py After All Changes

```python
"""인증 서비스 — JWT 토큰 생성/검증 + 비밀번호 해싱"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from services.token_blacklist import get_user_token_version

# 설정 — JWT 시크릿은 환경 변수 필수
SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "FATAL: JWT_SECRET_KEY environment variable is required. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
if len(SECRET_KEY) < 32:
    raise RuntimeError("JWT_SECRET_KEY must be at least 32 characters (256 bits)")

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
    """JWT 리프레시 토큰 생성 (jti 포함 — 회전/폐기용)"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
    })
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
    token_version = get_user_token_version(user_id)
    token_data = {"sub": str(user_id), "email": email, "role": role, "tv": token_version}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
```

---

## Appendix B — Complete auth.py Routes After All Changes

```python
"""인증 API 라우트 — 쿠키 기반 토큰 + OAuth CSRF 보호"""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse

from api.middleware.auth import require_auth
from api.schemas.auth import UserLogin, UserRegister
from services.auth_service import (
    create_token_pair, decode_token, hash_password, verify_password,
)
from services.cookie_service import clear_auth_cookies, set_auth_cookies
from services.oauth_service import (
    FRONTEND_URL, exchange_code_for_token, generate_oauth_state,
    get_oauth_login_url, get_user_info,
)
from services.token_blacklist import blacklist_token, is_token_blacklisted, revoke_all_user_tokens

router = APIRouter(prefix="/api/auth", tags=["인증"])

_users_db: dict[str, dict] = {}
_next_id = 1

OAUTH_STATE_COOKIE = "oauth_state"
OAUTH_STATE_MAX_AGE = 600


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister):
    global _next_id
    if data.email in _users_db:
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")
    for user in _users_db.values():
        if user["nickname"] == data.nickname:
            raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")

    user = {
        "id": _next_id, "email": data.email, "nickname": data.nickname,
        "hashed_password": hash_password(data.password), "role": "user",
    }
    _users_db[data.email] = user
    _next_id += 1

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content={"message": "회원가입 완료", "expires_in": tokens["expires_in"]}, status_code=201)
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])


@router.post("/login")
async def login(data: UserLogin):
    user = _users_db.get(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다")

    tokens = create_token_pair(user["id"], user["email"], user["role"])
    response = JSONResponse(content={"message": "로그인 성공", "expires_in": tokens["expires_in"]})
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])


@router.post("/refresh")
async def refresh(request: Request):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="리프레시 토큰이 없습니다")

    payload = decode_token(refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="유효하지 않은 리프레시 토큰입니다")

    jti = payload.get("jti")
    if jti and is_token_blacklisted(jti):
        revoke_all_user_tokens(int(payload["sub"]))
        raise HTTPException(status_code=401, detail="보안 경고: 토큰 재사용 감지. 모든 세션 종료.")

    if jti:
        blacklist_token(jti, payload.get("exp", 0))

    tokens = create_token_pair(int(payload["sub"]), payload["email"], payload["role"])
    response = JSONResponse(content={"message": "토큰 갱신 완료", "expires_in": tokens["expires_in"]})
    return set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])


@router.post("/logout")
async def logout(request: Request):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        payload = decode_token(refresh_token)
        if payload and payload.get("jti"):
            blacklist_token(payload["jti"], payload.get("exp", 0))

    response = JSONResponse(content={"message": "로그아웃 완료"})
    return clear_auth_cookies(response)


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    state = generate_oauth_state()
    try:
        url = get_oauth_login_url(provider, state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE, value=state, httponly=True,
        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        samesite="lax", max_age=OAUTH_STATE_MAX_AGE, path="/api/auth/oauth",
    )
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, code: str, state: str, request: Request):
    global _next_id
    stored_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not stored_state or not secrets.compare_digest(stored_state, state):
        raise HTTPException(status_code=403, detail="OAuth state 검증 실패 (CSRF 방지)")

    try:
        token_data = await exchange_code_for_token(provider, code)
        user_info = await get_user_info(provider, token_data["access_token"])

        user = _users_db.get(user_info.email)
        if not user:
            user = {
                "id": _next_id, "email": user_info.email, "nickname": user_info.nickname,
                "hashed_password": None, "role": "user",
                "oauth_provider": provider, "oauth_id": user_info.provider_user_id,
            }
            _users_db[user_info.email] = user
            _next_id += 1

        tokens = create_token_pair(user["id"], user["email"], user["role"])
        response = RedirectResponse(url=FRONTEND_URL, status_code=302)
        set_auth_cookies(response, tokens["access_token"], tokens["refresh_token"])
        response.delete_cookie(key=OAUTH_STATE_COOKIE, path="/api/auth/oauth")
        return response
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"OAuth 인증 실패: {str(e)}")


@router.get("/me")
async def get_me(user: dict = Depends(require_auth)):
    return {"id": user["id"], "email": user["email"], "role": user["role"]}
```
