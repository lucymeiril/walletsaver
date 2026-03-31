"""
반응형 디자인 테스트 — WalletSavior (지갑 지키미)
표준 브레이크포인트에서의 레이아웃 적응성을 검증합니다.
"""

import pytest
from responsive import (
    BreakpointCheck, DeviceType, LayoutCheck,
    PageResponsiveResult, ResponsiveEvaluation,
    STANDARD_BREAKPOINTS, create_walletsavior_responsive_evaluation,
)


class TestBreakpoints:
    """브레이크포인트 정의 테스트"""

    def test_standard_breakpoints_count(self):
        """8개 표준 브레이크포인트가 정의되어 있는지 확인"""
        assert len(STANDARD_BREAKPOINTS) == 8

    def test_mobile_breakpoints(self):
        """모바일 브레이크포인트 확인"""
        mobile = {w for w, d in STANDARD_BREAKPOINTS.items() if d == DeviceType.MOBILE}
        assert mobile == {360, 390, 414}

    def test_tablet_breakpoints(self):
        """태블릿 브레이크포인트 확인"""
        tablet = {w for w, d in STANDARD_BREAKPOINTS.items() if d == DeviceType.TABLET}
        assert tablet == {768, 1024}

    def test_desktop_breakpoints(self):
        """데스크톱 브레이크포인트 확인"""
        desktop = {w for w, d in STANDARD_BREAKPOINTS.items() if d == DeviceType.DESKTOP}
        assert desktop == {1280, 1440, 1920}


class TestResponsiveEvaluation:
    """반응형 평가 전체 검증"""

    @pytest.fixture
    def evaluation(self):
        return create_walletsavior_responsive_evaluation()

    def test_evaluation_validates(self, evaluation):
        """평가가 유효성 검증을 통과하는지 확인"""
        assert evaluation.validate() is True

    def test_evaluation_has_all_pages(self, evaluation):
        """6개 페이지 모두 평가되었는지 확인"""
        pages = [pr.page for pr in evaluation.page_results]
        assert len(pages) == 6
        for expected_page in ["Home", "Hotdeal", "Price", "Mart", "Local", "Community"]:
            assert expected_page in pages

    def test_evaluation_has_checks(self, evaluation):
        """검사 항목이 존재하는지 확인"""
        assert evaluation.total_checks > 0

    def test_overall_pass_rate(self, evaluation):
        """전체 통과율이 90% 이상인지 확인 (대체로 잘 되어 있음)"""
        assert evaluation.overall_pass_rate >= 90

    def test_home_page_fully_responsive(self, evaluation):
        """홈 페이지가 모든 브레이크포인트에서 통과하는지 확인"""
        home = evaluation.get_page_result("Home")
        assert home is not None
        assert home.pass_rate == 100.0

    def test_price_page_has_chart_checks(self, evaluation):
        """가격 페이지에 차트 리사이즈 검사가 포함되어 있는지 확인"""
        price = evaluation.get_page_result("Price")
        assert price is not None
        chart_checks = [c for c in price.checks if c.check_type == LayoutCheck.CHART_RESIZE]
        assert len(chart_checks) > 0

    def test_known_failures_documented(self, evaluation):
        """알려진 실패 항목이 문서화되어 있는지 확인"""
        failures = []
        for pr in evaluation.page_results:
            failures.extend(pr.get_failures())
        # 360px에서 몇 개 실패가 알려져 있음
        assert len(failures) >= 1
        for f in failures:
            assert f.details, "실패 항목에 상세 설명 필요"

    def test_evaluation_to_dict(self, evaluation):
        """딕셔너리 변환이 올바른지 확인"""
        d = evaluation.to_dict()
        assert "target" in d
        assert "total_checks" in d
        assert "pages" in d
        assert len(d["pages"]) == 6


class TestPageResponsiveResult:
    """페이지별 결과 테스트"""

    def test_pass_rate_calculation(self):
        """통과율 계산 검증"""
        result = PageResponsiveResult(page="Test", checks=[
            BreakpointCheck(360, DeviceType.MOBILE, LayoutCheck.NAVIGATION, "Test", True),
            BreakpointCheck(360, DeviceType.MOBILE, LayoutCheck.CARD_REFLOW, "Test", False, "실패"),
        ])
        assert result.pass_rate == 50.0

    def test_empty_checks_rate(self):
        """검사 없을 때 통과율 0"""
        result = PageResponsiveResult(page="Test")
        assert result.pass_rate == 0.0
