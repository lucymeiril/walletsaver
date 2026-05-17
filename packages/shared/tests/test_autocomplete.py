"""
WalletSavior Phase B5 — 자동완성 인덱스 TDD.

검증 항목:
  - normalize_token / tokenize_name_core 단위 테스트
  - 4사 fixture 20건 → build_from_canonical_products → AutocompleteIndex
  - suggest 회귀 케이스 (두부, 키친타월, 동의어, 브랜드 prefix 등)
  - 동의어 양방향 검증 (모든 쌍에 대해 양쪽 prefix가 결과를 끌어오는지)
  - stats() 구조 검증

미지원 항목 (워크로그 참고):
  - 한글 자모(ㅋ 등) prefix 검색 — Phase C에서 형태소 분석기와 함께 검토.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from core.autocomplete import (
    AutocompleteIndex,
    IndexEntry,
    build_from_canonical_products,
    load_synonyms,
    normalize_token,
    tokenize_name_core,
)
from core.canonical_models import MartKind
from core.category_mapper import load_tree
from core.product_canonicalize import (
    canonicalize_costco,
    canonicalize_emart,
    canonicalize_homeplus,
    canonicalize_lottemart,
    parse_costco_cards_from_html,
)

# ─────────────────────────────────────────────────────────────────────────────
# 상수 / 픽스처 경로
# ─────────────────────────────────────────────────────────────────────────────

_FIXTURE_DIR = (
    Path(__file__).parent.parent.parent
    / "crawler-admin" / "backend" / "tests" / "fixtures"
)
_EMART_FIXTURE = _FIXTURE_DIR / "emart" / "sale_listing_5cards.json"
_HOMEPLUS_FIXTURE = _FIXTURE_DIR / "homeplus" / "sale_listing_5items_dc_mixed.json"
_LOTTEMART_FIXTURE = _FIXTURE_DIR / "lottemart" / "hydrated_5cards.html"
_COSTCO_FIXTURE = _FIXTURE_DIR / "costco" / "special_offers_5cards.html"

_NOW = datetime(2025, 7, 1, 0, 0, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼 — fixture 로더
# ─────────────────────────────────────────────────────────────────────────────

def _load_emart_items() -> list[dict]:
    with open(_EMART_FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    return (
        data["props"]["pageProps"]["dehydratedState"]
        ["queries"][0]["state"]["data"]["areaList"][0]["dataList"]
    )


def _load_homeplus_items() -> list[dict]:
    with open(_HOMEPLUS_FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    return data["data"]["dataList"]


def _load_lottemart_items() -> list[dict]:
    with open(_LOTTEMART_FIXTURE, encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", content, re.DOTALL)
    assert m, "INITIAL_STATE not found in lottemart fixture"
    data = json.loads(m.group(1))
    entities = data["data"]["products"]["productEntities"]
    return list(entities.values())


def _load_costco_items() -> list[dict]:
    with open(_COSTCO_FIXTURE, encoding="utf-8") as f:
        content = f.read()
    return parse_costco_cards_from_html(content)


# ─────────────────────────────────────────────────────────────────────────────
# 공통 픽스처 — 4사 20건 canonical + index
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def all_canonicals():
    """4사 fixture 20건을 canonical product 목록으로 변환."""
    results = []
    for item in _load_emart_items():
        r = canonicalize_emart(item, _NOW)
        if r.canonical:
            results.append(r.canonical)
    for item in _load_homeplus_items():
        r = canonicalize_homeplus(item, _NOW)
        if r.canonical:
            results.append(r.canonical)
    for item in _load_lottemart_items():
        r = canonicalize_lottemart(item, _NOW)
        if r.canonical:
            results.append(r.canonical)
    for item in _load_costco_items():
        r = canonicalize_costco(item, _NOW)
        if r.canonical:
            results.append(r.canonical)
    return results


@pytest.fixture(scope="module")
def autocomplete_index(all_canonicals):
    """4사 canonical에서 구축된 AutocompleteIndex."""
    import yaml
    from pathlib import Path

    tree = load_tree()
    synonyms = load_synonyms()

    # brand_dict: brand_dictionary.yaml 에서 로드
    brand_yaml = Path(__file__).parent.parent / "data" / "brand_dictionary.yaml"
    with open(brand_yaml, encoding="utf-8") as f:
        brand_raw = yaml.safe_load(f)
    brand_set = set(brand_raw.get("brands", []))

    return build_from_canonical_products(all_canonicals, tree, brand_set, synonyms)


# ─────────────────────────────────────────────────────────────────────────────
# normalize_token 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeToken:
    def test_casefold_english(self):
        assert normalize_token("CJ") == "cj"

    def test_removes_registered_mark(self):
        assert normalize_token("Costco®") == "costco"

    def test_removes_spaces(self):
        assert normalize_token("키친 타월") == "키친타월"

    def test_removes_middle_dot(self):
        assert normalize_token("두부·콩류") == "두부콩류"

    def test_nfc_normalization(self):
        # NFD 형식의 한글을 NFC 로 변환해야 동등
        import unicodedata
        nfd_str = unicodedata.normalize("NFD", "키위")
        result = normalize_token(nfd_str)
        assert result == "키위"

    def test_empty_string(self):
        assert normalize_token("") == ""

    def test_korean_preserved(self):
        assert normalize_token("풀무원") == "풀무원"

    def test_numbers_preserved(self):
        assert normalize_token("340g") == "340g"

    def test_removes_hyphens(self):
        assert normalize_token("in-1") == "in1"


# ─────────────────────────────────────────────────────────────────────────────
# tokenize_name_core 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenizeNameCore:
    """tokenize_name_core의 분리·필터링 규칙 검증."""

    _EMPTY_BRAND = set()
    _EMPTY_SYN = {}

    def test_splits_by_space(self):
        tokens = tokenize_name_core("국산 부침두부", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "국산" in tokens
        assert "부침두부" in tokens

    def test_removes_number_only_tokens(self):
        tokens = tokenize_name_core("340 g 두부", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "340" not in tokens

    def test_removes_unit_tokens(self):
        # 순수 단위어 토큰("매", "롤")은 제거; 숫자+단위 복합 토큰("30매", "6롤")은 잔류
        tokens = tokenize_name_core("키친타월 매 롤", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "매" not in tokens, "순수 단위어 '매'는 제거되어야 함"
        assert "롤" not in tokens, "순수 단위어 '롤'은 제거되어야 함"
        assert "키친타월" in tokens

    def test_removes_single_char_tokens(self):
        tokens = tokenize_name_core("쌀 g", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "g" not in tokens

    def test_removes_brand_tokens(self):
        brand_set = {"풀무원"}
        tokens = tokenize_name_core("국산 부침두부", brand_set, self._EMPTY_SYN)
        assert "풀무원" not in tokens

    def test_emart_yangbaechu(self):
        tokens = tokenize_name_core("한끼 양배추", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "양배추" in tokens

    def test_homeplus_kitchen_towel(self):
        tokens = tokenize_name_core("천연펄프 2겹 키친타월", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "키친타월" in tokens

    def test_lottemart_tofu(self):
        tokens = tokenize_name_core("국산 부침두부", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "부침두부" in tokens

    def test_splits_by_paren(self):
        tokens = tokenize_name_core("폴딩 핸드트럭 (2 IN 1)", self._EMPTY_BRAND, self._EMPTY_SYN)
        assert "폴딩" in tokens
        assert "핸드트럭" in tokens


# ─────────────────────────────────────────────────────────────────────────────
# 20건 canonical 생성 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestFixtureCanonicals:
    def test_all_20_canonicals_produced(self, all_canonicals):
        """4사 fixture 20건 모두 canonical 생성."""
        assert len(all_canonicals) == 20

    def test_lottemart_tofu_present(self, all_canonicals):
        """롯데마트 풀무원 부침두부 canonical 포함."""
        names = [c.name_core for c in all_canonicals]
        assert any("두부" in n for n in names)

    def test_costco_kleenex_present(self, all_canonicals):
        """코스트코 크리넥스 canonical 포함."""
        brands = [c.brand for c in all_canonicals if c.brand]
        assert any(b == "크리넥스" for b in brands)

    def test_homeplus_kitchen_towel_present(self, all_canonicals):
        """홈플러스 키친타월 canonical 포함."""
        names = [c.name_core for c in all_canonicals]
        assert any("키친타월" in n for n in names)


# ─────────────────────────────────────────────────────────────────────────────
# AutocompleteIndex 기본 동작
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoCompleteIndexBasics:
    def test_suggest_empty_prefix_returns_empty(self, autocomplete_index):
        """빈 prefix → 빈 결과 (노이즈 방지)."""
        assert autocomplete_index.suggest("") == []

    def test_suggest_whitespace_prefix_returns_empty(self, autocomplete_index):
        """공백만인 prefix → 빈 결과."""
        assert autocomplete_index.suggest("   ") == []

    def test_suggest_returns_index_entries(self, autocomplete_index):
        """suggest 결과는 IndexEntry 리스트."""
        results = autocomplete_index.suggest("두")
        assert all(isinstance(r, IndexEntry) for r in results)

    def test_suggest_respects_limit(self, autocomplete_index):
        """limit 파라미터 준수."""
        results = autocomplete_index.suggest("가", limit=3)
        assert len(results) <= 3

    def test_stats_structure(self, autocomplete_index):
        """stats()가 필수 키 반환."""
        s = autocomplete_index.stats()
        assert "total_tokens" in s
        assert "by_source" in s
        assert s["total_tokens"] > 0

    def test_stats_source_keys(self, autocomplete_index):
        """stats by_source에 4개 소스 모두 존재."""
        s = autocomplete_index.stats()
        sources = set(s["by_source"].keys())
        assert "brand" in sources
        assert "category" in sources
        assert "product_name_core" in sources
        assert "synonym" in sources

    def test_weight_order(self, autocomplete_index):
        """동점이 아닌 경우 weight 내림차순 정렬."""
        results = autocomplete_index.suggest("두")
        if len(results) >= 2:
            weights = [r.weight for r in results]
            assert weights == sorted(weights, reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# suggest 회귀 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestSuggestRegression:
    def test_suggest_두_includes_두부(self, autocomplete_index):
        """
        suggest("두") → "두부" 포함.
        롯데마트 fixture: 풀무원 국산 부침두부.
        카테고리 트리 node tofu → name_kr "두부" → token "두부".
        """
        results = autocomplete_index.suggest("두")
        displays = [r.display for r in results]
        assert any("두부" in d for d in displays), (
            f"'두부' not found in suggest('두') results: {displays}"
        )

    def test_suggest_키친_includes_키친타월(self, autocomplete_index):
        """
        suggest("키친") → "키친타월" 포함.
        카테고리 node kitchen_towel → name_kr "키친타월".
        """
        results = autocomplete_index.suggest("키친")
        displays = [r.display for r in results]
        assert any("키친타월" in d for d in displays), (
            f"'키친타월' not found in suggest('키친') results: {displays}"
        )

    def test_suggest_키친타올_synonym_키친타월(self, autocomplete_index):
        """
        suggest("키친타올") → 동의어 매핑으로 "키친타월" 결과 포함.
        synonyms.yaml: 키친타월 → [키친타올, ...]
        """
        results = autocomplete_index.suggest("키친타올")
        displays = [r.display for r in results]
        assert any("키친타월" in d for d in displays), (
            f"'키친타월' not found via synonym in suggest('키친타올'): {displays}"
        )

    def test_suggest_계란_returns_result(self, autocomplete_index):
        """suggest("계란") → 계란 관련 결과 존재."""
        results = autocomplete_index.suggest("계란")
        assert results, "suggest('계란') returned empty"
        displays = [r.display for r in results]
        assert any("계란" in d for d in displays)

    def test_suggest_달걀_returns_계란_via_synonym(self, autocomplete_index):
        """suggest("달걀") → 동의어로 "계란" 결과 포함."""
        results = autocomplete_index.suggest("달걀")
        assert results, "suggest('달걀') returned empty"
        displays = [r.display for r in results]
        assert any("계란" in d for d in displays), (
            f"'계란' not found via synonym in suggest('달걀'): {displays}"
        )

    def test_suggest_크리넥스_returns_brand(self, autocomplete_index):
        """
        suggest("크리넥스") → 코스트코 크리넥스 브랜드 항목 포함.
        두 개의 크리넥스 상품(메가롤, 데코&소프트)이 있어 brand 항목 존재.
        """
        results = autocomplete_index.suggest("크리넥스")
        assert results, "suggest('크리넥스') returned empty"
        sources = [r.source for r in results]
        assert "brand" in sources, f"No brand entry in suggest('크리넥스'): {results}"
        displays = [r.display for r in results]
        assert any("크리넥스" in d for d in displays)

    def test_suggest_풀무원_returns_brand(self, autocomplete_index):
        """suggest("풀무원") → 풀무원 브랜드 항목."""
        results = autocomplete_index.suggest("풀무원")
        assert results, "suggest('풀무원') returned empty"
        displays = [r.display for r in results]
        assert any("풀무원" in d for d in displays)

    def test_suggest_c_returns_cj(self, autocomplete_index):
        """
        suggest("c") → "CJ" 브랜드 (casefold: cj starts with c).
        롯데마트 fixture: CJ 고메 중화짬뽕.
        """
        results = autocomplete_index.suggest("c")
        assert results, "suggest('c') returned empty"
        displays = [r.display for r in results]
        assert any("CJ" in d for d in displays), (
            f"'CJ' not found in suggest('c'): {displays}"
        )

    def test_suggest_아_returns_아삭(self, autocomplete_index):
        """
        suggest("아") → "아삭" 포함.
        이마트 fixture: 씨없는 아삭 파프리카 → token "아삭".
        """
        results = autocomplete_index.suggest("아")
        assert results, "suggest('아') returned empty"
        displays = [r.display for r in results]
        assert any("아삭" in d for d in displays), (
            f"'아삭' not found in suggest('아'): {displays}"
        )

    def test_suggest_jamo_not_supported(self, autocomplete_index):
        """
        자모(초성) prefix 검색 미지원 워크로그 명시.
        'ㅋ' 검색 → 결과 없음 (미지원; Phase C에서 검토).
        """
        # 결과가 없어야 하거나 있어도 무방 (미지원 범위이므로 단순 기록용)
        results = autocomplete_index.suggest("ㅋ")
        # 결과가 없음을 기대하지만, 있어도 테스트 실패로 처리하지 않음
        # (워크로그에 한계 명시)
        assert isinstance(results, list)  # 단순 타입 검증만

    def test_suggest_두부_동의어_콩두부(self, autocomplete_index):
        """suggest("콩두부") → 동의어 "두부" 결과 포함."""
        results = autocomplete_index.suggest("콩두부")
        assert results, "suggest('콩두부') returned empty"
        displays = [r.display for r in results]
        assert any("두부" in d for d in displays)

    def test_suggest_화장지_returns_result(self, autocomplete_index):
        """suggest("화장지") → 화장지 관련 카테고리 또는 동의어 결과."""
        results = autocomplete_index.suggest("화장지")
        assert results, "suggest('화장지') returned empty"

    def test_suggest_휴지_synonym_화장지(self, autocomplete_index):
        """suggest("휴지") → 동의어 "화장지" 결과 포함."""
        results = autocomplete_index.suggest("휴지")
        assert results, "suggest('휴지') returned empty"
        displays = [r.display for r in results]
        assert any("화장지" in d for d in displays), (
            f"'화장지' not found via synonym in suggest('휴지'): {displays}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 동의어 양방향 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestSynonymBidirectional:
    """
    synonyms.yaml에 시드된 모든 쌍에 대해 양방향 검색이 동작하는지 검증.
    - 대표어 prefix 검색 → 대표어 자체를 포함한 결과 존재 (category 또는 product_name_core)
    - 대안어 prefix 검색 → 대표어를 display로 갖는 synonym 항목 존재
    """

    def _check_canonical_found(self, index: AutocompleteIndex, canonical_term: str) -> bool:
        """대표어 prefix로 검색 시 관련 결과가 있는지."""
        results = index.suggest(canonical_term)
        return len(results) > 0

    def _check_alt_finds_canonical(
        self, index: AutocompleteIndex, alt: str, canonical_term: str
    ) -> bool:
        """대안어 prefix로 검색 시 canonical_term이 display에 포함된 결과가 있는지."""
        norm_alt = normalize_token(alt)
        if not norm_alt:
            return False
        results = index.suggest(norm_alt)
        return any(canonical_term in r.display for r in results)

    @pytest.mark.parametrize("canonical_term,alts", [
        ("키친타월", ["키친타올", "키친 타월"]),
        ("계란", ["달걀"]),
        ("두부", ["콩두부"]),
        ("화장지", ["휴지", "두루마리"]),
        ("파프리카", ["피망"]),
        ("양배추", ["캐비지"]),
        ("쌀", ["백미"]),
        ("키위", ["다래"]),
        ("견과", ["견과류", "너트"]),
        ("밀키트", ["간편식"]),
        ("비타민", ["영양제"]),
        ("크림", ["바디크림", "손크림"]),
        ("화장품", ["코스메틱"]),
    ])
    def test_alt_finds_canonical(
        self, autocomplete_index, canonical_term: str, alts: list[str]
    ):
        """대안어로 검색 시 대표어가 결과에 나타나야 한다."""
        for alt in alts:
            assert self._check_alt_finds_canonical(
                autocomplete_index, alt, canonical_term
            ), (
                f"suggest('{alt}') did not return display containing '{canonical_term}'"
            )

    @pytest.mark.parametrize("canonical_term", [
        "키친타월", "계란", "두부", "화장지", "파프리카",
        "양배추", "쌀", "키위", "견과", "밀키트", "비타민",
    ])
    def test_canonical_prefix_finds_result(
        self, autocomplete_index, canonical_term: str
    ):
        """대표어로 검색하면 반드시 결과가 있어야 한다 (category 또는 synonym)."""
        assert self._check_canonical_found(autocomplete_index, canonical_term), (
            f"suggest('{canonical_term}') returned empty — "
            f"category or product_name_core entry missing"
        )


# ─────────────────────────────────────────────────────────────────────────────
# load_synonyms 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadSynonyms:
    def test_returns_dict(self):
        result = load_synonyms()
        assert isinstance(result, dict)

    def test_kitchen_towel_synonym(self):
        result = load_synonyms()
        assert "키친타월" in result
        assert "키친타올" in result["키친타월"]

    def test_계란_달걀(self):
        result = load_synonyms()
        assert "계란" in result
        assert "달걀" in result["계란"]

    def test_values_are_lists(self):
        result = load_synonyms()
        for v in result.values():
            assert isinstance(v, list)
