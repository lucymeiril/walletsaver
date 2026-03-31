"""카테고리 트리 빌드 및 계층 검증 테스트."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from category_data.categories import (
    CATEGORIES,
    find_category,
    get_children,
    get_descendants,
    get_ancestors,
    get_root_categories,
    get_all_ids,
    get_category_tree,
    flatten_tree,
    validate_tree,
)


class TestCategoryData:
    """카테고리 데이터 무결성 테스트."""

    def test_total_count_minimum(self):
        """300개 이상 카테고리가 있어야 한다."""
        assert len(CATEGORIES) >= 300

    def test_no_duplicate_ids(self):
        """카테고리 ID 가 중복되지 않아야 한다."""
        ids = [c["id"] for c in CATEGORIES]
        assert len(ids) == len(set(ids)), f"중복 ID 발견: {len(ids) - len(set(ids))}개"

    def test_all_categories_have_required_fields(self):
        """필수 필드가 모두 있어야 한다."""
        required = {"id", "name", "parent_id", "depth", "sort_order", "is_active"}
        for cat in CATEGORIES:
            missing = required - set(cat.keys())
            assert not missing, f"카테고리 {cat['id']} 에 필드 누락: {missing}"

    def test_parent_id_references_exist(self):
        """parent_id 가 가리키는 카테고리가 존재해야 한다."""
        all_ids = set(get_all_ids())
        for cat in CATEGORIES:
            if cat["parent_id"] is not None:
                assert cat["parent_id"] in all_ids, \
                    f"{cat['id']}: parent_id '{cat['parent_id']}' 가 존재하지 않음"

    def test_depth_consistency(self):
        """depth 가 parent 의 depth + 1 이어야 한다."""
        idx = {c["id"]: c for c in CATEGORIES}
        for cat in CATEGORIES:
            if cat["parent_id"]:
                parent = idx[cat["parent_id"]]
                assert cat["depth"] == parent["depth"] + 1, \
                    f"{cat['id']}: depth={cat['depth']}, parent depth={parent['depth']}"

    def test_root_categories_have_depth_zero(self):
        """루트 카테고리는 depth=0 이어야 한다."""
        for cat in CATEGORIES:
            if cat["parent_id"] is None:
                assert cat["depth"] == 0, f"{cat['id']}: 루트인데 depth={cat['depth']}"

    def test_validate_tree_returns_no_errors(self):
        """트리 검증에서 오류가 없어야 한다."""
        errors = validate_tree()
        assert errors == [], f"검증 오류: {errors}"

    def test_all_active_by_default(self):
        """모든 카테고리가 기본적으로 활성화되어야 한다."""
        for cat in CATEGORIES:
            assert cat["is_active"] is True


class TestCategoryHierarchy:
    """카테고리 계층 구조 테스트."""

    def test_root_categories_exist(self):
        """루트 카테고리가 존재해야 한다."""
        roots = get_root_categories()
        assert len(roots) >= 20  # 최소 20개 최상위

    def test_root_category_names(self):
        """주요 최상위 카테고리가 있어야 한다."""
        root_names = {c["name"] for c in get_root_categories()}
        expected = {"농산물", "축산물", "수산물", "가공식품", "생활용품", "음료",
                    "유제품", "주류", "건강식품", "간식", "주유소", "식당",
                    "배달", "의류", "가전", "디지털", "가구", "화장품"}
        missing = expected - root_names
        assert not missing, f"누락된 최상위 카테고리: {missing}"

    def test_agriculture_subcategories(self):
        """농산물에 하위 카테고리(엽채류, 과채류, 근채류, 과일류, 버섯류)가 있어야 한다."""
        children = get_children("agriculture")
        names = {c["name"] for c in children}
        expected = {"엽채류", "과채류", "근채류", "과일류", "버섯류", "곡류"}
        missing = expected - names
        assert not missing, f"누락된 농산물 하위: {missing}"

    def test_agriculture_has_50_plus_descendants(self):
        """농산물에 50개 이상의 모든 하위 카테고리가 있어야 한다."""
        descendants = get_descendants("agriculture")
        assert len(descendants) >= 50

    def test_livestock_subcategories(self):
        """축산물에 소고기, 돼지고기, 닭고기 등이 있어야 한다."""
        children = get_children("livestock")
        names = {c["name"] for c in children}
        assert "소고기" in names
        assert "돼지고기" in names
        assert "닭고기" in names

    def test_seafood_subcategories(self):
        """수산물에 생선, 갑각류, 조개류 등이 있어야 한다."""
        children = get_children("seafood")
        names = {c["name"] for c in children}
        assert "생선" in names
        assert "갑각류" in names
        assert "조개류" in names


class TestCategoryLookup:
    """카테고리 검색 테스트."""

    def test_find_existing_category(self):
        """존재하는 카테고리를 찾을 수 있어야 한다."""
        cat = find_category("livestock.pork.belly")
        assert cat is not None
        assert cat["name"] == "삼겹살"

    def test_find_nonexistent_category(self):
        """존재하지 않는 카테고리는 None."""
        assert find_category("nonexistent.category") is None

    def test_get_children(self):
        """직접 자식을 반환해야 한다."""
        children = get_children("beverage")
        assert len(children) >= 5  # water, soda, juice, coffee, tea, ...

    def test_get_ancestors(self):
        """조상 카테고리를 반환해야 한다."""
        ancestors = get_ancestors("agriculture.fruit.apple")
        ancestor_ids = [a["id"] for a in ancestors]
        assert "agriculture.fruit" in ancestor_ids
        assert "agriculture" in ancestor_ids

    def test_get_ancestors_root(self):
        """루트 카테고리의 조상은 빈 리스트."""
        ancestors = get_ancestors("agriculture")
        assert ancestors == []

    def test_get_all_ids(self):
        """모든 ID 를 반환해야 한다."""
        ids = get_all_ids()
        assert len(ids) == len(CATEGORIES)


class TestCategoryTree:
    """카테고리 트리 빌드 테스트."""

    def test_tree_has_root_nodes(self):
        """트리에 루트 노드가 있어야 한다."""
        tree = get_category_tree()
        assert len(tree) >= 20

    def test_tree_nodes_have_children(self):
        """트리 노드에 children 리스트가 있어야 한다."""
        tree = get_category_tree()
        for node in tree:
            assert "children" in node

    def test_agriculture_tree_has_children(self):
        """농산물 트리 노드에 자식이 있어야 한다."""
        tree = get_category_tree()
        agri = next(n for n in tree if n["id"] == "agriculture")
        assert len(agri["children"]) >= 5

    def test_flatten_tree_roundtrip(self):
        """트리 → flat → 갯수 일치."""
        tree = get_category_tree()
        flat = flatten_tree(tree)
        assert len(flat) == len(CATEGORIES)
