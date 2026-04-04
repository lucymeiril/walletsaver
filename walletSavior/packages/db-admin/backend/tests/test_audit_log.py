"""Audit logging tests."""
import pytest
from services.audit import _safe_json


class TestSafeJson:
    def test_none(self):
        assert _safe_json(None) is None

    def test_primitives(self):
        assert _safe_json("hello") == "hello"
        assert _safe_json(42) == 42
        assert _safe_json(3.14) == 3.14
        assert _safe_json(True) is True

    def test_small_dict(self):
        d = {"a": 1, "b": 2}
        assert _safe_json(d) == d

    def test_large_dict_truncated(self):
        d = {"key": "x" * 15_000}
        result = _safe_json(d)
        assert result["_truncated"] is True
        assert "preview" in result

    def test_small_list(self):
        lst = [1, 2, 3]
        assert _safe_json(lst) == lst

    def test_large_list_truncated(self):
        lst = list(range(200))
        result = _safe_json(lst)
        assert result["_truncated"] is True
        assert result["count"] == 200
        assert len(result["sample"]) == 5

    def test_non_serializable(self):
        result = _safe_json(object())
        assert isinstance(result, str)
