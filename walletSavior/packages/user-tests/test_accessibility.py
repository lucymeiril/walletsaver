"""
접근성 테스트 — WalletSavior (지갑 지키미)
WCAG 2.1 AA 기준의 접근성 체크리스트를 검증합니다.
"""

import pytest
from accessibility import (
    AccessibilityCheck, AccessibilityEvaluation, ComplianceLevel,
    ColorContrastResult, TouchTargetResult, FontSizeCheck,
    check_color_contrast, hex_to_relative_luminance, calculate_contrast_ratio,
    create_walletsavior_accessibility_evaluation,
)


class TestColorContrast:
    """색상 대비 검사 테스트"""

    def test_black_on_white_passes(self):
        """검정 on 흰색은 높은 대비율"""
        result = check_color_contrast("#000000", "#FFFFFF")
        assert result.ratio >= 4.5
        assert result.passes_aa_normal is True

    def test_white_on_white_fails(self):
        """흰색 on 흰색은 대비율 부족"""
        result = check_color_contrast("#FFFFFF", "#FFFFFF")
        assert result.ratio < 4.5
        assert result.passes_aa_normal is False

    def test_body_text_contrast(self):
        """본문 텍스트(#333 on #FFF) 대비율 AA 충족"""
        result = check_color_contrast("#333333", "#FFFFFF")
        assert result.passes_aa_normal is True
        assert result.ratio >= 4.5

    def test_discount_badge_contrast(self):
        """할인 뱃지(#FFF on #E53935) 대비율 검증"""
        result = check_color_contrast("#FFFFFF", "#E53935")
        assert result.passes_aa_large is True  # 대형 텍스트 기준 충족

    def test_relative_luminance_black(self):
        """검정 색상의 상대 휘도는 0에 가까움"""
        lum = hex_to_relative_luminance("#000000")
        assert lum == pytest.approx(0.0, abs=0.01)

    def test_relative_luminance_white(self):
        """흰색의 상대 휘도는 1에 가까움"""
        lum = hex_to_relative_luminance("#FFFFFF")
        assert lum == pytest.approx(1.0, abs=0.01)

    def test_contrast_ratio_symmetric(self):
        """대비율 계산이 순서에 무관한지 확인"""
        r1 = check_color_contrast("#333333", "#FFFFFF")
        r2 = check_color_contrast("#FFFFFF", "#333333")
        assert r1.ratio == pytest.approx(r2.ratio, abs=0.1)


class TestAccessibilityEvaluation:
    """접근성 평가 전체 검증"""

    @pytest.fixture
    def evaluation(self):
        return create_walletsavior_accessibility_evaluation()

    def test_evaluation_validates(self, evaluation):
        """평가가 유효성 검증을 통과하는지 확인"""
        assert evaluation.validate() is True

    def test_evaluation_has_all_categories(self, evaluation):
        """모든 접근성 카테고리가 포함되어 있는지 확인"""
        categories = set(c.category for c in evaluation.checks)
        expected = {"color_contrast", "keyboard", "screen_reader", "font_size", "touch_target"}
        assert expected.issubset(categories)

    def test_evaluation_has_color_results(self, evaluation):
        """색상 대비 결과가 포함되어 있는지 확인"""
        assert len(evaluation.color_results) >= 3

    def test_evaluation_has_touch_results(self, evaluation):
        """터치 타겟 결과가 포함되어 있는지 확인"""
        assert len(evaluation.touch_results) >= 3

    def test_evaluation_pass_rate(self, evaluation):
        """접근성 통과율이 계산되는지 확인"""
        rate = evaluation.pass_rate
        assert 0 <= rate <= 100

    def test_evaluation_to_dict(self, evaluation):
        """딕셔너리 변환이 올바른지 확인"""
        d = evaluation.to_dict()
        assert "target" in d
        assert "total_checks" in d
        assert "pass_rate" in d
        assert d["total_checks"] > 0


class TestTouchTargets:
    """터치 타겟 크기 테스트"""

    def test_adequate_touch_target(self):
        """충분한 크기의 터치 타겟"""
        tt = TouchTargetResult("버튼", 48, 48, "Home")
        assert tt.meets_minimum is True

    def test_small_touch_target_fails(self):
        """작은 터치 타겟은 실패"""
        tt = TouchTargetResult("아이콘", 30, 30, "Home")
        assert tt.meets_minimum is False

    def test_minimum_touch_target(self):
        """정확히 44x44px은 통과"""
        tt = TouchTargetResult("버튼", 44, 44, "Home")
        assert tt.meets_minimum is True


class TestFontSizes:
    """글꼴 크기 테스트"""

    def test_body_font_passes(self):
        """본문 글꼴 16px >= 14px 통과"""
        fc = FontSizeCheck("body", 16, 14)
        assert fc.passes is True

    def test_small_font_fails(self):
        """10px 글꼴은 14px 최소 기준 미달"""
        fc = FontSizeCheck("body", 10, 14)
        assert fc.passes is False

    def test_caption_font_passes(self):
        """캡션 12px >= 12px 통과"""
        fc = FontSizeCheck("caption", 12, 12)
        assert fc.passes is True

    def test_evaluation_font_checks(self):
        """평가의 글꼴 검사가 모두 통과하는지 확인"""
        evaluation = create_walletsavior_accessibility_evaluation()
        for fc in evaluation.font_checks:
            assert fc.passes is True, f"{fc.element_type}: {fc.size_px}px < {fc.min_required_px}px"
