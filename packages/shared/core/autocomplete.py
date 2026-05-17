"""
WalletSavior Phase B5 — 검색바 자동완성 키워드 인덱스.

역할:
    4사 canonical 상품 목록·카테고리 트리·브랜드 사전·동의어 사전으로부터
    prefix 기반 자동완성 인덱스를 구축한다.
    KoNLPy·MeCab 같은 외부 형태소 분석기 없이 (1) 공백/특수문자 split,
    (2) 동의어 매핑, (3) 브랜드 사전 우선순위로 처리한다.

한계:
    - 한글 자모(초성) 검색 미지원 ('ㅋ' 입력 → 결과 없음). Phase C에서 검토.
    - 형태소 분석 없이 공백 split만 사용하므로 복합어 내부 token 검색 불가
      ('부침두부' 입력 시 '두부'가 별도 토큰으로 추출되지 않음).
      대신 카테고리 트리(예: node 'tofu' → name_kr '두부')로 커버.

사용법:
    from core.autocomplete import (
        build_from_canonical_products, load_synonyms,
        normalize_token, tokenize_name_core,
        AutocompleteIndex, IndexEntry,
    )
    synonyms = load_synonyms()
    index = build_from_canonical_products(canonicals, tree, brand_set, synonyms)
    results = index.suggest("두")
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

_DATA_DIR = Path(__file__).parent.parent / "data"
_SYNONYMS_FILE = _DATA_DIR / "synonyms.yaml"

# 단위어 토큰 집합 — tokenize_name_core에서 제거 대상
# B2 units.py 의 KOREAN_UNIT_MAP 과 중복 정의를 피하면서 로컬 확장
_UNIT_TOKENS: frozenset[str] = frozenset([
    "g", "kg", "ml", "l", "매", "개", "롤", "팩", "봉", "장", "입",
    "정", "ct", "ea", "set", "세트",
])

# 이름 분할 패턴 — 공백, 괄호, 하이픈, 특수 분리자
_SPLIT_RE = re.compile(r"[\s\(\)\[\]\-&/·×,;:\.]+")


# ══════════════════════════════════════════════════════
# 공개 데이터 클래스
# ══════════════════════════════════════════════════════

@dataclass
class IndexEntry:
    """
    자동완성 인덱스의 단일 항목.

    token       : 정규화된 토큰 (소문자·NFC·공백 제거). prefix 매칭에 사용.
    display     : 사용자에게 보일 원본 문자열.
    source      : 항목 출처 — "brand"|"category"|"product_name_core"|"synonym".
    weight      : 추천 가중치. 브랜드 0.9, 카테고리 0.8, 상품명 0.7, 동의어 0.6.
    canonical_id: 상품명 토큰이거나 브랜드 항목인 경우 연결된 CanonicalProduct.id.
    category_node_id: 카테고리 항목인 경우 CategoryNode.id.
    """
    token: str
    display: str
    source: str
    weight: float
    canonical_id: Optional[str] = None
    category_node_id: Optional[str] = None


# ══════════════════════════════════════════════════════
# 정규화 / 토큰화 유틸
# ══════════════════════════════════════════════════════

def normalize_token(s: str) -> str:
    """
    NFC 정규화 → casefold → 공백·특수문자 제거.

    예: "Costco®" → "costco", "키친 타월" → "키친타월", "두부·콩류" → "두부콩류".
    한글·영문·숫자는 보존. 언더스코어는 제거.
    """
    s = unicodedata.normalize("NFC", s)
    s = s.casefold()
    # \w 는 Python 유니코드 모드에서 한글·영문·숫자·_를 포함함
    s = re.sub(r"[^\w]", "", s)
    s = s.replace("_", "")
    return s


def tokenize_name_core(name: str, brand_dict: set, synonyms: dict) -> list[str]:
    """
    상품명 핵심 토큰 추출.

    처리 순서:
      1) 공백·괄호·하이픈 등으로 분할
      2) 빈 토큰 제거
      3) 숫자만인 토큰 제거 ("340", "30" 등)
      4) 단위어 토큰 제거 ("g", "kg", "ml", "매", "개", "롤", "팩", "봉" 등)
      5) 길이 1자 이하 토큰 제거 (한글 1자는 검색 노이즈)
      6) 브랜드 사전 토큰 제거 (brand 소스로 별도 처리되므로)

    반환: 정제된 토큰 원본 리스트 (normalize는 호출자가 적용).
    synonyms 파라미터는 향후 확장을 위해 수용하나 현재는 미사용.
    """
    parts = _SPLIT_RE.split(name)
    tokens = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # 숫자만인 토큰 제거
        if re.fullmatch(r"\d+", part):
            continue
        # 단위어 토큰 제거 (대소문자 무관)
        if normalize_token(part) in _UNIT_TOKENS:
            continue
        # 1자 이하 제거
        if len(part) <= 1:
            continue
        # 브랜드 제거 (브랜드는 별도 source로 인덱싱됨)
        if part in brand_dict:
            continue
        tokens.append(part)
    return tokens


# ══════════════════════════════════════════════════════
# 동의어 로딩
# ══════════════════════════════════════════════════════

@lru_cache(maxsize=1)
def load_synonyms() -> dict[str, list[str]]:
    """
    synonyms.yaml 로드.

    반환: {대표어: [대안 표현 리스트], ...}
    예: {"키친타월": ["키친타올", "키친 타월"], "계란": ["달걀"], ...}

    양방향 검색은 AutocompleteIndex 빌드 단계에서 역방향 항목을 추가해 구현.
    """
    with open(_SYNONYMS_FILE, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return raw.get("synonyms", {}) or {}


# ══════════════════════════════════════════════════════
# 인덱스
# ══════════════════════════════════════════════════════

class AutocompleteIndex:
    """
    prefix 기반 자동완성 인덱스.

    내부적으로 IndexEntry 리스트를 보유하며, suggest() 호출 시 선형 스캔.
    상품 수가 수만 건 이하이면 충분히 빠름.
    규모 확장이 필요하면 trie 또는 DB FTS5 인덱스로 교체 권장 (B6 참고).
    """

    def __init__(self, entries: list[IndexEntry]) -> None:
        self._entries = entries

    def suggest(self, prefix: str, limit: int = 10) -> list[IndexEntry]:
        """
        prefix로 시작하는 IndexEntry 목록 반환.

        - prefix 정규화 후 token.startswith() 매칭.
        - 빈 prefix는 빈 리스트 반환 (노이즈 방지).
        - 정렬: weight 내림차순 → token 오름차순.
        - 중복 제거: (token, source, canonical_id) 기준.
        """
        if not prefix:
            return []
        norm_prefix = normalize_token(prefix)
        if not norm_prefix:
            return []

        matches = [e for e in self._entries if e.token.startswith(norm_prefix)]
        matches.sort(key=lambda e: (-e.weight, e.token))

        seen: set[tuple] = set()
        result: list[IndexEntry] = []
        for e in matches:
            key = (e.token, e.source, e.canonical_id)
            if key not in seen:
                seen.add(key)
                result.append(e)
                if len(result) >= limit:
                    break
        return result

    def stats(self) -> dict:
        """인덱스 통계 — 총 토큰 수, 소스별 분포."""
        source_counts = Counter(e.source for e in self._entries)
        return {
            "total_tokens": len(self._entries),
            "by_source": dict(source_counts),
        }


# ══════════════════════════════════════════════════════
# 빌더
# ══════════════════════════════════════════════════════

def build_from_canonical_products(
    canonicals: list,        # list[CanonicalProduct]
    category_tree,           # CategoryTree from category_mapper
    brand_dict: set,         # set of brand name strings
    synonyms: dict,          # {canonical_term: [alt_terms]}
) -> AutocompleteIndex:
    """
    CanonicalProduct 목록으로부터 AutocompleteIndex 구축.

    인덱싱 순서:
      1) 카테고리 트리 전체 노드 → category 항목 (weight 0.8)
      2) 각 canonical의 brand → brand 항목 (weight 0.9)
      3) 각 canonical의 name_core 토큰 → product_name_core 항목 (weight 0.7)
      4) synonyms → alt 형태가 canonical 형태를 가리키는 synonym 항목 (weight 0.6)

    중복 제거: (normalize_token, source, canonical_id) 기준으로 동일 항목 재추가 방지.
    """
    entries: list[IndexEntry] = []
    seen: set[tuple] = set()

    def _add(
        display: str,
        source: str,
        weight: float,
        canonical_id: Optional[str] = None,
        category_node_id: Optional[str] = None,
    ) -> None:
        """중복 방지하며 entries에 추가."""
        tok = normalize_token(display)
        if not tok:
            return
        key = (tok, source, canonical_id)
        if key in seen:
            return
        seen.add(key)
        entries.append(IndexEntry(
            token=tok,
            display=display,
            source=source,
            weight=weight,
            canonical_id=canonical_id,
            category_node_id=category_node_id,
        ))

    # 1. 카테고리 트리 전체 노드
    for node_id in sorted(category_tree.all_ids()):
        node = category_tree.get(node_id)
        if node and node.name_kr:
            _add(node.name_kr, "category", 0.8, category_node_id=node_id)

    # 2. 브랜드 항목 + 3. 상품명 토큰
    for canonical in canonicals:
        cid = canonical.id

        if canonical.brand:
            _add(canonical.brand, "brand", 0.9, canonical_id=cid)

        name_tokens = tokenize_name_core(canonical.name_core, brand_dict, synonyms)
        for tok_display in name_tokens:
            _add(tok_display, "product_name_core", 0.7, canonical_id=cid)

    # 4. 동의어 항목 — 대안어 → 대표어 방향 (alt → canonical_display)
    for canonical_display, alts in synonyms.items():
        for alt in alts:
            # alt를 검색하면 canonical_display가 결과로 나옴
            alt_tok = normalize_token(alt)
            if not alt_tok:
                continue
            key = (alt_tok, "synonym", None)
            if key in seen:
                continue
            seen.add(key)
            entries.append(IndexEntry(
                token=alt_tok,
                display=canonical_display,
                source="synonym",
                weight=0.6,
            ))

    return AutocompleteIndex(entries)
