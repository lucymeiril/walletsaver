"""Health check endpoint tests."""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHealthCheck:
    """Enhanced /api/health 엔드포인트 테스트."""

    @pytest.fixture
    def client_no_storage(self):
        """storage=None인 앱 클라이언트 — DB 연결 무시."""
        from fastapi.testclient import TestClient
        from api.app import create_app
        app = create_app()
        app.state.storage = None  # 강제로 storage 제거
        return TestClient(app)

    def test_health_degraded_no_db(self, client_no_storage):
        """DB 미연결 시 degraded 상태."""
        resp = client_no_storage.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["version"] == "0.1.0"
        assert "checks" in data
        assert data["checks"]["db"]["status"] == "disconnected"

    def test_health_has_memory_check(self, client_no_storage):
        """메모리 체크가 포함되어 있다."""
        resp = client_no_storage.get("/api/health")
        data = resp.json()
        assert "memory" in data["checks"]
        mem = data["checks"]["memory"]
        assert mem["status"] in ("ok", "warning", "critical", "unknown")

    def test_health_has_playwright_check(self, client_no_storage):
        """Playwright 브라우저 풀 체크가 포함되어 있다."""
        resp = client_no_storage.get("/api/health")
        data = resp.json()
        assert "playwright" in data["checks"]

    @patch("psutil.Process")
    def test_health_memory_warning(self, mock_process_cls, client_no_storage):
        """메모리 600MB 시 warning 상태."""
        mock_proc = MagicMock()
        mock_mem = MagicMock()
        mock_mem.rss = 600 * 1024 * 1024  # 600 MB
        mock_proc.memory_info.return_value = mock_mem
        mock_process_cls.return_value = mock_proc

        resp = client_no_storage.get("/api/health")
        data = resp.json()
        assert data["checks"]["memory"]["status"] == "warning"

    def test_health_structure(self, client_no_storage):
        """응답 구조 확인: status, version, checks."""
        resp = client_no_storage.get("/api/health")
        data = resp.json()
        assert "status" in data
        assert "version" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)


class TestHealthWithStorage:
    """Storage가 있는 경우의 health check."""

    @pytest.fixture
    def client_with_mock_storage(self):
        from fastapi.testclient import TestClient
        from api.app import create_app

        mock_storage = MagicMock()
        mock_storage.search_products.return_value = []
        # circuit_state를 MagicMock이 아닌 실제 문자열로 설정
        mock_storage.circuit_state = "closed"
        app = create_app(storage=mock_storage)
        return TestClient(app)

    def test_health_with_storage_has_db_check(self, client_with_mock_storage):
        """Storage가 있으면 DB 체크가 실행된다."""
        resp = client_with_mock_storage.get("/api/health")
        data = resp.json()
        assert "db" in data["checks"]
        assert data["checks"]["db"]["status"] == "ok"
