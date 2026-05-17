"""
카테고리 매퍼 TDD — Phase B3

테스트 구성:
    1. 트리 정합성 — YAML 로드 후 구조 검증
    2. 홈플러스 매핑 — fixture 5건 + 미매핑 케이스
    3. 롯데마트 매핑 — fixture 5건 + 미매핑 케이스
    4. 코스트코 매핑 — fixture 5건(4 unique path) + 미매핑 케이스
    5. 이마트 매핑 — 항상 None+reason 검증
    6. 입력 유효성 — 빈/None 입력 처리
"""

from __future__ import annotations

import pytest

from core.category_mapper import (
    REASON_EMART_NO_CATEGORY,
    REASON_INVALID_INPUT,
    REASON_UNMAPPED_NEW_CATEGORY,
    CategoryTree,
    MappedCategory,
    load_tree,
    map_costco,
    map_emart,
    map_homeplus,
    map_lottemart,
)


# ────────────────────────────────────────────────────────────────
# 헬퍼
# ────────────────────────────────────────────────────────────────

def assert_mapped(result: tuple, expected_id: str) -> MappedCategory:
    """성공 케이스 공통 검증."""
    mapped, reason = result
    assert reason is None, f"reason should be None for success, got: {reason}"
    assert mapped is not None, "MappedCategory should not be None"
    assert isinstance(mapped, MappedCategory)
    assert mapped.internal_node_id == expected_id, (
        f"expected node_id={expected_id!r}, got={mapped.internal_node_id!r}"
    )
    assert mapped.confidence == 1.0
    assert len(mapped.internal_path) >= 1
    assert mapped.internal_path[-1] == expected_id
    assert mapped.source_raw  # non-empty
    return mapped


def assert_unmapped(result: tuple, expected_reason: str) -> None:
    """실패 케이스 공통 검증."""
    mapped, reason = result
    assert mapped is None, f"MappedCategory should be None, got: {mapped}"
    assert reason == expected_reason, (
        f"expected reason={expected_reason!r}, got={reason!r}"
    )


# ────────────────────────────────────────────────────────────────
# 1. 트리 정합성
# ────────────────────────────────────────────────────────────────

class TestTreeIntegrity:
    """category_tree.yaml 구조 검증."""

    def test_tree_loads_without_error(self):
        tree = load_tree()
        assert isinstance(tree, CategoryTree)

    def test_no_duplicate_ids(self):
        """중복 id가 없어야 함."""
        tree = load_tree()
        ids = list(tree.all_ids())
        assert len(ids) == len(set(ids)), "Duplicate ids found in category_tree.yaml"

    def test_all_parent_ids_exist(self):
        """모든 노드의 parent_id가 트리 내에 존재해야 함."""
        tree = load_tree()
        all_ids = tree.all_ids()
        for node_id in all_ids:
            node = tree.get(node_id)
            assert node is not None
            if node.parent_id is not None:
                assert node.parent_id in all_ids, (
                    f"Node {node_id!r} has parent_id={node.parent_id!r} which doesn't exist"
                )

    def test_level_range_1_to_4(self):
        """모든 노드의 level은 1~4 범위 내."""
        tree = load_tree()
        for node_id in tree.all_ids():
            node = tree.get(node_id)
            assert 1 <= node.level <= 4, (
                f"Node {node_id!r} has level={node.level}, expected 1-4"
            )

    def test_root_nodes_have_no_parent(self):
        """level=1 노드는 parent_id가 null."""
        tree = load_tree()
        for node_id in tree.all_ids():
            node = tree.get(node_id)
            if node.level == 1:
                assert node.parent_id is None, (
                    f"Root node {node_id!r} should have parent_id=None"
                )

    def test_required_fixture_nodes_exist(self):
        """fixture 커버리지를 위한 필수 노드 존재 확인."""
        required = [
            "kitchen_towel", "nut", "imported_beef", "croaker", "socks",
            "egg", "kiwi", "paprika", "tofu", "meal_kit",
            "body_hand_care", "vitamin", "moving_equipment", "bath_tissue",
            "leaf_vegetable", "root_vegetable", "beef_bulgogi", "rice",
        ]
        tree = load_tree()
        missing = [nid for nid in required if tree.get(nid) is None]
        assert not missing, f"Missing required nodes: {missing}"

    def test_path_ids_for_kitchen_towel(self):
        """kitchen_towel 경로: household > sanitary > kitchen_towel."""
        tree = load_tree()
        path = tree.path_ids("kitchen_towel")
        assert path == ["household", "sanitary", "kitchen_towel"]

    def test_path_ids_for_vitamin(self):
        """vitamin 경로: beauty_health > health_supplement > vitamin."""
        tree = load_tree()
        path = tree.path_ids("vitamin")
        assert path == ["beauty_health", "health_supplement", "vitamin"]

    def test_path_ids_for_egg(self):
        """egg 경로: fresh_food > meat_egg > egg."""
        tree = load_tree()
        path = tree.path_ids("egg")
        assert path == ["fresh_food", "meat_egg", "egg"]


# ────────────────────────────────────────────────────────────────
# 2. 홈플러스 매핑
# ────────────────────────────────────────────────────────────────

class TestMapHomeplus:
    """홈플러스 5단계 카테고리 → internal 노드 변환."""

    def test_kitchen_towel(self):
        """fixture: 잘풀리는집 천연펄프 2겹 키친타월 150매*6롤."""
        result = map_homeplus(
            rcateNm="제지/위생/뷰티",
            lcateNm="제지/위생/뷰티",
            mcateNm="화장지/키친타월/물티슈",
            scateNm="키친타월",
            dcateNm="빨아쓰는 키친타월",
        )
        mapped = assert_mapped(result, "kitchen_towel")
        assert "household" in mapped.internal_path

    def test_nut(self):
        """fixture: 머거본 믹스파티 프렌즈 800G(통)."""
        result = map_homeplus(
            rcateNm="견과",
            lcateNm="견과",
            mcateNm="믹스넛/하루견과",
            scateNm="믹스넛",
            dcateNm="믹스넛",
        )
        assert_mapped(result, "nut")

    def test_imported_beef(self):
        """fixture: 호주청정우 앞다리 불고기&샤브샤브 600G(팩)."""
        result = map_homeplus(
            rcateNm="정육/계란",
            lcateNm="정육/계란",
            mcateNm="수입육",
            scateNm="국거리/불고기/다짐/샤브샤브",
            dcateNm="호주산냉장/냉동정육류",
        )
        mapped = assert_mapped(result, "imported_beef")
        assert "fresh_food" in mapped.internal_path
        assert "meat_egg" in mapped.internal_path

    def test_croaker(self):
        """fixture: 영광 참굴비 행사(1.0kg내외/20마리)."""
        result = map_homeplus(
            rcateNm="수산물/건어물",
            lcateNm="수산물/건어물",
            mcateNm="생선",
            scateNm="조기/굴비",
            dcateNm="굴비",
        )
        assert_mapped(result, "croaker")

    def test_socks(self):
        """fixture: 게스남성중목행사로고중목6족양말."""
        result = map_homeplus(
            rcateNm="패션의류/잡화",
            lcateNm="패션잡화",
            mcateNm="양말/스타킹",
            scateNm="양말",
            dcateNm="남성캐쥬얼양말",
        )
        mapped = assert_mapped(result, "socks")
        assert "fashion_apparel" in mapped.internal_path

    def test_chilled_chicken(self):
        """fixture(3-item): simplus 숯불닭꼬치 520G."""
        result = map_homeplus(
            rcateNm="냉장/냉동",
            lcateNm="냉장/냉동/밀키트",
            mcateNm="피자/핫도그/치킨",
            scateNm="치킨",
            dcateNm="치킨",
        )
        assert_mapped(result, "chilled_chicken")

    def test_olive_oil(self):
        """fixture(3-item): simplus 엑스트라버진 올리브유 1L."""
        result = map_homeplus(
            rcateNm="장류/양념/제빵",
            lcateNm="장류/양념/제빵",
            mcateNm="식용유/참기름",
            scateNm="올리브유",
            dcateNm="올리브유",
        )
        assert_mapped(result, "olive_oil")

    def test_unmapped_returns_none_and_reason(self):
        """존재하지 않는 카테고리 → None + UNMAPPED_NEW_CATEGORY."""
        result = map_homeplus(
            rcateNm="가짜대분류",
            lcateNm="가짜중분류",
            mcateNm="가짜소분류",
            scateNm="가짜세분류",
            dcateNm="",
        )
        assert_unmapped(result, REASON_UNMAPPED_NEW_CATEGORY)

    def test_invalid_empty_input(self):
        """필수 필드 빈 문자열 → INVALID_INPUT."""
        result = map_homeplus(
            rcateNm="",
            lcateNm="",
            mcateNm="",
            scateNm="",
        )
        assert_unmapped(result, REASON_INVALID_INPUT)

    def test_dcateNm_does_not_affect_mapping(self):
        """dcateNm이 달라도 scateNm까지 같으면 동일 매핑."""
        r1 = map_homeplus("견과", "견과", "믹스넛/하루견과", "믹스넛", "믹스넛A")
        r2 = map_homeplus("견과", "견과", "믹스넛/하루견과", "믹스넛", "믹스넛B")
        assert r1[0].internal_node_id == r2[0].internal_node_id == "nut"


# ────────────────────────────────────────────────────────────────
# 3. 롯데마트 매핑
# ────────────────────────────────────────────────────────────────

class TestMapLottemart:
    """롯데마트 categoryPath 배열 → internal 노드 변환."""

    def test_egg(self):
        """fixture: 행복생생란 (특란, 30입)."""
        result = map_lottemart(["정육ㆍ계란", "계란ㆍ메추리알", "일반란"])
        mapped = assert_mapped(result, "egg")
        assert "fresh_food" in mapped.internal_path

    def test_kiwi(self):
        """fixture: 제스프리 골드키위 (EA)."""
        result = map_lottemart(["과일", "파인애플ㆍ키위", "키위ㆍ참다래"])
        assert_mapped(result, "kiwi")

    def test_paprika(self):
        """fixture: 국내산 파프리카 (개)."""
        result = map_lottemart(["채소", "고추ㆍ파프리카ㆍ피망", "파프리카"])
        mapped = assert_mapped(result, "paprika")
        assert "vegetable" in mapped.internal_path

    def test_tofu(self):
        """fixture: 풀무원 국산 부침두부 (340G).
        롯데마트는 두부를 '채소' 하위에 분류하지만,
        internal 노드는 processed_food > tofu_soy > tofu."""
        result = map_lottemart(["채소", "두부ㆍ나또ㆍ콩나물ㆍ숙주나물", "두부"])
        mapped = assert_mapped(result, "tofu")
        assert "processed_food" in mapped.internal_path

    def test_meal_kit(self):
        """fixture: CJ 고메 중화짬뽕 (2인분) (652G)."""
        result = map_lottemart(["간편식ㆍ밀키트", "밀키트", "중식"])
        assert_mapped(result, "meal_kit")

    def test_unmapped_returns_none_and_reason(self):
        """존재하지 않는 경로 → None + UNMAPPED_NEW_CATEGORY."""
        result = map_lottemart(["없는카테고리", "없는중분류", "없는소분류"])
        assert_unmapped(result, REASON_UNMAPPED_NEW_CATEGORY)

    def test_empty_list_invalid(self):
        """빈 리스트 → INVALID_INPUT."""
        result = map_lottemart([])
        assert_unmapped(result, REASON_INVALID_INPUT)

    def test_single_element_path(self):
        """단일 원소 경로 — 미매핑이어도 crash 없음."""
        result = map_lottemart(["단일카테고리"])
        # 매핑에 없으므로 UNMAPPED_NEW_CATEGORY
        assert_unmapped(result, REASON_UNMAPPED_NEW_CATEGORY)

    def test_source_raw_preserves_middle_dot(self):
        """source_raw에 ㆍ 원문이 보존되는지 확인."""
        result = map_lottemart(["정육ㆍ계란", "계란ㆍ메추리알", "일반란"])
        mapped, _ = result
        assert "ㆍ" in mapped.source_raw


# ────────────────────────────────────────────────────────────────
# 4. 코스트코 매핑
# ────────────────────────────────────────────────────────────────

class TestMapCostco:
    """코스트코 URL 경로 → internal 노드 변환."""

    def test_body_hand_care_full_url(self):
        """fixture: Bioderma Atoderm Ultra Cream — 전체 URL 형식."""
        result = map_costco(
            "/BeautyHouseholdPersonal-Care/BathBodyOral-Care/Body-LotionBody-Cream"
            "/Bioderma-Atoderm-Ultra-Cream-500ml-x-2/p/602630"
        )
        mapped = assert_mapped(result, "body_hand_care")
        assert "beauty_health" in mapped.internal_path
        assert "skin_care" in mapped.internal_path

    def test_vitamin_full_url(self):
        """fixture: Daewoong Pharm Impactamune 84ct."""
        result = map_costco(
            "/HealthSupplement/VitaminMineral/Multi-Vitamin"
            "/Daewoong-Pharm-Impactamune-84ct/p/658831"
        )
        assert_mapped(result, "vitamin")

    def test_moving_equipment_hand_truck(self):
        """fixture: Stanley Folding Hand Truck 2-IN-1 (핸드트럭)."""
        result = map_costco(
            "/HardwareAutomotive/Power-ToolsWork-Equipment/Building-Materials"
            "/Stanley-Folding-Hand-Truck-2-IN-1/p/629419"
        )
        mapped = assert_mapped(result, "moving_equipment")
        assert "home_kitchen" in mapped.internal_path

    def test_bath_tissue_kleenex_pure(self):
        """fixture: Kleenex Pure Soft Mega Rolls Bath Tissue 40m x 60 (화장지 1)."""
        result = map_costco(
            "/BeautyHouseholdPersonal-Care/BathFacial-Tissue/BathFacial-Tissue"
            "/Kleenex-Pure-Soft-Mega-Rolls-Bath-Tissue-40m-x-60/p/718582"
        )
        mapped = assert_mapped(result, "bath_tissue")
        assert "household" in mapped.internal_path

    def test_bath_tissue_kleenex_deco(self):
        """fixture: Kleenex Deco Soft Bath Tissue 40m x 30roll x 2 (화장지 2).
        다른 상품이지만 같은 category path → 같은 internal 노드."""
        result = map_costco(
            "/BeautyHouseholdPersonal-Care/BathFacial-Tissue/BathFacial-Tissue"
            "/Kleenex-Deco-Soft-Bath-Tissue-40m-x-30roll-x-2/p/529204"
        )
        assert_mapped(result, "bath_tissue")

    def test_category_only_path_no_product(self):
        """상품명 세그먼트 없는 카테고리 경로도 처리."""
        result = map_costco(
            "/BeautyHouseholdPersonal-Care/BathFacial-Tissue/BathFacial-Tissue"
        )
        assert_mapped(result, "bath_tissue")

    def test_unmapped_returns_none_and_reason(self):
        """매핑 테이블에 없는 경로 → None + UNMAPPED_NEW_CATEGORY."""
        result = map_costco("/NonExistent/Category/Path/Product/p/99999")
        assert_unmapped(result, REASON_UNMAPPED_NEW_CATEGORY)

    def test_empty_url_invalid(self):
        """빈 URL → INVALID_INPUT."""
        result = map_costco("")
        assert_unmapped(result, REASON_INVALID_INPUT)

    def test_url_without_p_segment(self):
        """'/p/' 없는 URL도 정상 처리."""
        result = map_costco(
            "BeautyHouseholdPersonal-Care/BathBodyOral-Care/Body-LotionBody-Cream"
        )
        assert_mapped(result, "body_hand_care")


# ────────────────────────────────────────────────────────────────
# 5. 이마트 매핑
# ────────────────────────────────────────────────────────────────

class TestMapEmart:
    """이마트 — 카테고리 없음 → 항상 None + reason."""

    def test_cabbage_always_none(self):
        """fixture: 한끼 양배추 800g — siteNo=7009."""
        result = map_emart("[농할 20%쿠폰 상세 다운] 한끼 양배추 800g 통", site_no="7009")
        assert_unmapped(result, REASON_EMART_NO_CATEGORY)

    def test_potato_always_none(self):
        """fixture: 김제 햇 감자 1.5kg 박스 — siteNo=6001."""
        result = map_emart("[농할 20%쿠폰 상세 다운] 김제 햇 감자 1.5kg 박스", site_no="6001")
        assert_unmapped(result, REASON_EMART_NO_CATEGORY)

    def test_paprika_always_none(self):
        """fixture: 씨없는 아삭 파프리카(봉)."""
        result = map_emart("씨없는 아삭 파프리카(봉)", site_no="6001")
        assert_unmapped(result, REASON_EMART_NO_CATEGORY)

    def test_beef_bulgogi_always_none(self):
        """fixture: [냉장] 언양식 소불고기 500g — siteNo=7009."""
        result = map_emart("[냉장] 언양식 소불고기 500g", site_no="7009")
        assert_unmapped(result, REASON_EMART_NO_CATEGORY)

    def test_rice_always_none(self):
        """fixture: 철원 오대쌀 10kg — siteNo=7009."""
        result = map_emart("철원 오대쌀 10kg", site_no="7009")
        assert_unmapped(result, REASON_EMART_NO_CATEGORY)

    def test_no_site_no_also_none(self):
        """site_no 없어도 동일하게 None."""
        result = map_emart("임의 상품명")
        assert_unmapped(result, REASON_EMART_NO_CATEGORY)


# ────────────────────────────────────────────────────────────────
# 6. 내부 경로 일관성
# ────────────────────────────────────────────────────────────────

class TestInternalPathConsistency:
    """internal_path가 트리 구조와 일치하는지 검증."""

    def test_path_is_ancestry_chain(self):
        """모든 매핑 결과의 internal_path가 트리 상 실제 부모-자식 체인인지 확인."""
        tree = load_tree()
        test_cases = [
            map_homeplus("제지/위생/뷰티", "제지/위생/뷰티", "화장지/키친타월/물티슈", "키친타월"),
            map_lottemart(["정육ㆍ계란", "계란ㆍ메추리알", "일반란"]),
            map_costco("/HealthSupplement/VitaminMineral/Multi-Vitamin/p/123"),
        ]
        for mapped, reason in test_cases:
            assert mapped is not None
            for i in range(1, len(mapped.internal_path)):
                child_id = mapped.internal_path[i]
                parent_id = mapped.internal_path[i - 1]
                child_node = tree.get(child_id)
                assert child_node is not None
                assert child_node.parent_id == parent_id, (
                    f"Path broken: {parent_id!r} is not parent of {child_id!r}"
                )
