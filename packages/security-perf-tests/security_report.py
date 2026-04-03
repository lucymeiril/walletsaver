"""
보안 테스트 보고서 생성기.

기능:
- 모든 보안 테스트 결과 집계
- 위험 분류 (Critical, High, Medium, Low, Info)
- OWASP Top 10 커버리지 매핑
- 개선 권고사항
- JSON 내보내기
"""

import json
import os
from datetime import datetime
from pathlib import Path


# ═══════════════════════════════════════════════
# OWASP Top 10 (2021) Mapping
# ═══════════════════════════════════════════════

OWASP_TOP10 = {
    "A01": "Broken Access Control",
    "A02": "Cryptographic Failures",
    "A03": "Injection",
    "A04": "Insecure Design",
    "A05": "Security Misconfiguration",
    "A06": "Vulnerable and Outdated Components",
    "A07": "Identification and Authentication Failures",
    "A08": "Software and Data Integrity Failures",
    "A09": "Security Logging and Monitoring Failures",
    "A10": "Server-Side Request Forgery (SSRF)",
}


# ═══════════════════════════════════════════════
# Security Findings
# ═══════════════════════════════════════════════

def get_security_findings():
    """Return all security findings from test analysis."""
    return [
        # Critical
        {
            "id": "SEC-001",
            "severity": "Critical",
            "category": "Authentication",
            "owasp": "A07",
            "title": "Default JWT Secret Key in Development",
            "description": (
                "JWT_SECRET_KEY defaults to 'dev-secret-key-change-in-production'. "
                "If not overridden via environment variable, tokens can be forged."
            ),
            "file": "packages/website/backend/services/auth_service.py:9",
            "remediation": (
                "Remove default value. Require JWT_SECRET_KEY environment variable. "
                "Fail startup if not set. Use a cryptographically random 256-bit key."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-002",
            "severity": "Critical",
            "category": "Access Control",
            "owasp": "A01",
            "title": "Crawler-Admin API Has No Authentication",
            "description": (
                "All crawler-admin endpoints (/api/crawlers, /api/schedules, /api/logs) "
                "have no authentication. Anyone can trigger crawlers, modify schedules, "
                "and read internal logs."
            ),
            "file": "packages/crawler-admin/backend/api/routes/crawlers.py",
            "remediation": (
                "Add require_admin middleware to all crawler-admin routes. "
                "Implement API key authentication for service-to-service calls."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-003",
            "severity": "Critical",
            "category": "Access Control",
            "owasp": "A01",
            "title": "DB-Admin API Has No Authentication",
            "description": (
                "All db-admin endpoints (CRUD for products, prices, categories) "
                "have no authentication. Anyone can create, modify, or delete data."
            ),
            "file": "packages/db-admin/backend/api/routes/products.py",
            "remediation": (
                "Add authentication middleware to all db-admin routes. "
                "Restrict write operations to admin users only."
            ),
            "status": "FINDING",
        },

        # High
        {
            "id": "SEC-004",
            "severity": "High",
            "category": "Security Misconfiguration",
            "owasp": "A05",
            "title": "CORS Allows All Origins on Admin APIs",
            "description": (
                "Crawler-admin and db-admin APIs have CORS allow_origins=['*'] "
                "with allow_credentials=True. This allows any website to make "
                "authenticated requests to admin APIs."
            ),
            "file": "packages/crawler-admin/backend/api/app.py:15",
            "remediation": (
                "Restrict CORS origins to specific admin dashboard URLs. "
                "Never use wildcard with credentials. Consider IP whitelisting."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-005",
            "severity": "High",
            "category": "Authentication",
            "owasp": "A07",
            "title": "OAuth Tokens Exposed in URL Redirect",
            "description": (
                "OAuth callback redirects include access_token and refresh_token "
                "as URL query parameters, exposing them in browser history, "
                "server logs, and referrer headers."
            ),
            "file": "packages/website/backend/api/routes/auth.py:106",
            "remediation": (
                "Use authorization code pattern: redirect with a short-lived code, "
                "then exchange it for tokens via a POST request. "
                "Or use fragment (#) instead of query parameters."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-006",
            "severity": "High",
            "category": "Cryptographic Failures",
            "owasp": "A02",
            "title": "Default Database Credentials in Configuration",
            "description": (
                "Database connection strings contain default credentials "
                "(user:password, walletsavior:changeme) in source code."
            ),
            "file": "packages/db-admin/backend/config.py",
            "remediation": (
                "Remove default credentials from source code. "
                "Require DATABASE_URL as environment variable. "
                "Use secrets management (HashiCorp Vault, AWS Secrets Manager)."
            ),
            "status": "FINDING",
        },

        # Medium
        {
            "id": "SEC-007",
            "severity": "Medium",
            "category": "Security Misconfiguration",
            "owasp": "A05",
            "title": "Overly Permissive CORS Methods and Headers",
            "description": (
                "Website API allows all methods and headers via CORS "
                "(allow_methods=['*'], allow_headers=['*']). Should restrict "
                "to actually needed methods and headers."
            ),
            "file": "packages/website/backend/api/app.py:40-41",
            "remediation": (
                "Restrict allow_methods to ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']. "
                "Restrict allow_headers to ['Content-Type', 'Authorization']."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-008",
            "severity": "Medium",
            "category": "Authentication",
            "owasp": "A07",
            "title": "No Rate Limiting on Authentication Endpoints",
            "description": (
                "Login and registration endpoints have no rate limiting, "
                "allowing unlimited brute force attempts."
            ),
            "file": "packages/website/backend/api/routes/auth.py",
            "remediation": (
                "Implement rate limiting (e.g., slowapi). Limit to 5 login "
                "attempts per minute per IP. Add account lockout after 10 failures."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-009",
            "severity": "Medium",
            "category": "Security Headers",
            "owasp": "A05",
            "title": "Missing Security Response Headers",
            "description": (
                "API responses are missing security headers: "
                "X-Content-Type-Options, X-Frame-Options, "
                "Strict-Transport-Security, Content-Security-Policy."
            ),
            "file": "packages/website/backend/api/app.py",
            "remediation": (
                "Add security headers middleware: "
                "X-Content-Type-Options: nosniff, "
                "X-Frame-Options: DENY, "
                "Strict-Transport-Security: max-age=31536000."
            ),
            "status": "FINDING",
        },

        # Low
        {
            "id": "SEC-010",
            "severity": "Low",
            "category": "Input Validation",
            "owasp": "A03",
            "title": "No Content Size Limit on Post Bodies",
            "description": (
                "Community post creation has no explicit limit on content size. "
                "Users could submit extremely large posts."
            ),
            "file": "packages/website/backend/api/routes/community.py",
            "remediation": (
                "Add max_length validation to PostCreate content field. "
                "Recommended limit: 50,000 characters."
            ),
            "status": "FINDING",
        },
        {
            "id": "SEC-011",
            "severity": "Low",
            "category": "OAuth",
            "owasp": "A07",
            "title": "OAuth Redirect Base Uses HTTP",
            "description": (
                "OAUTH_REDIRECT_BASE defaults to http://localhost:8000 (HTTP). "
                "In production, this should use HTTPS."
            ),
            "file": "packages/website/backend/services/oauth_service.py",
            "remediation": (
                "Set OAUTH_REDIRECT_BASE to HTTPS URL in production. "
                "Add validation to reject HTTP in non-development environments."
            ),
            "status": "FINDING",
        },

        # Info / Passing
        {
            "id": "SEC-012",
            "severity": "Info",
            "category": "Authentication",
            "owasp": "A07",
            "title": "JWT Token Type Validation Implemented",
            "description": (
                "Auth middleware correctly validates token type is 'access', "
                "preventing refresh tokens from being used for API access."
            ),
            "file": "packages/website/backend/api/middleware/auth.py:21",
            "remediation": "No action needed. Well implemented.",
            "status": "PASS",
        },
        {
            "id": "SEC-013",
            "severity": "Info",
            "category": "Authentication",
            "owasp": "A02",
            "title": "bcrypt Password Hashing with Salt",
            "description": (
                "Password hashing uses bcrypt via passlib with automatic salting. "
                "Each hash is unique even for identical passwords."
            ),
            "file": "packages/website/backend/services/auth_service.py:14",
            "remediation": "No action needed. Well implemented.",
            "status": "PASS",
        },
        {
            "id": "SEC-014",
            "severity": "Info",
            "category": "Access Control",
            "owasp": "A01",
            "title": "Post Ownership Validation for Modifications",
            "description": (
                "Community post update/delete operations correctly verify "
                "post ownership (author_id check) preventing IDOR."
            ),
            "file": "packages/website/backend/api/routes/community.py:135",
            "remediation": "No action needed. Well implemented.",
            "status": "PASS",
        },
        {
            "id": "SEC-015",
            "severity": "Info",
            "category": "Plugin Security",
            "owasp": "A04",
            "title": "Plugin Iframe Sandbox Properly Configured",
            "description": (
                "Plugin iframes use sandbox attributes that prevent "
                "top-level navigation and popups. allow-same-origin is "
                "only granted with network:external permission."
            ),
            "file": "packages/website/frontend/src/plugins/runtime/PluginSandbox.jsx",
            "remediation": "No action needed. Well implemented.",
            "status": "PASS",
        },
        {
            "id": "SEC-016",
            "severity": "Info",
            "category": "Input Validation",
            "owasp": "A03",
            "title": "Pydantic Input Validation on All Endpoints",
            "description": (
                "All API endpoints use Pydantic models for input validation, "
                "including email format, password requirements, and field types."
            ),
            "file": "packages/website/backend/api/schemas/",
            "remediation": "No action needed. Well implemented.",
            "status": "PASS",
        },
    ]


def get_owasp_coverage():
    """Map findings to OWASP Top 10 categories."""
    findings = get_security_findings()
    coverage = {}
    for code, name in OWASP_TOP10.items():
        related = [f for f in findings if f["owasp"] == code]
        coverage[code] = {
            "name": name,
            "findings_count": len(related),
            "covered": len(related) > 0,
            "findings": [f["id"] for f in related],
        }
    return coverage


def generate_report():
    """Generate the full security report as a dict."""
    findings = get_security_findings()
    owasp = get_owasp_coverage()

    severity_counts = {}
    for f in findings:
        sev = f["severity"]
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    status_counts = {}
    for f in findings:
        st = f["status"]
        status_counts[st] = status_counts.get(st, 0) + 1

    covered = sum(1 for v in owasp.values() if v["covered"])

    report = {
        "report": {
            "title": "WalletSavior Security Assessment Report",
            "generated_at": datetime.now().isoformat(),
            "version": "1.0.0",
            "project": "지갑 지키미 (WalletSavior)",
        },
        "summary": {
            "total_findings": len(findings),
            "by_severity": severity_counts,
            "by_status": status_counts,
            "owasp_coverage": f"{covered}/{len(OWASP_TOP10)}",
        },
        "owasp_top10_coverage": owasp,
        "findings": findings,
        "recommendations": {
            "immediate": [
                "Set strong JWT_SECRET_KEY via environment variable",
                "Add authentication to crawler-admin and db-admin APIs",
                "Restrict CORS origins on admin APIs",
                "Fix OAuth token exposure in redirect URLs",
                "Remove default database credentials from source code",
            ],
            "short_term": [
                "Implement rate limiting on auth endpoints",
                "Add security response headers (CSP, HSTS, X-Content-Type-Options)",
                "Restrict CORS methods and headers to minimum needed",
                "Add content size limits for user-generated content",
            ],
            "long_term": [
                "Implement comprehensive security logging and monitoring",
                "Set up automated dependency vulnerability scanning",
                "Implement CSRF protection for state-changing operations",
                "Add API key rotation mechanism",
                "Conduct penetration testing by external security team",
            ],
        },
    }
    return report


def export_report_json(output_path=None):
    """Export the security report as JSON."""
    report = generate_report()
    if output_path is None:
        output_path = str(
            Path(__file__).parent / "security_report_output.json"
        )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return output_path


# ═══════════════════════════════════════════════
# Test for the report generator itself
# ═══════════════════════════════════════════════

def test_report_generation():
    """보고서 생성이 성공해야 한다."""
    report = generate_report()
    assert "report" in report
    assert "summary" in report
    assert "findings" in report
    assert "owasp_top10_coverage" in report
    assert "recommendations" in report
    assert report["summary"]["total_findings"] >= 10


def test_owasp_coverage():
    """OWASP Top 10 커버리지가 충분해야 한다."""
    coverage = get_owasp_coverage()
    covered = sum(1 for v in coverage.values() if v["covered"])
    assert covered >= 5, f"Only {covered}/10 OWASP categories covered"


def test_severity_distribution():
    """위험도 분포가 합리적이어야 한다."""
    findings = get_security_findings()
    severities = [f["severity"] for f in findings]
    assert "Critical" in severities
    assert "High" in severities
    assert "Info" in severities


def test_export_json():
    """JSON 내보내기가 성공해야 한다."""
    output_path = str(Path(__file__).parent / "security_report_output.json")
    try:
        path = export_report_json(output_path)
        assert os.path.exists(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "findings" in data
        assert len(data["findings"]) >= 10
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def test_all_findings_have_required_fields():
    """모든 발견사항이 필수 필드를 가져야 한다."""
    findings = get_security_findings()
    required_fields = ["id", "severity", "category", "owasp", "title",
                       "description", "remediation", "status"]
    for finding in findings:
        for field in required_fields:
            assert field in finding, \
                f"Finding {finding.get('id', '?')} missing field: {field}"


def test_recommendations_structure():
    """권고사항 구조가 올바라야 한다."""
    report = generate_report()
    recs = report["recommendations"]
    assert "immediate" in recs
    assert "short_term" in recs
    assert "long_term" in recs
    assert len(recs["immediate"]) >= 3
    assert len(recs["short_term"]) >= 3


if __name__ == "__main__":
    path = export_report_json()
    report = generate_report()
    print(f"\n{'='*60}")
    print(f" WalletSavior Security Report")
    print(f"{'='*60}")
    print(f" Generated: {report['report']['generated_at']}")
    print(f" Total Findings: {report['summary']['total_findings']}")
    print(f" By Severity: {report['summary']['by_severity']}")
    print(f" OWASP Coverage: {report['summary']['owasp_coverage']}")
    print(f" Report saved to: {path}")
    print(f"{'='*60}")
