"""StorageProxy circuit breaker tests."""
import sys
import os
import time
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestStorageProxy:
    """StorageProxy 서킷브레이커 동작 테스트."""

    @pytest.fixture(autouse=True)
    def reset_circuit(self):
        """각 테스트 전에 서킷브레이커 상태 초기화."""
        import api.utils.storage_proxy as sp
        sp._db_circuit._state = sp._db_circuit.CLOSED
        sp._db_circuit._failure_count = 0
        sp._db_circuit._last_failure_time = 0
        yield

    def _make_proxy(self, storage=None):
        from api.utils.storage_proxy import StorageProxy
        if storage is None:
            storage = MagicMock()
        return StorageProxy(storage)

    def test_proxy_passes_through_on_success(self):
        """정상 호출 시 underlying storage 결과를 그대로 반환."""
        mock_storage = MagicMock()
        mock_storage.search_products.return_value = [{"name": "삼겹살"}]
        proxy = self._make_proxy(mock_storage)

        result = proxy.search_products("삼겹살")

        assert result == [{"name": "삼겹살"}]
        mock_storage.search_products.assert_called_once_with("삼겹살")

    def test_proxy_records_failure_and_opens(self):
        """3회 연속 실패 시 서킷 OPEN → 4번째 호출은 [] 반환."""
        mock_storage = MagicMock()
        mock_storage.search_products.side_effect = Exception("DB down")
        proxy = self._make_proxy(mock_storage)

        # 3회 실패
        for _ in range(3):
            try:
                proxy.search_products("")
            except Exception:
                pass

        assert proxy.circuit_state == "open"

        # 4번째 호출은 서킷 OPEN으로 바로 [] 반환
        result = proxy.search_products("")
        assert result == []

    def test_proxy_recovers_after_timeout(self):
        """서킷 OPEN → recovery timeout 경과 → 성공 시 CLOSED."""
        import api.utils.storage_proxy as sp

        mock_storage = MagicMock()
        mock_storage.search_products.side_effect = Exception("DB down")
        proxy = self._make_proxy(mock_storage)

        # 3회 실패 → OPEN
        for _ in range(3):
            try:
                proxy.search_products("")
            except Exception:
                pass

        assert proxy.circuit_state == "open"

        # recovery timeout 경과 시뮬레이션
        sp._db_circuit._last_failure_time = time.time() - 60

        # 이제 half_open → 성공하면 CLOSED
        mock_storage.search_products.side_effect = None
        mock_storage.search_products.return_value = [{"name": "복구"}]

        result = proxy.search_products("")
        assert result == [{"name": "복구"}]
        assert proxy.circuit_state == "closed"

    def test_proxy_bool_truthiness(self):
        """if storage: 체크가 underlying이 Not None이면 True."""
        proxy = self._make_proxy(MagicMock())
        assert bool(proxy) is True

        from api.utils.storage_proxy import StorageProxy
        proxy_none = StorageProxy(None)
        assert bool(proxy_none) is False

    def test_circuit_state_exposed(self):
        """circuit_state 프로퍼티가 현재 상태를 반환한다."""
        proxy = self._make_proxy(MagicMock())
        assert proxy.circuit_state == "closed"

        import api.utils.storage_proxy as sp
        sp._db_circuit._state = sp._db_circuit.OPEN
        sp._db_circuit._last_failure_time = time.time()
        assert proxy.circuit_state == "open"

    def test_proxy_non_callable_attr(self):
        """호출 불가능한 속성은 그대로 전달."""
        mock_storage = MagicMock()
        mock_storage.some_value = 42
        proxy = self._make_proxy(mock_storage)
        assert proxy.some_value == 42
