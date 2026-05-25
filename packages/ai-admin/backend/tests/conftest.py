"""2026-05-25 보류: AI 라이브 파이프라인 feature flag 설정.

기존 회귀 테스트들은 flag=true로 실행되어야 한다.
test_live_ai_flag.py는 flag를 명시적으로 override한다.
"""
import os
import sys

import pytest


def pytest_configure(config):
    """pytest 시작 시 가장 먼저 호출되는 hook - 환경변수를 설정한다."""
    os.environ["WALLETSAVIOR_LIVE_AI_ENABLED"] = "true"


@pytest.fixture(scope="session", autouse=True)
def enable_ai_pipeline_for_tests():
    """기존 회귀 테스트들이 깨지지 않도록 flag=true 설정."""
    from services import ai_ingestion
    ai_ingestion.WALLETSAVIOR_LIVE_AI_ENABLED = True
    
    try:
        from api.routes import ingest as ingest_routes
        ingest_routes.WALLETSAVIOR_LIVE_AI_ENABLED = True
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def reset_ai_flag_for_each_test(monkeypatch: pytest.MonkeyPatch):
    """각 test 함수마다 flag를 다시 설정하여 monkeypatch가 reset되어도 유지되도록 한다."""
    from services import ai_ingestion
    monkeypatch.setattr(ai_ingestion, "WALLETSAVIOR_LIVE_AI_ENABLED", True)
    
    try:
        from api.routes import ingest as ingest_routes
        monkeypatch.setattr(ingest_routes, "WALLETSAVIOR_LIVE_AI_ENABLED", True)
    except ImportError:
        pass





