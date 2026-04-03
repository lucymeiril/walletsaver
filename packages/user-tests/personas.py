"""
사용자 페르소나 정의 — WalletSavior (지갑 지키미)

다양한 사용자 유형을 정의하여 UX 테스트 시나리오의 기반으로 활용합니다.
각 페르소나는 실제 사용자 행동 패턴을 반영합니다.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List


class TechLevel(IntEnum):
    """기술 숙련도 (1: 초보 ~ 5: 전문가)"""
    BEGINNER = 1
    BASIC = 2
    INTERMEDIATE = 3
    ADVANCED = 4
    EXPERT = 5


@dataclass
class UserPersona:
    """사용자 페르소나 정의"""
    id: str
    name: str
    description: str
    age_range: str
    goals: List[str]
    pain_points: List[str]
    tech_level: TechLevel
    typical_tasks: List[str]
    devices: List[str] = field(default_factory=lambda: ["mobile"])
    preferred_features: List[str] = field(default_factory=list)

    def validate(self) -> bool:
        """페르소나 데이터 유효성 검증"""
        if not self.id or not self.name:
            return False
        if not self.goals or not self.typical_tasks:
            return False
        if not isinstance(self.tech_level, TechLevel):
            return False
        if not self.description:
            return False
        if not self.pain_points:
            return False
        if not self.devices:
            return False
        return True


# ─── 페르소나 정의 ───────────────────────────────────────────

BEGINNER = UserPersona(
    id="beginner",
    name="초보 사용자",
    description="스마트폰으로 장보기 정보를 처음 검색하는 사용자. 복잡한 기능보다 직관적인 UI를 선호하며, 오늘의 핫딜이나 근처 마트 세일 정보를 빠르게 확인하고 싶어함.",
    age_range="40-60대",
    goals=[
        "오늘 뭐가 싼지 한눈에 보기",
        "근처 마트 세일 정보 확인",
        "복잡한 조작 없이 정보 얻기",
    ],
    pain_points=[
        "너무 많은 메뉴와 버튼에 혼란",
        "작은 글씨를 읽기 어려움",
        "영어/전문 용어 이해 어려움",
        "뒤로 가기나 홈으로 돌아가는 방법을 모름",
    ],
    tech_level=TechLevel.BEGINNER,
    typical_tasks=[
        "앱 열기 → 오늘의 핫딜 확인",
        "핫딜 클릭 → 가격 정보 확인",
        "관심 상품 북마크",
        "근처 마트 세일 전단지 보기",
    ],
    devices=["mobile"],
    preferred_features=["오늘의 핫딜", "대형마트 세일"],
)

BUDGET_SHOPPER = UserPersona(
    id="budget_shopper",
    name="알뜰 주부/주남",
    description="매주 장보기 전에 가격 비교를 하는 알뜰 소비자. 마트별 세일 정보를 비교하고, 최저가 마트를 찾아 장보기 목록을 만듦. 가격 추이도 확인하여 구매 타이밍을 결정.",
    age_range="30-50대",
    goals=[
        "마트별 가격 비교로 최저가 찾기",
        "주간 장보기 목록 최적화",
        "세일 전단지 미리 확인",
        "가격 추이를 보고 구매 시점 결정",
    ],
    pain_points=[
        "마트별 가격 비교가 번거로움",
        "세일 기간을 놓치는 경우",
        "실제 가격과 앱 가격이 다를 때",
        "장보기 목록 관리 불편",
    ],
    tech_level=TechLevel.INTERMEDIATE,
    typical_tasks=[
        "삼겹살 검색 → 마트별 가격 비교",
        "가격 차트 확인 → 구매 시점 판단",
        "마트 전단지 보기 → 세일 품목 확인",
        "마트 교차 비교 → 최적 장보기 계획",
    ],
    devices=["mobile", "tablet"],
    preferred_features=["가격 비교", "마트 세일", "가격 차트"],
)

POWER_USER = UserPersona(
    id="power_user",
    name="핫딜 고인물",
    description="핫딜 커뮤니티를 매일 순회하며 최저가를 추적하는 파워 유저. 고인물 모드를 활용하여 깊이 있는 가격 분석을 하고, 커뮤니티에 딜 정보를 공유하며, 투표로 딜 품질을 평가.",
    age_range="20-40대",
    goals=[
        "역대 최저가 갱신 여부 즉시 확인",
        "고인물 모드로 심층 가격 분석",
        "커뮤니티에 핫딜 정보 공유 및 추천",
        "가성비 최적화 전략 수립",
    ],
    pain_points=[
        "이미 본 딜이 계속 노출됨",
        "가격 이력 데이터가 부족할 때",
        "커뮤니티 글 작성이 번거로움",
        "모바일에서 고급 기능 접근 어려움",
    ],
    tech_level=TechLevel.EXPERT,
    typical_tasks=[
        "핫딜 검색 → 고인물 모드 활성화 → 심층 분석",
        "가격 추이 차트 분석 → 구매 판단",
        "커뮤니티 글 작성 → 딜 정보 공유",
        "딜 투표(추천/비추천) → 품질 평가",
    ],
    devices=["mobile", "desktop"],
    preferred_features=["고인물 모드", "가격 차트", "커뮤니티", "투표"],
)

STUDENT = UserPersona(
    id="student",
    name="자취생",
    description="제한된 예산으로 생활하는 대학생/사회 초년생. 배달비 포함 가격 비교, 직접 요리 vs 외식 비용 분석, 근처 저렴한 식당 찾기 등 실질적인 절약 정보를 원함.",
    age_range="20-30대",
    goals=[
        "최소 비용으로 한 끼 해결",
        "요리 vs 외식(배달) 비용 비교",
        "근처 저렴한 맛집 찾기",
        "주유비 절약 (가장 싼 주유소 찾기)",
    ],
    pain_points=[
        "배달비까지 포함한 실제 비용 파악 어려움",
        "근처 매장 정보가 부정확할 때",
        "1인분 기준 가격 비교 어려움",
        "학생 할인이나 쿠폰 정보 부족",
    ],
    tech_level=TechLevel.ADVANCED,
    typical_tasks=[
        "요리 vs 배달 비용 비교",
        "근처 저렴한 식당 찾기",
        "주유소 가격 비교 → 최저가 주유소 방문",
        "핫딜 중 가성비 좋은 식료품 찾기",
    ],
    devices=["mobile"],
    preferred_features=["요리 vs 외식 비교", "주유소 가격", "근처 맛집"],
)

ADMIN = UserPersona(
    id="admin",
    name="관리자",
    description="크롤러와 데이터베이스를 관리하는 시스템 관리자. 크롤링 상태 모니터링, 실패한 작업 재실행, 데이터 품질 검증, 통계 확인 등 운영 업무를 수행.",
    age_range="25-45",
    goals=[
        "크롤러 상태 실시간 모니터링",
        "실패한 크롤링 즉시 재실행",
        "데이터 품질 및 정합성 검증",
        "시스템 통계 및 리포트 확인",
    ],
    pain_points=[
        "크롤링 실패 원인 파악 어려움",
        "대량 데이터 처리 시 느린 응답",
        "여러 대시보드를 오가며 확인해야 함",
        "에러 로그 분석이 번거로움",
    ],
    tech_level=TechLevel.EXPERT,
    typical_tasks=[
        "대시보드 확인 → 크롤러 상태 모니터링",
        "실패 크롤러 확인 → 재실행",
        "데이터 품질 리뷰 → 이상 데이터 처리",
        "통계 데이터 확인 → 리포트 내보내기",
    ],
    devices=["desktop"],
    preferred_features=["대시보드", "크롤러 관리", "로그 뷰어", "데이터 내보내기"],
)


ALL_PERSONAS = [BEGINNER, BUDGET_SHOPPER, POWER_USER, STUDENT, ADMIN]


def get_persona(persona_id: str) -> UserPersona:
    """ID로 페르소나 조회"""
    for p in ALL_PERSONAS:
        if p.id == persona_id:
            return p
    raise ValueError(f"알 수 없는 페르소나: {persona_id}")


def get_personas_by_tech_level(level: TechLevel) -> List[UserPersona]:
    """기술 숙련도별 페르소나 필터링"""
    return [p for p in ALL_PERSONAS if p.tech_level == level]
