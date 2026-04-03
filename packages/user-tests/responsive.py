"""
반응형 디자인 평가 프레임워크 — WalletSavior (지갑 지키미)

표준 브레이크포인트에서의 레이아웃 적응성을 평가합니다.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional


class DeviceType(Enum):
    """디바이스 유형"""
    MOBILE = "mobile"
    TABLET = "tablet"
    DESKTOP = "desktop"


class LayoutCheck(Enum):
    """레이아웃 검사 항목"""
    NAVIGATION = "navigation"       # 네비게이션 적응
    CARD_REFLOW = "card_reflow"     # 카드 리플로우
    CHART_RESIZE = "chart_resize"   # 차트 리사이즈
    MODAL_FIT = "modal_fit"         # 모달 맞춤
    FONT_SCALE = "font_scale"       # 폰트 스케일링
    IMAGE_SCALE = "image_scale"     # 이미지 스케일링
    TOUCH_VS_CLICK = "touch_click"  # 터치/클릭 적응
    HORIZONTAL_SCROLL = "h_scroll"  # 수평 스크롤 없음


STANDARD_BREAKPOINTS = {
    360: DeviceType.MOBILE,
    390: DeviceType.MOBILE,
    414: DeviceType.MOBILE,
    768: DeviceType.TABLET,
    1024: DeviceType.TABLET,
    1280: DeviceType.DESKTOP,
    1440: DeviceType.DESKTOP,
    1920: DeviceType.DESKTOP,
}


@dataclass
class BreakpointCheck:
    """개별 브레이크포인트 검사 결과"""
    width: int
    device_type: DeviceType
    check_type: LayoutCheck
    page: str
    passes: bool
    details: str = ""

    def validate(self) -> bool:
        return self.width > 0 and bool(self.page)


@dataclass
class PageResponsiveResult:
    """페이지별 반응형 검사 결과"""
    page: str
    checks: List[BreakpointCheck] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passes)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passes)

    @property
    def pass_rate(self) -> float:
        if not self.checks:
            return 0.0
        return round(self.pass_count / len(self.checks) * 100, 1)

    def get_failures(self) -> List[BreakpointCheck]:
        return [c for c in self.checks if not c.passes]


@dataclass
class ResponsiveEvaluation:
    """전체 반응형 디자인 평가"""
    target: str
    page_results: List[PageResponsiveResult] = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return sum(len(pr.checks) for pr in self.page_results)

    @property
    def total_passes(self) -> int:
        return sum(pr.pass_count for pr in self.page_results)

    @property
    def total_failures(self) -> int:
        return sum(pr.fail_count for pr in self.page_results)

    @property
    def overall_pass_rate(self) -> float:
        if self.total_checks == 0:
            return 0.0
        return round(self.total_passes / self.total_checks * 100, 1)

    def validate(self) -> bool:
        if not self.target:
            return False
        if not self.page_results:
            return False
        return True

    def get_page_result(self, page: str) -> Optional[PageResponsiveResult]:
        for pr in self.page_results:
            if pr.page == page:
                return pr
        return None

    def to_dict(self) -> Dict:
        return {
            "target": self.target,
            "total_checks": self.total_checks,
            "total_passes": self.total_passes,
            "total_failures": self.total_failures,
            "overall_pass_rate": self.overall_pass_rate,
            "pages": [
                {
                    "page": pr.page,
                    "checks": len(pr.checks),
                    "pass_rate": pr.pass_rate,
                    "failures": [
                        {"width": f.width, "check": f.check_type.value, "details": f.details}
                        for f in pr.get_failures()
                    ],
                }
                for pr in self.page_results
            ],
        }


# ─── WalletSavior 반응형 평가 생성 ───────────────────────────

def _create_page_checks(page: str, page_specific_fails: Dict = None) -> PageResponsiveResult:
    """페이지별 반응형 검사 생성"""
    if page_specific_fails is None:
        page_specific_fails = {}

    result = PageResponsiveResult(page=page)
    common_checks = [
        LayoutCheck.NAVIGATION,
        LayoutCheck.CARD_REFLOW,
        LayoutCheck.FONT_SCALE,
        LayoutCheck.HORIZONTAL_SCROLL,
        LayoutCheck.MODAL_FIT,
    ]

    for width, device_type in STANDARD_BREAKPOINTS.items():
        for check_type in common_checks:
            fail_key = (width, check_type)
            passes = fail_key not in page_specific_fails
            details = page_specific_fails.get(fail_key, "정상 동작")

            result.checks.append(BreakpointCheck(
                width=width,
                device_type=device_type,
                check_type=check_type,
                page=page,
                passes=passes,
                details=details if not passes else f"{device_type.value} {width}px에서 정상 동작",
            ))

    return result


def create_walletsavior_responsive_evaluation() -> ResponsiveEvaluation:
    """WalletSavior 반응형 디자인 평가 생성"""
    evaluation = ResponsiveEvaluation(target="WalletSavior (지갑 지키미)")

    # 홈 페이지 — 전반적 양호
    evaluation.page_results.append(_create_page_checks("Home"))

    # 핫딜 페이지 — 필터 칩 360px에서 약간 좁음
    evaluation.page_results.append(_create_page_checks("Hotdeal", {
        (360, LayoutCheck.CARD_REFLOW): "360px에서 필터 칩이 2줄로 넘침, 가로 스크롤 권장",
    }))

    # 가격 비교 페이지 — 차트가 모바일에서 밀림
    price_checks = _create_page_checks("Price", {
        (360, LayoutCheck.HORIZONTAL_SCROLL): "360px에서 가격 비교 표 가로 스크롤 발생",
    })
    # 차트 리사이즈 검사 추가
    for width, device_type in STANDARD_BREAKPOINTS.items():
        price_checks.checks.append(BreakpointCheck(
            width=width,
            device_type=device_type,
            check_type=LayoutCheck.CHART_RESIZE,
            page="Price",
            passes=width >= 390,
            details="차트가 너비에 맞게 리사이즈됨" if width >= 390 else "360px에서 차트 라벨 겹침",
        ))
    evaluation.page_results.append(price_checks)

    # 마트 페이지 — 전단지 뷰어 모바일 적응
    evaluation.page_results.append(_create_page_checks("Mart"))

    # 내 주변 페이지 — 지도 모바일 적응
    evaluation.page_results.append(_create_page_checks("Local"))

    # 커뮤니티 페이지 — 이미지 업로드 모바일 적응
    evaluation.page_results.append(_create_page_checks("Community"))

    return evaluation
