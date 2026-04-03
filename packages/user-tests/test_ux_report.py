"""
UX 보고서 테스트 — WalletSavior (지갑 지키미)
UX 평가 보고서 생성 및 내보내기 기능을 검증합니다.
"""

import json
import pytest
from ux_report import (
    UXReport, PageAnalysis, Recommendation, Priority,
    create_walletsavior_ux_report,
)


class TestUXReport:
    """UX 보고서 전체 검증"""

    @pytest.fixture
    def report(self):
        return create_walletsavior_ux_report()

    def test_report_validates(self, report):
        """보고서가 유효성 검증을 통과하는지 확인"""
        assert report.validate() is True

    def test_report_has_all_pages(self, report):
        """6개 페이지 분석이 모두 포함되어 있는지 확인"""
        assert len(report.pages) == 6

    def test_report_average_score(self, report):
        """평균 점수가 합리적 범위인지 확인"""
        avg = report.average_score
        assert 1.0 <= avg <= 10.0

    def test_report_has_recommendations(self, report):
        """권고 사항이 존재하는지 확인"""
        recs = report.all_recommendations
        assert len(recs) >= 10, "권고 사항이 10개 미만"

    def test_report_has_critical_recommendations(self, report):
        """P0 긴급 권고가 존재하는지 확인"""
        critical = report.critical_recommendations
        assert len(critical) >= 1

    def test_report_has_high_recommendations(self, report):
        """P1 높은 우선순위 권고가 존재하는지 확인"""
        high = report.high_recommendations
        assert len(high) >= 1


class TestPageAnalysis:
    """페이지 분석 테스트"""

    @pytest.fixture
    def report(self):
        return create_walletsavior_ux_report()

    @pytest.mark.parametrize("idx", range(6))
    def test_page_score_in_range(self, report, idx):
        """각 페이지 점수가 1~10 범위인지 확인"""
        page = report.pages[idx]
        assert 1 <= page.score <= 10, f"{page.page}: 점수 {page.score} 범위 밖"

    @pytest.mark.parametrize("idx", range(6))
    def test_page_has_strengths(self, report, idx):
        """각 페이지에 강점이 있는지 확인"""
        page = report.pages[idx]
        assert len(page.strengths) >= 2, f"{page.page}: 강점이 2개 미만"

    @pytest.mark.parametrize("idx", range(6))
    def test_page_has_weaknesses(self, report, idx):
        """각 페이지에 약점이 있는지 확인"""
        page = report.pages[idx]
        assert len(page.weaknesses) >= 2, f"{page.page}: 약점이 2개 미만"

    @pytest.mark.parametrize("idx", range(6))
    def test_page_validates(self, report, idx):
        """각 페이지 분석이 유효한지 확인"""
        page = report.pages[idx]
        assert page.validate() is True


class TestReportExport:
    """보고서 내보내기 테스트"""

    @pytest.fixture
    def report(self):
        return create_walletsavior_ux_report()

    def test_json_export_valid(self, report):
        """JSON 내보내기가 유효한 JSON인지 확인"""
        json_str = report.to_json()
        data = json.loads(json_str)
        assert isinstance(data, dict)

    def test_json_export_has_pages(self, report):
        """JSON 내보내기에 페이지 데이터가 포함되어 있는지 확인"""
        data = json.loads(report.to_json())
        assert "pages" in data
        assert len(data["pages"]) == 6

    def test_json_export_has_scores(self, report):
        """JSON 내보내기에 점수가 포함되어 있는지 확인"""
        data = json.loads(report.to_json())
        assert "average_score" in data
        for page in data["pages"]:
            assert "score" in page

    def test_json_export_korean_text(self, report):
        """JSON 내보내기에 한국어 텍스트가 포함되어 있는지 확인"""
        json_str = report.to_json()
        assert "지갑" in json_str  # 한국어 포함 확인

    def test_text_export_not_empty(self, report):
        """텍스트 보고서가 비어있지 않은지 확인"""
        text = report.to_text()
        assert len(text) > 100

    def test_text_export_has_sections(self, report):
        """텍스트 보고서에 섹션이 포함되어 있는지 확인"""
        text = report.to_text()
        assert "강점" in text
        assert "약점" in text
        assert "평균 점수" in text

    def test_text_export_has_all_pages(self, report):
        """텍스트 보고서에 모든 페이지가 포함되어 있는지 확인"""
        text = report.to_text()
        assert "Home" in text
        assert "Hotdeal" in text
        assert "Price" in text

    def test_text_export_has_summary(self, report):
        """텍스트 보고서에 종합 요약이 있는지 확인"""
        text = report.to_text()
        assert "종합 요약" in text


class TestRecommendation:
    """권고 사항 테스트"""

    def test_recommendation_validation(self):
        """권고 사항 유효성 검증"""
        rec = Recommendation(
            id="TEST-01", title="테스트 권고",
            description="테스트 설명",
            priority=Priority.P1_HIGH,
            page="Home", category="테스트",
        )
        assert rec.validate() is True

    def test_recommendation_invalid(self):
        """빈 권고 사항은 유효하지 않음"""
        rec = Recommendation(
            id="", title="", description="",
            priority=Priority.P1_HIGH,
            page="", category="",
        )
        assert rec.validate() is False

    def test_priority_ordering(self):
        """우선순위 순서 확인"""
        assert Priority.P0_CRITICAL < Priority.P1_HIGH
        assert Priority.P1_HIGH < Priority.P2_MEDIUM
        assert Priority.P2_MEDIUM < Priority.P3_NICE_TO_HAVE
