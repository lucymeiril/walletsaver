"""LIKE pattern escape tests."""
from api.security import escape_like


class TestEscapeLike:
    def test_percent_escaped(self):
        assert escape_like("100%") == "100\\%"

    def test_underscore_escaped(self):
        assert escape_like("a_b") == "a\\_b"

    def test_backslash_escaped(self):
        assert escape_like("a\\b") == "a\\\\b"

    def test_combined(self):
        assert escape_like("%_\\") == "\\%\\_\\\\"

    def test_normal_string_unchanged(self):
        assert escape_like("삼겹살") == "삼겹살"

    def test_empty_string(self):
        assert escape_like("") == ""

    def test_all_percents(self):
        assert escape_like("%%%") == "\\%\\%\\%"
