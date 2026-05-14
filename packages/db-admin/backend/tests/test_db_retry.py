"""Tests for retry logic on transient DB errors."""
import pytest
from sqlalchemy.exc import OperationalError, IntegrityError

from services.db_retry import retry_on_db_error, is_retryable, execute_with_retry


class TestIsRetryable:
    def test_database_locked(self):
        exc = OperationalError("database is locked", None, None)
        assert is_retryable(exc) is True

    def test_database_busy(self):
        exc = OperationalError("database is busy", None, None)
        assert is_retryable(exc) is True

    def test_non_retryable_operational_error(self):
        exc = OperationalError("no such table: foo", None, None)
        assert is_retryable(exc) is False

    def test_non_operational_error(self):
        exc = ValueError("something else")
        assert is_retryable(exc) is False

    def test_integrity_error_not_retryable(self):
        exc = IntegrityError("UNIQUE constraint failed", None, None)
        assert is_retryable(exc) is False


class TestRetryOnDbError:
    def test_succeeds_after_transient_error(self):
        """Retry decorator succeeds on second attempt after SQLITE_BUSY."""
        call_count = 0

        @retry_on_db_error(max_retries=3, base_delay=0.01)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OperationalError("database is locked", None, None)
            return "ok"

        assert flaky() == "ok"
        assert call_count == 2

    def test_raises_after_max_attempts(self):
        """Retry decorator raises after exhausting retries."""
        @retry_on_db_error(max_retries=2, base_delay=0.01)
        def always_fail():
            raise OperationalError("database is locked", None, None)

        with pytest.raises(OperationalError):
            always_fail()

    def test_non_retryable_error_not_retried(self):
        """Non-transient errors raise immediately."""
        call_count = 0

        @retry_on_db_error(max_retries=3, base_delay=0.01)
        def integrity_error():
            nonlocal call_count
            call_count += 1
            raise OperationalError("no such table: foo", None, None)

        with pytest.raises(OperationalError):
            integrity_error()
        assert call_count == 1

    def test_no_error_no_retry(self):
        """Function succeeds on first try — no retry needed."""
        @retry_on_db_error(max_retries=3, base_delay=0.01)
        def success():
            return 42

        assert success() == 42

    def test_preserves_function_name(self):
        """Decorated function preserves __name__."""
        @retry_on_db_error()
        def my_func():
            pass
        assert my_func.__name__ == "my_func"


class TestExecuteWithRetry:
    def test_succeeds_on_first_try(self):
        """execute_with_retry succeeds when no error."""
        from unittest.mock import MagicMock
        session = MagicMock()
        session.execute.return_value = "result"
        result = execute_with_retry(session, "SELECT 1", base_delay=0.01)
        assert result == "result"

    def test_retries_on_transient_error(self):
        """execute_with_retry retries transient errors."""
        from unittest.mock import MagicMock
        session = MagicMock()
        session.execute.side_effect = [
            OperationalError("database is locked", None, None),
            "result",
        ]
        result = execute_with_retry(session, "SELECT 1", base_delay=0.01)
        assert result == "result"
        assert session.execute.call_count == 2
