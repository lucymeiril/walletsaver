"""SSE disconnect detection tests."""
import sys
import os
import json
import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSSEDisconnect:
    """area-explore-stream SSE 엔드포인트 disconnect/timeout 테스트."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from api.app import create_app
        app = create_app()
        return TestClient(app)

    @patch("api.routes.naver_local._search_single_category_sync")
    @patch("api.routes.naver_local._geocode_sync")
    def test_sse_normal_flow(self, mock_geocode, mock_search, client):
        """정상 흐름: 모든 카테고리 결과 + done 이벤트."""
        mock_geocode.return_value = {"lat": 37.5, "lng": 127.0}
        mock_search.side_effect = [
            {"name": "주유소", "icon": "⛽", "count": 2, "items": [{"name": "a"}, {"name": "b"}]},
            {"name": "음식", "icon": "🍽️", "count": 1, "items": [{"name": "c"}]},
        ]

        resp = client.get(
            "/api/local/area-explore-stream?location_name=강남&categories=주유소,음식"
        )
        assert resp.status_code == 200

        events = [
            line.replace("data: ", "")
            for line in resp.text.strip().split("\n")
            if line.startswith("data: ")
        ]
        assert len(events) >= 2  # 최소 2개 카테고리 결과

        # 마지막 이벤트는 done
        last = json.loads(events[-1])
        assert last.get("done") is True

    @patch("api.routes.naver_local._search_single_category_sync")
    @patch("api.routes.naver_local._geocode_sync")
    def test_sse_partial_failure(self, mock_geocode, mock_search, client):
        """2번째 카테고리 실패해도 나머지 카테고리는 성공."""
        mock_geocode.return_value = {"lat": 37.5, "lng": 127.0}
        mock_search.side_effect = [
            {"name": "주유소", "icon": "⛽", "count": 1, "items": [{"name": "a"}]},
            Exception("검색 실패"),
            {"name": "카페", "icon": "☕", "count": 1, "items": [{"name": "b"}]},
        ]

        resp = client.get(
            "/api/local/area-explore-stream?location_name=강남&categories=주유소,음식,카페"
        )
        assert resp.status_code == 200

        events = [
            line.replace("data: ", "")
            for line in resp.text.strip().split("\n")
            if line.startswith("data: ")
        ]

        # 에러 이벤트 확인
        parsed = [json.loads(e) for e in events if e.strip()]
        error_events = [e for e in parsed if "error" in e and e.get("error") != ""]
        assert len(error_events) >= 1

        # done 이벤트 존재
        done_events = [e for e in parsed if e.get("done") is True]
        assert len(done_events) == 1

    @patch("api.routes.naver_local._search_single_category_sync")
    @patch("api.routes.naver_local._geocode_sync")
    def test_sse_error_gen_without_location(self, mock_geocode, mock_search, client):
        """location_name과 좌표 모두 없으면 에러 이벤트."""
        resp = client.get("/api/local/area-explore-stream")
        assert resp.status_code == 200

        events = [
            line.replace("data: ", "")
            for line in resp.text.strip().split("\n")
            if line.startswith("data: ")
        ]
        assert len(events) >= 1
        parsed = json.loads(events[0])
        assert "error" in parsed
