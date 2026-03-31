"""
WalletSavior 보안·성능 테스트 — 공통 fixture.

Security & Performance 테스트가 사용하는 공유 fixture:
- FastAPI TestClient (website, crawler-admin, db-admin)
- JWT 토큰 생성 헬퍼
- 보안 테스트용 mock 앱
- 인젝션 페이로드 데이터
"""

import sys
import os
import time
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Generator

# --- 경로 설정 ---
ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES = ROOT / "packages"
WEBSITE_BACKEND = PACKAGES / "website" / "backend"
CRAWLER_BACKEND = PACKAGES / "crawler-admin" / "backend"
DB_BACKEND = PACKAGES / "db-admin" / "backend"
SHARED = PACKAGES / "shared"

_proj = str(ROOT / "proj")
if _proj in sys.path:
    sys.path.remove(_proj)

for p in [
    str(DB_BACKEND),
    str(WEBSITE_BACKEND),
    str(CRAWLER_BACKEND),
    str(SHARED),
]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest
import importlib.util
from fastapi.testclient import TestClient


def _load_module_from_path(module_name, file_path):
    """파일 경로로 모듈 직접 로드 (이름 충돌 방지)."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════
# Website App
# ═══════════════════════════════════════════════

@pytest.fixture
def website_app():
    """Website FastAPI app (mock mode)."""
    saved_path = sys.path.copy()
    sys.path.insert(0, str(WEBSITE_BACKEND))
    try:
        mod = _load_module_from_path(
            "website_api_app",
            str(WEBSITE_BACKEND / "api" / "app.py"),
        )
        app = mod.create_app(storage=None, engine=None, event_bus=None)
        return app
    finally:
        sys.path = saved_path


@pytest.fixture
def website_client(website_app) -> TestClient:
    return TestClient(website_app)


# ═══════════════════════════════════════════════
# Crawler-Admin App
# ═══════════════════════════════════════════════

@pytest.fixture
def crawler_admin_app():
    """Crawler-admin FastAPI app."""
    api_modules = {k: v for k, v in sys.modules.items() if k == "api" or k.startswith("api.")}
    for k in api_modules:
        del sys.modules[k]
    saved_path = sys.path.copy()
    sys.path.insert(0, str(CRAWLER_BACKEND))
    try:
        mod = _load_module_from_path(
            "crawler_api_app",
            str(CRAWLER_BACKEND / "api" / "app.py"),
        )
        app = mod.create_app()
        return app
    finally:
        for k in [k for k in sys.modules if k == "api" or k.startswith("api.")]:
            del sys.modules[k]
        sys.modules.update(api_modules)
        sys.path = saved_path


@pytest.fixture
def crawler_admin_client(crawler_admin_app) -> TestClient:
    return TestClient(crawler_admin_app)


# ═══════════════════════════════════════════════
# Auth Service Access
# ═══════════════════════════════════════════════

@pytest.fixture
def auth_service():
    """Direct access to auth_service module."""
    saved_path = sys.path.copy()
    sys.path.insert(0, str(WEBSITE_BACKEND))
    try:
        mod = _load_module_from_path(
            "auth_svc",
            str(WEBSITE_BACKEND / "services" / "auth_service.py"),
        )
        return mod
    finally:
        sys.path = saved_path


# ═══════════════════════════════════════════════
# JWT Token Fixtures
# ═══════════════════════════════════════════════

@pytest.fixture
def auth_token():
    """유효한 JWT 액세스 토큰."""
    from services.auth_service import create_access_token
    return create_access_token(
        data={"sub": "1", "email": "test@example.com", "role": "user"},
        expires_delta=timedelta(hours=1),
    )


@pytest.fixture
def admin_token():
    """관리자 JWT 토큰."""
    from services.auth_service import create_access_token
    return create_access_token(
        data={"sub": "99", "email": "admin@example.com", "role": "admin"},
        expires_delta=timedelta(hours=1),
    )


@pytest.fixture
def other_user_token():
    """다른 사용자 JWT 토큰 (IDOR 테스트용)."""
    from services.auth_service import create_access_token
    return create_access_token(
        data={"sub": "2", "email": "other@example.com", "role": "user"},
        expires_delta=timedelta(hours=1),
    )


@pytest.fixture
def expired_token():
    """만료된 JWT 토큰."""
    from services.auth_service import create_access_token
    return create_access_token(
        data={"sub": "1", "email": "test@example.com", "role": "user"},
        expires_delta=timedelta(seconds=-1),
    )


@pytest.fixture
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def other_user_headers(other_user_token):
    return {"Authorization": f"Bearer {other_user_token}"}


# ═══════════════════════════════════════════════
# Security Test Helpers
# ═══════════════════════════════════════════════

SQL_INJECTION_PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1 UNION SELECT * FROM users",
    "admin'--",
    "' OR 1=1 --",
    "1; DELETE FROM products WHERE 1=1",
    "' UNION SELECT NULL, username, password FROM users --",
    "'; EXEC xp_cmdshell('dir'); --",
    "1' AND '1'='1",
    "' OR ''='",
]

XSS_PAYLOADS = [
    "<script>alert('XSS')</script>",
    "<img src=x onerror=alert('XSS')>",
    "<svg onload=alert('XSS')>",
    "javascript:alert('XSS')",
    "<iframe src='javascript:alert(1)'>",
    "'-alert(1)-'",
    "<body onload=alert('XSS')>",
    '"><img src=x onerror=alert(1)//>',
    "<details open ontoggle=alert(1)>",
    "<input onfocus=alert(1) autofocus>",
]

PATH_TRAVERSAL_PAYLOADS = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\system32\\config\\sam",
    "....//....//....//etc/passwd",
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "..%252f..%252f..%252fetc%252fpasswd",
    "/etc/passwd%00.jpg",
    "..\\..\\..\\..\\boot.ini",
]

COMMAND_INJECTION_PAYLOADS = [
    "; ls -la",
    "| cat /etc/passwd",
    "$(whoami)",
    "`whoami`",
    "&& dir",
    "|| echo vulnerable",
    "; rm -rf /",
    "| net user",
]

CRLF_INJECTION_PAYLOADS = [
    "test\r\nSet-Cookie: hacked=true",
    "test%0d%0aSet-Cookie:%20hacked=true",
    "test\r\nX-Injected: true",
    "test\r\n\r\n<html>injected</html>",
]

UNICODE_ATTACK_PAYLOADS = [
    "\u0000",           # Null byte
    "\uff1cscript\uff1e",  # Fullwidth <script>
    "test\u202efdp.exe",   # Right-to-left override
    "\ud800",              # Lone surrogate
    "A" * 10000,           # Long string
]

KOREAN_SPECIAL_PAYLOADS = [
    "양파'; DROP TABLE products; --",
    "삼겹살<script>alert(1)</script>",
    "사과\r\nX-Injected: true",
    "감자 OR 1=1",
    "우유%00.jpg",
]


@pytest.fixture
def sql_injection_payloads():
    return SQL_INJECTION_PAYLOADS


@pytest.fixture
def xss_payloads():
    return XSS_PAYLOADS


@pytest.fixture
def path_traversal_payloads():
    return PATH_TRAVERSAL_PAYLOADS


@pytest.fixture
def command_injection_payloads():
    return COMMAND_INJECTION_PAYLOADS


# ═══════════════════════════════════════════════
# Performance Helpers
# ═══════════════════════════════════════════════

class Timer:
    """Simple context manager for measuring elapsed time."""
    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self.start
        self.elapsed_ms = self.elapsed * 1000


@pytest.fixture
def timer():
    return Timer


# ═══════════════════════════════════════════════
# Security Report Collector
# ═══════════════════════════════════════════════

class SecurityFinding:
    """Represents a single security finding."""
    def __init__(self, category: str, title: str, severity: str,
                 description: str, owasp: str = "", remediation: str = "",
                 status: str = "PASS"):
        self.category = category
        self.title = title
        self.severity = severity
        self.description = description
        self.owasp = owasp
        self.remediation = remediation
        self.status = status

    def to_dict(self):
        return {
            "category": self.category,
            "title": self.title,
            "severity": self.severity,
            "description": self.description,
            "owasp": self.owasp,
            "remediation": self.remediation,
            "status": self.status,
        }


class SecurityReportCollector:
    """Collects security test findings across test sessions."""
    _findings: list = []

    @classmethod
    def add_finding(cls, finding: SecurityFinding):
        cls._findings.append(finding)

    @classmethod
    def get_findings(cls):
        return cls._findings

    @classmethod
    def clear(cls):
        cls._findings = []


@pytest.fixture
def report_collector():
    return SecurityReportCollector
