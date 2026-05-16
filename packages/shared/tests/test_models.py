"""
core.models 테스트 (TDD).

Pydantic 모델의 생성, 유효성 검증, 직렬화를 검증한다.
"""

import pytest
from datetime import datetime

from shared.core.models import (
    CrawlerInfo,
    CrawlerGroup,
    CrawlRequest,
    CrawlResult,
    CrawlStatus,
    StrategyFailure,
    ErrorType,
    DiagnosisReport,
    Event,
)


class TestCrawlerInfo:

    def test_create_with_required_fields(self):
        info = CrawlerInfo(name="이마트", group=CrawlerGroup.MART)
        assert info.name == "이마트"
        assert info.group == CrawlerGroup.MART
        assert info.version == "1.0.0"  # 기본값
        assert info.strategies == []

    def test_create_with_all_fields(self):
        info = CrawlerInfo(
            name="쿠팡",
            version="2.0.0",
            group=CrawlerGroup.MART,
            description="온라인 리테일 가격 수집",
            target_url="https://www.coupang.com",
            strategies=["requests"],
            schedule="0 9 * * *",
        )
        assert info.target_url == "https://www.coupang.com"
        assert info.schedule == "0 9 * * *"

    def test_serialization(self):
        info = CrawlerInfo(name="테스트", group=CrawlerGroup.HOTDEAL)
        data = info.model_dump()
        assert data["name"] == "테스트"
        assert data["group"] == "hotdeals"


class TestCrawlResult:

    def test_success_result(self, sample_crawl_result_success):
        result = sample_crawl_result_success
        assert result.status == CrawlStatus.SUCCESS
        assert result.items_count == 5
        assert result.strategy_used == "requests"
        assert len(result.items) == 5

    def test_failed_result(self, sample_crawl_result_failed):
        result = sample_crawl_result_failed
        assert result.status == CrawlStatus.FAILED
        assert len(result.errors) == 2
        assert result.errors[0].error_type == ErrorType.HTTP_ERROR
        assert result.errors[1].error_type == ErrorType.CAPTCHA_DETECTED

    def test_default_values(self):
        result = CrawlResult(status=CrawlStatus.PENDING, crawler_name="test")
        assert result.items_count == 0
        assert result.items == []
        assert result.errors == []
        assert result.strategy_used is None
        assert isinstance(result.started_at, datetime)


class TestStrategyFailure:

    def test_create(self):
        failure = StrategyFailure(
            strategy_name="selenium",
            error_type=ErrorType.CAPTCHA_DETECTED,
            error_msg="CAPTCHA detected",
            status_code=403,
        )
        assert failure.strategy_name == "selenium"
        assert failure.status_code == 403


class TestDiagnosisReport:

    def test_create(self):
        report = DiagnosisReport(
            crawler_name="이마트",
            overall_error_type=ErrorType.IP_BANNED,
            summary="IP가 차단된 것으로 보입니다.",
            failures=[
                StrategyFailure(
                    strategy_name="requests",
                    error_type=ErrorType.IP_BANNED,
                    error_msg="403 Forbidden",
                ),
            ],
            recommendation="프록시를 교체하거나 요청 간격을 늘리세요.",
        )
        assert report.overall_error_type == ErrorType.IP_BANNED
        assert len(report.failures) == 1
        assert "프록시" in report.recommendation


class TestEvent:

    def test_create(self):
        event = Event(
            event_type="crawl.completed",
            data={"crawler": "이마트", "items": 10},
            source="engine",
        )
        assert event.event_type == "crawl.completed"
        assert event.data["items"] == 10
        assert event.source == "engine"
        assert isinstance(event.timestamp, datetime)

    def test_default_values(self):
        event = Event(event_type="test")
        assert event.data == {}
        assert event.source == ""


class TestCrawlRequest:

    def test_minimal(self):
        req = CrawlRequest(crawler_name="이마트")
        assert req.crawler_name == "이마트"
        assert req.url is None
        assert req.force_strategy is None

    def test_with_strategy(self):
        req = CrawlRequest(
            crawler_name="코스트코",
            url="https://costco.co.kr",
            force_strategy="playwright",
        )
        assert req.force_strategy == "playwright"
