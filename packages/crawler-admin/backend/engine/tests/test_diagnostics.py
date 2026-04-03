"""
DiagnosticsEngine 테스트 (TDD).

실패 원인 자동 분류, 심각도 판정, 추천 대응 생성을 검증한다.
"""

import pytest

from core.models import (
    CrawlResult, CrawlStatus, StrategyFailure, ErrorType, DiagnosisReport,
)
from engine.diagnostics import DiagnosticsEngine


@pytest.fixture
def diag():
    return DiagnosticsEngine()


class TestDiagnosticsEngine:

    def test_analyze_ip_banned(self, diag):
        """IP 차단이 가장 심각한 에러인 경우."""
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="이마트",
            errors=[
                StrategyFailure(strategy_name="requests", error_type=ErrorType.HTTP_ERROR, error_msg="403"),
                StrategyFailure(strategy_name="selenium", error_type=ErrorType.IP_BANNED, error_msg="blocked"),
            ],
        )
        report = diag.analyze(result)

        assert report.crawler_name == "이마트"
        assert report.overall_error_type == ErrorType.IP_BANNED
        assert "프록시" in report.recommendation
        assert len(report.failures) == 2

    def test_analyze_captcha(self, diag):
        """CAPTCHA 감지."""
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="코스트코",
            errors=[
                StrategyFailure(strategy_name="requests", error_type=ErrorType.CAPTCHA_DETECTED, error_msg="captcha"),
            ],
        )
        report = diag.analyze(result)

        assert report.overall_error_type == ErrorType.CAPTCHA_DETECTED
        assert "CAPTCHA" in report.recommendation

    def test_analyze_dom_changed(self, diag):
        """DOM 구조 변경."""
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="홈플러스",
            errors=[
                StrategyFailure(strategy_name="selenium", error_type=ErrorType.DOM_CHANGED, error_msg="selector not found"),
            ],
        )
        report = diag.analyze(result)

        assert report.overall_error_type == ErrorType.DOM_CHANGED
        assert "셀렉터" in report.recommendation

    def test_analyze_empty_errors(self, diag):
        """에러 리스트가 비어 있을 때."""
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="test",
            errors=[],
        )
        report = diag.analyze(result)

        assert report.overall_error_type == ErrorType.UNKNOWN
        assert "에러 정보가 없습니다" in report.summary

    def test_analyze_severity_ordering(self, diag):
        """IP_BANNED > JS_CHALLENGE > HTTP_ERROR 심각도 순서."""
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="test",
            errors=[
                StrategyFailure(strategy_name="a", error_type=ErrorType.HTTP_ERROR, error_msg="err"),
                StrategyFailure(strategy_name="b", error_type=ErrorType.JS_CHALLENGE, error_msg="err"),
                StrategyFailure(strategy_name="c", error_type=ErrorType.IP_BANNED, error_msg="err"),
            ],
        )
        report = diag.analyze(result)

        # IP_BANNED이 가장 심각
        assert report.overall_error_type == ErrorType.IP_BANNED

    def test_summary_contains_crawler_name(self, diag):
        """요약에 크롤러 이름이 포함된다."""
        result = CrawlResult(
            status=CrawlStatus.FAILED,
            crawler_name="롯데마트",
            errors=[
                StrategyFailure(strategy_name="requests", error_type=ErrorType.TIMEOUT, error_msg="timeout"),
            ],
        )
        report = diag.analyze(result)

        assert "롯데마트" in report.summary

    def test_analyze_failure_individual(self, diag):
        """개별 실패 분석."""
        failure = StrategyFailure(
            strategy_name="selenium",
            error_type=ErrorType.CAPTCHA_DETECTED,
            error_msg="captcha found",
        )
        analysis = diag.analyze_failure(failure)

        assert analysis["error_type"] == "captcha_detected"
        assert analysis["severity"] == 9
        assert "CAPTCHA" in analysis["description"]
