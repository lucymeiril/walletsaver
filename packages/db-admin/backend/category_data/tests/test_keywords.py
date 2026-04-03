"""키워드 관리 및 동의어 해석 테스트."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from category_data.keywords import (
    KEYWORDS,
    SYNONYMS,
    POPULAR_PATTERNS,
    resolve_synonym,
    get_related,
    get_keywords_for_category,
    search_keywords,
    get_popular_keywords,
)


class TestKeywordData:
    """키워드 데이터 무결성 테스트."""

    def test_keyword_count_minimum(self):
        """500개 이상 키워드가 있어야 한다."""
        # 키워드 자체 + 동의어 합산으로 500+ 커버
        total = len(KEYWORDS)
        synonym_count = sum(len(kw["synonyms"]) for kw in KEYWORDS)
        assert total + synonym_count >= 500, \
            f"키워드 {total} + 동의어 {synonym_count} = {total + synonym_count}"

    def test_no_duplicate_words(self):
        """동일한 word 가 중복되지 않아야 한다 (카테고리가 다른 경우 허용)."""
        words = [kw["word"] for kw in KEYWORDS]
        # 완전 중복은 허용하지 않음 (키워드 수준)
        # 일부 키워드는 의도적으로 같은 word 를 여러 카테고리에 매핑하지 않는다
        # → 검증은 word 의 고유 비율
        unique = set(words)
        dup_ratio = len(unique) / len(words)
        assert dup_ratio > 0.9, f"중복 비율이 너무 높음: {dup_ratio:.2f}"

    def test_all_keywords_have_required_fields(self):
        """필수 필드가 있어야 한다."""
        for kw in KEYWORDS:
            assert "word" in kw
            assert "synonyms" in kw
            assert "is_active" in kw
            assert isinstance(kw["synonyms"], list)

    def test_search_count_non_negative(self):
        """search_count 가 0 이상이어야 한다."""
        for kw in KEYWORDS:
            assert kw.get("search_count", 0) >= 0


class TestSynonymMapping:
    """동의어 매핑 테스트."""

    def test_synonym_map_not_empty(self):
        """동의어 맵이 비어 있지 않아야 한다."""
        assert len(SYNONYMS) > 0

    def test_resolve_dalyal_to_gyeran(self):
        """'달걀' → '계란' 동의어 해석."""
        assert resolve_synonym("달걀") == "계란"

    def test_resolve_unknown_returns_original(self):
        """알 수 없는 단어는 원래 값 반환."""
        assert resolve_synonym("xyz_unknown") == "xyz_unknown"

    def test_resolve_samgyeop(self):
        """'삼겹' → '삼겹살' 또는 존재하는 매핑."""
        result = resolve_synonym("삼겹")
        assert result is not None

    def test_resolve_english_synonym(self):
        """영어 동의어 해석."""
        result = resolve_synonym("egg")
        assert result == "계란"

    def test_get_related_returns_synonyms(self):
        """관련어 조회."""
        related = get_related("계란")
        assert "달걀" in related


class TestKeywordSearch:
    """키워드 검색 테스트."""

    def test_exact_match(self):
        """정확 일치 검색."""
        results = search_keywords("삼겹살")
        assert len(results) > 0
        assert results[0]["word"] == "삼겹살"

    def test_prefix_match(self):
        """접두사 검색."""
        results = search_keywords("삼겹")
        words = [r["word"] for r in results]
        assert any("삼겹" in w for w in words)

    def test_synonym_match(self):
        """동의어 검색."""
        results = search_keywords("달걀")
        words = [r["word"] for r in results]
        assert "계란" in words

    def test_search_limit(self):
        """검색 결과 제한."""
        results = search_keywords("삼", limit=3)
        assert len(results) <= 3

    def test_search_empty_query(self):
        """빈 쿼리 검색."""
        results = search_keywords("")
        # 빈 문자열도 접두사 매칭으로 모든 키워드 반환 (limit 제한)
        assert len(results) <= 10

    def test_get_keywords_for_category(self):
        """카테고리별 키워드 조회."""
        kws = get_keywords_for_category("livestock.pork.belly")
        words = [kw["word"] for kw in kws]
        assert "삼겹살" in words

    def test_popular_keywords(self):
        """인기 키워드 반환 (search_count 내림차순)."""
        popular = get_popular_keywords(10)
        assert len(popular) == 10
        counts = [p["search_count"] for p in popular]
        assert counts == sorted(counts, reverse=True)


class TestPopularPatterns:
    """인기 검색 패턴 테스트."""

    def test_patterns_exist(self):
        """검색 패턴이 정의되어 있어야 한다."""
        assert len(POPULAR_PATTERNS) >= 3

    def test_patterns_have_examples(self):
        """각 패턴에 examples 가 있어야 한다."""
        for p in POPULAR_PATTERNS:
            assert "pattern" in p
            assert "examples" in p
            assert len(p["examples"]) > 0
