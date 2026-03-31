"""
페르소나 정의 테스트 — WalletSavior (지갑 지키미)
각 페르소나가 올바르게 정의되어 있고, 완전한 데이터를 가지는지 검증합니다.
"""

import pytest
from personas import (
    UserPersona, TechLevel, ALL_PERSONAS,
    BEGINNER, BUDGET_SHOPPER, POWER_USER, STUDENT, ADMIN,
    get_persona, get_personas_by_tech_level,
)


class TestPersonaDefinitions:
    """페르소나 기본 정의 검증"""

    def test_all_five_personas_defined(self):
        """5개 페르소나가 모두 정의되어 있는지 확인"""
        assert len(ALL_PERSONAS) == 5

    def test_all_persona_ids_unique(self):
        """페르소나 ID가 중복되지 않는지 확인"""
        ids = [p.id for p in ALL_PERSONAS]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_validates(self, persona):
        """각 페르소나가 유효성 검증을 통과하는지 확인"""
        assert persona.validate() is True

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_has_name_and_description(self, persona):
        """각 페르소나가 이름과 설명을 가지는지 확인"""
        assert persona.name, f"{persona.id}: 이름 없음"
        assert persona.description, f"{persona.id}: 설명 없음"
        assert len(persona.description) >= 20, f"{persona.id}: 설명이 너무 짧음"

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_has_goals(self, persona):
        """각 페르소나가 최소 2개 이상의 목표를 가지는지 확인"""
        assert len(persona.goals) >= 2, f"{persona.id}: 목표가 2개 미만"

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_has_pain_points(self, persona):
        """각 페르소나가 최소 2개 이상의 불편 사항을 가지는지 확인"""
        assert len(persona.pain_points) >= 2, f"{persona.id}: 불편 사항이 2개 미만"

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_has_typical_tasks(self, persona):
        """각 페르소나가 최소 2개 이상의 대표 작업을 가지는지 확인"""
        assert len(persona.typical_tasks) >= 2, f"{persona.id}: 대표 작업이 2개 미만"

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_has_valid_tech_level(self, persona):
        """기술 숙련도가 유효한 범위인지 확인"""
        assert isinstance(persona.tech_level, TechLevel)
        assert 1 <= persona.tech_level <= 5

    @pytest.mark.parametrize("persona", ALL_PERSONAS, ids=lambda p: p.id)
    def test_persona_has_devices(self, persona):
        """각 페르소나가 디바이스 정보를 가지는지 확인"""
        assert len(persona.devices) >= 1
        for device in persona.devices:
            assert device in ["mobile", "tablet", "desktop"]


class TestPersonaCharacteristics:
    """페르소나 특성 적절성 검증"""

    def test_beginner_is_low_tech(self):
        """초보 사용자의 기술 숙련도가 낮은지 확인"""
        assert BEGINNER.tech_level == TechLevel.BEGINNER

    def test_power_user_is_expert(self):
        """고인물의 기술 숙련도가 전문가인지 확인"""
        assert POWER_USER.tech_level == TechLevel.EXPERT

    def test_admin_is_expert(self):
        """관리자의 기술 숙련도가 전문가인지 확인"""
        assert ADMIN.tech_level == TechLevel.EXPERT

    def test_student_uses_mobile(self):
        """자취생이 모바일을 주로 사용하는지 확인"""
        assert "mobile" in STUDENT.devices

    def test_admin_uses_desktop(self):
        """관리자가 데스크톱을 주로 사용하는지 확인"""
        assert "desktop" in ADMIN.devices

    def test_budget_shopper_intermediate_tech(self):
        """알뜰 소비자의 기술 숙련도가 중간인지 확인"""
        assert BUDGET_SHOPPER.tech_level == TechLevel.INTERMEDIATE


class TestPersonaLookup:
    """페르소나 조회 기능 테스트"""

    def test_get_persona_by_id(self):
        """ID로 페르소나 조회"""
        persona = get_persona("beginner")
        assert persona.name == "초보 사용자"

    def test_get_persona_invalid_id_raises(self):
        """잘못된 ID로 조회 시 에러"""
        with pytest.raises(ValueError, match="알 수 없는 페르소나"):
            get_persona("nonexistent")

    def test_get_personas_by_tech_level(self):
        """기술 숙련도별 필터링"""
        experts = get_personas_by_tech_level(TechLevel.EXPERT)
        assert len(experts) == 2  # power_user, admin
        assert all(p.tech_level == TechLevel.EXPERT for p in experts)

    def test_persona_korean_text(self):
        """페르소나 정보가 한국어로 작성되었는지 확인"""
        for persona in ALL_PERSONAS:
            # 이름에 한국어 포함 확인
            assert any('\uac00' <= c <= '\ud7a3' for c in persona.name), \
                f"{persona.id}: 이름에 한국어가 없음"
