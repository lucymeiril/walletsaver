"""
사용자 여정 정의 — WalletSavior (지갑 지키미)

각 페르소나별 주요 사용자 여정(User Journey)을 정의합니다.
테스트에서 각 여정의 단계가 올바르게 구성되었는지 검증합니다.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from personas import UserPersona, ALL_PERSONAS, get_persona


class StepType(Enum):
    """여정 단계 유형"""
    NAVIGATE = "navigate"       # 페이지 이동
    SEARCH = "search"           # 검색
    CLICK = "click"             # 클릭/탭
    SCROLL = "scroll"           # 스크롤
    INPUT = "input"             # 입력
    TOGGLE = "toggle"           # 토글/스위치
    VERIFY = "verify"           # 검증 (화면 확인)
    WAIT = "wait"               # 대기 (로딩 등)


@dataclass
class JourneyStep:
    """사용자 여정의 개별 단계"""
    order: int
    action: StepType
    target: str
    description: str
    expected_result: str
    page: str
    is_critical: bool = False

    def validate(self) -> bool:
        return bool(self.target and self.description and self.expected_result and self.page)


@dataclass
class UserJourney:
    """사용자 여정 시나리오"""
    id: str
    persona_id: str
    title: str
    description: str
    steps: List[JourneyStep]
    preconditions: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)

    def validate(self) -> bool:
        if not self.id or not self.persona_id or not self.title:
            return False
        if not self.steps:
            return False
        if not self.success_criteria:
            return False
        orders = [s.order for s in self.steps]
        if orders != sorted(orders):
            return False
        return all(s.validate() for s in self.steps)

    @property
    def critical_steps(self) -> List[JourneyStep]:
        return [s for s in self.steps if s.is_critical]

    @property
    def pages_visited(self) -> List[str]:
        seen = []
        for s in self.steps:
            if s.page not in seen:
                seen.append(s.page)
        return seen


# ─── 초보 사용자 여정 ────────────────────────────────────────

BEGINNER_JOURNEY = UserJourney(
    id="beginner_first_visit",
    persona_id="beginner",
    title="초보 사용자의 첫 방문",
    description="앱을 처음 열어 오늘의 핫딜을 확인하고, 관심 상품을 북마크하는 기본 여정",
    preconditions=["앱 첫 실행", "로그인 불필요"],
    steps=[
        JourneyStep(
            order=1,
            action=StepType.NAVIGATE,
            target="홈 페이지",
            description="앱을 열어 홈 화면 확인",
            expected_result="히어로 검색바, 카테고리 퀵링크, 오늘의 핫딜 섹션이 표시됨",
            page="Home",
            is_critical=True,
        ),
        JourneyStep(
            order=2,
            action=StepType.SCROLL,
            target="오늘의 핫딜 섹션",
            description="아래로 스크롤하여 오늘의 핫딜 목록 확인",
            expected_result="핫딜 카드 목록이 보이고 가격과 할인율이 표시됨",
            page="Home",
        ),
        JourneyStep(
            order=3,
            action=StepType.CLICK,
            target="핫딜 카드",
            description="관심 있는 핫딜 카드 클릭",
            expected_result="핫딜 상세 정보 표시 (가격, 출처, 기간)",
            page="Hotdeal",
            is_critical=True,
        ),
        JourneyStep(
            order=4,
            action=StepType.VERIFY,
            target="가격 정보",
            description="가격 정보와 할인율 확인",
            expected_result="원가, 할인가, 할인율이 명확하게 표시됨 (₩ 포맷)",
            page="Hotdeal",
            is_critical=True,
        ),
        JourneyStep(
            order=5,
            action=StepType.CLICK,
            target="북마크 버튼",
            description="관심 상품 북마크",
            expected_result="북마크 아이콘 활성화, 저장 완료 피드백",
            page="Hotdeal",
        ),
    ],
    success_criteria=[
        "3단계 이내에 원하는 정보 확인 가능",
        "모든 텍스트가 한국어로 표시됨",
        "가격 정보를 한눈에 이해 가능",
        "북마크 완료 피드백이 즉시 표시됨",
    ],
)

# ─── 알뜰 주부/주남 여정 ─────────────────────────────────────

BUDGET_SHOPPER_JOURNEY = UserJourney(
    id="budget_price_comparison",
    persona_id="budget_shopper",
    title="알뜰 소비자의 가격 비교",
    description="특정 상품을 검색하여 마트별 가격을 비교하고, 전단지를 확인하는 여정",
    preconditions=["삼겹살 구매 계획", "주변 마트 위치 파악"],
    steps=[
        JourneyStep(
            order=1,
            action=StepType.NAVIGATE,
            target="가격 비교 페이지",
            description="가격 비교 페이지로 이동",
            expected_result="검색바와 자동완성이 표시됨",
            page="Price",
            is_critical=True,
        ),
        JourneyStep(
            order=2,
            action=StepType.SEARCH,
            target="검색바",
            description="'삼겹살' 검색",
            expected_result="자동완성 목록에 관련 상품 표시",
            page="Price",
            is_critical=True,
        ),
        JourneyStep(
            order=3,
            action=StepType.VERIFY,
            target="마트별 가격 비교 표",
            description="마트별 가격 비교 결과 확인",
            expected_result="이마트, 홈플러스, 롯데마트 등 가격이 비교 표로 표시됨",
            page="Price",
            is_critical=True,
        ),
        JourneyStep(
            order=4,
            action=StepType.CLICK,
            target="가격 차트",
            description="가격 추이 차트 확인",
            expected_result="최근 가격 변동 그래프가 표시됨",
            page="Price",
        ),
        JourneyStep(
            order=5,
            action=StepType.NAVIGATE,
            target="마트 페이지",
            description="최저가 마트의 전단지 확인",
            expected_result="해당 마트 전단지(세일 정보) 표시",
            page="Mart",
        ),
        JourneyStep(
            order=6,
            action=StepType.VERIFY,
            target="전단지 뷰어",
            description="전단지에서 세일 품목 확인",
            expected_result="세일 품목, 기간, 할인 가격 표시",
            page="Mart",
            is_critical=True,
        ),
    ],
    success_criteria=[
        "최저가 마트를 즉시 식별 가능",
        "가격 차이가 한눈에 비교 가능",
        "전단지 정보가 최신 상태",
        "마트 간 이동이 자연스러움",
    ],
)

# ─── 핫딜 고인물 여정 ────────────────────────────────────────

POWER_USER_JOURNEY = UserJourney(
    id="power_user_deep_analysis",
    persona_id="power_user",
    title="핫딜 고인물의 심층 분석",
    description="고인물 모드를 활용하여 심층 가격 분석을 하고, 커뮤니티에 정보를 공유하는 여정",
    preconditions=["계정 로그인 완료", "고인물 모드 사용 경험 있음"],
    steps=[
        JourneyStep(
            order=1,
            action=StepType.NAVIGATE,
            target="핫딜 페이지",
            description="핫딜 페이지로 이동",
            expected_result="카테고리/출처 필터, 가격대 뱃지, 무한 스크롤 표시",
            page="Hotdeal",
        ),
        JourneyStep(
            order=2,
            action=StepType.SEARCH,
            target="핫딜 검색",
            description="특정 상품 검색",
            expected_result="검색 결과와 필터 옵션 표시",
            page="Hotdeal",
            is_critical=True,
        ),
        JourneyStep(
            order=3,
            action=StepType.NAVIGATE,
            target="가격 비교 페이지",
            description="상세 가격 분석을 위해 가격 페이지 이동",
            expected_result="가격 비교 및 분석 도구 표시",
            page="Price",
        ),
        JourneyStep(
            order=4,
            action=StepType.TOGGLE,
            target="고인물 모드 스위치",
            description="고인물 모드 활성화",
            expected_result="추가 분석 도구, 상세 차트, 히스토리 데이터 표시",
            page="Price",
            is_critical=True,
        ),
        JourneyStep(
            order=5,
            action=StepType.VERIFY,
            target="심층 분석 데이터",
            description="역대가, 평균가, 변동성 등 심층 데이터 확인",
            expected_result="역대 최저가, 평균가, 가격 변동 추이 표시",
            page="Price",
            is_critical=True,
        ),
        JourneyStep(
            order=6,
            action=StepType.NAVIGATE,
            target="커뮤니티 페이지",
            description="커뮤니티에 딜 정보 공유",
            expected_result="글 작성 폼 접근 가능",
            page="Community",
        ),
        JourneyStep(
            order=7,
            action=StepType.INPUT,
            target="글 작성 폼",
            description="핫딜 게시판에 딜 정보 작성 (이미지 첨부)",
            expected_result="글 작성 완료, DB 가격 검증 연동",
            page="Community",
            is_critical=True,
        ),
        JourneyStep(
            order=8,
            action=StepType.CLICK,
            target="투표 버튼",
            description="다른 딜에 추천/비추천 투표",
            expected_result="투표 반영, 투표 수 업데이트 표시",
            page="Community",
        ),
    ],
    success_criteria=[
        "고인물 모드 전환이 즉각적",
        "심층 분석 데이터가 정확하고 유용",
        "커뮤니티 글 작성이 3분 이내 완료",
        "투표 결과가 즉시 반영",
    ],
)

# ─── 자취생 여정 ─────────────────────────────────────────────

STUDENT_JOURNEY = UserJourney(
    id="student_budget_meal",
    persona_id="student",
    title="자취생의 한 끼 해결",
    description="요리 vs 배달 비용을 비교하고, 근처 저렴한 식당과 주유소를 찾는 여정",
    preconditions=["위치 정보 허용", "예산 제한 있음"],
    steps=[
        JourneyStep(
            order=1,
            action=StepType.NAVIGATE,
            target="내 주변 페이지",
            description="내 주변 페이지로 이동",
            expected_result="주변 주유소, 식당 정보 표시",
            page="Local",
            is_critical=True,
        ),
        JourneyStep(
            order=2,
            action=StepType.VERIFY,
            target="요리 vs 외식 비교",
            description="요리 비용과 외식/배달 비용 비교 확인",
            expected_result="재료비 기반 요리 비용 vs 배달 비용이 비교 표시됨",
            page="Local",
            is_critical=True,
        ),
        JourneyStep(
            order=3,
            action=StepType.CLICK,
            target="주변 식당 탭",
            description="근처 저렴한 식당 목록 확인",
            expected_result="가격순 정렬된 주변 식당 목록",
            page="Local",
        ),
        JourneyStep(
            order=4,
            action=StepType.VERIFY,
            target="식당 가격 정보",
            description="식당별 메뉴 가격 확인",
            expected_result="메뉴 가격과 거리 정보 표시",
            page="Local",
        ),
        JourneyStep(
            order=5,
            action=StepType.CLICK,
            target="주유소 탭",
            description="근처 주유소 가격 비교",
            expected_result="가격순 정렬된 주변 주유소 목록",
            page="Local",
            is_critical=True,
        ),
        JourneyStep(
            order=6,
            action=StepType.VERIFY,
            target="주유소 가격",
            description="주유소별 유가 확인",
            expected_result="휘발유/경유 가격, 거리, 셀프 여부 표시",
            page="Local",
        ),
    ],
    success_criteria=[
        "요리 vs 외식 비교가 직관적",
        "주변 최저가 주유소를 바로 확인",
        "거리 대비 가격 효율 판단 가능",
        "1인분 기준 가격이 명확히 표시됨",
    ],
)

# ─── 관리자 여정 ─────────────────────────────────────────────

ADMIN_JOURNEY = UserJourney(
    id="admin_monitoring",
    persona_id="admin",
    title="관리자의 시스템 모니터링",
    description="크롤러 상태를 확인하고, 실패한 작업을 재실행하며, 데이터 품질을 검증하는 여정",
    preconditions=["관리자 계정 로그인", "크롤러 실행 이력 존재"],
    steps=[
        JourneyStep(
            order=1,
            action=StepType.NAVIGATE,
            target="크롤러 대시보드",
            description="크롤러 관리 대시보드 확인",
            expected_result="크롤러 상태 요약, 성공/실패 통계 표시",
            page="CrawlerAdmin-Dashboard",
            is_critical=True,
        ),
        JourneyStep(
            order=2,
            action=StepType.VERIFY,
            target="크롤러 상태",
            description="실행 중/대기/실패 크롤러 상태 확인",
            expected_result="상태별 색상 구분, 최근 실행 시간 표시",
            page="CrawlerAdmin-Dashboard",
        ),
        JourneyStep(
            order=3,
            action=StepType.CLICK,
            target="실패 크롤러",
            description="실패한 크롤러 선택하여 상세 확인",
            expected_result="에러 로그, 실패 원인, 마지막 성공 시간 표시",
            page="CrawlerAdmin-Crawlers",
            is_critical=True,
        ),
        JourneyStep(
            order=4,
            action=StepType.CLICK,
            target="재실행 버튼",
            description="실패한 크롤러 재실행",
            expected_result="재실행 확인 다이얼로그 → 실행 시작 피드백",
            page="CrawlerAdmin-Crawlers",
            is_critical=True,
        ),
        JourneyStep(
            order=5,
            action=StepType.NAVIGATE,
            target="DB 관리 대시보드",
            description="데이터 품질 검증을 위해 DB 관리 이동",
            expected_result="데이터 통계, 최근 변경 요약 표시",
            page="DBAdmin-Dashboard",
        ),
        JourneyStep(
            order=6,
            action=StepType.VERIFY,
            target="데이터 품질 지표",
            description="데이터 정합성 및 품질 지표 확인",
            expected_result="데이터 건수, 이상치, 누락 데이터 표시",
            page="DBAdmin-Analytics",
            is_critical=True,
        ),
        JourneyStep(
            order=7,
            action=StepType.CLICK,
            target="내보내기 버튼",
            description="통계 데이터 내보내기",
            expected_result="CSV/JSON 내보내기 옵션, 다운로드 시작",
            page="DBAdmin-Analytics",
        ),
    ],
    success_criteria=[
        "크롤러 상태를 대시보드에서 즉시 파악",
        "실패 원인을 로그에서 쉽게 확인",
        "재실행 결과 피드백이 명확",
        "데이터 품질 이상을 빠르게 감지",
    ],
)


ALL_JOURNEYS = [
    BEGINNER_JOURNEY,
    BUDGET_SHOPPER_JOURNEY,
    POWER_USER_JOURNEY,
    STUDENT_JOURNEY,
    ADMIN_JOURNEY,
]


def get_journeys_for_persona(persona_id: str) -> List[UserJourney]:
    """페르소나별 여정 조회"""
    return [j for j in ALL_JOURNEYS if j.persona_id == persona_id]
