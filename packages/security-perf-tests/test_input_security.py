"""
입력 검증 보안 테스트 — SQL 인젝션, XSS, 경로 탐색, 명령 인젝션.

Tests:
- SQL injection on search, community posts, comments
- XSS injection in posts, comments, usernames
- Path traversal in file upload paths
- Command injection in crawler configuration
- CRLF injection in headers
- Unicode/encoding attacks
- Oversized payload handling
- Korean + special characters in search
"""

import pytest
import json

from conftest import (
    SQL_INJECTION_PAYLOADS,
    XSS_PAYLOADS,
    PATH_TRAVERSAL_PAYLOADS,
    COMMAND_INJECTION_PAYLOADS,
    CRLF_INJECTION_PAYLOADS,
    UNICODE_ATTACK_PAYLOADS,
    KOREAN_SPECIAL_PAYLOADS,
)


# ═══════════════════════════════════════════════
# SQL Injection Tests
# ═══════════════════════════════════════════════

class TestSQLInjection:
    """SQL 인젝션 방어 테스트."""

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS)
    def test_search_query_sql_injection(self, website_client, payload):
        """검색 쿼리에서 SQL 인젝션이 차단되어야 한다."""
        resp = website_client.get("/api/search", params={"q": payload})
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            body = resp.text.lower()
            assert "error" not in body or "sql" not in body

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    def test_post_title_sql_injection(self, website_client, auth_headers, payload):
        """게시글 제목에서 SQL 인젝션이 차단되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": payload,
            "content": "정상 콘텐츠",
            "post_type": "free",
        })
        # Should either accept (stored safely) or reject — never execute SQL
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            data = resp.json()["data"]
            assert data["title"] == payload  # Stored as-is, not interpreted

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:5])
    def test_comment_sql_injection(self, website_client, auth_headers, payload):
        """댓글 내용에서 SQL 인젝션이 차단되어야 한다."""
        # First get a valid post ID
        posts_resp = website_client.get("/api/posts")
        if posts_resp.status_code == 200 and posts_resp.json().get("data"):
            post_id = posts_resp.json()["data"][0]["id"]
            resp = website_client.post(
                f"/api/posts/{post_id}/comments",
                headers=auth_headers,
                json={"content": payload},
            )
            assert resp.status_code in (200, 400, 422)

    @pytest.mark.parametrize("payload", SQL_INJECTION_PAYLOADS[:3])
    def test_autocomplete_sql_injection(self, website_client, payload):
        """자동완성에서 SQL 인젝션이 차단되어야 한다."""
        resp = website_client.get("/api/search/autocomplete", params={"q": payload})
        assert resp.status_code in (200, 400, 422)


# ═══════════════════════════════════════════════
# XSS Prevention Tests
# ═══════════════════════════════════════════════

class TestXSSPrevention:
    """XSS 방어 테스트."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_post_title_xss_stored_safely(self, website_client, auth_headers, payload):
        """게시글 제목에 XSS 페이로드가 안전하게 처리되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": payload,
            "content": "정상 콘텐츠",
            "post_type": "free",
        })
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            # JSON API — content-type should be application/json
            assert "text/html" not in resp.headers.get("content-type", "")

    @pytest.mark.parametrize("payload", XSS_PAYLOADS[:5])
    def test_post_content_xss_stored_safely(self, website_client, auth_headers, payload):
        """게시글 본문에 XSS 페이로드가 안전하게 처리되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "정상 제목",
            "content": payload,
            "post_type": "free",
        })
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            data = resp.json()["data"]
            assert data["content"] == payload  # Stored as data, not executed

    @pytest.mark.parametrize("payload", XSS_PAYLOADS[:5])
    def test_search_xss_safe(self, website_client, payload):
        """검색 결과에서 XSS가 실행되지 않아야 한다."""
        resp = website_client.get("/api/search", params={"q": payload})
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            assert "application/json" in content_type

    def test_json_content_type_prevents_xss(self, website_client, auth_headers):
        """응답이 application/json으로 반환되어 브라우저 XSS 실행을 방지한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "<script>alert(1)</script>",
            "content": "<img src=x onerror=alert(1)>",
            "post_type": "free",
        })
        if resp.status_code == 200:
            assert "application/json" in resp.headers["content-type"]


# ═══════════════════════════════════════════════
# Path Traversal Tests
# ═══════════════════════════════════════════════

class TestPathTraversal:
    """경로 탐색 공격 방어 테스트."""

    @pytest.mark.parametrize("payload", PATH_TRAVERSAL_PAYLOADS)
    def test_search_path_traversal(self, website_client, payload):
        """검색에서 경로 탐색이 차단되어야 한다."""
        resp = website_client.get("/api/search", params={"q": payload})
        assert resp.status_code in (200, 400, 422)
        if resp.status_code == 200:
            body = resp.text
            assert "/etc/passwd" not in body
            assert "root:" not in body

    @pytest.mark.parametrize("payload", PATH_TRAVERSAL_PAYLOADS[:3])
    def test_post_url_path_traversal(self, website_client, auth_headers, payload):
        """게시글 URL 필드에서 경로 탐색이 차단되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "테스트",
            "content": "테스트 콘텐츠",
            "post_type": "hotdeal",
            "url": payload,
        })
        assert resp.status_code in (200, 400, 422)


# ═══════════════════════════════════════════════
# Command Injection Tests
# ═══════════════════════════════════════════════

class TestCommandInjection:
    """명령 인젝션 방어 테스트."""

    @pytest.mark.parametrize("payload", COMMAND_INJECTION_PAYLOADS)
    def test_search_command_injection(self, website_client, payload):
        """검색에서 명령 인젝션이 차단되어야 한다."""
        resp = website_client.get("/api/search", params={"q": payload})
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.parametrize("payload", COMMAND_INJECTION_PAYLOADS[:4])
    def test_crawler_admin_command_injection(self, crawler_admin_client, payload):
        """크롤러 관리에서 명령 인젝션이 차단되어야 한다."""
        resp = crawler_admin_client.get(f"/api/crawlers/{payload}/status")
        # Should not execute any commands, just return 404 or similar
        assert resp.status_code in (200, 400, 404, 422)


# ═══════════════════════════════════════════════
# CRLF Injection Tests
# ═══════════════════════════════════════════════

class TestCRLFInjection:
    """CRLF 인젝션 방어 테스트."""

    @pytest.mark.parametrize("payload", CRLF_INJECTION_PAYLOADS)
    def test_search_crlf_injection(self, website_client, payload):
        """검색 파라미터에서 CRLF 인젝션이 차단되어야 한다."""
        resp = website_client.get("/api/search", params={"q": payload})
        assert resp.status_code in (200, 400, 422)
        # Check no injected headers
        assert "hacked" not in str(resp.headers)
        assert "X-Injected" not in str(resp.headers)

    def test_crlf_in_post_title(self, website_client, auth_headers):
        """게시글 제목에서 CRLF 인젝션이 차단되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "Test\r\nX-Injected: true",
            "content": "CRLF test",
            "post_type": "free",
        })
        assert resp.status_code in (200, 400, 422)
        assert "X-Injected" not in str(resp.headers)


# ═══════════════════════════════════════════════
# Unicode / Encoding Attack Tests
# ═══════════════════════════════════════════════

class TestUnicodeAttacks:
    """유니코드/인코딩 공격 방어 테스트."""

    def test_null_byte_in_search(self, website_client):
        """널 바이트가 포함된 검색이 안전하게 처리되어야 한다."""
        resp = website_client.get("/api/search", params={"q": "test\x00admin"})
        assert resp.status_code in (200, 400, 422)

    def test_long_string_in_search(self, website_client):
        """매우 긴 문자열이 안전하게 처리되어야 한다."""
        resp = website_client.get("/api/search", params={"q": "A" * 10000})
        assert resp.status_code in (200, 400, 413, 422)

    def test_unicode_fullwidth_script_tag(self, website_client, auth_headers):
        """전각 문자 스크립트 태그가 안전하게 처리되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "\uff1cscript\uff1ealert(1)\uff1c/script\uff1e",
            "content": "유니코드 테스트",
            "post_type": "free",
        })
        assert resp.status_code in (200, 400, 422)

    def test_rtl_override_in_search(self, website_client):
        """RTL 오버라이드 문자가 안전하게 처리되어야 한다."""
        resp = website_client.get("/api/search", params={"q": "test\u202efdp.exe"})
        assert resp.status_code in (200, 400, 422)


# ═══════════════════════════════════════════════
# Oversized Payload Tests
# ═══════════════════════════════════════════════

class TestOversizedPayloads:
    """과대 페이로드 처리 테스트."""

    def test_large_post_body(self, website_client, auth_headers):
        """1MB 이상의 게시글 본문이 적절하게 처리되어야 한다."""
        large_content = "가" * 500000  # ~1.5MB in UTF-8
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "대용량 테스트",
            "content": large_content,
            "post_type": "free",
        })
        # Should either accept or reject with appropriate status
        assert resp.status_code in (200, 400, 413, 422)

    def test_large_search_query(self, website_client):
        """대용량 검색 쿼리가 적절하게 처리되어야 한다."""
        # Use a shorter but still large query to avoid URL length limits
        resp = website_client.get("/api/search", params={"q": "양파" * 500})
        assert resp.status_code in (200, 400, 413, 414, 422)

    def test_many_query_parameters(self, website_client):
        """매우 많은 쿼리 파라미터가 안전하게 처리되어야 한다."""
        params = {f"param_{i}": f"value_{i}" for i in range(100)}
        params["q"] = "양파"
        resp = website_client.get("/api/search", params=params)
        assert resp.status_code in (200, 400, 413, 422)


# ═══════════════════════════════════════════════
# Korean + Special Characters Tests
# ═══════════════════════════════════════════════

class TestKoreanSpecialCharacters:
    """한국어 + 특수문자 처리 테스트."""

    @pytest.mark.parametrize("payload", KOREAN_SPECIAL_PAYLOADS)
    def test_korean_injection_in_search(self, website_client, payload):
        """한국어+인젝션 혼합 검색이 안전하게 처리되어야 한다."""
        resp = website_client.get("/api/search", params={"q": payload})
        assert resp.status_code in (200, 400, 422)

    def test_korean_in_post_creation(self, website_client, auth_headers):
        """한국어 게시글이 정상적으로 생성되어야 한다."""
        resp = website_client.post("/api/posts", headers=auth_headers, json={
            "title": "이마트 삼겹살 특가! 100g당 1,100원",
            "content": "오늘부터 3일간 진행하는 삼겹살 할인행사입니다. 🔥🎉",
            "post_type": "hotdeal",
            "price": 1100,
            "original_price": 1850,
        })
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "삼겹살" in data["title"]

    def test_special_chars_in_search(self, website_client):
        """특수문자 검색이 안전하게 처리되어야 한다."""
        special_queries = ["(양파)", "[삼겹살]", "{감자}", "<사과>", "우유|두유"]
        for q in special_queries:
            resp = website_client.get("/api/search", params={"q": q})
            assert resp.status_code in (200, 400, 422)
