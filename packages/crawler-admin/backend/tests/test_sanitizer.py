"""Tests for data sanitization functions."""

import pytest
from pipeline.sanitizer import sanitize_text, sanitize_url, sanitize_number, sanitize_record


class TestSanitizeText:
    def test_strips_html_tags(self):
        assert "<script>" not in sanitize_text('<script>alert("xss")</script>Hello')
        assert "Hello" in sanitize_text("<b>Hello</b>")

    def test_escapes_special_chars(self):
        result = sanitize_text('test & "quotes"')
        assert "&amp;" in result
        assert "&quot;" in result

    def test_truncates_to_max_length(self):
        long_text = "a" * 1000
        assert len(sanitize_text(long_text, max_length=100)) == 100

    def test_removes_null_bytes(self):
        assert "\x00" not in sanitize_text("hello\x00world")

    def test_removes_control_chars(self):
        assert "\x01" not in sanitize_text("hello\x01world")

    def test_none_returns_empty(self):
        assert sanitize_text(None) == ""

    def test_preserves_korean(self):
        assert "삼겹살" in sanitize_text("신선한 삼겹살 500g")

    def test_collapses_whitespace(self):
        assert sanitize_text("hello    world") == "hello world"


class TestSanitizeUrl:
    def test_blocks_javascript_scheme(self):
        assert sanitize_url("javascript:alert(1)") == ""

    def test_blocks_data_scheme(self):
        assert sanitize_url("data:text/html,<script>alert(1)</script>") == ""

    def test_allows_http(self):
        assert sanitize_url("http://example.com") == "http://example.com"

    def test_allows_https(self):
        assert sanitize_url("https://example.com/path") == "https://example.com/path"

    def test_truncates_long_url(self):
        url = "https://example.com/" + "a" * 3000
        assert len(sanitize_url(url)) == 2048

    def test_none_returns_empty(self):
        assert sanitize_url(None) == ""

    def test_removes_control_chars(self):
        assert "\x00" not in sanitize_url("https://example.com/\x00path")


class TestSanitizeNumber:
    def test_valid_int(self):
        assert sanitize_number(12500) == 12500.0

    def test_valid_float(self):
        assert sanitize_number(99.9) == 99.9

    def test_string_number(self):
        assert sanitize_number("12500") == 12500.0

    def test_out_of_range_negative(self):
        assert sanitize_number(-1) is None

    def test_out_of_range_high(self):
        assert sanitize_number(999_999_999) is None

    def test_none_returns_none(self):
        assert sanitize_number(None) is None

    def test_invalid_string(self):
        assert sanitize_number("not a number") is None


class TestSanitizeRecord:
    def test_sanitizes_all_fields(self):
        record = {
            "product_name": '<script>alert("xss")</script>Fresh Pork',
            "store": "E-Mart",
            "source_url": "javascript:alert(1)",
            "price": 12500,
            "original_price": -100,
        }
        result = sanitize_record(record)
        assert "<script>" not in result["product_name"]
        assert result["source_url"] == ""
        assert result["price"] == 12500.0
        assert result["original_price"] is None

    def test_preserves_unknown_fields(self):
        record = {"custom_field": "value", "product_name": "test"}
        result = sanitize_record(record)
        assert result["custom_field"] == "value"
