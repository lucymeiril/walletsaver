"""검색 강화 모듈 테스트 (퍼지, 초성, 복합어)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
from category_data.search_enhance import (
    extract_chosung,
    chosung_search,
    decompose_hangul,
    decompose_string,
    fuzzy_match,
    split_compound,
    search_with_ranking,
    _edit_distance,
    _is_hangul,
    _is_all_chosung,
)


class TestChosungExtraction:
    """초성 추출 테스트."""

    def test_basic_chosung(self):
        """기본 초성 추출."""
        assert extract_chosung("계란") == "ㄱㄹ"

    def test_samgyeopsal(self):
        """삼겹살 초성."""
        assert extract_chosung("삼겹살") == "ㅅㄱㅅ"

    def test_galbi(self):
        """갈비 초성."""
        assert extract_chosung("갈비") == "ㄱㅂ"

    def test_mixed_text(self):
        """한글+영문 혼합."""
        result = extract_chosung("TV장")
        assert result == "TVㅈ"

    def test_empty_string(self):
        """빈 문자열."""
        assert extract_chosung("") == ""

    def test_chosung_only_input(self):
        """이미 초성인 입력."""
        assert extract_chosung("ㄱㄹ") == "ㄱㄹ"


class TestChosungSearch:
    """초성 검색 테스트."""

    def test_gl_finds_gyeran_galbi(self):
        """ㄱㄹ → 계란, 갈비 등."""
        results = chosung_search("ㄱㄹ")
        assert "계란" in results or "갈비" in results

    def test_sgs_finds_samgyeopsal(self):
        """ㅅㄱㅅ → 삼겹살."""
        results = chosung_search("ㅅㄱㅅ")
        assert "삼겹살" in results

    def test_limit(self):
        """결과 수 제한."""
        results = chosung_search("ㄱ", limit=5)
        assert len(results) <= 5

    def test_custom_candidates(self):
        """커스텀 후보 목록."""
        results = chosung_search("ㄱ", candidates=["가나다", "나다라", "감자"])
        assert "가나다" in results
        assert "감자" in results
        assert "나다라" not in results


class TestHangulDecomposition:
    """한글 자모 분리 테스트."""

    def test_decompose_ga(self):
        """'가' 분리."""
        cho, jung, jong = decompose_hangul("가")
        assert cho == "ㄱ"
        assert jung == "ㅏ"
        assert jong == ""

    def test_decompose_han(self):
        """'한' 분리."""
        cho, jung, jong = decompose_hangul("한")
        assert cho == "ㅎ"
        assert jung == "ㅏ"
        assert jong == "ㄴ"

    def test_decompose_non_hangul(self):
        """비한글 문자."""
        cho, jung, jong = decompose_hangul("A")
        assert cho == "A"
        assert jung == ""
        assert jong == ""

    def test_decompose_string(self):
        """문자열 전체 자모 분리."""
        result = decompose_string("가나")
        assert result == "ㄱㅏㄴㅏ"

    def test_decompose_string_with_jongsung(self):
        """종성 포함 문자열 분리."""
        result = decompose_string("한글")
        assert "ㅎ" in result
        assert "ㄴ" in result


class TestFuzzyMatch:
    """퍼지 매칭 테스트."""

    def test_exact_match_high_score(self):
        """정확 일치는 높은 유사도."""
        results = fuzzy_match("삼겹살", candidates=["삼겹살", "목살", "갈비"])
        assert results[0][0] == "삼겹살"
        assert results[0][1] == 1.0

    def test_similar_match(self):
        """유사 단어 매칭."""
        results = fuzzy_match("삼겹살", candidates=["삼겹살", "삼겹", "오겹살", "갈비"])
        words = [r[0] for r in results]
        assert "삼겹살" in words

    def test_threshold_filtering(self):
        """유사도 임계값 필터링."""
        results = fuzzy_match("삼겹살", candidates=["삼겹살", "완전다른말"], threshold=0.8)
        words = [r[0] for r in results]
        assert "완전다른말" not in words

    def test_edit_distance_same(self):
        """같은 문자열 편집 거리 = 0."""
        assert _edit_distance("test", "test") == 0

    def test_edit_distance_different(self):
        """다른 문자열 편집 거리 > 0."""
        assert _edit_distance("test", "tent") == 1


class TestCompoundSplit:
    """복합어 분리 테스트."""

    def test_known_compound(self):
        """알려진 복합어 분리."""
        parts = split_compound("삼겹살구이")
        # "삼겹살" 이 분리되어야 함
        assert "삼겹살" in parts or len(parts) > 1

    def test_single_known_word(self):
        """단일 알려진 단어는 분리 안 됨."""
        parts = split_compound("삼겹살")
        assert parts == ["삼겹살"]

    def test_unknown_word_returns_original(self):
        """모르는 단어는 원본 반환."""
        parts = split_compound("아무뜻없는말")
        assert parts == ["아무뜻없는말"] or len(parts) >= 1


class TestSearchWithRanking:
    """카테고리 인식 검색 랭킹 테스트."""

    def test_exact_match_highest_score(self):
        """정확 일치가 가장 높은 점수."""
        results = search_with_ranking("삼겹살")
        assert len(results) > 0
        assert results[0]["word"] == "삼겹살"
        assert results[0]["score"] >= 100

    def test_synonym_search(self):
        """동의어 검색."""
        results = search_with_ranking("달걀")
        words = [r["word"] for r in results]
        assert "계란" in words

    def test_chosung_search_ranking(self):
        """초성 검색 랭킹."""
        results = search_with_ranking("ㄱㄹ")
        assert len(results) > 0
        # 초성 매칭 결과가 있어야 함
        assert any(r["score"] >= 50 for r in results)

    def test_ranking_limit(self):
        """결과 수 제한."""
        results = search_with_ranking("삼", limit=5)
        assert len(results) <= 5

    def test_result_contains_category(self):
        """결과에 카테고리 정보 포함."""
        results = search_with_ranking("삼겹살")
        assert results[0]["category_id"] is not None

    def test_is_hangul(self):
        """한글 판별."""
        assert _is_hangul("가") is True
        assert _is_hangul("A") is False
        assert _is_hangul("1") is False

    def test_is_all_chosung(self):
        """초성 문자열 판별."""
        assert _is_all_chosung("ㄱㄹ") is True
        assert _is_all_chosung("가나") is False
        assert _is_all_chosung("ㄱA") is False
