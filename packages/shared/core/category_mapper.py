"""
카테고리 변환기 — WalletSavior Phase B3

역할:
    4사(홈플러스·롯데마트·코스트코·이마트) raw 카테고리를
    WalletSavior 통합 카테고리 트리의 내부 노드 ID로 변환한다.

설계 원칙:
    - 매핑 테이블은 YAML 파일(category_mappings/*.yaml)에 있으므로
      새 카테고리 키 추가 시 이 코드를 수정할 필요 없음.
    - 미매핑 raw는 silent drop 금지. 반드시 (None, reason_code) 반환.
    - 슬래시/ㆍ 등 마트별 OR 구분자는 이 모듈에서 처리하고
      외부에는 정규화된 internal_path만 노출.
    - 트리는 프로세스당 한 번만 로드(캐시).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

# YAML 파일 위치 — 이 파일 기준 상대 경로
_DATA_DIR = Path(__file__).parent.parent / "data"
_TREE_FILE = _DATA_DIR / "category_tree.yaml"
_MAPPINGS_DIR = _DATA_DIR / "category_mappings"

# ── 리뷰 큐 reason 코드 ─────────────────────────────────────────
# 변환기가 실패할 때 반환하는 reason code.
# ProductReviewQueue 소비자가 이 코드로 처리 방식을 분기할 수 있음.
REASON_UNMAPPED_NEW_CATEGORY = "UNMAPPED_NEW_CATEGORY"
REASON_EMART_NO_CATEGORY = "EMART_NO_CATEGORY_IN_RESPONSE"
REASON_INVALID_INPUT = "INVALID_INPUT"


@dataclass
class CategoryNode:
    """통합 카테고리 트리의 단일 노드."""
    id: str
    name_kr: str
    name_en: str
    parent_id: Optional[str]
    display_order: int
    default_unit_kind: str
    level: int = 1  # 1=대분류, 2=중분류, 3=소분류, 4=세분류


@dataclass
class CategoryTree:
    """
    통합 카테고리 트리 — category_tree.yaml에서 로드.

    사용법:
        tree = load_tree()
        node = tree.get("kitchen_towel")
        path = tree.path_ids("kitchen_towel")  # ["household", "sanitary", "kitchen_towel"]
    """
    _nodes: dict[str, CategoryNode] = field(default_factory=dict)

    def get(self, node_id: str) -> Optional[CategoryNode]:
        return self._nodes.get(node_id)

    def path_ids(self, node_id: str) -> list[str]:
        """루트→node_id 경로의 id 목록 반환."""
        path = []
        current_id: Optional[str] = node_id
        while current_id is not None:
            node = self._nodes.get(current_id)
            if node is None:
                break
            path.append(node.id)
            current_id = node.parent_id
        return list(reversed(path))

    def all_ids(self) -> set[str]:
        return set(self._nodes.keys())


@dataclass
class MappedCategory:
    """
    변환 결과 DTO.

    internal_node_id : 트리 노드의 stable id (예: "kitchen_towel")
    internal_path    : 루트에서 노드까지의 id 경로
                       (예: ["household", "sanitary", "kitchen_towel"])
    confidence       : 1.0 = 정확 매핑, < 1.0 = 퍼지/추정 매핑
    source_raw       : 매핑에 사용된 raw 카테고리 문자열 (디버깅·감사용)
    """
    internal_node_id: str
    internal_path: list[str]
    confidence: float
    source_raw: str


# ── 트리 로딩 ────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_tree() -> CategoryTree:
    """
    category_tree.yaml을 파싱해 CategoryTree를 반환한다.
    프로세스당 최초 1회만 파싱(lru_cache).
    """
    with open(_TREE_FILE, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    nodes_raw: list[dict] = raw.get("nodes", [])
    nodes: dict[str, CategoryNode] = {}

    for item in nodes_raw:
        node_id = item["id"]
        parent_id = item.get("parent_id")

        # level 계산: parent 체인을 따라가며 depth 산출
        # YAML이 순서대로 로드된다고 가정 (parent가 항상 먼저 등장)
        level = 1
        pid = parent_id
        while pid is not None:
            parent_node = nodes.get(pid)
            if parent_node is None:
                break
            level = parent_node.level + 1
            break

        nodes[node_id] = CategoryNode(
            id=node_id,
            name_kr=item["name_kr"],
            name_en=item.get("name_en", ""),
            parent_id=parent_id if parent_id else None,
            display_order=item.get("display_order", 0),
            default_unit_kind=item.get("default_unit_kind", "EACH"),
            level=level,
        )

    return CategoryTree(_nodes=nodes)


@lru_cache(maxsize=4)
def _load_mapping(mart: str) -> dict[str, str]:
    """
    category_mappings/{mart}.yaml을 로드해 {raw_key: internal_node_id} 반환.
    프로세스당 최초 1회만 파싱.
    """
    path = _MAPPINGS_DIR / f"{mart}.yaml"
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("mappings", {}) or {}


def _resolve(raw_key: str, mart: str, source_raw: str) -> tuple[MappedCategory | None, str | None]:
    """
    raw_key를 mart 매핑 테이블에서 조회해 MappedCategory 또는 (None, reason) 반환.
    내부 헬퍼 — 외부에서 직접 호출 금지.
    """
    mapping = _load_mapping(mart)
    node_id = mapping.get(raw_key)
    if node_id is None:
        return None, REASON_UNMAPPED_NEW_CATEGORY

    tree = load_tree()
    node = tree.get(node_id)
    if node is None:
        # 매핑 테이블에는 있으나 트리에 없는 경우 — 데이터 불일치
        return None, REASON_UNMAPPED_NEW_CATEGORY

    return MappedCategory(
        internal_node_id=node_id,
        internal_path=tree.path_ids(node_id),
        confidence=1.0,
        source_raw=source_raw,
    ), None


# ── 마트별 공개 API ──────────────────────────────────────────────

def map_homeplus(
    rcateNm: str,
    lcateNm: str,
    mcateNm: str,
    scateNm: str,
    dcateNm: str = "",
) -> tuple[MappedCategory | None, str | None]:
    """
    홈플러스 5단계 카테고리를 통합 트리 노드로 변환.

    키 구성: "rcateNm|lcateNm|mcateNm|scateNm"
      - dcateNm(5단계)은 키에서 제외: 동일 scateNm 안에서 dcateNm만 다른 상품들을
        같은 internal 노드로 collapse.
      - 슬래시(/)는 홈플러스 OR 표기로 원문 그대로 키에 포함.

    반환:
      (MappedCategory, None) 성공
      (None, reason_code)    실패
    """
    if not all([rcateNm, lcateNm, mcateNm, scateNm]):
        return None, REASON_INVALID_INPUT

    raw_key = f"{rcateNm}|{lcateNm}|{mcateNm}|{scateNm}"
    return _resolve(raw_key, "homeplus", raw_key)


def map_lottemart(
    category_path: list[str],
) -> tuple[MappedCategory | None, str | None]:
    """
    롯데마트 categoryPath 배열을 통합 트리 노드로 변환.

    키 구성: "/".join(category_path)
      - "ㆍ" 구분자는 단일 토큰으로 유지 (분리하지 않음).
        예: ["정육ㆍ계란", "계란ㆍ메추리알", "일반란"] → "정육ㆍ계란/계란ㆍ메추리알/일반란"
      - "ㆍ"의 OR 의미(여러 카테고리 합성 표기)는 internal 단일 노드로 collapse.

    반환:
      (MappedCategory, None) 성공
      (None, reason_code)    실패
    """
    if not category_path or not all(s.strip() for s in category_path):
        return None, REASON_INVALID_INPUT

    raw_key = "/".join(category_path)
    return _resolve(raw_key, "lottemart", raw_key)


def map_costco(url_path: str) -> tuple[MappedCategory | None, str | None]:
    """
    코스트코 URL 경로를 통합 트리 노드로 변환.

    정규화 규칙 (내부 처리):
      1. 앞뒤 "/" 제거
      2. "/p/" 이후 상품명 세그먼트 제거 → 카테고리 3단계만 추출
      3. 소문자 변환 없이 원문 slug 유지 (CamelCase)

    예:
      "/BeautyHouseholdPersonal-Care/BathBodyOral-Care/Body-LotionBody-Cream/ProductName/p/123"
      → "BeautyHouseholdPersonal-Care/BathBodyOral-Care/Body-LotionBody-Cream"

    반환:
      (MappedCategory, None) 성공
      (None, reason_code)    실패
    """
    if not url_path or not url_path.strip():
        return None, REASON_INVALID_INPUT

    # "/p/" 이후 제거
    normalized = re.sub(r"/p/.*$", "", url_path)
    # 앞뒤 "/" 제거
    normalized = normalized.strip("/")
    # 빈 세그먼트 제거 후 최대 3단계만 사용
    segments = [s for s in normalized.split("/") if s]
    if not segments:
        return None, REASON_INVALID_INPUT

    raw_key = "/".join(segments[:3])
    return _resolve(raw_key, "costco", raw_key)


def map_emart(
    item_name: str,
    site_no: str | None = None,
) -> tuple[MappedCategory | None, str | None]:
    """
    이마트 상품을 통합 트리 노드로 변환.

    현재 상태: 이마트 검색결과 API 응답에 카테고리 정보가 없음.
      - 응답 필드: itemId, itemName, siteNo, salestrNo, brandName 등
      - displayCategory, categoryPath 등 분류 정보 미포함 (확인됨: Phase B3)
      - 따라서 항상 (None, EMART_NO_CATEGORY_IN_RESPONSE) 반환.
      - 해당 상품은 ProductReviewQueue로 전달해 B4에서 처리.

    B4 처리 후보:
      1) 상품 상세 페이지 breadcrumb 파싱
      2) itemName 토큰 기반 분류 (규칙/NLP)
      3) 이마트 카테고리 API 별도 호출

    반환:
      (None, "EMART_NO_CATEGORY_IN_RESPONSE") 항상
    """
    # pylint: disable=unused-argument
    return None, REASON_EMART_NO_CATEGORY


def map_algumon(
    category_hint: str,
) -> tuple[MappedCategory | None, str | None]:
    """
    알구몬 카테고리 힌트(커뮤니티 or 게시 카테고리)를 통합 트리 노드로 변환.

    키: category_hints 첫 번째 토큰 원문
    반환:
      (MappedCategory, None) 성공
      (None, reason_code)    실패
    """
    if not category_hint or not category_hint.strip():
        return None, REASON_INVALID_INPUT
    raw_key = category_hint.strip()
    return _resolve(raw_key, "algumon", raw_key)


def map_kokodalin(
    category_name: str,
) -> tuple[MappedCategory | None, str | None]:
    """
    코코달인 API category_name을 통합 트리 노드로 변환.

    키: API 응답의 category_name 원문 (한글)
    반환:
      (MappedCategory, None) 성공
      (None, reason_code)    실패
    """
    if not category_name or not category_name.strip():
        return None, REASON_INVALID_INPUT
    raw_key = category_name.strip()
    return _resolve(raw_key, "kokodalin", raw_key)
