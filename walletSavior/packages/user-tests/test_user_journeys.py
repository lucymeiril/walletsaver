"""
사용자 여정 테스트 — WalletSavior (지갑 지키미)
각 페르소나별 여정이 올바르게 구성되고, 단계가 실행 가능한지 검증합니다.
"""

import pytest
from journeys import (
    UserJourney, JourneyStep, StepType,
    ALL_JOURNEYS, BEGINNER_JOURNEY, BUDGET_SHOPPER_JOURNEY,
    POWER_USER_JOURNEY, STUDENT_JOURNEY, ADMIN_JOURNEY,
    get_journeys_for_persona,
)
from personas import ALL_PERSONAS


class TestJourneyDefinitions:
    """여정 기본 정의 검증"""

    def test_all_five_journeys_defined(self):
        """5개 여정이 모두 정의되어 있는지 확인"""
        assert len(ALL_JOURNEYS) == 5

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_journey_validates(self, journey):
        """각 여정이 유효성 검증을 통과하는지 확인"""
        assert journey.validate() is True

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_journey_has_steps(self, journey):
        """각 여정이 최소 3단계 이상인지 확인"""
        assert len(journey.steps) >= 3, f"{journey.id}: 단계가 3개 미만"

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_journey_steps_ordered(self, journey):
        """여정 단계가 순서대로 정렬되어 있는지 확인"""
        orders = [s.order for s in journey.steps]
        assert orders == sorted(orders), f"{journey.id}: 단계 순서 불일치"

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_journey_has_success_criteria(self, journey):
        """각 여정이 성공 기준을 가지는지 확인"""
        assert len(journey.success_criteria) >= 2, f"{journey.id}: 성공 기준이 2개 미만"

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_journey_has_critical_steps(self, journey):
        """각 여정에 핵심 단계가 최소 1개 이상인지 확인"""
        assert len(journey.critical_steps) >= 1, f"{journey.id}: 핵심 단계 없음"

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_journey_linked_to_persona(self, journey):
        """각 여정이 유효한 페르소나에 연결되어 있는지 확인"""
        persona_ids = [p.id for p in ALL_PERSONAS]
        assert journey.persona_id in persona_ids, \
            f"{journey.id}: 잘못된 페르소나 ID '{journey.persona_id}'"


class TestBeginnerJourney:
    """초보 사용자 여정 검증"""

    def test_beginner_starts_at_home(self):
        """초보 사용자 여정이 홈에서 시작하는지 확인"""
        first_step = BEGINNER_JOURNEY.steps[0]
        assert first_step.page == "Home"
        assert first_step.action == StepType.NAVIGATE

    def test_beginner_journey_includes_bookmark(self):
        """북마크 단계가 포함되어 있는지 확인"""
        actions = [(s.action, s.target) for s in BEGINNER_JOURNEY.steps]
        assert any("북마크" in target for _, target in actions)

    def test_beginner_journey_max_steps(self):
        """초보 사용자 여정이 7단계 이하인지 확인 (간단해야 함)"""
        assert len(BEGINNER_JOURNEY.steps) <= 7


class TestBudgetShopperJourney:
    """알뜰 소비자 여정 검증"""

    def test_budget_journey_includes_search(self):
        """검색 단계가 포함되어 있는지 확인"""
        actions = [s.action for s in BUDGET_SHOPPER_JOURNEY.steps]
        assert StepType.SEARCH in actions

    def test_budget_journey_visits_price_and_mart(self):
        """가격 비교 페이지와 마트 페이지를 방문하는지 확인"""
        pages = BUDGET_SHOPPER_JOURNEY.pages_visited
        assert "Price" in pages
        assert "Mart" in pages


class TestPowerUserJourney:
    """고인물 사용자 여정 검증"""

    def test_power_user_uses_advanced_mode(self):
        """고인물 모드 활성화 단계가 있는지 확인"""
        actions = [(s.action, s.target) for s in POWER_USER_JOURNEY.steps]
        assert any(s.action == StepType.TOGGLE and "고인물" in s.target
                    for s in POWER_USER_JOURNEY.steps)

    def test_power_user_posts_to_community(self):
        """커뮤니티 글 작성 단계가 있는지 확인"""
        pages = POWER_USER_JOURNEY.pages_visited
        assert "Community" in pages


class TestStudentJourney:
    """자취생 여정 검증"""

    def test_student_checks_local(self):
        """내 주변 페이지를 방문하는지 확인"""
        pages = STUDENT_JOURNEY.pages_visited
        assert "Local" in pages

    def test_student_compares_costs(self):
        """요리 vs 외식 비교 단계가 있는지 확인"""
        has_comparison = any("요리" in s.target or "외식" in s.target or "비교" in s.target
                            for s in STUDENT_JOURNEY.steps)
        assert has_comparison


class TestAdminJourney:
    """관리자 여정 검증"""

    def test_admin_checks_crawler_dashboard(self):
        """크롤러 대시보드 확인 단계가 있는지 확인"""
        pages = ADMIN_JOURNEY.pages_visited
        assert any("Crawler" in p or "Admin" in p for p in pages)

    def test_admin_can_rerun_failed_crawler(self):
        """실패 크롤러 재실행 단계가 있는지 확인"""
        has_rerun = any("재실행" in s.description for s in ADMIN_JOURNEY.steps)
        assert has_rerun


class TestJourneyLookup:
    """여정 조회 기능 테스트"""

    def test_get_journeys_for_beginner(self):
        """초보 사용자 여정 조회"""
        journeys = get_journeys_for_persona("beginner")
        assert len(journeys) >= 1
        assert all(j.persona_id == "beginner" for j in journeys)

    def test_get_journeys_for_nonexistent_persona(self):
        """존재하지 않는 페르소나 여정 조회"""
        journeys = get_journeys_for_persona("nonexistent")
        assert journeys == []

    @pytest.mark.parametrize("journey", ALL_JOURNEYS, ids=lambda j: j.id)
    def test_all_steps_have_expected_results(self, journey):
        """모든 단계에 기대 결과가 정의되어 있는지 확인"""
        for step in journey.steps:
            assert step.expected_result, \
                f"{journey.id} 단계 {step.order}: 기대 결과 없음"
