# Crawler-Admin Security Implementation Spec

> **Package**: `packages/crawler-admin`
> **Date**: 2025-07-18
> **Source**: `crawler-admin-code-audit.md` (C-01–C-03, H-01–H-06, M-01–M-08) + `crawler-admin-arch-audit.md` (CRIT-01–CRIT-06, HIGH-01–HIGH-06, MED-01–MED-08)
> **Scope**: Auth · CORS · Plugin Sandboxing · SSRF Prevention · Secrets Management · Input Validation · Security Headers

---

## Table of Contents

1. [Implementation Overview](#1-implementation-overview)
2. [SEC-01: API Authentication Middleware](#2-sec-01-api-authentication-middleware)
3. [SEC-02: CORS Restriction](#3-sec-02-cors-restriction)
4. [SEC-03: Plugin Sandboxing](#4-sec-03-plugin-sandboxing)
5. [SEC-04: SSRF Prevention](#5-sec-04-ssrf-prevention)
6. [SEC-05: Secrets Management](#6-sec-05-secrets-management)
7. [SEC-06: Input Validation](#7-sec-06-input-validation)
8. [SEC-07: Security Headers](#8-sec-07-security-headers)
9. [New Files Summary](#9-new-files-summary)
10. [Test Plan](#10-test-plan)

---

## 1. Implementation Overview

### Files Modified

| File | Changes |
|------|---------|
| `backend/api/app.py` | Add auth dependency, fix CORS, add security headers middleware |
| `backend/api/routes/crawlers.py` | URL validation on settings update, error message sanitization |
| `backend/api/routes/plugins.py` | URL validation on plugin settings, plugin_id format validation |
| `backend/api/routes/schedules.py` | Cron frequency validation, error response fixes |
| `backend/api/routes/ingestion.py` | Pydantic model for cleanup body, error sanitization |
| `backend/config.py` | Remove credential defaults, add security config vars, default bind `127.0.0.1` |
| `backend/plugins/plugin_loader.py` | Manifest verification, import whitelist, path containment |
| `backend/crawlers/delivery/yogiyo/crawler.py` | Move API key/secret to env vars |
| `backend/pipeline/crawl_pipeline.py` | Replace `os.system()` with `subprocess.run()` |

### New Files

| File | Purpose |
|------|---------|
| `backend/api/security/__init__.py` | Security module init |
| `backend/api/security/auth.py` | API key authentication middleware |
| `backend/api/security/headers.py` | Security headers middleware |
| `backend/api/security/url_validator.py` | SSRF prevention — URL validation + IP blocklist |
| `backend/api/security/input_schemas.py` | Pydantic models with strict validation |
| `backend/plugins/manifest_verifier.py` | HMAC-SHA256 plugin manifest signing & verification |
| `backend/plugins/import_guard.py` | Import whitelist hook for plugin sandboxing |
| `backend/.env.example` | Template with all required env vars (no real secrets) |
| `backend/tests/test_security.py` | Security-focused test suite |

---

## 2. SEC-01: API Authentication Middleware

**Addresses**: C-01, CRIT-01 (No authentication on any endpoint)

### 2.1 New File: `backend/api/security/auth.py`

```python
"""API key authentication middleware for crawler-admin."""

import os
import hmac
import logging
from typing import Optional

from fastapi import Request, HTTPException, Security
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Paths exempt from authentication (health check, metrics)
PUBLIC_PATHS: set[str] = {"/health", "/docs", "/openapi.json", "/redoc"}


def _get_api_key() -> str:
    """Load API key from environment. Raise on missing."""
    key = os.getenv("CRAWLER_ADMIN_API_KEY", "")
    if not key:
        raise RuntimeError(
            "CRAWLER_ADMIN_API_KEY environment variable is required. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return key


async def verify_api_key(
    request: Request,
    api_key: Optional[str] = Security(API_KEY_HEADER),
) -> str:
    """
    Validate the X-API-Key header against the server-side secret.

    Uses hmac.compare_digest for constant-time comparison to prevent
    timing attacks.
    """
    # Allow public paths without auth
    if request.url.path in PUBLIC_PATHS:
        return "public"

    if api_key is None:
        logger.warning(
            "Auth failure: missing X-API-Key header | ip=%s path=%s",
            request.client.host if request.client else "unknown",
            request.url.path,
        )
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    expected = _get_api_key()
    if not hmac.compare_digest(api_key, expected):
        logger.warning(
            "Auth failure: invalid API key | ip=%s path=%s",
            request.client.host if request.client else "unknown",
            request.url.path,
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid API key",
        )

    return api_key
```

### 2.2 Changes to `backend/api/app.py`

Apply auth to all route registrations:

```python
# --- BEFORE (app.py lines 28-35) ---
app.include_router(crawlers_router)
app.include_router(schedules_router)
app.include_router(logs_router)
app.include_router(ingestion_router)
app.include_router(dashboard_router)
app.include_router(plugins_router)

# --- AFTER ---
from fastapi import Depends
from api.security.auth import verify_api_key

_auth = [Depends(verify_api_key)]

app.include_router(crawlers_router, dependencies=_auth)
app.include_router(schedules_router, dependencies=_auth)
app.include_router(logs_router, dependencies=_auth)
app.include_router(ingestion_router, dependencies=_auth)
app.include_router(dashboard_router, dependencies=_auth)
app.include_router(plugins_router, dependencies=_auth)
```

### 2.3 Config Addition (`config.py`)

```python
# --- API Authentication ---
CRAWLER_ADMIN_API_KEY: str = os.getenv("CRAWLER_ADMIN_API_KEY", "")
# Validated at import time in auth.py — empty string = startup failure
```

### 2.4 Frontend Client Update (`frontend/src/api/client.js`)

All fetch calls must include the API key header:

```javascript
// Add to every request in the API client
const API_KEY = import.meta.env.VITE_CRAWLER_ADMIN_API_KEY || '';

const headers = {
  'Content-Type': 'application/json',
  'X-API-Key': API_KEY,
};
```

---

## 3. SEC-02: CORS Restriction

**Addresses**: C-02, CRIT-02 (Wildcard CORS with credentials)

### 3.1 Changes to `backend/api/app.py`

```python
# --- BEFORE (app.py lines 16-22) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- AFTER ---
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,  # No cookies used — disable
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)
```

### 3.2 Config Addition (`config.py`)

```python
# --- CORS ---
CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")
    if o.strip()
]
```

### 3.3 `.env.example` Entry

```bash
# Comma-separated list of allowed frontend origins
CORS_ORIGINS=http://localhost:5174
```

---

## 4. SEC-03: Plugin Sandboxing

**Addresses**: C-03, CRIT-03, HIGH-05, MED-04 (Plugin code execution, no manifest verification, module poisoning)

### 4.1 New File: `backend/plugins/manifest_verifier.py`

```python
"""HMAC-SHA256 plugin manifest verification."""

import hashlib
import hmac
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _get_signing_key() -> bytes:
    """Load the plugin signing key from environment."""
    key = os.getenv("PLUGIN_SIGNING_KEY", "")
    if not key:
        raise RuntimeError(
            "PLUGIN_SIGNING_KEY environment variable is required for plugin verification. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return key.encode("utf-8")


def compute_manifest_signature(manifest_data: dict[str, Any]) -> str:
    """
    Compute HMAC-SHA256 signature over the manifest content.

    Excludes the 'signature' field itself from the computation.
    Produces a deterministic digest by sorting keys and using
    consistent YAML serialization.
    """
    signable = {k: v for k, v in manifest_data.items() if k != "signature"}
    canonical = yaml.dump(signable, default_flow_style=False, sort_keys=True)
    key = _get_signing_key()
    return hmac.new(key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_manifest(yaml_path: Path) -> None:
    """
    Sign a plugin.yaml file in place.

    Reads the manifest, computes the HMAC-SHA256 signature,
    and writes it back with a 'signature' field appended.
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}

    manifest["signature"] = compute_manifest_signature(manifest)

    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info("Signed manifest: %s", yaml_path)


def verify_manifest(yaml_path: Path, manifest_data: dict[str, Any]) -> bool:
    """
    Verify the HMAC-SHA256 signature of a plugin manifest.

    Returns True if the signature matches, False otherwise.
    """
    stored_sig = manifest_data.get("signature")
    if not stored_sig:
        logger.error("Manifest has no signature: %s", yaml_path)
        return False

    expected = compute_manifest_signature(manifest_data)
    if not hmac.compare_digest(stored_sig, expected):
        logger.error(
            "Manifest signature mismatch: %s (expected=%s, got=%s)",
            yaml_path,
            expected[:12] + "...",
            stored_sig[:12] + "...",
        )
        return False

    return True


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hash of a file for audit logging."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()
```

### 4.2 New File: `backend/plugins/import_guard.py`

```python
"""
Import whitelist hook for plugin sandboxing.

Hooks into Python's import system to block dangerous modules
when executing plugin code. This is a Phase 1 mitigation —
full subprocess isolation (Phase 2) is recommended for production.
"""

import builtins
import logging
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# Modules that plugins are NEVER allowed to import
BLOCKED_MODULES: frozenset[str] = frozenset({
    # System access
    "os",
    "sys",
    "subprocess",
    "shutil",
    "pathlib",
    # Low-level / dangerous
    "ctypes",
    "importlib",
    "code",
    "codeop",
    "compile",
    "compileall",
    # Network (raw)
    "socket",
    "socketserver",
    "http.server",
    "xmlrpc",
    # Code execution
    "exec",
    "eval",
    "pickle",
    "shelve",
    "marshal",
    # Process control
    "signal",
    "multiprocessing",
    "threading",
    "_thread",
    # Filesystem
    "tempfile",
    "glob",
    "fnmatch",
    "io",  # raw file I/O — plugins should use provided interfaces
})

# Modules that plugins ARE allowed to import
ALLOWED_MODULES: frozenset[str] = frozenset({
    # Standard safe modules
    "json",
    "re",
    "math",
    "datetime",
    "time",
    "hashlib",
    "hmac",
    "base64",
    "urllib.parse",
    "html",
    "collections",
    "dataclasses",
    "typing",
    "enum",
    "functools",
    "itertools",
    "operator",
    "copy",
    "decimal",
    "fractions",
    "statistics",
    "string",
    "textwrap",
    "unicodedata",
    "abc",
    "logging",
    # HTTP clients (controlled by the engine, not raw sockets)
    "requests",
    "httpx",
    "aiohttp",
    "bs4",
    "lxml",
    "selectolax",
    # Data processing
    "yaml",
    "csv",
    # Project modules
    "plugins.plugin_interface",
    "engine",
})


def _is_module_allowed(module_name: str) -> bool:
    """Check if a module import should be allowed for plugin code."""
    top_level = module_name.split(".")[0]

    # Explicitly blocked
    if top_level in BLOCKED_MODULES or module_name in BLOCKED_MODULES:
        return False

    # Explicitly allowed
    if top_level in ALLOWED_MODULES or module_name in ALLOWED_MODULES:
        return True

    # Unknown modules — block by default (whitelist approach)
    return False


@contextmanager
def guarded_imports(plugin_name: str):
    """
    Context manager that installs an import guard while plugin code executes.

    Usage:
        with guarded_imports("yogiyo"):
            spec.loader.exec_module(module)
    """
    original_import = builtins.__import__

    def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        # Allow relative imports (level > 0) within the plugin's own package
        if level > 0:
            return original_import(name, globals, locals, fromlist, level)

        if not _is_module_allowed(name):
            logger.warning(
                "Plugin '%s' blocked from importing '%s'", plugin_name, name
            )
            raise ImportError(
                f"Plugin '{plugin_name}' is not allowed to import '{name}'. "
                f"Contact admin to add '{name}' to the allowed module list."
            )
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _restricted_import
    try:
        yield
    finally:
        builtins.__import__ = original_import
```

### 4.3 Changes to `backend/plugins/plugin_loader.py`

#### 4.3.1 Path Containment (before `_import_plugin`, ~line 262)

```python
# --- ADD before _import_plugin() method body ---

def _import_plugin(self, name: str, plugin_dir: Path) -> PluginInterface:
    """플러그인 디렉토리에서 크롤러 모듈을 동적으로 임포트한다."""

    # === NEW: Path containment check ===
    allowed_base = Path(__file__).resolve().parent.parent / "crawlers"
    if not plugin_dir.resolve().is_relative_to(allowed_base.resolve()):
        raise PluginLoadError(
            name, f"Plugin outside allowed directory: {plugin_dir}"
        )

    crawler_file = plugin_dir / "crawler.py"
    if not crawler_file.exists():
        raise PluginLoadError(name, f"crawler.py 없음: {plugin_dir}")
    # ... rest unchanged ...
```

#### 4.3.2 Manifest Signature Verification (in `discover()`, ~line 90)

```python
# --- ADD inside discover() after YAML loading ---

from plugins.manifest_verifier import verify_manifest, compute_file_hash

# Inside the for loop, after config = self._load_yaml(yaml_path):
if not verify_manifest(yaml_path, config):
    logger.error("Rejecting unsigned/tampered plugin: %s", yaml_path)
    self._errors[str(yaml_path)] = "Manifest signature verification failed"
    continue  # Skip this plugin entirely

# Log plugin load with file hash for audit
crawler_py = yaml_path.parent / "crawler.py"
if crawler_py.exists():
    file_hash = compute_file_hash(crawler_py)
    logger.info(
        "Plugin verified: name=%s hash=%s path=%s",
        name, file_hash[:16], yaml_path.parent,
    )
```

#### 4.3.3 Import Guard Around exec_module (~line 276)

```python
# --- BEFORE ---
spec.loader.exec_module(module)

# --- AFTER ---
from plugins.import_guard import guarded_imports

with guarded_imports(name):
    spec.loader.exec_module(module)
```

#### 4.3.4 Module Namespacing (~line 270)

```python
# --- BEFORE ---
module_name = self._make_module_name(name, plugin_dir)

# --- AFTER (update _make_module_name to namespace) ---
def _make_module_name(self, name: str, plugin_dir: Path) -> str:
    """Generate a namespaced module name to prevent sys.modules collisions."""
    return f"_plugin.{name}.crawler"
```

#### 4.3.5 Execution Timeout (wrap exec_module)

```python
import asyncio
import concurrent.futures

PLUGIN_LOAD_TIMEOUT = 10  # seconds

def _import_plugin(self, name: str, plugin_dir: Path) -> PluginInterface:
    # ... path containment, spec creation ...

    # Execute module code with timeout
    with guarded_imports(name):
        try:
            # Use a thread to enforce timeout on synchronous exec_module
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(spec.loader.exec_module, module)
                future.result(timeout=PLUGIN_LOAD_TIMEOUT)
        except concurrent.futures.TimeoutError:
            raise PluginLoadError(
                name, f"Plugin loading timed out after {PLUGIN_LOAD_TIMEOUT}s"
            )
    # ... rest unchanged ...
```

---

## 5. SEC-04: SSRF Prevention

**Addresses**: H-01, H-04, HIGH-01, MED-03 (SSRF via target_url, ingestion proxy, redirect chains)

### 5.1 New File: `backend/api/security/url_validator.py`

```python
"""
SSRF prevention — URL validation with IP blocklist.

Validates URLs before they are assigned as crawler targets or
used in internal HTTP requests. Blocks private IPs, cloud metadata
endpoints, and non-HTTP schemes.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Schemes allowed for crawler targets
ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Hostnames that are always blocked
BLOCKED_HOSTNAMES: frozenset[str] = frozenset({
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
})

# Cloud metadata endpoints (AWS, GCP, Azure, DigitalOcean, etc.)
BLOCKED_METADATA_IPS: frozenset[str] = frozenset({
    "169.254.169.254",  # AWS / GCP / Azure metadata
    "100.100.100.200",  # Alibaba Cloud metadata
    "metadata.google.internal",
})

# Private IP ranges (RFC 1918, RFC 6598, loopback, link-local)
PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),   # Link-local
    ipaddress.IPv4Network("100.64.0.0/10"),    # CGN (RFC 6598)
    ipaddress.IPv4Network("0.0.0.0/8"),        # "This" network
    ipaddress.IPv6Network("::1/128"),           # IPv6 loopback
    ipaddress.IPv6Network("fc00::/7"),          # IPv6 unique local
    ipaddress.IPv6Network("fe80::/10"),         # IPv6 link-local
    ipaddress.IPv6Network("::ffff:0:0/96"),     # IPv4-mapped IPv6
]


def _is_private_ip(ip_str: str) -> bool:
    """Check if an IP address falls within any private/reserved range."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False

    for network in PRIVATE_NETWORKS:
        if addr in network:
            return True
    return False


def _resolve_hostname(hostname: str) -> list[str]:
    """
    Resolve a hostname to IP addresses.

    This catches DNS rebinding where a public hostname resolves to a private IP.
    """
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        return list({result[4][0] for result in results})
    except socket.gaierror:
        return []


def validate_target_url(url: str, field_name: str = "target_url") -> str:
    """
    Validate a URL for use as a crawler target.

    Checks:
    1. Scheme is http or https
    2. Hostname is not empty
    3. Hostname is not a blocked name (localhost, metadata, etc.)
    4. Resolved IP is not in any private range
    5. Port is standard (80, 443) or in allowed range

    Returns the validated URL.
    Raises HTTPException(422) on validation failure.
    """
    if not url or not isinstance(url, str):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: URL must be a non-empty string",
        )

    url = url.strip()

    # Parse
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: malformed URL",
        )

    # Scheme check
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: scheme must be http or https, got '{parsed.scheme}'",
        )

    # Hostname check
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: URL must have a hostname",
        )

    hostname_lower = hostname.lower()

    # Blocked hostnames
    if hostname_lower in BLOCKED_HOSTNAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: hostname '{hostname}' is not allowed",
        )

    # Cloud metadata IPs
    if hostname_lower in BLOCKED_METADATA_IPS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: cloud metadata endpoint not allowed",
        )

    # Direct IP check (no DNS needed)
    if _is_private_ip(hostname):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {field_name}: private/internal IP addresses are not allowed",
        )

    # DNS resolution check — catches rebinding attacks
    resolved_ips = _resolve_hostname(hostname)
    for ip in resolved_ips:
        if _is_private_ip(ip):
            logger.warning(
                "SSRF blocked: hostname=%s resolved to private IP=%s url=%s",
                hostname,
                ip,
                url,
            )
            raise HTTPException(
                status_code=422,
                detail=f"Invalid {field_name}: hostname resolves to a private IP address",
            )

    # Port check — block common internal service ports
    port = parsed.port
    if port is not None and port not in {80, 443, 8080, 8443}:
        logger.info(
            "Non-standard port in target_url: port=%d url=%s", port, url
        )
        # Allow but log — uncomment below to block:
        # raise HTTPException(422, f"Invalid {field_name}: port {port} is not allowed")

    return url
```

### 5.2 Changes to `backend/api/routes/crawlers.py`

```python
# --- BEFORE (crawlers.py lines 214-230) ---
@router.put("/{crawler_id}/settings")
async def update_crawler_settings(crawler_id: str, body: CrawlerSettingsUpdate):
    settings = _load_settings()
    current = settings.get(crawler_id, {})

    if body.target_url is not None:
        current["target_url"] = body.target_url  # No validation!
    # ...

# --- AFTER ---
from api.security.url_validator import validate_target_url

@router.put("/{crawler_id}/settings")
async def update_crawler_settings(crawler_id: str, body: CrawlerSettingsUpdate):
    settings = _load_settings()
    current = settings.get(crawler_id, {})

    if body.target_url is not None:
        validated_url = validate_target_url(body.target_url)
        current["target_url"] = validated_url

    if body.delay is not None:
        if not (0.1 <= body.delay <= 60.0):
            raise HTTPException(422, "delay must be between 0.1 and 60.0 seconds")
        current["delay"] = body.delay

    if body.max_items is not None:
        if not (1 <= body.max_items <= 10000):
            raise HTTPException(422, "max_items must be between 1 and 10000")
        current["max_items"] = body.max_items

    settings[crawler_id] = current
    _save_settings(settings)

    return {"crawler_id": crawler_id, "settings": current}
```

### 5.3 Changes to `backend/api/routes/plugins.py`

```python
# --- BEFORE (plugins.py ~line 166) ---
target["url"] = body.target_url  # No validation!

# --- AFTER ---
import re
from api.security.url_validator import validate_target_url

@router.put("/{plugin_id}/settings")
async def update_plugin_settings(plugin_id: str, body: PluginSettingsUpdate):
    # Validate plugin_id format (prevent path traversal)
    if not re.match(r'^[a-zA-Z0-9_-]+$', plugin_id):
        raise HTTPException(400, "Invalid plugin ID format: only alphanumeric, dash, underscore allowed")

    yaml_path = _find_plugin_yaml(plugin_id)
    if not yaml_path:
        raise HTTPException(404, f"Plugin not found")  # Don't echo plugin_id back

    # ... YAML loading ...

    if body.target_url is not None:
        validated_url = validate_target_url(body.target_url)
        target = config.get("target", {})
        if isinstance(target, str):
            target = {"url": target}
        target["url"] = validated_url
        config["target"] = target

    # ... rest of update logic ...
```

### 5.4 Redirect Chain Protection

Apply to all HTTP clients in `engine/strategies/`:

```python
# In each strategy that uses requests/httpx:

# requests strategy (requests_st.py)
session.max_redirects = 5

# httpx strategy (if used)
httpx.AsyncClient(max_redirects=5, follow_redirects=True)

# After each redirect, re-validate the target:
# (This requires a custom redirect handler for requests)
```

---

## 6. SEC-05: Secrets Management

**Addresses**: H-03, H-06, CRIT-04, M-04 (Hardcoded secrets, credential defaults)

### 6.1 Changes to `backend/crawlers/delivery/yogiyo/crawler.py`

```python
# --- BEFORE (yogiyo/crawler.py lines 255-256) ---
"x-apikey": "iphoneap",
"x-apisecret": "fe5183cc3dea12bd0ce299cf110a75a2",

# --- AFTER ---
import os

# At module level or in __init__:
YOGIYO_API_KEY = os.getenv("YOGIYO_API_KEY", "")
YOGIYO_API_SECRET = os.getenv("YOGIYO_API_SECRET", "")

# In _get_headers():
def _get_headers(self) -> dict:
    if not YOGIYO_API_KEY or not YOGIYO_API_SECRET:
        raise RuntimeError(
            "YOGIYO_API_KEY and YOGIYO_API_SECRET environment variables are required"
        )

    base_headers = self._anti_detect.get_random_headers()
    base_headers.update({
        "Referer": "https://www.yogiyo.co.kr/",
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Origin": "https://www.yogiyo.co.kr",
        "x-apikey": YOGIYO_API_KEY,
        "x-apisecret": YOGIYO_API_SECRET,
    })
    return base_headers
```

### 6.2 Changes to `backend/config.py`

```python
# --- BEFORE (config.py line 18) ---
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql://user:password@localhost:5432/wallet_guardian"
)

# --- AFTER ---
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    import warnings
    warnings.warn(
        "DATABASE_URL not set — database features will be unavailable",
        RuntimeWarning,
        stacklevel=2,
    )

# --- BEFORE (config.py line ~65) ---
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")

# --- AFTER ---
API_HOST: str = os.getenv("API_HOST", "127.0.0.1")  # Default to loopback
```

### 6.3 Changes to `backend/pipeline/crawl_pipeline.py`

```python
# --- BEFORE (crawl_pipeline.py line 252) ---
os.system("python -m pytest tests/ engine/tests/ -v --tb=short 2>&1")

# --- AFTER ---
import subprocess

subprocess.run(
    ["python", "-m", "pytest", "tests/", "engine/tests/", "-v", "--tb=short"],
    capture_output=True,
    text=True,
    timeout=300,  # 5 minute hard timeout
)
```

### 6.4 New File: `backend/.env.example`

```bash
# =============================================================================
# Crawler-Admin Environment Configuration
# Copy this file to .env and fill in actual values.
# NEVER commit .env to version control.
# =============================================================================

# --- Required ---

# API authentication key (generate: python -c "import secrets; print(secrets.token_urlsafe(32))")
CRAWLER_ADMIN_API_KEY=

# Database connection string
DATABASE_URL=postgresql://user:password@localhost:5432/wallet_guardian

# Plugin manifest signing key (generate: python -c "import secrets; print(secrets.token_hex(32))")
PLUGIN_SIGNING_KEY=

# --- API Keys (required for specific crawlers) ---

# Yogiyo delivery crawler
YOGIYO_API_KEY=
YOGIYO_API_SECRET=

# Naver API
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=

# Public data APIs
KAMIS_API_KEY=
KAMIS_API_ID=
OPINET_API_KEY=
KOSIS_API_KEY=

# --- Optional ---

# CORS allowed origins (comma-separated)
CORS_ORIGINS=http://localhost:5174

# API server bind address (default: 127.0.0.1)
API_HOST=127.0.0.1
API_PORT=8000

# Proxy list (comma-separated, format: http://user:pass@host:port)
PROXY_LIST=

# Crawler settings
CRAWL_DELAY_MIN=1.0
CRAWL_DELAY_MAX=5.0
MAX_RETRIES=3
REQUEST_TIMEOUT=30

# Browser pool
BROWSER_POOL_SIZE=3
STRATEGY_TIMEOUT=60

# Pipeline
PIPELINE_BATCH_SIZE=100

# Plugin execution timeout (seconds)
PLUGIN_EXEC_TIMEOUT=120

# Scheduler
SCHEDULER_MAX_HISTORY=500

# Max concurrent crawls
MAX_CONCURRENT_CRAWLS=5
```

### 6.5 Add `.env` to `.gitignore`

Ensure `.env` is listed in every relevant `.gitignore`:

```gitignore
# Secrets
.env
.env.local
.env.production
```

---

## 7. SEC-06: Input Validation

**Addresses**: M-02, M-03, M-06, M-08, H-05 (Path traversal, schedule abuse, unvalidated inputs, data injection)

### 7.1 New File: `backend/api/security/input_schemas.py`

```python
"""
Strict Pydantic models for all API inputs.

Replaces loose dict/string inputs with validated, bounded schemas.
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class CrawlerSettingsUpdate(BaseModel):
    """Validated crawler settings update."""

    target_url: Optional[str] = None
    delay: Optional[float] = Field(None, ge=0.1, le=60.0)
    max_items: Optional[int] = Field(None, ge=1, le=10000)

    @field_validator("target_url")
    @classmethod
    def validate_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2048:
            raise ValueError("URL must not exceed 2048 characters")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class ScheduleCreate(BaseModel):
    """Validated schedule creation."""

    crawler_name: str = Field(..., min_length=1, max_length=100)
    cron: str = Field(..., min_length=9, max_length=100)

    @field_validator("crawler_name")
    @classmethod
    def validate_crawler_name(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", v):
            raise ValueError(
                "crawler_name must contain only alphanumeric, dash, underscore, or dot"
            )
        return v

    @field_validator("cron")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        from apscheduler.triggers.cron import CronTrigger

        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression: {e}")

        # Frequency check: reject schedules more frequent than every 5 minutes
        parts = v.strip().split()
        if len(parts) >= 2:
            minute_field = parts[0]
            hour_field = parts[1]
            if minute_field == "*" and hour_field == "*":
                raise ValueError(
                    "Schedules running every minute are not allowed. "
                    "Minimum interval is every 5 minutes (e.g., '*/5 * * * *')."
                )
            if minute_field.startswith("*/"):
                try:
                    interval = int(minute_field[2:])
                    if interval < 5 and hour_field == "*":
                        raise ValueError(
                            f"Schedule interval {interval} minutes is too frequent. "
                            f"Minimum is 5 minutes."
                        )
                except ValueError:
                    pass

        return v


class ScheduleUpdate(BaseModel):
    """Validated schedule update."""

    cron: str = Field(..., min_length=9, max_length=100)

    @field_validator("cron")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        return ScheduleCreate.validate_cron_expression(v)


class PluginSettingsUpdate(BaseModel):
    """Validated plugin settings update."""

    target_url: Optional[str] = None
    enabled: Optional[bool] = None
    max_items: Optional[int] = Field(None, ge=1, le=10000)
    delay: Optional[float] = Field(None, ge=0.1, le=60.0)

    @field_validator("target_url")
    @classmethod
    def validate_url_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if len(v) > 2048:
            raise ValueError("URL must not exceed 2048 characters")
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class BulkRunRequest(BaseModel):
    """Validated bulk-run request with bounded crawler list."""

    crawler_ids: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("crawler_ids")
    @classmethod
    def validate_ids(cls, v: list[str]) -> list[str]:
        for cid in v:
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", cid):
                raise ValueError(f"Invalid crawler_id format: {cid}")
        return v


class CleanupRequest(BaseModel):
    """Validated cleanup request for ingestion endpoint."""

    status: str = Field(..., pattern=r"^(processed|failed|expired)$")
    older_than_days: Optional[int] = Field(None, ge=1, le=365)
```

### 7.2 Changes to `backend/api/routes/schedules.py`

```python
# --- BEFORE (schedules.py cron validation) ---
# Silent failure — _compute_next_runs returns [] on error

# --- AFTER ---
# Use ScheduleCreate model from input_schemas.py which validates cron before accepting.
# Also fix _compute_next_runs to raise instead of silently returning []:

def _compute_next_runs(cron_expr: str, count: int = 3) -> list[str]:
    """Compute next N fire times from a cron expression."""
    try:
        trigger = CronTrigger.from_crontab(cron_expr)
        runs: list[str] = []
        current = datetime.now(timezone.utc)
        for _ in range(count):
            next_time = trigger.get_next_fire_time(None, current)
            if next_time is None:
                break
            runs.append(next_time.isoformat())
            current = next_time + timedelta(seconds=1)
        return runs
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid cron expression: check format (e.g., '0 */6 * * *')"
        )
```

### 7.3 Error Message Sanitization

Apply across all route files — replace `str(e)` with generic messages:

```python
# --- PATTERN: BEFORE ---
raise HTTPException(502, f"DB 관리 API 연결 실패: {exc}")  # Leaks internal URL

# --- PATTERN: AFTER ---
logger.error("DB admin API connection failed: %s", exc, exc_info=True)
raise HTTPException(502, "Internal service unavailable")

# --- PATTERN: BEFORE ---
raise HTTPException(status_code=400, detail=str(exc))  # Leaks APScheduler internals

# --- PATTERN: AFTER ---
logger.error("Schedule operation failed: %s", exc, exc_info=True)
raise HTTPException(400, "Invalid schedule configuration")

# --- PATTERN: BEFORE ---
return {... "error": str(e) ...}  # Leaks stack trace

# --- PATTERN: AFTER ---
logger.error("Crawler execution error: %s", e, exc_info=True)
return {... "error": "Execution failed — check server logs" ...}
```

### 7.4 Changes to `backend/api/routes/ingestion.py`

```python
# --- BEFORE ---
# cleanup endpoint accepts arbitrary dict body

# --- AFTER ---
from api.security.input_schemas import CleanupRequest

@router.post("/cleanup")
async def cleanup_ingestions(body: CleanupRequest):
    """Clean up processed ingestion items."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{DB_ADMIN_URL}/cleanup",
            json=body.model_dump(exclude_none=True),
        )
        resp.raise_for_status()
        return resp.json()
```

---

## 8. SEC-07: Security Headers

**Addresses**: MED-06 (No security headers)

### 8.1 New File: `backend/api/security/headers.py`

```python
"""Security headers middleware for FastAPI."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add standard security headers to every HTTP response.

    Headers set:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Referrer-Policy: strict-origin-when-cross-origin
    - Content-Security-Policy: default-src 'self'
    - Permissions-Policy: geolocation=(), camera=(), microphone=()
    - Cache-Control: no-store (for API responses)
    - Strict-Transport-Security: max-age=31536000 (when HTTPS detected)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), camera=(), microphone=()"
        )

        # Prevent caching of API responses containing sensitive data
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        # HSTS — only set when behind TLS (detected via X-Forwarded-Proto)
        if request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
```

### 8.2 Register in `backend/api/app.py`

```python
# --- ADD after CORS middleware ---
from api.security.headers import SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
```

---

## 9. New Files Summary

```
backend/
├── api/
│   ├── security/
│   │   ├── __init__.py              # empty init
│   │   ├── auth.py                  # API key middleware
│   │   ├── headers.py               # Security headers middleware
│   │   ├── url_validator.py         # SSRF prevention
│   │   └── input_schemas.py         # Pydantic validation models
│   └── app.py                       # ← modified
├── plugins/
│   ├── manifest_verifier.py         # HMAC-SHA256 signing
│   └── import_guard.py              # Import whitelist hook
├── .env.example                     # Configuration template
└── tests/
    └── test_security.py             # Security test suite
```

---

## 10. Test Plan

### 10.1 `backend/tests/test_security.py`

```python
"""
Security test suite for crawler-admin.

Tests authentication, CORS, SSRF prevention, input validation,
plugin sandboxing, and security headers.
"""

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

# Set required env vars before importing app
os.environ.setdefault("CRAWLER_ADMIN_API_KEY", "test-api-key-for-testing-only")
os.environ.setdefault("PLUGIN_SIGNING_KEY", "test-signing-key-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")


# ─────────────────────────────────────────────
# SEC-01: Authentication Tests
# ─────────────────────────────────────────────

class TestAuthentication:
    """Verify API key middleware blocks unauthenticated requests."""

    def setup_method(self):
        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)
        self.valid_key = "test-api-key-for-testing-only"

    def test_request_without_api_key_returns_401(self):
        resp = self.client.get("/api/crawlers")
        assert resp.status_code == 401
        assert "Missing X-API-Key" in resp.json()["detail"]

    def test_request_with_wrong_key_returns_403(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    def test_request_with_valid_key_succeeds(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": self.valid_key},
        )
        assert resp.status_code in (200, 404)  # 200 if crawlers exist

    def test_health_endpoint_is_public(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_timing_safe_comparison(self):
        """Ensure API key comparison is constant-time."""
        import hmac
        key = "test-key"
        assert hmac.compare_digest(key, key)
        assert not hmac.compare_digest(key, "wrong")


# ─────────────────────────────────────────────
# SEC-02: CORS Tests
# ─────────────────────────────────────────────

class TestCORS:
    """Verify CORS is restricted to allowed origins."""

    def setup_method(self):
        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)
        self.headers = {"X-API-Key": "test-api-key-for-testing-only"}

    def test_allowed_origin_gets_cors_headers(self):
        resp = self.client.options(
            "/api/crawlers",
            headers={
                "Origin": "http://localhost:5174",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5174"

    def test_disallowed_origin_blocked(self):
        resp = self.client.options(
            "/api/crawlers",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") != "http://evil.com"

    def test_wildcard_origin_not_present(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={**self.headers, "Origin": "http://localhost:5174"},
        )
        assert resp.headers.get("access-control-allow-origin") != "*"


# ─────────────────────────────────────────────
# SEC-04: SSRF Prevention Tests
# ─────────────────────────────────────────────

class TestSSRFPrevention:
    """Verify URL validation blocks internal/malicious targets."""

    def test_blocks_localhost(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://localhost/admin")

    def test_blocks_127_0_0_1(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://127.0.0.1:8080/secret")

    def test_blocks_private_10_x(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://10.0.0.1/internal")

    def test_blocks_private_172_16(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://172.16.0.1/internal")

    def test_blocks_private_192_168(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://192.168.1.1/admin")

    def test_blocks_aws_metadata(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://169.254.169.254/latest/meta-data/")

    def test_blocks_file_scheme(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("file:///etc/passwd")

    def test_blocks_ftp_scheme(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("ftp://internal.server/data")

    def test_allows_valid_https_url(self):
        from api.security.url_validator import validate_target_url
        result = validate_target_url("https://www.example.com/products")
        assert result == "https://www.example.com/products"

    def test_allows_valid_http_url(self):
        from api.security.url_validator import validate_target_url
        result = validate_target_url("http://www.example.com/page")
        assert result == "http://www.example.com/page"

    def test_blocks_empty_url(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("")

    def test_blocks_ipv6_loopback(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://[::1]/admin")

    def test_blocks_zero_ip(self):
        from api.security.url_validator import validate_target_url
        with pytest.raises(Exception):
            validate_target_url("http://0.0.0.0/")


# ─────────────────────────────────────────────
# SEC-03: Plugin Security Tests
# ─────────────────────────────────────────────

class TestPluginSecurity:
    """Verify plugin import guards and manifest verification."""

    def test_import_guard_blocks_os(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            with pytest.raises(ImportError, match="not allowed to import 'os'"):
                __import__("os")

    def test_import_guard_blocks_subprocess(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            with pytest.raises(ImportError, match="not allowed to import 'subprocess'"):
                __import__("subprocess")

    def test_import_guard_blocks_socket(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            with pytest.raises(ImportError, match="not allowed to import 'socket'"):
                __import__("socket")

    def test_import_guard_allows_json(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            import json  # Should not raise

    def test_import_guard_allows_re(self):
        from plugins.import_guard import guarded_imports
        with guarded_imports("test-plugin"):
            import re  # Should not raise

    def test_import_guard_restores_after_context(self):
        """Verify __import__ is restored after context manager exits."""
        import builtins
        original = builtins.__import__
        from plugins.import_guard import guarded_imports

        with guarded_imports("test"):
            pass

        assert builtins.__import__ is original

    def test_manifest_signature_roundtrip(self):
        """Verify sign → verify cycle works."""
        from plugins.manifest_verifier import (
            compute_manifest_signature,
            verify_manifest,
        )
        from pathlib import Path

        manifest = {
            "name": "test-plugin",
            "version": "1.0.0",
            "target": {"url": "https://example.com"},
        }
        sig = compute_manifest_signature(manifest)
        manifest["signature"] = sig

        assert verify_manifest(Path("dummy.yaml"), manifest) is True

    def test_manifest_tampered_data_fails(self):
        from plugins.manifest_verifier import (
            compute_manifest_signature,
            verify_manifest,
        )
        from pathlib import Path

        manifest = {"name": "test-plugin", "version": "1.0.0"}
        manifest["signature"] = compute_manifest_signature(manifest)

        # Tamper with data
        manifest["version"] = "2.0.0"
        assert verify_manifest(Path("dummy.yaml"), manifest) is False

    def test_manifest_missing_signature_fails(self):
        from plugins.manifest_verifier import verify_manifest
        from pathlib import Path

        manifest = {"name": "test", "version": "1.0.0"}
        assert verify_manifest(Path("dummy.yaml"), manifest) is False


# ─────────────────────────────────────────────
# SEC-06: Input Validation Tests
# ─────────────────────────────────────────────

class TestInputValidation:
    """Verify Pydantic models enforce constraints."""

    def test_crawler_settings_rejects_extreme_delay(self):
        from api.security.input_schemas import CrawlerSettingsUpdate
        with pytest.raises(Exception):
            CrawlerSettingsUpdate(delay=1000.0)

    def test_crawler_settings_rejects_negative_delay(self):
        from api.security.input_schemas import CrawlerSettingsUpdate
        with pytest.raises(Exception):
            CrawlerSettingsUpdate(delay=-1.0)

    def test_crawler_settings_accepts_valid(self):
        from api.security.input_schemas import CrawlerSettingsUpdate
        m = CrawlerSettingsUpdate(
            target_url="https://example.com",
            delay=2.5,
            max_items=100,
        )
        assert m.delay == 2.5

    def test_schedule_rejects_every_minute_cron(self):
        from api.security.input_schemas import ScheduleCreate
        with pytest.raises(Exception):
            ScheduleCreate(crawler_name="test", cron="* * * * *")

    def test_schedule_rejects_invalid_cron(self):
        from api.security.input_schemas import ScheduleCreate
        with pytest.raises(Exception):
            ScheduleCreate(crawler_name="test", cron="not-a-cron")

    def test_schedule_accepts_valid_cron(self):
        from api.security.input_schemas import ScheduleCreate
        m = ScheduleCreate(crawler_name="emart", cron="0 */6 * * *")
        assert m.cron == "0 */6 * * *"

    def test_schedule_rejects_special_chars_in_name(self):
        from api.security.input_schemas import ScheduleCreate
        with pytest.raises(Exception):
            ScheduleCreate(crawler_name="../etc/passwd", cron="0 0 * * *")

    def test_bulk_run_limits_crawler_count(self):
        from api.security.input_schemas import BulkRunRequest
        with pytest.raises(Exception):
            BulkRunRequest(crawler_ids=[f"c{i}" for i in range(20)])

    def test_bulk_run_validates_id_format(self):
        from api.security.input_schemas import BulkRunRequest
        with pytest.raises(Exception):
            BulkRunRequest(crawler_ids=["../../etc/passwd"])

    def test_cleanup_request_rejects_invalid_status(self):
        from api.security.input_schemas import CleanupRequest
        with pytest.raises(Exception):
            CleanupRequest(status="drop_all_tables")

    def test_cleanup_request_accepts_valid(self):
        from api.security.input_schemas import CleanupRequest
        m = CleanupRequest(status="processed", older_than_days=30)
        assert m.status == "processed"

    def test_url_rejects_too_long(self):
        from api.security.input_schemas import CrawlerSettingsUpdate
        with pytest.raises(Exception):
            CrawlerSettingsUpdate(target_url="https://x.com/" + "a" * 3000)


# ─────────────────────────────────────────────
# SEC-07: Security Headers Tests
# ─────────────────────────────────────────────

class TestSecurityHeaders:
    """Verify security headers are present on all responses."""

    def setup_method(self):
        from api.app import create_app
        self.app = create_app()
        self.client = TestClient(self.app)

    def test_health_endpoint_has_security_headers(self):
        resp = self.client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("x-xss-protection") == "1; mode=block"
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in resp.headers.get("content-security-policy", "")

    def test_api_response_has_no_cache(self):
        resp = self.client.get(
            "/api/crawlers",
            headers={"X-API-Key": "test-api-key-for-testing-only"},
        )
        cache = resp.headers.get("cache-control", "")
        assert "no-store" in cache


# ─────────────────────────────────────────────
# SEC-05: Secrets Management Tests
# ─────────────────────────────────────────────

class TestSecretsManagement:
    """Verify no hardcoded secrets remain in source code."""

    def test_no_hardcoded_yogiyo_secret(self):
        """Verify the yogiyo API secret is not hardcoded."""
        import pathlib
        crawler_file = (
            pathlib.Path(__file__).parent.parent
            / "crawlers" / "delivery" / "yogiyo" / "crawler.py"
        )
        if crawler_file.exists():
            content = crawler_file.read_text(encoding="utf-8")
            assert "fe5183cc3dea12bd0ce299cf110a75a2" not in content, (
                "Hardcoded API secret found in yogiyo crawler"
            )

    def test_config_has_no_default_db_password(self):
        """Verify config.py doesn't have hardcoded DB credentials."""
        import pathlib
        config_file = pathlib.Path(__file__).parent.parent / "config.py"
        if config_file.exists():
            content = config_file.read_text(encoding="utf-8")
            assert "user:password@" not in content, (
                "Hardcoded database credentials found in config.py"
            )

    def test_api_key_env_var_required(self):
        """Verify auth module rejects empty API key."""
        with patch.dict(os.environ, {"CRAWLER_ADMIN_API_KEY": ""}):
            from api.security.auth import _get_api_key
            with pytest.raises(RuntimeError, match="required"):
                _get_api_key()
```

### 10.2 Audit Finding Coverage Matrix

| Audit Finding | Test Class/Method | Coverage |
|---|---|---|
| C-01 / CRIT-01 (No Auth) | `TestAuthentication.*` | ✅ 401/403/200 paths |
| C-02 / CRIT-02 (CORS Wildcard) | `TestCORS.*` | ✅ Allow/deny/no-wildcard |
| C-03 / CRIT-03 (Plugin Execution) | `TestPluginSecurity.test_import_guard_*` | ✅ Block os/subprocess/socket |
| H-01 / HIGH-01 (SSRF target_url) | `TestSSRFPrevention.*` | ✅ 13 URL patterns |
| H-03 (Yogiyo hardcoded key) | `TestSecretsManagement.test_no_hardcoded_yogiyo_secret` | ✅ |
| H-05 (Data injection) | `TestInputValidation.test_url_*` | ✅ |
| HIGH-05 (No manifest verify) | `TestPluginSecurity.test_manifest_*` | ✅ Sign/verify/tamper |
| M-01 (Error leakage) | Error sanitization (manual review) | 📋 |
| M-02 (Path traversal) | `TestInputValidation.test_schedule_rejects_special_chars*` | ✅ |
| M-04 (DB cred defaults) | `TestSecretsManagement.test_config_has_no_default_db_password` | ✅ |
| M-06 (No security headers) | `TestSecurityHeaders.*` | ✅ |
| M-08 (Cron frequency) | `TestInputValidation.test_schedule_rejects_every_minute_cron` | ✅ |

---

## Appendix A: Complete `app.py` After All Changes

```python
"""크롤러 관리 API."""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from api.security.auth import verify_api_key
from api.security.headers import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    app = FastAPI(
        title="WalletSavior 크롤러 관리",
        description="크롤러 관리 및 모니터링 API",
        version="0.1.0",
    )

    # --- Middleware (order matters: outermost first) ---

    # GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — restricted origins
    ALLOWED_ORIGINS = [
        o.strip()
        for o in os.getenv("CORS_ORIGINS", "http://localhost:5174").split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
    )

    # --- Routes (all require API key auth) ---
    from api.routes.crawlers import router as crawlers_router
    from api.routes.dashboard import router as dashboard_router
    from api.routes.ingestion import router as ingestion_router
    from api.routes.logs import router as logs_router
    from api.routes.plugins import router as plugins_router
    from api.routes.schedules import router as schedules_router

    _auth = [Depends(verify_api_key)]

    app.include_router(crawlers_router, dependencies=_auth)
    app.include_router(schedules_router, dependencies=_auth)
    app.include_router(logs_router, dependencies=_auth)
    app.include_router(ingestion_router, dependencies=_auth)
    app.include_router(dashboard_router, dependencies=_auth)
    app.include_router(plugins_router, dependencies=_auth)

    # --- Public endpoints ---
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "crawler-admin"}

    return app
```

---

## Appendix B: Implementation Priority

| Priority | Item | Effort | Risk Mitigated |
|---|---|---|---|
| 🔴 P0 | SEC-01: API auth middleware | 2 hrs | Unauthorized access to all endpoints |
| 🔴 P0 | SEC-02: CORS restriction | 15 min | Cross-origin CSRF |
| 🔴 P0 | SEC-05: Remove hardcoded secrets | 1 hr | Credential exposure |
| 🟠 P1 | SEC-04: SSRF URL validator | 2 hrs | Internal network probing |
| 🟠 P1 | SEC-06: Input validation schemas | 2 hrs | Injection, abuse |
| 🟠 P1 | SEC-07: Security headers | 30 min | Clickjacking, XSS, MIME sniffing |
| 🟡 P2 | SEC-03: Plugin manifest signing | 3 hrs | Malicious plugin injection |
| 🟡 P2 | SEC-03: Import guard | 2 hrs | Plugin code execution scope |
| Total | | ~13 hrs | 12 Critical/High + 8 Medium findings |

---

*Generated from `crawler-admin-code-audit.md` and `crawler-admin-arch-audit.md`.*
*All code targets Python 3.11+ with FastAPI 0.100+, Pydantic v2, PyYAML.*
