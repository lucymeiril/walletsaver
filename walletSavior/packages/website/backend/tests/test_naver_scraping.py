"""Naver scraping recovery tests — circuit breaker, retry, browser pool."""
import sys
import os
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestRetryLogic:
    """_search_with_retry 재시도 로직 테스트."""

    @pytest.fixture(autouse=True)
    def reset_circuit(self):
        """각 테스트 전에 서킷브레이커 상태 초기화."""
        from api.routes.naver_local import _naver_circuit
        _naver_circuit._state = _naver_circuit.CLOSED
        _naver_circuit._failure_count = 0
        _naver_circuit._last_failure_time = 0
        yield

    @patch("api.routes.naver_local._search_via_playwright_sync")
    def test_retry_succeeds_on_second_attempt(self, mock_search):
        """첫 번째 실패 후 두 번째에 성공하면 결과를 반환한다."""
        from api.routes.naver_local import _search_with_retry, _naver_circuit

        mock_search.side_effect = [
            Exception("timeout"),
            [{"name": "테스트 맛집"}],
        ]

        with patch("api.routes.naver_local.time.sleep"):
            result = _search_with_retry("맛집", 37.5, 127.0, 10)

        assert len(result) == 1
        assert result[0]["name"] == "테스트 맛집"
        assert mock_search.call_count == 2
        assert _naver_circuit.state == "closed"

    @patch("api.routes.naver_local._search_via_playwright_sync")
    def test_retry_exhausted_returns_empty(self, mock_search):
        """3회 모두 실패하면 빈 리스트 반환 + 서킷 실패 기록."""
        from api.routes.naver_local import _search_with_retry, _naver_circuit

        mock_search.side_effect = Exception("persistent error")

        with patch("api.routes.naver_local.time.sleep"):
            result = _search_with_retry("맛집", 37.5, 127.0, 10)

        assert result == []
        assert mock_search.call_count == 3
        assert _naver_circuit._failure_count >= 1

    @patch("api.routes.naver_local._search_via_playwright_sync")
    def test_circuit_breaker_opens_after_threshold(self, mock_search):
        """5회 연속 실패 시 서킷이 OPEN으로 전환된다."""
        from api.routes.naver_local import _search_with_retry, _naver_circuit

        mock_search.side_effect = Exception("fail")

        with patch("api.routes.naver_local.time.sleep"):
            for _ in range(5):
                _search_with_retry("맛집", 37.5, 127.0, 10)

        assert _naver_circuit.state == "open"

    @patch("api.routes.naver_local._search_via_playwright_sync")
    def test_circuit_breaker_rejects_when_open(self, mock_search):
        """서킷이 OPEN이면 Playwright 호출 없이 [] 반환."""
        from api.routes.naver_local import _search_with_retry, _naver_circuit

        # 서킷을 OPEN으로 수동 설정
        _naver_circuit._state = _naver_circuit.OPEN
        _naver_circuit._last_failure_time = time.time()

        result = _search_with_retry("맛집", 37.5, 127.0, 10)

        assert result == []
        mock_search.assert_not_called()

    @patch("api.routes.naver_local._search_via_playwright_sync")
    def test_circuit_breaker_recovers_after_timeout(self, mock_search):
        """서킷 OPEN → recovery timeout 경과 → 성공 시 CLOSED로 복귀."""
        from api.routes.naver_local import _search_with_retry, _naver_circuit

        # 서킷을 OPEN으로 설정하되, 충분히 오래된 시간으로 설정
        _naver_circuit._state = _naver_circuit.OPEN
        _naver_circuit._failure_count = 5
        _naver_circuit._last_failure_time = time.time() - 200  # 120s 초과

        mock_search.return_value = [{"name": "복구된 맛집"}]

        result = _search_with_retry("맛집", 37.5, 127.0, 10)

        assert len(result) == 1
        assert _naver_circuit.state == "closed"


class TestBrowserPool:
    """_BrowserPool crash recovery 및 is_healthy 테스트."""

    def test_browser_pool_is_healthy_no_browser(self):
        """브라우저 미실행 시 is_healthy() → True (lazy-start)."""
        from api.routes.naver_local import _BrowserPool
        pool = _BrowserPool(idle_timeout=10)
        assert pool.is_healthy() is True

    def test_browser_pool_is_healthy_with_mock(self):
        """연결된 브라우저가 있으면 is_healthy() → True."""
        from api.routes.naver_local import _BrowserPool
        pool = _BrowserPool(idle_timeout=10)

        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = True
        pool._browser = mock_browser

        assert pool.is_healthy() is True

    def test_browser_pool_unhealthy_when_disconnected(self):
        """브라우저가 연결 끊어지면 is_healthy() → False."""
        from api.routes.naver_local import _BrowserPool
        pool = _BrowserPool(idle_timeout=10)

        mock_browser = MagicMock()
        mock_browser.is_connected.return_value = False
        pool._browser = mock_browser

        assert pool.is_healthy() is False

    def test_browser_pool_unhealthy_when_is_connected_crashes(self):
        """is_connected()가 예외를 던지면 is_healthy() → False."""
        from api.routes.naver_local import _BrowserPool
        pool = _BrowserPool(idle_timeout=10)

        mock_browser = MagicMock()
        mock_browser.is_connected.side_effect = Exception("browser dead")
        pool._browser = mock_browser

        assert pool.is_healthy() is False

    def test_force_cleanup(self):
        """force_cleanup()이 타이머를 취소하고 리소스를 정리한다."""
        from api.routes.naver_local import _BrowserPool
        pool = _BrowserPool(idle_timeout=10)

        mock_timer = MagicMock()
        pool._cleanup_timer = mock_timer
        mock_browser = MagicMock()
        pool._browser = mock_browser

        pool.force_cleanup()

        mock_timer.cancel.assert_called_once()
        mock_browser.close.assert_called_once()
        assert pool._browser is None
        assert pool._cleanup_timer is None


class TestBoundedCache:
    """TTLCache 기반 bounded cache 테스트."""

    def test_cache_get_set(self):
        """캐시 get/set이 정상 동작한다."""
        from api.routes.naver_local import _cache_get, _cache_set, _geo_area_cache
        _geo_area_cache.clear()

        _cache_set("test_key", {"data": "value"})
        result = _cache_get("test_key")
        assert result == {"data": "value"}

    def test_cache_miss(self):
        """없는 키를 조회하면 None 반환."""
        from api.routes.naver_local import _cache_get, _geo_area_cache
        _geo_area_cache.clear()

        result = _cache_get("nonexistent")
        assert result is None
