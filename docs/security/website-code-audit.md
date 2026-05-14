# 🔒 Website Sub-Project — Code-Level Security Audit

> **Scope**: `packages/website/backend/` (FastAPI) + `packages/website/frontend/src/` (React/Vite)
> **Auditor**: Automated Code Review (Copilot)
> **Date**: 2025-07-16
> **Status**: Initial Audit — Pre-Production

---

## Executive Summary

The Website sub-project is the **public-facing** surface of WalletSavior — hot deals, price comparison, community, and local map. It handles user authentication (JWT + OAuth), community-generated content (posts, comments, votes), and embeds a plugin system with sandboxed iframes.

**41 findings** identified across 14 security domains:

| Severity | Count |
|----------|-------|
| 🔴 Critical | 9 |
| 🟠 High | 12 |
| 🟡 Medium | 13 |
| 🔵 Low | 7 |

The most severe issues involve **stored XSS via `dangerouslySetInnerHTML`** on unsanitized community content, **JWT tokens in localStorage** (theft via any XSS), **OAuth tokens leaked in URL query strings**, and a **plugin MessageBridge that accepts all origins by default**.

---

## 🔴 Critical Findings

### C-01 · Stored XSS via `dangerouslySetInnerHTML` on User-Generated Content

| Field | Value |
|-------|-------|
| **File** | `frontend/src/pages/Community/CommunityPage.jsx:773` |
| **Risk** | Stored XSS — full account takeover |
| **CVSS** | 9.6 |

**Description**: Community post body (HTML from TipTap rich-text editor) is rendered with React's `dangerouslySetInnerHTML` with **zero sanitization**.

```jsx
// CommunityPage.jsx:773
{post.body && <div className={`${s.modalContent} ${s.richContent}`}
  dangerouslySetInnerHTML={{ __html: post.body }} />}
```

The backend (`community.py:79-80`) stores `title` and `content` verbatim — no HTML stripping or sanitization.

**Attack Vector**:
1. Attacker writes a community post with malicious HTML/JS via the rich-text editor or direct API call.
2. Content stored as-is in the database.
3. Every user who views the post executes the attacker's script.
4. Script steals `localStorage.getItem('access_token')` and `localStorage.getItem('refresh_token')`.

**Fix**:
```bash
# Backend — install bleach
pip install bleach
```
```python
# community.py — sanitize before storing
import bleach
ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'u', 'h2', 'h3', 'ul', 'ol', 'li', 'a', 'img']
ALLOWED_ATTRS = {'a': ['href', 'title'], 'img': ['src', 'alt']}

post.content = bleach.clean(body.content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
post.title = bleach.clean(body.title, tags=[], strip=True)
```
```jsx
// Frontend — add DOMPurify as defense-in-depth
import DOMPurify from 'dompurify';
dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(post.body) }}
```

---

### C-02 · JWT Access & Refresh Tokens Stored in localStorage

| Field | Value |
|-------|-------|
| **File** | `frontend/src/services/api.js:68,74` · `frontend/src/services/authService.js:9,48` |
| **Risk** | Token theft via any XSS vulnerability |
| **CVSS** | 9.0 |

**Description**: Both access token and refresh token are stored in `localStorage`, which is accessible to any JavaScript running on the page — including XSS payloads (see C-01).

```javascript
// api.js:68
this.token = localStorage.getItem('access_token');
// api.js:74
localStorage.setItem('access_token', token);
// authService.js:9
localStorage.setItem('refresh_token', data.refresh_token);
```

**Attack Vector**: Any XSS (stored or reflected) → `localStorage.getItem('access_token')` → send to attacker server → full account takeover with long-lived refresh token.

**Fix**: Move tokens to `HttpOnly`, `Secure`, `SameSite=Strict` cookies set by the backend. The frontend should never see the raw token value.

---

### C-03 · OAuth Tokens Leaked in Redirect URL Query Parameters

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/auth.py:105-107` |
| **Risk** | Token exposure in browser history, server logs, referrer headers |
| **CVSS** | 8.8 |

**Description**: After OAuth callback, both access and refresh tokens are passed as URL query parameters in the redirect to the frontend:

```python
# auth.py:105-107
return RedirectResponse(
    url=f"http://localhost:5173/auth/callback?access_token={tokens['access_token']}&refresh_token={tokens['refresh_token']}"
)
```

**Attack Vector**: Tokens appear in browser history, web server access logs, proxy logs, CDN logs, and `Referer` headers sent to external resources on the callback page.

**Fix**: Use a short-lived authorization code pattern — redirect with an opaque code, then exchange it for tokens in a secure POST request. Alternatively, set tokens as `HttpOnly` cookies in the redirect response.

---

### C-04 · Hardcoded Default JWT Secret Key

| Field | Value |
|-------|-------|
| **File** | `backend/services/auth_service.py:9` |
| **Risk** | Token forgery if default key reaches production |
| **CVSS** | 9.8 |

**Description**:

```python
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
```

If the environment variable is not set (common in deployment mistakes), all JWTs are signed with a known, guessable key. An attacker can forge any user's token, including admin tokens.

**Fix**:
```python
SECRET_KEY = os.environ["JWT_SECRET_KEY"]  # Crash on startup if missing — fail safe
```
Ensure the production secret is at least 256 bits of cryptographic randomness.

---

### C-05 · Plugin MessageBridge Accepts All Origins by Default

| Field | Value |
|-------|-------|
| **File** | `frontend/src/plugins/sdk/MessageBridge.js:8,41-43` |
| **Risk** | Cross-origin message injection into host application |
| **CVSS** | 8.5 |

**Description**: The `MessageBridge` constructor defaults `allowedOrigins` to an empty array. The `isOriginAllowed` method returns `true` when the array is empty — meaning **any origin is accepted**:

```javascript
// MessageBridge.js:8
constructor({ targetWindow, targetOrigin = '*', allowedOrigins = [] }) {
// MessageBridge.js:41-43
isOriginAllowed(origin) {
    if (this._allowedOrigins.length === 0) return true;  // ALL origins accepted!
    return this._allowedOrigins.includes(origin);
}
```

**Attack Vector**: A malicious page in an iframe (or a compromised plugin) can send arbitrary messages to the host, invoking plugin API handlers, reading product data, or triggering navigation.

**Fix**:
```javascript
constructor({ targetWindow, targetOrigin = window.location.origin,
              allowedOrigins = [window.location.origin] }) {
```

---

### C-06 · Plugin iframe Sandbox Escape — `allow-scripts` + `allow-same-origin`

| Field | Value |
|-------|-------|
| **File** | `frontend/src/plugins/runtime/PluginSandbox.jsx:108-117` |
| **Risk** | Plugin can access host origin cookies, localStorage, DOM |
| **CVSS** | 8.5 |

**Description**: When a plugin requests `network:external`, the sandbox attribute includes **both** `allow-scripts` and `allow-same-origin`:

```javascript
// PluginSandbox.jsx:108-111
function buildSandboxAttr(permissions) {
    const parts = ['allow-scripts'];
    if (permissions.includes('network:external')) {
        parts.push('allow-same-origin');  // ← DANGER
    }
```

Per the [HTML spec](https://html.spec.whatwg.org/multipage/iframe-embed-object.html#attr-iframe-sandbox), combining `allow-scripts` + `allow-same-origin` allows the framed content to remove the sandbox entirely and access the parent's origin.

**Fix**: Serve plugin content from a **different origin** (e.g., `plugins.wallet-savior.local`), or never combine `allow-scripts` with `allow-same-origin`.

---

### C-07 · No CSRF Protection on State-Changing Endpoints

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/community.py` (POST/PUT/DELETE) · `backend/api/routes/hotdeals.py:110-148` |
| **Risk** | Unauthorized actions performed via cross-site requests |
| **CVSS** | 7.5 |

**Description**: All POST, PUT, and DELETE endpoints use Bearer token authentication only. There is no CSRF token mechanism. Since CORS `allow_credentials=True` is enabled, cookies (if any) are sent cross-origin.

Furthermore, several hotdeal endpoints (`/vote`, `/report`, `/comments`) use raw `request.json()` without Pydantic validation:

```python
# hotdeals.py:117-118
body = await request.json()
vote_type = body.get("vote_type", "hot")
```

**Fix**: If tokens are moved to cookies, implement `SameSite=Strict` + CSRF token (double-submit cookie pattern). If staying with Bearer headers, ensure tokens are never auto-sent.

---

### C-08 · CORS Allows Credentials with Wildcard Methods/Headers

| Field | Value |
|-------|-------|
| **File** | `backend/api/app.py:35-46` |
| **Risk** | Credential leakage to permitted origins |
| **CVSS** | 7.5 |

**Description**:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", ...],
    allow_credentials=True,    # ← credentials sent
    allow_methods=["*"],       # ← all HTTP methods
    allow_headers=["*"],       # ← all headers
)
```

While origins are restricted to localhost, this configuration is insecure for production. Any origin mismatch or future addition could expose credentials. `allow_methods=["*"]` permits TRACE (which can leak headers).

**Fix**:
```python
allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
allow_headers=["Content-Type", "Authorization"],
```
Add production origins via environment variable.

---

### C-09 · Hotdeal Comment Endpoints Have No Authentication

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/hotdeals.py:170-198` |
| **Risk** | Anonymous spam, abuse, impersonation |
| **CVSS** | 7.5 |

**Description**: The hotdeal comment creation endpoint accepts an `author` field from the request body with **no authentication** and **no rate limiting**:

```python
# hotdeals.py:174-176
body = await request.json()
content = body.get("content", "").strip()
author = body.get("author", "익명")  # user-supplied, no auth
```

Similarly, comment deletion (`DELETE /{hotdeal_id}/comments/{comment_id}`) has **no authentication** — anyone can delete any comment.

**Fix**: Add `Depends(require_auth)` to comment creation and deletion endpoints. Remove the user-supplied `author` field; derive it from the authenticated user.

---

## 🟠 High Findings

### H-01 · No Backend Sanitization of User-Generated Content Fields

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/community.py:197-205` · `backend/api/schemas/community.py:14-22` |
| **Risk** | Stored XSS, HTML injection |

**Description**: `PostCreate` and `CommentCreate` schemas accept `title`, `content`, `category`, and `url` fields with **no sanitization, no max-length enforcement, and no HTML stripping**:

```python
# community.py:200-201 — stored verbatim
title=body.title,      # no sanitization
content=body.content,   # no sanitization
```

The `content` field for community posts is Pydantic `str` with no `max_length`:

```python
class PostCreate(BaseModel):
    title: str          # unbounded
    content: str        # unbounded — could be multi-MB
```

**Fix**: Add `max_length` constraints to Pydantic models. Sanitize HTML content with `bleach` before storage.

---

### H-02 · No File Upload Size/Type Validation in Rich-Text Editor

| Field | Value |
|-------|-------|
| **File** | `frontend/src/components/community/RichTextEditor.jsx:29-43` |
| **Risk** | Memory exhaustion, malicious file types |

**Description**: Images are uploaded as base64 Data URLs with no size or MIME validation:

```javascript
// RichTextEditor.jsx:40
reader.readAsDataURL(file);  // No size check, no type validation
```

A 50 MB image would be base64-encoded (67 MB) and embedded directly into the post content, sent to the backend, and stored in the database.

**Fix**:
```javascript
const MAX_SIZE = 5 * 1024 * 1024; // 5MB
const ALLOWED = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
if (file.size > MAX_SIZE) return alert('이미지 크기는 5MB 이하만 가능합니다');
if (!ALLOWED.includes(file.type)) return alert('지원하지 않는 이미지 형식입니다');
```

---

### H-03 · Missing HTTP Security Headers

| Field | Value |
|-------|-------|
| **File** | `backend/api/app.py` (entire file — no security header middleware) |
| **Risk** | Clickjacking, MIME sniffing, XSS bypass |

**Description**: The API returns no security headers:
- `X-Content-Type-Options` → MIME sniffing attacks
- `X-Frame-Options` → clickjacking
- `Content-Security-Policy` → XSS bypass
- `Strict-Transport-Security` → MITM downgrade
- `Referrer-Policy` → information leakage

**Fix**: Add middleware:
```python
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
    return response
```

---

### H-04 · OAuth Flow Missing `state` Parameter (CSRF on OAuth)

| Field | Value |
|-------|-------|
| **File** | `backend/services/oauth_service.py:64-74` |
| **Risk** | OAuth CSRF — attacker forces login to attacker's account |

**Description**: The OAuth login URL generation does not include a `state` parameter:

```python
# oauth_service.py:67-72
params = {
    "client_id": config["client_id"],
    "redirect_uri": f"{REDIRECT_BASE}/api/auth/oauth/{provider}/callback",
    "response_type": "code",
    "scope": config["scope"],
    # No "state" parameter!
}
```

**Attack Vector**: Attacker initiates OAuth with their own account, gets the callback URL, tricks victim into visiting it → victim is logged in as attacker → victim enters sensitive data.

**Fix**: Generate a cryptographic random `state` value, store it in the session, and validate it in the callback.

---

### H-05 · Password Validation Too Weak

| Field | Value |
|-------|-------|
| **File** | `backend/api/schemas/auth.py:18-25` |
| **Risk** | Credential compromise via dictionary attacks |

**Description**: Password requirements only enforce ≥8 chars + ≥1 digit:

```python
if len(v) < 8:
    raise ValueError("비밀번호는 8자 이상이어야 합니다")
if not any(c.isdigit() for c in v):
    raise ValueError("비밀번호에 숫자가 포함되어야 합니다")
```

Passwords like `password1`, `12345678`, `qwerty12` pass validation.

**Fix**: Require uppercase, lowercase, digit, and special character. Add a compromised-password dictionary check (e.g., `zxcvbn`).

---

### H-06 · Nickname Not Sanitized — Stored XSS Vector

| Field | Value |
|-------|-------|
| **File** | `backend/api/schemas/auth.py:27-32` · `backend/api/routes/community.py:75,99` |
| **Risk** | XSS via `author_nickname` field rendered in post/comment lists |

**Description**: Nicknames are validated only for length (2-20 chars), not for content:

```python
@field_validator("nickname")
def validate_nickname(cls, v):
    if len(v) < 2 or len(v) > 20:
        raise ValueError("닉네임은 2-20자여야 합니다")
    return v  # No character restriction
```

A nickname like `<img/onerror=alert(1) src=x>` (29 chars — would need length increase, but `<b onmouseover=...>hi</b>` at 20 chars fits) is accepted and rendered in post listings.

**Fix**: Allow only alphanumeric + Korean characters: `re.match(r'^[가-힣a-zA-Z0-9_]{2,20}$', v)`.

---

### H-07 · `create_post` Allows Unauthenticated "Guest" Posts

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/community.py:186-189` |
| **Risk** | Spam, abuse, content injection without accountability |

**Description**: The `create_post` endpoint uses `get_current_user` (optional auth) instead of `require_auth`. If no user is authenticated, it creates a guest user:

```python
async def create_post(body: PostCreate, user: dict = Depends(get_current_user)):
    if not user:
        user = {"id": 0, "email": "guest@wallet.local", "nickname": "게스트", "role": "guest"}
```

All guest posts share `user_id=0` — no accountability, no rate limiting.

**Fix**: Change to `Depends(require_auth)` for community posts.

---

### H-08 · Search Query Injection into Playwright Browser Navigation

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/naver_local.py:236` |
| **Risk** | URL injection, potential SSRF via headless browser |

**Description**: The user-supplied `query` parameter is directly interpolated into the Naver Maps URL and navigated to by a headless Chromium browser:

```python
# naver_local.py:236
url = f"https://map.naver.com/p/search/{query}"
page.goto(url, timeout=20000)
```

If `query` contains URL-special characters or path traversal sequences (e.g., `../../`, `javascript:`, `data:`), it could manipulate browser behavior.

**Fix**: URL-encode the query parameter and validate against a whitelist pattern:
```python
from urllib.parse import quote
if not re.match(r'^[\w가-힣\s,.]+$', query):
    raise HTTPException(400, "유효하지 않은 검색어입니다")
url = f"https://map.naver.com/p/search/{quote(query)}"
```

---

### H-09 · Plugin Manifest Fetched Over Arbitrary URL (No HTTPS Requirement)

| Field | Value |
|-------|-------|
| **File** | `frontend/src/plugins/manager/PluginInstaller.js:115-121` |
| **Risk** | Man-in-the-middle plugin code injection |

**Description**: `_fetchManifest(url)` accepts any URL without protocol validation:

```javascript
async _fetchManifest(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`매니페스트 다운로드 실패: ${response.status}`);
    return response.json();
}
```

**Fix**: Validate URL starts with `https://` before fetching. Add Subresource Integrity (SRI) hashes.

---

### H-10 · MessageBridge Response Sent to `'*'` When Origin is `'null'`

| Field | Value |
|-------|-------|
| **File** | `frontend/src/plugins/sdk/MessageBridge.js:135,145` |
| **Risk** | Response data sent to any listening origin |

**Description**: When the message source origin is `'null'` (sandboxed iframe without `allow-same-origin`), responses are sent to `'*'`:

```javascript
event.source.postMessage(response, event.origin === 'null' ? '*' : event.origin);
```

Any window can receive the response data.

**Fix**: If origin is `'null'`, use the known plugin origin from configuration. Never use `'*'` with sensitive data.

---

### H-11 · In-Memory User Database (Auth State Lost on Restart)

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/auth.py:17-18` |
| **Risk** | Data loss, inconsistent auth state |

**Description**: User accounts are stored in a Python dict:

```python
_users_db: dict[str, dict] = {}
_next_id = 1
```

All registered users are lost on server restart. OAuth users created via callback are also lost.

**Fix**: Persist users in the SQLite database (same as community posts).

---

### H-12 · User Enumeration via Registration Error Messages

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/auth.py:26-32` |
| **Risk** | Attacker can discover valid email addresses and nicknames |

**Description**: Registration returns specific messages revealing whether an email or nickname is already registered:

```python
if data.email in _users_db:
    raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다")
for user in _users_db.values():
    if user["nickname"] == data.nickname:
        raise HTTPException(status_code=400, detail="이미 사용 중인 닉네임입니다")
```

**Fix**: Return a generic error: `"회원가입에 실패했습니다. 입력 정보를 확인해주세요"`.

---

## 🟡 Medium Findings

### M-01 · Rate Limiter Memory Leak

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/hotdeals.py:24-39` |
| **Risk** | Memory exhaustion over time |

**Description**: `_rate_limit_store` is an in-memory dict that grows without bound. Expired entries are cleaned per-IP on access, but IPs that make a single request leave entries forever.

**Fix**: Add periodic cleanup or use a TTL-based cache (like the existing `TTLCache`).

---

### M-02 · Rate Limiting Only on Hotdeal Vote/Report Endpoints

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/hotdeals.py:23-39` |
| **Risk** | Brute force on auth, spam on other endpoints |

**Description**: Rate limiting is only applied to `/hotdeals/{id}/vote` and `/hotdeals/{id}/report`. Auth endpoints (`/login`, `/register`, `/refresh`), community endpoints, and search are unprotected.

**Fix**: Add rate limiting middleware across all endpoints (e.g., `slowapi` library for FastAPI).

---

### M-03 · IP-Based Rate Limiting Can Be Spoofed Behind Proxy

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/hotdeals.py:113` |
| **Risk** | Rate limit bypass |

**Description**: Uses `request.client.host` which may be the proxy's IP, not the actual client:

```python
client_ip = request.client.host if request.client else "unknown"
```

**Fix**: Use `X-Forwarded-For` header with trusted proxy validation.

---

### M-04 · Exception Messages Exposed to Users via OAuth Errors

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/auth.py:109` |
| **Risk** | Information disclosure |

**Description**: Full exception message is returned to the client:

```python
raise HTTPException(status_code=400, detail=f"OAuth 인증 실패: {str(e)}")
```

Internal error details (stack traces, config issues, provider URLs) may be leaked.

**Fix**: Return generic error message; log the full exception server-side.

---

### M-05 · Silent Exception Swallowing Hides Failures

| Field | Value |
|-------|-------|
| **File** | `backend/api/app.py:164-165,174,183,191` · `backend/api/routes/hotdeals.py:127-128,145-146,165-166` |
| **Risk** | Undetected failures in production |

**Description**: Multiple places catch and ignore exceptions with `except Exception: pass`:

```python
try:
    result["hotdeals"] = s.get_hotdeals(sort="recent", per_page=10)
except Exception:
    pass  # Silently ignored
```

**Fix**: Log exceptions with `logger.exception()` at minimum.

---

### M-06 · No Authentication Audit Logging

| Field | Value |
|-------|-------|
| **File** | `backend/api/middleware/auth.py:17-19` · `backend/api/routes/auth.py` |
| **Risk** | Cannot detect brute-force attacks |

**Description**: Failed authentication attempts (invalid tokens, wrong passwords, expired tokens) are not logged. No audit trail exists for security monitoring.

**Fix**: Log all auth events (login, failure, token refresh, OAuth callback) with IP, timestamp, and result.

---

### M-07 · OAuth URL Parameters Not Properly Encoded

| Field | Value |
|-------|-------|
| **File** | `backend/services/oauth_service.py:73` |
| **Risk** | URL injection in OAuth redirect |

**Description**: OAuth query parameters are joined manually without URL encoding:

```python
query = "&".join(f"{k}={v}" for k, v in params.items() if v)
```

If any value contains `&` or `=`, the URL is malformed.

**Fix**: Use `urllib.parse.urlencode(params)`.

---

### M-08 · SQLite Thread Safety Disabled

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/community.py:57-60` |
| **Risk** | Race conditions, data corruption under concurrent requests |

**Description**:

```python
_db_engine = create_engine(
    f"sqlite:///{_db_path}",
    connect_args={"check_same_thread": False},
)
```

This disables SQLite's thread-safety check, which is required for multi-threaded FastAPI.

**Fix**: Use connection pooling with `pool_size=1` and `pool_pre_ping=True`, or switch to PostgreSQL for production.

---

### M-09 · Sensitive Data in localStorage (Privacy Concerns)

| Field | Value |
|-------|-------|
| **File** | `frontend/src/stores/appStore.js:141-150` |
| **Risk** | Privacy exposure, user profiling |

**Description**: The Zustand store persists user-sensitive data to localStorage:

```javascript
partialize: (state) => ({
    favorites: state.favorites,        // purchase interests
    recentSearches: state.recentSearches,  // search history
    shoppingList: state.shoppingList,      // shopping habits
    priceAlerts: state.priceAlerts,        // financial targets
})
```

Any XSS or malicious extension can read this data.

**Fix**: Move sensitive data to server-side storage. Keep only UI preferences client-side.

---

### M-10 · Hotdeal Vote/Report Endpoints Use Raw `request.json()` Without Pydantic Validation

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/hotdeals.py:117-118,138-139,174-176` |
| **Risk** | Input validation bypass, type confusion |

**Description**: Three hotdeal endpoints parse JSON manually instead of using Pydantic models:

```python
body = await request.json()
vote_type = body.get("vote_type", "hot")
reason = body.get("reason", "")
```

The `reason` field is unbounded — could be megabytes of text.

**Fix**: Create Pydantic models with `max_length` constraints and use them as FastAPI request body parameters.

---

### M-11 · No Content Security Policy (CSP) for Frontend

| Field | Value |
|-------|-------|
| **File** | `frontend/` (no CSP configuration found) |
| **Risk** | XSS bypass, inline script execution |

**Description**: No CSP header or meta tag is configured. Even if XSS is prevented by React, a missing CSP means any injected script will execute without restriction.

**Fix**: Add CSP header in production reverse proxy or via Vite HTML template meta tag.

---

### M-12 · Naver Maps Iframe Has No Sandbox Attributes

| Field | Value |
|-------|-------|
| **File** | `frontend/src/pages/Local/LocalPage.jsx:69` (and render section) |
| **Risk** | Potential clickjacking if Naver Maps returns unexpected content |

**Description**: The Naver Maps iframe URL is constructed from user-controllable lat/lng values and rendered without `sandbox` attributes.

**Fix**: Add `sandbox="allow-scripts allow-same-origin"` and validate lat/lng are numeric.

---

### M-13 · `post.url` Rendered as Clickable Link Without Validation

| Field | Value |
|-------|-------|
| **File** | `frontend/src/pages/Community/CommunityPage.jsx:776-778` |
| **Risk** | `javascript:` URL injection |

**Description**:

```jsx
{post.url && (
    <a href={post.url} target="_blank" rel="noopener noreferrer" className={s.dealLink}>
        🔗 핫딜 링크로 이동
    </a>
)}
```

If `post.url` contains `javascript:alert(1)`, clicking the link executes JavaScript.

**Fix**: Validate URL starts with `https://` or `http://` before rendering.

---

## 🔵 Low Findings

### L-01 · No Token Revocation Mechanism

| Field | Value |
|-------|-------|
| **File** | `backend/services/auth_service.py` (entire file) |
| **Risk** | Compromised tokens valid until expiry |

**Description**: No token blacklist or revocation mechanism exists. Once issued, tokens are valid for their full lifetime (30 min for access, 7 days for refresh).

**Fix**: Implement a token blacklist (Redis-backed) checked on each request, or use short-lived tokens with refresh rotation.

---

### L-02 · OAuth Redirect URI Hardcoded to localhost

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/auth.py:106` · `backend/services/oauth_service.py:61` |
| **Risk** | OAuth broken in production |

**Description**: `http://localhost:5173` and `http://localhost:8000` are hardcoded. Must be configurable via environment variable.

---

### L-03 · Database Connection String Default Contains Fake Credentials

| Field | Value |
|-------|-------|
| **File** | `backend/config.py:17` |
| **Risk** | Accidental use in production |

```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/wallet_guardian")
```

**Fix**: Crash on startup if `DATABASE_URL` is not set in production mode.

---

### L-04 · `console.error` Calls Left in Production Frontend

| Field | Value |
|-------|-------|
| **File** | Multiple pages: `CommunityPage.jsx`, `api.js`, etc. |
| **Risk** | Information disclosure to browser console |

**Fix**: Strip `console.*` calls for production builds or route to a logging service.

---

### L-05 · No Email Verification on Registration

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/auth.py:21-45` |
| **Risk** | Fake accounts, spam |

**Description**: Users can register with any email without verification.

**Fix**: Implement email confirmation flow with time-limited token.

---

### L-06 · View Count Increment Has No Duplicate Prevention

| Field | Value |
|-------|-------|
| **File** | `backend/api/routes/community.py:236-237` |
| **Risk** | Artificially inflated view counts |

```python
post.view_count += 1  # Increments on every request — no IP/session dedup
```

**Fix**: Track unique views per session or IP.

---

### L-07 · Plugin Examples Use `innerHTML` (Low Risk — Sandboxed)

| Field | Value |
|-------|-------|
| **File** | `frontend/src/plugins/examples/price-alert-widget/index.html:81,84` · `frontend/src/plugins/examples/deal-timer/index.html:98` |
| **Risk** | Low — examples run in sandboxed iframe |

**Description**: Plugin example HTML files use `innerHTML` to render dynamic content. Since they run inside sandboxed iframes, the risk is contained to the plugin's own context.

**Fix**: Use `textContent` for text-only data. Document security requirements for plugin developers.

---

## Summary by Security Domain

| Domain | Findings | Worst Severity |
|--------|----------|----------------|
| **XSS** | C-01, H-01, H-06, M-13, L-07 | 🔴 Critical |
| **Authentication** | C-02, C-04, H-07, H-11, H-12, M-06, L-01, L-05 | 🔴 Critical |
| **OAuth** | C-03, H-04, M-04, M-07, L-02 | 🔴 Critical |
| **Plugin Security** | C-05, C-06, H-09, H-10 | 🔴 Critical |
| **CSRF** | C-07, C-08 | 🔴 Critical |
| **Input Validation** | H-01, H-02, H-05, M-10 | 🟠 High |
| **API Security** | C-09, M-02, M-03 | 🔴 Critical |
| **Injection** | H-08 | 🟠 High |
| **Security Headers** | H-03, M-11, M-12 | 🟠 High |
| **Error Handling** | M-04, M-05, L-04 | 🟡 Medium |
| **Data Privacy** | M-09, L-03 | 🟡 Medium |
| **Data Integrity** | M-08, L-06 | 🟡 Medium |

---

## Remediation Priority

### Phase 1 — Critical (Week 1)
1. **C-01**: Add DOMPurify to frontend + bleach to backend
2. **C-02**: Move tokens to HttpOnly cookies
3. **C-03**: Remove tokens from OAuth redirect URL
4. **C-04**: Remove default JWT secret; crash if missing
5. **C-05**: Fix MessageBridge default origins
6. **C-06**: Separate plugin origins or remove `allow-same-origin`
7. **C-07**: Add CSRF protection
8. **C-09**: Add authentication to hotdeal comment endpoints

### Phase 2 — High (Week 2)
9. **H-01**: Add backend sanitization + field length limits
10. **H-02**: Add file upload validation (size, type)
11. **H-03**: Add security headers middleware
12. **H-04**: Add OAuth `state` parameter
13. **H-08**: URL-encode Playwright search query
14. **H-11**: Persist users to database
15. **H-12**: Generic registration error messages

### Phase 3 — Medium (Week 3-4)
16. Add rate limiting across all endpoints (M-02)
17. Implement audit logging (M-06)
18. Add CSP headers (M-11)
19. Fix silent exception swallowing (M-05)
20. Move sensitive data server-side (M-09)
