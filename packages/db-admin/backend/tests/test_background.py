"""Tests for safe background task wrapper."""
import logging
import pytest

from api.background import safe_task, add_safe_task


class TestSafeTask:
    def test_catches_exception(self, caplog):
        """safe_task wraps exceptions and logs them."""
        @safe_task
        def exploding_task():
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR):
            exploding_task()  # should not raise
        assert "Background task 'exploding_task' failed" in caplog.text

    def test_passes_through_on_success(self):
        """safe_task returns result on success."""
        @safe_task
        def good_task():
            return 42
        assert good_task() == 42

    def test_passes_args(self):
        """safe_task forwards arguments."""
        @safe_task
        def add(a, b):
            return a + b
        assert add(3, 4) == 7

    def test_preserves_function_name(self):
        """Decorated function preserves __name__."""
        @safe_task
        def my_task():
            pass
        assert my_task.__name__ == "my_task"

    def test_returns_none_on_error(self):
        """safe_task returns None when exception is caught."""
        @safe_task
        def fail():
            raise RuntimeError("fail")
        result = fail()
        assert result is None


class TestAddSafeTask:
    def test_adds_wrapped_task(self):
        """add_safe_task adds a wrapped task to BackgroundTasks."""
        from unittest.mock import MagicMock
        bg_tasks = MagicMock()

        def my_func(x):
            return x

        add_safe_task(bg_tasks, my_func, 42)
        bg_tasks.add_task.assert_called_once()
