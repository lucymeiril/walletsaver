"""
전역 pytest fixture.
모든 테스트에서 사용 가능한 공통 fixture 정의.
"""

import asyncio
import pytest

from core.events import EventBus
from core.models import (
    CrawlerInfo,
    CrawlerGroup,
    CrawlRequest,
    CrawlResult,
    CrawlStatus,
    StrategyFailure,
    ErrorType,
    Event,
)


@pytest.fixture
def event_bus():
    """깨끗한 EventBus 인스턴스."""
    bus = EventBus()
    yield bus
    bus.clear()


@pytest.fixture
def sample_crawler_info():
    """샘플 크롤러 정보."""
    return CrawlerInfo(
        name="테스트 크롤러",
        version="1.0.0",
        group=CrawlerGroup.MART,
        description="테스트용 크롤러",
        target_url="https://example.com",
        strategies=["requests", "selenium"],
    )


@pytest.fixture
def sample_crawl_request():
    """샘플 크롤링 요청."""
    return CrawlRequest(
        crawler_name="테스트 크롤러",
        url="https://example.com/products",
    )


@pytest.fixture
def sample_crawl_result_success():
    """성공한 크롤링 결과."""
    return CrawlResult(
        status=CrawlStatus.SUCCESS,
        crawler_name="테스트 크롤러",
        strategy_used="requests",
        items_count=5,
        items=[
            {"name": "사과", "price": 3000},
            {"name": "배", "price": 5000},
            {"name": "감자", "price": 2000},
            {"name": "양파", "price": 1500},
            {"name": "당근", "price": 1800},
        ],
    )


@pytest.fixture
def sample_crawl_result_failed():
    """실패한 크롤링 결과."""
    return CrawlResult(
        status=CrawlStatus.FAILED,
        crawler_name="테스트 크롤러",
        items_count=0,
        errors=[
            StrategyFailure(
                strategy_name="requests",
                error_type=ErrorType.HTTP_ERROR,
                error_msg="403 Forbidden",
                status_code=403,
            ),
            StrategyFailure(
                strategy_name="selenium",
                error_type=ErrorType.CAPTCHA_DETECTED,
                error_msg="CAPTCHA detected on page",
            ),
        ],
        error_msg="모든 전략 실패",
    )
