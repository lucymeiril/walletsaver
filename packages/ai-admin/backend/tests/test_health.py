"""health 엔드포인트 테스트."""
from fastapi.testclient import TestClient

from api.app import create_app


def test_health_returns_ok():
    client = TestClient(create_app())
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "ai-admin"
    assert "uptime_seconds" in body
