"""
카테고리 트리 + 속성 태그 시스템.

"양파가 다 같은 양파가 아니다" — 계층 분류 + 속성 태그 하이브리드.

사용 예:
    tree = CategoryTree()
    tree.add("축산물", "돼지고기", "삼겹살")
    tree.add("축산물", "돼지고기", "앞다리")
    node = tree.find("삼겹살")
    node.path  # "축산물 > 돼지고기 > 삼겹살"
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class ProductAttribute(BaseModel):
    """상품 속성 태그 — 같은 품목도 속성에 따라 가격이 다름."""
    key: str        # "storage", "origin", "grade", "cert", "type"
    value: str      # "냉동", "국산", "1등급", "동물복지", "PB"

    def __str__(self) -> str:
        return f"{self.key}={self.value}"


# 표준 속성 키 정의
class AttrKeys:
    STORAGE = "storage"       # 보관: 냉동/냉장/실온
    ORIGIN = "origin"         # 원산지: 국산/미국/호주/스페인
    GRADE = "grade"           # 등급: 1++/1+/1/2/3
    CERT = "cert"             # 인증: 동물복지/무항생제/유기농/HACCP
    PRODUCT_TYPE = "type"     # 유형: 마트PB/일반/프리미엄/대용량
    UNIT = "unit"             # 단위: 100g/kg/팩/묶음
    BRAND = "brand"           # 브랜드: 하림/목우촌 등

# 표준 속성 값 정의
STORAGE_VALUES = ["냉동", "냉장", "실온", "생물"]
ORIGIN_VALUES = ["국산", "미국", "호주", "캐나다", "스페인", "독일", "페루", "칠레", "뉴질랜드", "중국"]
GRADE_VALUES = ["1++", "1+", "1등급", "2등급", "3등급", "특", "상", "보통"]
CERT_VALUES = ["동물복지", "무항생제", "유기농", "HACCP", "GAP", "친환경"]


class CategoryNode(BaseModel):
    """카테고리 트리의 노드."""
    id: int = 0
    name: str
    parent_name: Optional[str] = None
    depth: int = 0
    path: str = ""
    children: list[CategoryNode] = Field(default_factory=list)
    # 이 카테고리에 적용 가능한 속성 키
    applicable_attrs: list[str] = Field(default_factory=list)

    def add_child(self, child: CategoryNode) -> CategoryNode:
        child.parent_name = self.name
        child.depth = self.depth + 1
        child.path = f"{self.path} > {child.name}" if self.path else child.name
        self.children.append(child)
        return child

    def find(self, name: str) -> Optional[CategoryNode]:
        if self.name == name:
            return self
        for child in self.children:
            result = child.find(name)
            if result:
                return result
        return None

    def all_leaves(self) -> list[CategoryNode]:
        if not self.children:
            return [self]
        leaves = []
        for c in self.children:
            leaves.extend(c.all_leaves())
        return leaves

    def all_nodes(self) -> list[CategoryNode]:
        nodes = [self]
        for c in self.children:
            nodes.extend(c.all_nodes())
        return nodes


class CategoryTree:
    """계층형 카테고리 트리 — KAMIS 기반."""

    def __init__(self):
        self.root = CategoryNode(name="전체", path="전체")
        self._id_counter = 1

    def add(self, *path: str, attrs: list[str] | None = None) -> CategoryNode:
        """경로를 따라 노드 추가. 이미 있으면 기존 노드 반환."""
        current = self.root
        for name in path:
            existing = None
            for child in current.children:
                if child.name == name:
                    existing = child
                    break
            if existing:
                current = existing
            else:
                node = CategoryNode(id=self._id_counter, name=name)
                self._id_counter += 1
                current.add_child(node)
                current = node
        if attrs:
            current.applicable_attrs = attrs
        return current

    def find(self, name: str) -> Optional[CategoryNode]:
        return self.root.find(name)

    def all_categories(self) -> list[CategoryNode]:
        return self.root.all_nodes()[1:]  # root 제외

    def get_path(self, name: str) -> str:
        node = self.find(name)
        return node.path if node else ""


def build_default_tree() -> CategoryTree:
    """KAMIS 기반 기본 카테고리 트리 구축."""
    tree = CategoryTree()

    # 채소류
    tree.add("채소류", "엽경채류", "배추", attrs=[AttrKeys.ORIGIN, AttrKeys.STORAGE])
    tree.add("채소류", "엽경채류", "양배추", attrs=[AttrKeys.ORIGIN, AttrKeys.STORAGE])
    tree.add("채소류", "엽경채류", "시금치")
    tree.add("채소류", "근채류", "양파", attrs=[AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("채소류", "근채류", "감자", attrs=[AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("채소류", "근채류", "당근")
    tree.add("채소류", "과채류", "토마토")
    tree.add("채소류", "과채류", "오이")
    tree.add("채소류", "과채류", "고추")
    tree.add("채소류", "조미채소", "대파")
    tree.add("채소류", "조미채소", "마늘")
    tree.add("채소류", "조미채소", "생강")

    # 과일류
    tree.add("과일류", "사과", attrs=[AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("과일류", "배")
    tree.add("과일류", "감귤")
    tree.add("과일류", "포도")
    tree.add("과일류", "딸기")
    tree.add("과일류", "바나나", attrs=[AttrKeys.ORIGIN])
    tree.add("과일류", "수박")

    # 축산물
    tree.add("축산물", "돼지고기", "삼겹살", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN, AttrKeys.GRADE, AttrKeys.CERT])
    tree.add("축산물", "돼지고기", "앞다리", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN])
    tree.add("축산물", "돼지고기", "목살", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN])
    tree.add("축산물", "돼지고기", "갈비", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN])
    tree.add("축산물", "소고기", "등심", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("축산물", "소고기", "갈비살", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("축산물", "소고기", "안심", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("축산물", "닭고기", "가슴살", attrs=[AttrKeys.STORAGE, AttrKeys.CERT])
    tree.add("축산물", "닭고기", "통닭", attrs=[AttrKeys.STORAGE, AttrKeys.CERT])
    tree.add("축산물", "란류", "계란", attrs=[AttrKeys.CERT, AttrKeys.ORIGIN])

    # 수산물
    tree.add("수산물", "생선류", "고등어", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN])
    tree.add("수산물", "생선류", "갈치")
    tree.add("수산물", "생선류", "명태")
    tree.add("수산물", "갑각류", "새우", attrs=[AttrKeys.STORAGE, AttrKeys.ORIGIN])
    tree.add("수산물", "갑각류", "킹크랩", attrs=[AttrKeys.STORAGE])
    tree.add("수산물", "패류", "홍합")
    tree.add("수산물", "패류", "조개")

    # 곡류
    tree.add("곡류", "쌀", attrs=[AttrKeys.ORIGIN, AttrKeys.GRADE])
    tree.add("곡류", "보리")
    tree.add("곡류", "잡곡")

    # 유제품
    tree.add("유제품", "우유", attrs=[AttrKeys.BRAND, AttrKeys.CERT])
    tree.add("유제품", "요거트")
    tree.add("유제품", "치즈")
    tree.add("유제품", "버터")

    # 가공식품
    tree.add("가공식품", "면류", "라면", attrs=[AttrKeys.BRAND])
    tree.add("가공식품", "면류", "국수")
    tree.add("가공식품", "즉석밥", attrs=[AttrKeys.BRAND])
    tree.add("가공식품", "통조림", attrs=[AttrKeys.BRAND])
    tree.add("가공식품", "두부", attrs=[AttrKeys.BRAND, AttrKeys.STORAGE])
    tree.add("가공식품", "만두", attrs=[AttrKeys.BRAND, AttrKeys.STORAGE])
    tree.add("가공식품", "냉동식품")

    # 조미료
    tree.add("조미료", "유지류", "식용유")
    tree.add("조미료", "장류", "간장")
    tree.add("조미료", "장류", "된장")
    tree.add("조미료", "장류", "고추장")
    tree.add("조미료", "설탕")
    tree.add("조미료", "소금")

    # 음료
    tree.add("음료", "탄산음료")
    tree.add("음료", "주스")
    tree.add("음료", "커피")
    tree.add("음료", "생수")

    return tree
