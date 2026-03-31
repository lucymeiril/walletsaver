"""
휴리스틱 평가 테스트 — WalletSavior (지갑 지키미)
닐슨 10대 사용성 휴리스틱 평가가 올바르게 수행되었는지 검증합니다.
"""

import pytest
from heuristics import (
    HeuristicItem, HeuristicEvaluation, Finding, Severity,
    create_walletsavior_evaluation,
)


class TestHeuristicEvaluation:
    """휴리스틱 평가 전체 검증"""

    @pytest.fixture
    def evaluation(self):
        return create_walletsavior_evaluation()

    def test_evaluation_validates(self, evaluation):
        """평가가 유효성 검증을 통과하는지 확인"""
        assert evaluation.validate() is True

    def test_all_ten_heuristics(self, evaluation):
        """10개 휴리스틱이 모두 평가되었는지 확인"""
        assert len(evaluation.items) == 10

    def test_heuristic_ids_h1_to_h10(self, evaluation):
        """H1~H10 ID가 모두 존재하는지 확인"""
        ids = {item.id for item in evaluation.items}
        expected = {f"H{i}" for i in range(1, 11)}
        assert ids == expected

    @pytest.mark.parametrize("idx", range(10))
    def test_each_heuristic_has_korean_name(self, evaluation, idx):
        """각 휴리스틱에 한국어 이름이 있는지 확인"""
        item = evaluation.items[idx]
        assert item.name_ko, f"{item.id}: 한국어 이름 없음"
        assert any('\uac00' <= c <= '\ud7a3' for c in item.name_ko)

    @pytest.mark.parametrize("idx", range(10))
    def test_each_heuristic_score_in_range(self, evaluation, idx):
        """각 점수가 1~5 범위인지 확인"""
        item = evaluation.items[idx]
        assert 1 <= item.score <= 5, f"{item.id}: 점수 {item.score}이 범위 밖"

    @pytest.mark.parametrize("idx", range(10))
    def test_each_heuristic_has_recommendations(self, evaluation, idx):
        """각 휴리스틱에 개선 권고가 있는지 확인"""
        item = evaluation.items[idx]
        assert len(item.recommendations) >= 1, f"{item.id}: 권고 사항 없음"

    def test_average_score_reasonable(self, evaluation):
        """평균 점수가 합리적 범위인지 확인"""
        avg = evaluation.average_score
        assert 2.0 <= avg <= 5.0, f"평균 점수 {avg}이 비합리적"

    def test_has_findings(self, evaluation):
        """발견 사항이 존재하는지 확인"""
        assert len(evaluation.all_findings) >= 5

    def test_findings_validate(self, evaluation):
        """모든 발견 사항이 유효한지 확인"""
        for finding in evaluation.all_findings:
            assert finding.validate(), f"유효하지 않은 발견 사항: {finding.description[:30]}"

    def test_has_critical_findings(self, evaluation):
        """주요/치명적 발견 사항이 있는지 확인"""
        critical = evaluation.critical_findings
        assert len(critical) >= 1, "주요 이상 발견 사항이 없음"

    def test_get_item_by_id(self, evaluation):
        """ID로 휴리스틱 항목 조회"""
        item = evaluation.get_item_by_id("H1")
        assert item is not None
        assert item.name == "Visibility of System Status"

    def test_to_dict(self, evaluation):
        """딕셔너리 변환 검증"""
        d = evaluation.to_dict()
        assert "evaluator" in d
        assert "average_score" in d
        assert len(d["items"]) == 10
        assert "total_findings" in d


class TestFinding:
    """개별 발견 사항 테스트"""

    def test_finding_validation(self):
        """발견 사항 유효성 검증"""
        finding = Finding(
            description="테스트 발견 사항",
            page="Home",
            severity=Severity.MINOR,
            recommendation="테스트 권고",
        )
        assert finding.validate() is True

    def test_empty_finding_invalid(self):
        """빈 발견 사항은 유효하지 않음"""
        finding = Finding(description="", page="", severity=Severity.MINOR, recommendation="")
        assert finding.validate() is False
