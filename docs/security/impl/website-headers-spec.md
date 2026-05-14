# Website Security Hardening — Implementation Spec

**Scope:** Security Headers, Rate Limiting, Error Handling, API Docs, Request Size Limits, CSRF  
**Sub-project:** `packages/website/backend` (FastAPI)  
**Date:** 2025-07-17  
**Status:** Implementation Plan  
**Source findings:** `website-code-audit.md` (H-03, M-02, M-04, M-05, C-07, C-08), `website-arch-audit.md` (MEDIUM-01, HIGH-04, HIGH-06)

---

## Table of Contents

1. [Security Headers Middleware](#1-security-headers-middleware)
2. [Rate Limiting](#2-rate-limiting)
3. [Error Handling](#3-error-handling)
4. [API Docs — Disable in Production](#4-api-docs--disable-in-production)
5. [Request Size Limits](#5-request-size-limits)
6. [CSRF Protection](#6-csrf-protection)
7. [Integration — app.py Changes](#7-integration--apppy-changes)
8. [New Dependencies](#8-new-dependencies)
9. [Test Cases](#9-test-cases)
10. [Rollout Checklist](#10-rollout-checklist)

---

## 1. Security Headers Middleware

**Findings addressed:** H-03, M-11 (code audit), MEDIUM-01 (arch audit)

### 1.1 Current State

- **No security headers** are set anywhere in the backend.
- No CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, or Permissions-Policy.
- Missing headers enable clickjacking, MIME-sniffing, XSS bypass, and SSL-stripping attacks.

### 1.2 Implementation

Create `backend/api/middleware/security_headers.py`:

```python
"""
보안 헤더 미들웨어 — 모든 응답에 보안 HTTP 헤더를 추가합니다.

Findings: H-03, MEDIUM-01
"""

import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# CSP를 환경변수로 오버라이드할 수 있도록 지원
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    "connect-src 'self' https://openapi.naver.com https://map.naver.com; "
    "frame-src https://map.naver.com; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "object-src 'none';"
)

SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": os.getenv("CSP_POLICY", _DEFAULT_CSP),
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "0",  # disabled — CSP replaces legacy auditor
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "geolocation=(self), "
        "camera=(), "
        "microphone=(), "
        "payment=(), "
        "usb=()"
    ),
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "credentialless",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """모든 HTTP 응답에 보안 헤더를 추가합니다."""

    def __init__(self, app, headers: dict[str, str] | None = None):
        super().__init__(app)
        self._headers = headers or SECURITY_HEADERS

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for name, value in self._headers.items():
            response.headers[name] = value
        # 서버 소프트웨어 정보 제거 (정보 노출 방지)
        response.headers.pop("Server", None)
        return response
```

### 1.3 Header Reference

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Security-Policy` | see `_DEFAULT_CSP` above | Restricts resource loading; blocks inline scripts; limits frame sources to Naver Maps |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | Enforce HTTPS for 1 year; prevent SSL stripping |
| `X-Frame-Options` | `DENY` | Clickjacking protection (legacy fallback for `frame-ancestors 'none'`) |
| `X-Content-Type-Options` | `nosniff` | Block MIME-sniffing attacks |
| `X-XSS-Protection` | `0` | Disable legacy browser XSS auditor (can itself be exploited) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Prevent token/path leakage in Referer headers |
| `Permissions-Policy` | `geolocation=(self), camera=(), microphone=(), payment=(), usb=()` | Restrict browser APIs; only geolocation allowed (for Naver Maps) |
| `Cross-Origin-Opener-Policy` | `same-origin` | Isolate browsing context from cross-origin popups |
| `Cross-Origin-Resource-Policy` | `same-origin` | Block cross-origin resource reads |
| `Cross-Origin-Embedder-Policy` | `credentialless` | Cross-origin requests load without credentials unless opted in |

### 1.4 Dev vs. Production Notes

- In **development**, CSP `style-src 'unsafe-inline'` is required for Vite hot-reload and inline styles.
- In **production**, the nginx reverse proxy should also set these headers (belt-and-suspenders). See the nginx config in `website-arch-audit.md § Recommended Security Headers`.
- The `Strict-Transport-Security` header should only be sent over HTTPS. In dev (HTTP), the browser ignores it — no harm.

---

## 2. Rate Limiting

**Findings addressed:** M-02 (code audit — only vote/report limited), HIGH-04 (arch audit — no global rate limiting), HIGH-06 (arch audit — IP spoofing)

### 2.1 Current State

- Only 2 endpoints rate-limited: `/hotdeals/{id}/vote` and `/hotdeals/{id}/report` (10 req/min per IP).
- In-memory `dict` — resets on restart, doesn't work across workers.
- Uses `request.client.host` — spoofable behind proxy.
- Auth, community, search, scraping endpoints are **completely unprotected**.

### 2.2 Architecture Decision

Use **`slowapi`** (Starlette-compatible wrapper around `limits`) for per-route rate limiting. Storage backend:

| Environment | Storage | Reason |
|-------------|---------|--------|
| Dev / single-worker | `memory://` | Zero setup; redis is `requirements.txt` listed but unused |
| Production | `redis://redis:6379/1` | Survives restarts, multi-worker safe |

The storage URI is configurable via `RATE_LIMIT_STORAGE_URI` env var (default: `memory://`).

### 2.3 Implementation

Create `backend/api/middleware/rate_limit.py`:

```python
"""
레이트 리밋 설정 — slowapi 기반 per-IP 요청 제한.

Findings: M-02, HIGH-04, HIGH-06
"""

import os
import logging
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request

logger = logging.getLogger(__name__)

STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


def _get_client_ip(request: Request) -> str:
    """
    프록시 환경에서 실제 클라이언트 IP를 추출합니다.

    우선순위:
    1. X-Real-IP (nginx 등 신뢰할 수 있는 리버스 프록시가 설정)
    2. X-Forwarded-For 의 첫 번째 IP
    3. request.client.host (직접 연결)
    """
    # 프로덕션에서는 TRUSTED_PROXY_IPS 환경변수로 신뢰할 수 있는 프록시 IP 목록 설정
    trusted_proxies = set(
        os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    )

    client_host = request.client.host if request.client else "unknown"

    # 프록시 뒤에 있는 경우에만 헤더를 신뢰
    if client_host in trusted_proxies:
        # X-Real-IP 우선
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        # X-Forwarded-For 사용 (첫 번째 = 원래 클라이언트)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return client_host


limiter = Limiter(
    key_func=_get_client_ip,
    storage_uri=STORAGE_URI,
    default_limits=["100/minute"],  # 글로벌 기본값
)
```

### 2.4 Per-Route Rate Limit Tiers

| Tier | Limit | Endpoints | Rationale |
|------|-------|-----------|-----------|
| **Auth** | `5/minute` | `POST /api/auth/login`, `POST /api/auth/register`, `POST /api/auth/refresh` | Prevent credential stuffing & brute-force |
| **Write** | `30/minute` | `POST /api/posts`, `PUT /api/posts/{id}`, `DELETE /api/posts/{id}`, `POST /api/posts/{id}/comments`, `POST /api/posts/{id}/vote`, `POST /api/hotdeals/{id}/vote`, `POST /api/hotdeals/{id}/report` | Prevent spam & resource abuse |
| **Search / Scrape** | `20/minute` | `GET /api/search`, `GET /api/local/search`, `GET /api/local/nearby` | Playwright browser pool is expensive |
| **Read (default)** | `100/minute` | All other `GET` endpoints | Generous but bounded |

### 2.5 Applying to Routes

**Auth routes** — edit `backend/api/routes/auth.py`:

```python
from api.middleware.rate_limit import limiter

@router.post("/register", ...)
@limiter.limit("5/minute")
async def register(request: Request, data: UserRegister):
    ...

@router.post("/login", ...)
@limiter.limit("5/minute")
async def login(request: Request, data: UserLogin):
    ...

@router.post("/refresh", ...)
@limiter.limit("5/minute")
async def refresh(request: Request, data: TokenRefresh):
    ...
```

> **Important:** `request: Request` must be the first parameter for slowapi to extract the IP.

**Community write routes** — edit `backend/api/routes/community.py`:

```python
from api.middleware.rate_limit import limiter

@router.post("")
@limiter.limit("30/minute")
async def create_post(request: Request, body: PostCreate, user: dict = Depends(get_current_user)):
    ...

@router.post("/{post_id}/comments")
@limiter.limit("30/minute")
async def create_comment(request: Request, post_id: int, body: CommentCreate, user: dict = Depends(require_auth)):
    ...

@router.post("/{post_id}/vote")
@limiter.limit("30/minute")
async def vote_post(request: Request, post_id: int, body: VoteRequest, user: dict = Depends(require_auth)):
    ...
```

**Hotdeal write routes** — edit `backend/api/routes/hotdeals.py`:

```python
from api.middleware.rate_limit import limiter

# Remove old _rate_limit_store, _check_rate_limit function entirely.

@router.post("/{hotdeal_id}/vote")
@limiter.limit("30/minute")
async def vote_hotdeal(request: Request, hotdeal_id: int):
    ...

@router.post("/{hotdeal_id}/report")
@limiter.limit("30/minute")
async def report_hotdeal(request: Request, hotdeal_id: int):
    ...
```

**Search / Scrape routes** — edit `backend/api/routes/naver_local.py`, `backend/api/routes/search.py`:

```python
from api.middleware.rate_limit import limiter

@router.get("/search")
@limiter.limit("20/minute")
async def search(request: Request, ...):
    ...
```

### 2.6 Rate Limit Response Format

When rate-limited, slowapi returns:

```json
{
  "error": "Rate limit exceeded: 5 per 1 minute"
}
```

Override in `app.py` registration for consistent API format:

```python
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "error": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
            "detail": str(exc.detail),
            "retry_after": exc.detail,
        },
        headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
    )
```

### 2.7 Remove Old In-Memory Rate Limiter

Delete from `hotdeals.py`:
- Lines 23-39: `_rate_limit_store`, `_RATE_LIMIT_WINDOW`, `_RATE_LIMIT_MAX`, `_check_rate_limit()`
- All calls to `_check_rate_limit()` inside vote/report handlers (replace with `@limiter.limit` decorator)

---

## 3. Error Handling

**Findings addressed:** M-04 (info disclosure via OAuth errors), M-05 (silent exception swallowing)

### 3.1 Current State

- No global exception handler; FastAPI defaults expose validation errors with field names.
- OAuth callback leaks full exception strings: `f"OAuth 인증 실패: {str(e)}"`.
- Multiple `except Exception: pass` blocks silently swallow errors.
- No structured logging of errors.

### 3.2 Implementation

Create `backend/api/middleware/error_handler.py`:

```python
"""
글로벌 에러 핸들러 — 내부 정보 노출 방지 및 구조화된 에러 응답.

Findings: M-04, M-05
"""

import logging
import traceback
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("walletguardian.errors")


def register_error_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 글로벌 에러 핸들러를 등록합니다."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """HTTPException — detail은 그대로 반환 (개발자가 의도적으로 설정한 메시지)."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": exc.detail,
            },
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Pydantic 유효성 검사 실패 — 필드명과 메시지만 반환.
        내부 타입 정보, 스택 트레이스 제거.
        """
        safe_errors = []
        for err in exc.errors():
            safe_errors.append({
                "field": " → ".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", "유효하지 않은 값"),
            })
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "error": "입력값 유효성 검사 실패",
                "details": safe_errors,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        처리되지 않은 예외 — 내부 정보를 절대 클라이언트에 노출하지 않습니다.
        에러 ID를 생성하여 로그와 응답을 연결합니다.
        """
        error_id = uuid.uuid4().hex[:12]
        logger.error(
            "Unhandled exception [%s] %s %s: %s\n%s",
            error_id,
            request.method,
            request.url.path,
            str(exc),
            traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "서버 내부 오류가 발생했습니다.",
                "error_id": error_id,
            },
        )
```

### 3.3 Fix OAuth Error Leakage

In `backend/api/routes/auth.py`, line 109:

**Before:**
```python
except Exception as e:
    raise HTTPException(status_code=400, detail=f"OAuth 인증 실패: {str(e)}")
```

**After:**
```python
except Exception as e:
    logger.error("OAuth callback failed for provider=%s: %s", provider, str(e), exc_info=True)
    raise HTTPException(status_code=400, detail="OAuth 인증에 실패했습니다. 다시 시도해주세요.")
```

### 3.4 Replace Silent Exception Swallowing

Everywhere `except Exception: pass` appears (app.py lines 164-165, 174, 183, 191; hotdeals.py lines 127-128, 145-146, 165-166):

**Before:**
```python
try:
    result["hotdeals"] = s.get_hotdeals(sort="recent", per_page=10)
except Exception:
    pass
```

**After:**
```python
try:
    result["hotdeals"] = s.get_hotdeals(sort="recent", per_page=10)
except Exception:
    logger.exception("Failed to load hotdeals for dashboard")
    result["hotdeals"] = []
```

---

## 4. API Docs — Disable in Production

### 4.1 Current State

FastAPI auto-generates `/docs` (Swagger UI) and `/redoc` endpoints. These are accessible to anyone and expose the full API schema, including internal endpoints, parameter types, and error structures.

### 4.2 Implementation

In `backend/api/app.py`, `create_app()`:

```python
import os

def create_app() -> FastAPI:
    is_production = os.getenv("ENVIRONMENT", "development") == "production"

    app = FastAPI(
        title="WalletSavior API",
        version="1.0.0",
        # 프로덕션에서 API 문서 비활성화
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    ...
```

### 4.3 Environment Variable

| Variable | Values | Default |
|----------|--------|---------|
| `ENVIRONMENT` | `development`, `staging`, `production` | `development` |

When `ENVIRONMENT=production`:
- `/docs` → 404
- `/redoc` → 404
- `/openapi.json` → 404

---

## 5. Request Size Limits

**Findings addressed:** H-02 (code audit — no file upload size/type validation), MEDIUM-06 (arch audit — unbounded content fields)

### 5.1 Current State

- No request body size limit at any layer.
- Community post `content` field is unbounded (`str` with no `max_length`).
- Rich-text editor encodes images as base64 data URLs with no size check — a 50 MB image becomes 67 MB of JSON.
- Hotdeal vote/report use raw `request.json()` with no Pydantic validation — `reason` is unbounded.

### 5.2 Implementation — Global Body Size Limit

Create `backend/api/middleware/request_size.py`:

```python
"""
요청 본문 크기 제한 미들웨어.

Findings: H-02, MEDIUM-06
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 기본 최대 요청 크기: 10MB
DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Content-Length 기반 요청 크기 제한."""

    def __init__(self, app, max_body_size: int = DEFAULT_MAX_BODY_SIZE):
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            if int(content_length) > self.max_body_size:
                return JSONResponse(
                    status_code=413,
                    content={
                        "success": False,
                        "error": f"요청 크기가 제한을 초과했습니다 (최대 {self.max_body_size // (1024*1024)}MB).",
                    },
                )
        return await call_next(request)
```

### 5.3 Pydantic Schema Constraints

Edit `backend/api/schemas/community.py`:

```python
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional

class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50_000)  # ~50KB max
    post_type: str = Field(..., max_length=20)
    category: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0, le=100_000_000)
    url: Optional[str] = Field(None, max_length=2048)
    images: Optional[list[str]] = Field(None, max_length=10)  # max 10 images

class PostUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1, max_length=50_000)
    category: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0, le=100_000_000)
    url: Optional[str] = Field(None, max_length=2048)

class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5_000)  # ~5KB max
    parent_id: Optional[int] = None
```

### 5.4 Hotdeal Vote/Report — Add Pydantic Models

Create or edit `backend/api/schemas/hotdeals.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional

class HotdealVoteRequest(BaseModel):
    vote_type: str = Field("hot", pattern=r"^(hot|not)$")

class HotdealReportRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

class HotdealCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2_000)
```

Then update `hotdeals.py` to use Pydantic models instead of raw `request.json()`:

**Before:**
```python
body = await request.json()
vote_type = body.get("vote_type", "hot")
```

**After:**
```python
async def vote_hotdeal(request: Request, hotdeal_id: int, body: HotdealVoteRequest):
    vote_type = body.vote_type
```

### 5.5 Size Limit Summary

| Resource | Limit | Enforcement Layer |
|----------|-------|-------------------|
| Any HTTP body | 10 MB | `RequestSizeLimitMiddleware` |
| Post title | 200 chars | Pydantic `max_length` |
| Post content | 50,000 chars (~50 KB) | Pydantic `max_length` |
| Comment content | 5,000 chars (~5 KB) | Pydantic `max_length` |
| Images per post | 10 items | Pydantic `max_length` on list |
| URL field | 2,048 chars | Pydantic `max_length` |
| Vote type | `hot` or `not` only | Pydantic `pattern` |
| Report reason | 500 chars | Pydantic `max_length` |
| Hotdeal comment | 2,000 chars | Pydantic `max_length` |
| Image file (frontend) | 5 MB per file | Frontend JS validation |
| Price | 0 – 100,000,000 | Pydantic `ge`/`le` |

---

## 6. CSRF Protection

**Findings addressed:** C-07 (code audit — no CSRF), C-08 (code audit — CORS allows credentials)

### 6.1 Current State

- Auth uses Bearer token in `Authorization` header (not cookies).
- Bearer tokens are stored in `localStorage`.
- No CSRF token mechanism exists.
- CORS allows `credentials: true` with `allow_methods=["*"]`.

### 6.2 Architecture Decision

The current auth model uses **Bearer tokens in the Authorization header**. Browsers **do not auto-send** Authorization headers on cross-origin requests — only cookies are auto-sent. Therefore, **CSRF is not exploitable** in the current Bearer-token flow.

**However**, the planned migration to `httpOnly` cookies (to fix C-02 / HIGH-01) **will introduce CSRF risk**. This spec provides the CSRF implementation that must ship **simultaneously** with the cookie migration.

### 6.3 Chosen Pattern: Double-Submit Cookie

The **double-submit cookie** pattern:

1. Server sets a `csrf_token` cookie (NOT `httpOnly` — JS must read it).
2. For every state-changing request (POST/PUT/DELETE), the client sends the same value in the `X-CSRF-Token` header.
3. Server compares the cookie value with the header value. If they match, the request is legitimate (a cross-origin attacker cannot read the cookie to copy it into the header).

### 6.4 Implementation

Create `backend/api/middleware/csrf.py`:

```python
"""
CSRF 보호 미들웨어 — Double-Submit Cookie 패턴.

이 미들웨어는 httpOnly 쿠키 기반 인증으로 마이그레이션할 때 함께 활성화해야 합니다.
Bearer 토큰(Authorization 헤더) 사용 시에는 CSRF 공격이 불가능하므로
활성화하지 않아도 됩니다.

Findings: C-07
"""

import os
import secrets
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

logger = logging.getLogger(__name__)

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_LENGTH = 32
CSRF_COOKIE_SECURE = os.getenv("ENVIRONMENT", "development") == "production"
CSRF_COOKIE_SAMESITE = "strict"

# CSRF 검사 제외 경로 (인증 불필요한 읽기 전용 or 토큰 발급 경로)
CSRF_EXEMPT_PATHS: set[str] = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/auth/oauth",
}

# CSRF 검사 대상 HTTP 메서드
CSRF_PROTECTED_METHODS: set[str] = {"POST", "PUT", "DELETE", "PATCH"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-Submit Cookie CSRF 보호."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # GET/HEAD/OPTIONS는 CSRF 검사 불필요
        if request.method not in CSRF_PROTECTED_METHODS:
            response = await call_next(request)
            self._ensure_csrf_cookie(request, response)
            return response

        # 제외 경로 확인
        if self._is_exempt(request.url.path):
            response = await call_next(request)
            self._ensure_csrf_cookie(request, response)
            return response

        # Bearer 토큰 사용 시 CSRF 검사 생략
        # (Authorization 헤더는 브라우저가 자동으로 보내지 않음)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            response = await call_next(request)
            self._ensure_csrf_cookie(request, response)
            return response

        # Double-Submit Cookie 검증
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)

        if not cookie_token or not header_token:
            logger.warning(
                "CSRF token missing: cookie=%s, header=%s, path=%s",
                bool(cookie_token), bool(header_token), request.url.path,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": "CSRF 토큰이 필요합니다.",
                },
            )

        if not secrets.compare_digest(cookie_token, header_token):
            logger.warning("CSRF token mismatch for %s", request.url.path)
            return JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": "CSRF 토큰이 유효하지 않습니다.",
                },
            )

        response = await call_next(request)
        self._ensure_csrf_cookie(request, response)
        return response

    def _is_exempt(self, path: str) -> bool:
        """경로가 CSRF 검사에서 제외되는지 확인."""
        for exempt in CSRF_EXEMPT_PATHS:
            if path.startswith(exempt):
                return True
        return False

    @staticmethod
    def _ensure_csrf_cookie(request: Request, response: Response) -> None:
        """CSRF 쿠키가 없으면 새로 생성합니다."""
        if CSRF_COOKIE_NAME not in request.cookies:
            token = secrets.token_hex(CSRF_TOKEN_LENGTH)
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=token,
                httponly=False,  # JS가 읽어서 헤더에 포함해야 하므로 httpOnly=False
                secure=CSRF_COOKIE_SECURE,
                samesite=CSRF_COOKIE_SAMESITE,
                path="/",
                max_age=86400,  # 24시간
            )
```

### 6.5 Frontend Integration

The frontend must read the CSRF cookie and include it in state-changing requests:

```javascript
// utils/csrf.js
export function getCsrfToken() {
    const match = document.cookie.match(/csrf_token=([^;]+)/);
    return match ? match[1] : null;
}
```

```javascript
// api.js — Add to request interceptor
const csrfToken = getCsrfToken();
if (csrfToken && ['POST', 'PUT', 'DELETE', 'PATCH'].includes(method.toUpperCase())) {
    headers['X-CSRF-Token'] = csrfToken;
}
```

### 6.6 CSRF Activation Timeline

| Phase | Auth Model | CSRF Status |
|-------|-----------|-------------|
| **Now** (Bearer tokens in localStorage) | Authorization header | **Disabled** — not needed |
| **After cookie migration** (httpOnly cookies) | Cookies | **Enabled** — required |

The `CSRFMiddleware` code is written now but should be registered in `app.py` **only when the cookie migration ships**. The middleware already has a bypass for Bearer token auth as a safety net.

---

## 7. Integration — app.py Changes

### 7.1 Complete Middleware Registration Order

Middleware order in Starlette/FastAPI is **LIFO** — the last added middleware runs first. Register in this order:

```python
# backend/api/app.py — create_app() 내부

import os
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.middleware.request_size import RequestSizeLimitMiddleware
from api.middleware.error_handler import register_error_handlers
from api.middleware.rate_limit import limiter
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

def create_app() -> FastAPI:
    is_production = os.getenv("ENVIRONMENT", "development") == "production"

    app = FastAPI(
        title="WalletSavior API",
        version="1.0.0",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    # ── 에러 핸들러 등록 ──
    register_error_handlers(app)

    # ── 레이트 리밋 ──
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

    # ── 미들웨어 (LIFO: 마지막 추가 = 먼저 실행) ──

    # 1. CORS (기존 — 수정)
    ALLOWED_ORIGINS = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # 명시적으로 제한
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )

    # 2. GZip (기존)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # 3. 보안 헤더
    app.add_middleware(SecurityHeadersMiddleware)

    # 4. 요청 크기 제한
    app.add_middleware(RequestSizeLimitMiddleware, max_body_size=10 * 1024 * 1024)

    # 5. CSRF (httpOnly 쿠키 마이그레이션 후 활성화)
    # from api.middleware.csrf import CSRFMiddleware
    # app.add_middleware(CSRFMiddleware)

    # ── 라우터 등록 (기존 유지) ──
    ...
```

### 7.2 CORS Fix (C-08)

The CORS middleware must also be tightened:

**Before:**
```python
allow_methods=["*"],
allow_headers=["*"],
```

**After:**
```python
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
```

This blocks `TRACE` (XST attacks) and restricts headers to known values.

---

## 8. New Dependencies

Add to `backend/requirements.txt`:

```
slowapi>=0.1.9
```

> `slowapi` depends on `limits` which supports `memory://` and `redis://` backends. No additional packages needed for in-memory mode. For Redis, the already-installed `redis>=5.0.0` is sufficient.

No other new dependencies are required. All middleware is written with Starlette builtins.

---

## 9. Test Cases

### 9.1 Security Headers Tests

Create `backend/tests/test_security_headers.py`:

```python
"""보안 헤더 미들웨어 테스트"""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestSecurityHeaders:
    """모든 응답에 보안 헤더가 포함되는지 확인."""

    def test_hsts_header_present(self, client):
        r = client.get("/api/products")
        assert r.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains; preload"

    def test_x_frame_options_deny(self, client):
        r = client.get("/api/products")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_x_content_type_options_nosniff(self, client):
        r = client.get("/api/products")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy(self, client):
        r = client.get("/api/products")
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        r = client.get("/api/products")
        policy = r.headers.get("Permissions-Policy")
        assert "camera=()" in policy
        assert "microphone=()" in policy
        assert "geolocation=(self)" in policy

    def test_csp_present(self, client):
        r = client.get("/api/products")
        csp = r.headers.get("Content-Security-Policy")
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_cross_origin_policies(self, client):
        r = client.get("/api/products")
        assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
        assert r.headers.get("Cross-Origin-Resource-Policy") == "same-origin"

    def test_xxss_protection_disabled(self, client):
        r = client.get("/api/products")
        assert r.headers.get("X-XSS-Protection") == "0"

    def test_server_header_removed(self, client):
        r = client.get("/api/products")
        assert "Server" not in r.headers

    def test_headers_on_error_responses(self, client):
        """에러 응답에도 보안 헤더가 포함되는지 확인."""
        r = client.get("/api/posts/99999999")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
```

### 9.2 Rate Limiting Tests

Create `backend/tests/test_rate_limiting.py`:

```python
"""레이트 리밋 테스트"""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestRateLimiting:
    """레이트 리밋이 올바르게 동작하는지 확인."""

    def test_auth_login_rate_limit_allows_under_threshold(self, client):
        """5회 이하 요청은 허용."""
        for _ in range(5):
            r = client.post("/api/auth/login", json={
                "email": "test@test.com",
                "password": "wrong"
            })
            assert r.status_code != 429

    def test_auth_login_rate_limit_blocks_over_threshold(self, client):
        """5회 초과 시 429 반환."""
        for _ in range(6):
            r = client.post("/api/auth/login", json={
                "email": "test@test.com",
                "password": "wrong"
            })
        assert r.status_code == 429

    def test_rate_limit_response_format(self, client):
        """429 응답에 올바른 JSON 구조 확인."""
        for _ in range(6):
            r = client.post("/api/auth/login", json={
                "email": "test@test.com",
                "password": "wrong"
            })
        body = r.json()
        assert body["success"] is False
        assert "요청이 너무 많습니다" in body["error"]

    def test_rate_limit_retry_after_header(self, client):
        """429 응답에 Retry-After 헤더 포함."""
        for _ in range(6):
            r = client.post("/api/auth/login", json={
                "email": "test@test.com",
                "password": "wrong"
            })
        assert "Retry-After" in r.headers

    def test_read_endpoint_allows_100_requests(self, client):
        """읽기 엔드포인트는 100회까지 허용."""
        for i in range(100):
            r = client.get("/api/products")
            assert r.status_code != 429

    def test_different_ips_have_separate_limits(self, client):
        """IP별로 별도 제한 적용 (시뮬레이션)."""
        # 기본 IP로 5회 소진
        for _ in range(6):
            client.post("/api/auth/login", json={
                "email": "test@test.com", "password": "wrong"
            })
        # 다른 IP로 요청 (X-Forwarded-For 시뮬레이션은 프록시 설정에 따라 다름)
        # 단위 테스트에서는 기본 IP만 테스트 가능
```

### 9.3 Error Handling Tests

Create `backend/tests/test_error_handling.py`:

```python
"""에러 핸들링 테스트"""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestErrorHandling:
    """에러 응답이 안전한 형식인지 확인."""

    def test_404_returns_safe_error(self, client):
        r = client.get("/api/nonexistent-endpoint-12345")
        assert r.status_code == 404
        body = r.json()
        assert body["success"] is False
        assert "traceback" not in str(body).lower()
        assert "stack" not in str(body).lower()

    def test_validation_error_no_internal_types(self, client):
        """유효성 검사 에러에 내부 타입 정보가 노출되지 않는지 확인."""
        r = client.post("/api/auth/login", json={"email": 123})  # wrong type
        assert r.status_code == 422
        body = r.json()
        assert body["success"] is False
        assert "error" in body
        # Python 내부 타입 이름이 노출되지 않아야 함
        body_str = str(body)
        assert "pydantic" not in body_str.lower()

    def test_validation_error_shows_field_names(self, client):
        """어떤 필드가 잘못되었는지 사용자에게 알려줌."""
        r = client.post("/api/auth/register", json={
            "email": "not-an-email",
            "password": "short",
            "nickname": "a"
        })
        assert r.status_code == 422
        body = r.json()
        assert "details" in body or "error" in body

    def test_unhandled_exception_returns_error_id(self, client):
        """서버 내부 에러 시 에러 ID만 반환하고 스택 트레이스는 노출하지 않음."""
        # 이 테스트는 의도적으로 에러를 발생시키는 테스트 엔드포인트가 필요
        # 통합 테스트에서 더 상세하게 검증
        pass

    def test_oauth_error_no_internal_details(self, client):
        """OAuth 에러에 내부 정보가 포함되지 않는지 확인."""
        r = client.get("/api/auth/oauth/invalid_provider/callback?code=fake")
        body = r.json()
        body_str = str(body)
        # 내부 예외 메시지, 스택 트레이스, 파일 경로가 노출되지 않아야 함
        assert "traceback" not in body_str.lower()
        assert ".py" not in body_str
        assert "File " not in body_str
```

### 9.4 Request Size Limit Tests

Create `backend/tests/test_request_size.py`:

```python
"""요청 크기 제한 테스트"""
import pytest
from fastapi.testclient import TestClient
from api.app import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestRequestSizeLimits:
    """요청 본문 크기 제한이 올바르게 동작하는지 확인."""

    def test_normal_size_request_accepted(self, client):
        """일반 크기 요청은 정상 처리."""
        r = client.post("/api/auth/login", json={
            "email": "test@test.com",
            "password": "testpassword1"
        })
        assert r.status_code != 413

    def test_oversized_request_rejected(self, client):
        """10MB 초과 요청은 413 반환."""
        huge_content = "x" * (11 * 1024 * 1024)  # 11MB
        r = client.post(
            "/api/posts",
            json={"title": "test", "content": huge_content, "post_type": "free"},
            headers={"Content-Length": str(len(huge_content))}
        )
        assert r.status_code == 413

    def test_post_title_max_length(self, client):
        """게시글 제목은 200자 이하여야 함."""
        r = client.post("/api/posts", json={
            "title": "x" * 201,
            "content": "test content",
            "post_type": "free"
        })
        assert r.status_code == 422

    def test_post_content_max_length(self, client):
        """게시글 내용은 50,000자 이하여야 함."""
        r = client.post("/api/posts", json={
            "title": "test",
            "content": "x" * 50_001,
            "post_type": "free"
        })
        assert r.status_code == 422

    def test_comment_max_length(self, client):
        """댓글은 5,000자 이하여야 함."""
        # 게시글 ID 1이 있다고 가정 (없으면 404, 하지만 validation은 먼저 실행)
        r = client.post("/api/posts/1/comments", json={
            "content": "x" * 5_001
        })
        # 422 (validation) 또는 401 (auth) 또는 404 (not found) 중 하나
        assert r.status_code in (422, 401, 404)
```

### 9.5 API Docs Disable Tests

Create `backend/tests/test_api_docs.py`:

```python
"""API 문서 비활성화 테스트"""
import os
import pytest
from fastapi.testclient import TestClient


class TestApiDocsProduction:
    """프로덕션 환경에서 API 문서가 비활성화되는지 확인."""

    def test_docs_disabled_in_production(self):
        os.environ["ENVIRONMENT"] = "production"
        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        assert client.get("/docs").status_code == 404
        assert client.get("/redoc").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        os.environ.pop("ENVIRONMENT", None)

    def test_docs_enabled_in_development(self):
        os.environ["ENVIRONMENT"] = "development"
        from api.app import create_app
        app = create_app()
        client = TestClient(app)
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        assert client.get("/openapi.json").status_code == 200
        os.environ.pop("ENVIRONMENT", None)
```

### 9.6 CSRF Protection Tests

Create `backend/tests/test_csrf.py`:

```python
"""CSRF 보호 테스트 — httpOnly 쿠키 마이그레이션 후 활성화."""
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from api.middleware.csrf import CSRFMiddleware, CSRF_COOKIE_NAME, CSRF_HEADER_NAME


@pytest.fixture
def csrf_app():
    """CSRF 미들웨어가 활성화된 테스트 앱."""
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/api/get-csrf")
    async def get_csrf():
        return {"ok": True}

    @app.post("/api/test-post")
    async def test_post(request: Request):
        return {"ok": True}

    @app.post("/api/auth/login")
    async def login(request: Request):
        return {"ok": True}

    return TestClient(app)


class TestCSRFProtection:
    """CSRF Double-Submit Cookie 패턴 테스트."""

    def test_get_request_sets_csrf_cookie(self, csrf_app):
        """GET 요청 시 CSRF 쿠키가 설정됨."""
        r = csrf_app.get("/api/get-csrf")
        assert r.status_code == 200
        assert CSRF_COOKIE_NAME in r.cookies

    def test_post_without_csrf_token_rejected(self, csrf_app):
        """CSRF 토큰 없이 POST 요청하면 403."""
        r = csrf_app.post("/api/test-post", json={"data": "test"})
        assert r.status_code == 403
        assert "CSRF" in r.json()["error"]

    def test_post_with_valid_csrf_token_accepted(self, csrf_app):
        """유효한 CSRF 토큰이 있으면 POST 성공."""
        # 1. GET으로 CSRF 쿠키 획득
        get_r = csrf_app.get("/api/get-csrf")
        csrf_token = get_r.cookies[CSRF_COOKIE_NAME]

        # 2. POST에 쿠키 + 헤더 모두 포함
        r = csrf_app.post(
            "/api/test-post",
            json={"data": "test"},
            cookies={CSRF_COOKIE_NAME: csrf_token},
            headers={CSRF_HEADER_NAME: csrf_token},
        )
        assert r.status_code == 200

    def test_post_with_mismatched_csrf_token_rejected(self, csrf_app):
        """쿠키와 헤더의 CSRF 토큰이 다르면 403."""
        get_r = csrf_app.get("/api/get-csrf")
        csrf_token = get_r.cookies[CSRF_COOKIE_NAME]

        r = csrf_app.post(
            "/api/test-post",
            json={"data": "test"},
            cookies={CSRF_COOKIE_NAME: csrf_token},
            headers={CSRF_HEADER_NAME: "wrong-token-value"},
        )
        assert r.status_code == 403

    def test_auth_login_exempt_from_csrf(self, csrf_app):
        """로그인 경로는 CSRF 검사 제외."""
        r = csrf_app.post("/api/auth/login", json={
            "email": "test@test.com",
            "password": "test"
        })
        assert r.status_code != 403

    def test_bearer_token_bypasses_csrf(self, csrf_app):
        """Bearer 토큰 사용 시 CSRF 검사 생략."""
        r = csrf_app.post(
            "/api/test-post",
            json={"data": "test"},
            headers={"Authorization": "Bearer fake-jwt-token"},
        )
        # CSRF는 통과하지만, 인증 실패할 수 있음 (여기서는 테스트 앱이므로 200)
        assert r.status_code != 403
```

---

## 10. Rollout Checklist

### Phase 1 — Immediate (can ship now)

- [ ] Create `backend/api/middleware/security_headers.py`
- [ ] Create `backend/api/middleware/error_handler.py`
- [ ] Create `backend/api/middleware/request_size.py`
- [ ] Register `SecurityHeadersMiddleware` in `app.py`
- [ ] Register `RequestSizeLimitMiddleware` in `app.py`
- [ ] Call `register_error_handlers(app)` in `app.py`
- [ ] Fix CORS: `allow_methods` → explicit list, `allow_headers` → explicit list
- [ ] Fix CORS: add `X-CSRF-Token` to allowed headers (prep for Phase 3)
- [ ] Add `ENVIRONMENT` env var gating for `/docs`, `/redoc`, `/openapi.json`
- [ ] Fix OAuth error leakage in `auth.py:109` → generic message + logging
- [ ] Replace all `except Exception: pass` with `logger.exception(...)` + fallback
- [ ] Add Pydantic `max_length` / `ge` / `le` to `PostCreate`, `PostUpdate`, `CommentCreate`
- [ ] Create `HotdealVoteRequest`, `HotdealReportRequest`, `HotdealCommentCreate` Pydantic models
- [ ] Replace `request.json()` calls in `hotdeals.py` with Pydantic models
- [ ] Add `slowapi>=0.1.9` to `requirements.txt`
- [ ] Run `pip install -r requirements.txt`
- [ ] Run all tests

### Phase 2 — Rate Limiting (after slowapi installed)

- [ ] Create `backend/api/middleware/rate_limit.py`
- [ ] Register `limiter` and `rate_limit_handler` in `app.py`
- [ ] Add `@limiter.limit("5/minute")` to auth routes (login, register, refresh)
- [ ] Add `@limiter.limit("30/minute")` to community write routes
- [ ] Add `@limiter.limit("30/minute")` to hotdeal vote/report routes
- [ ] Add `@limiter.limit("20/minute")` to search/scrape routes
- [ ] Remove old `_rate_limit_store` and `_check_rate_limit()` from `hotdeals.py`
- [ ] Add `request: Request` as first param on all rate-limited endpoints
- [ ] Configure `TRUSTED_PROXY_IPS` env var for production
- [ ] Run rate limiting tests

### Phase 3 — CSRF (ship with cookie migration only)

- [ ] Create `backend/api/middleware/csrf.py`
- [ ] Create frontend `utils/csrf.js`
- [ ] Add `X-CSRF-Token` header to frontend API interceptor
- [ ] Uncomment `CSRFMiddleware` registration in `app.py`
- [ ] Run CSRF tests
- [ ] Verify no regression on Bearer token auth flow

### Verification

```bash
# Run all new tests
cd packages/website/backend
pytest tests/test_security_headers.py tests/test_rate_limiting.py \
       tests/test_error_handling.py tests/test_request_size.py \
       tests/test_api_docs.py tests/test_csrf.py -v

# Validate headers manually
curl -I http://localhost:8000/api/products | grep -E "(X-Frame|X-Content|Strict|Referrer|Permission|CSP)"

# Validate rate limiting
for i in $(seq 1 7); do
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://localhost:8000/api/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"test@t.com","password":"wrong"}'
done
# Expected: 5x 401, then 429

# Validate docs disabled
ENVIRONMENT=production uvicorn main:app &
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs
# Expected: 404

# Validate oversized request
python -c "import requests; requests.post('http://localhost:8000/api/posts', json={'title':'t','content':'x'*60000,'post_type':'free'})"
# Expected: 422 (content too long)
```

---

## New File Summary

| File | Purpose |
|------|---------|
| `backend/api/middleware/security_headers.py` | Security headers on all responses |
| `backend/api/middleware/error_handler.py` | Global exception handlers, error ID tracking |
| `backend/api/middleware/request_size.py` | Body size limiter (10 MB default) |
| `backend/api/middleware/rate_limit.py` | slowapi limiter config + IP extraction |
| `backend/api/middleware/csrf.py` | Double-submit cookie CSRF (activate with cookie auth) |
| `backend/api/schemas/hotdeals.py` | Pydantic models for vote/report/comment |
| `backend/tests/test_security_headers.py` | Header presence assertions |
| `backend/tests/test_rate_limiting.py` | Rate limit threshold + response format |
| `backend/tests/test_error_handling.py` | Safe error response assertions |
| `backend/tests/test_request_size.py` | Size limit enforcement |
| `backend/tests/test_api_docs.py` | Docs disabled in production |
| `backend/tests/test_csrf.py` | CSRF double-submit cookie flow |

## Modified File Summary

| File | Changes |
|------|---------|
| `backend/api/app.py` | Add middleware registration, env-gated docs, CORS fix, error handlers |
| `backend/api/routes/auth.py` | Add `@limiter.limit`, fix OAuth error message, add `request: Request` param |
| `backend/api/routes/community.py` | Add `@limiter.limit`, add `request: Request` param |
| `backend/api/routes/hotdeals.py` | Remove old rate limiter, add `@limiter.limit`, use Pydantic models |
| `backend/api/routes/naver_local.py` | Add `@limiter.limit("20/minute")` to search |
| `backend/api/routes/search.py` | Add `@limiter.limit("20/minute")` |
| `backend/api/schemas/community.py` | Add `max_length`, `ge`, `le` constraints |
| `backend/requirements.txt` | Add `slowapi>=0.1.9` |
