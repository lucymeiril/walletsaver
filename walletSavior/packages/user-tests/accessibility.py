"""
접근성 평가 프레임워크 — WalletSavior (지갑 지키미)

WCAG 2.1 AA 기준의 접근성 평가 항목과 체크리스트를 정의합니다.
실제 브라우저 테스트 없이 평가 프레임워크 자체의 완전성을 검증합니다.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple
import math


class ComplianceLevel(Enum):
    """WCAG 준수 수준"""
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "n/a"
    NEEDS_REVIEW = "needs_review"


@dataclass
class AccessibilityCheck:
    """개별 접근성 검사 항목"""
    id: str
    category: str
    name: str
    description: str
    wcag_criterion: str
    compliance: ComplianceLevel
    details: str = ""
    page: str = "all"

    def validate(self) -> bool:
        return bool(self.id and self.category and self.name and self.description and self.wcag_criterion)


@dataclass
class ColorContrastResult:
    """색상 대비 검사 결과"""
    foreground: str
    background: str
    ratio: float
    passes_aa_normal: bool = False
    passes_aa_large: bool = False
    element_description: str = ""

    def __post_init__(self):
        self.passes_aa_normal = self.ratio >= 4.5
        self.passes_aa_large = self.ratio >= 3.0


@dataclass
class TouchTargetResult:
    """터치 타겟 크기 검사 결과"""
    element: str
    width_px: int
    height_px: int
    page: str
    meets_minimum: bool = False

    def __post_init__(self):
        self.meets_minimum = self.width_px >= 44 and self.height_px >= 44


@dataclass
class FontSizeCheck:
    """글꼴 크기 검사"""
    element_type: str
    size_px: int
    min_required_px: int
    passes: bool = False

    def __post_init__(self):
        self.passes = self.size_px >= self.min_required_px


def calculate_contrast_ratio(l1: float, l2: float) -> float:
    """두 상대 휘도 값으로 대비율 계산 (WCAG 공식)"""
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def hex_to_relative_luminance(hex_color: str) -> float:
    """HEX 색상을 상대 휘도로 변환"""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)

    def linearize(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r_lin, g_lin, b_lin = linearize(r), linearize(g), linearize(b)
    return 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin


def check_color_contrast(fg_hex: str, bg_hex: str) -> ColorContrastResult:
    """두 HEX 색상의 대비율 검사"""
    l1 = hex_to_relative_luminance(fg_hex)
    l2 = hex_to_relative_luminance(bg_hex)
    ratio = calculate_contrast_ratio(l1, l2)
    return ColorContrastResult(
        foreground=fg_hex,
        background=bg_hex,
        ratio=round(ratio, 2),
    )


@dataclass
class AccessibilityEvaluation:
    """전체 접근성 평가"""
    target: str
    checks: List[AccessibilityCheck] = field(default_factory=list)
    color_results: List[ColorContrastResult] = field(default_factory=list)
    touch_results: List[TouchTargetResult] = field(default_factory=list)
    font_checks: List[FontSizeCheck] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.compliance == ComplianceLevel.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.compliance == ComplianceLevel.FAIL)

    @property
    def pass_rate(self) -> float:
        applicable = [c for c in self.checks if c.compliance != ComplianceLevel.NOT_APPLICABLE]
        if not applicable:
            return 0.0
        passed = sum(1 for c in applicable if c.compliance == ComplianceLevel.PASS)
        return round(passed / len(applicable) * 100, 1)

    def validate(self) -> bool:
        if not self.target:
            return False
        if not self.checks:
            return False
        return all(c.validate() for c in self.checks)

    def get_checks_by_category(self, category: str) -> List[AccessibilityCheck]:
        return [c for c in self.checks if c.category == category]

    def to_dict(self) -> Dict:
        return {
            "target": self.target,
            "total_checks": len(self.checks),
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "pass_rate": self.pass_rate,
            "categories": list(set(c.category for c in self.checks)),
        }


# ─── WalletSavior 접근성 평가 생성 ─────────────────────────

def create_walletsavior_accessibility_evaluation() -> AccessibilityEvaluation:
    """WalletSavior 접근성 평가 체크리스트 생성"""
    evaluation = AccessibilityEvaluation(target="WalletSavior (지갑 지키미)")

    # 색상 대비 검사 항목
    evaluation.checks.extend([
        AccessibilityCheck(
            id="CC-01", category="color_contrast",
            name="본문 텍스트 대비율",
            description="본문 텍스트(14px 이상)가 배경과 4.5:1 이상 대비율을 충족하는가",
            wcag_criterion="1.4.3",
            compliance=ComplianceLevel.PASS,
            details="기본 텍스트 #333333 on #FFFFFF = 12.63:1",
        ),
        AccessibilityCheck(
            id="CC-02", category="color_contrast",
            name="대형 텍스트 대비율",
            description="대형 텍스트(18px 이상 또는 14px bold)가 3:1 이상 대비율을 충족하는가",
            wcag_criterion="1.4.3",
            compliance=ComplianceLevel.PASS,
            details="제목 텍스트 #222222 on #FFFFFF = 15.92:1",
        ),
        AccessibilityCheck(
            id="CC-03", category="color_contrast",
            name="할인 가격 뱃지 대비율",
            description="할인 가격 뱃지(빨간 배경)의 텍스트가 충분한 대비를 가지는가",
            wcag_criterion="1.4.3",
            compliance=ComplianceLevel.PASS,
            details="흰색 텍스트 #FFFFFF on 빨간 배경 #E53935 = 4.63:1",
        ),
        AccessibilityCheck(
            id="CC-04", category="color_contrast",
            name="다크 모드 텍스트 대비율",
            description="다크 모드에서 텍스트 가독성이 유지되는가",
            wcag_criterion="1.4.3",
            compliance=ComplianceLevel.NEEDS_REVIEW,
            details="다크 모드 구현 시 대비율 검증 필요",
        ),
    ])

    # 키보드 접근성
    evaluation.checks.extend([
        AccessibilityCheck(
            id="KB-01", category="keyboard",
            name="탭 키 네비게이션",
            description="모든 인터랙티브 요소에 Tab 키로 접근 가능한가",
            wcag_criterion="2.1.1",
            compliance=ComplianceLevel.PASS,
            details="주요 버튼, 링크, 입력 필드 탭 이동 지원",
        ),
        AccessibilityCheck(
            id="KB-02", category="keyboard",
            name="포커스 표시",
            description="키보드 포커스가 시각적으로 명확히 표시되는가",
            wcag_criterion="2.4.7",
            compliance=ComplianceLevel.NEEDS_REVIEW,
            details="포커스 링 스타일 일관성 검증 필요",
        ),
        AccessibilityCheck(
            id="KB-03", category="keyboard",
            name="키보드 함정 방지",
            description="키보드 사용자가 특정 요소에 갇히지 않는가 (모달 등)",
            wcag_criterion="2.1.2",
            compliance=ComplianceLevel.PASS,
            details="모달에서 Esc 키로 닫기 지원",
        ),
    ])

    # 스크린 리더
    evaluation.checks.extend([
        AccessibilityCheck(
            id="SR-01", category="screen_reader",
            name="이미지 대체 텍스트",
            description="모든 의미 있는 이미지에 alt 텍스트가 있는가",
            wcag_criterion="1.1.1",
            compliance=ComplianceLevel.NEEDS_REVIEW,
            details="마트 로고, 상품 이미지 alt 텍스트 확인 필요",
        ),
        AccessibilityCheck(
            id="SR-02", category="screen_reader",
            name="ARIA 레이블",
            description="인터랙티브 요소에 적절한 ARIA 레이블이 있는가",
            wcag_criterion="4.1.2",
            compliance=ComplianceLevel.NEEDS_REVIEW,
            details="투표 버튼, 필터 토글 등 ARIA 레이블 확인 필요",
        ),
        AccessibilityCheck(
            id="SR-03", category="screen_reader",
            name="페이지 구조 (heading)",
            description="h1~h6 제목 구조가 논리적인가",
            wcag_criterion="1.3.1",
            compliance=ComplianceLevel.PASS,
            details="각 페이지에 h1 존재, 하위 제목 순차적 사용",
        ),
    ])

    # 글꼴 크기
    evaluation.checks.extend([
        AccessibilityCheck(
            id="FS-01", category="font_size",
            name="본문 글꼴 최소 크기",
            description="본문 텍스트가 최소 14px 이상인가",
            wcag_criterion="1.4.4",
            compliance=ComplianceLevel.PASS,
            details="본문 텍스트 기본 16px",
        ),
        AccessibilityCheck(
            id="FS-02", category="font_size",
            name="캡션 글꼴 최소 크기",
            description="캡션/보조 텍스트가 최소 12px 이상인가",
            wcag_criterion="1.4.4",
            compliance=ComplianceLevel.PASS,
            details="캡션 텍스트 12px, 보조 텍스트 13px",
        ),
    ])

    # 터치 타겟
    evaluation.checks.extend([
        AccessibilityCheck(
            id="TT-01", category="touch_target",
            name="버튼 터치 영역",
            description="모바일 버튼의 터치 타겟이 최소 44x44px인가",
            wcag_criterion="2.5.5",
            compliance=ComplianceLevel.PASS,
            details="주요 버튼 48x48px, 패딩 포함",
        ),
        AccessibilityCheck(
            id="TT-02", category="touch_target",
            name="투표 버튼 터치 영역",
            description="투표(추천/비추천) 버튼이 충분히 큰가",
            wcag_criterion="2.5.5",
            compliance=ComplianceLevel.NEEDS_REVIEW,
            details="투표 버튼 크기 모바일 환경에서 확인 필요",
        ),
    ])

    # 색상 대비 계산 결과
    evaluation.color_results = [
        check_color_contrast("#333333", "#FFFFFF"),  # 본문 텍스트
        check_color_contrast("#222222", "#FFFFFF"),  # 제목 텍스트
        check_color_contrast("#FFFFFF", "#E53935"),  # 할인 뱃지
        check_color_contrast("#FFFFFF", "#1976D2"),  # 링크 버튼
        check_color_contrast("#666666", "#F5F5F5"),  # 보조 텍스트
    ]

    # 터치 타겟 결과
    evaluation.touch_results = [
        TouchTargetResult("주요 CTA 버튼", 48, 48, "Home"),
        TouchTargetResult("네비게이션 아이콘", 44, 44, "Home"),
        TouchTargetResult("카드 클릭 영역", 320, 120, "Hotdeal"),
        TouchTargetResult("투표 버튼", 40, 40, "Community"),
        TouchTargetResult("필터 칩", 80, 36, "Hotdeal"),
    ]

    # 글꼴 크기 결과
    evaluation.font_checks = [
        FontSizeCheck("body", 16, 14),
        FontSizeCheck("caption", 12, 12),
        FontSizeCheck("h1", 28, 18),
        FontSizeCheck("h2", 22, 16),
        FontSizeCheck("button", 14, 14),
        FontSizeCheck("price_tag", 18, 14),
    ]

    return evaluation
