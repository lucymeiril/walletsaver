"""
WalletSavior 검색 강화 모듈.

- 한글 초성(chosung) 검색
- 자모 분리 기반 퍼지 매칭
- 복합어 분리
- 카테고리 인식 검색 랭킹
"""

from __future__ import annotations

import re
from typing import Optional

from .categories import CATEGORIES, find_category, get_descendants
from .keywords import KEYWORDS, SYNONYMS, resolve_synonym


# ──────────────────────────────────────────────
# 한글 자모 상수
# ──────────────────────────────────────────────

CHOSUNG_LIST = [
    "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ",
    "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]

JUNGSUNG_LIST = [
    "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ",
    "ㅙ", "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
]

JONGSUNG_LIST = [
    "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ",
    "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ",
    "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
]

_HANGUL_BASE = 0xAC00  # '가'
_HANGUL_END = 0xD7A3    # '힣'
_JUNGSUNG_COUNT = 21
_JONGSUNG_COUNT = 28

# 초성 유니코드 범위 (독립 자모)
_CHOSUNG_START = 0x3131  # ㄱ
_CHOSUNG_END = 0x314E    # ㅎ


# ──────────────────────────────────────────────
# 자모 분리/조합
# ──────────────────────────────────────────────

def _is_hangul(char: str) -> bool:
    """완성형 한글 여부."""
    code = ord(char)
    return _HANGUL_BASE <= code <= _HANGUL_END


def _is_chosung_char(char: str) -> bool:
    """독립 자모(초성) 문자 여부."""
    return char in CHOSUNG_LIST


def decompose_hangul(char: str) -> tuple[str, str, str]:
    """
    한글 한 글자를 초성, 중성, 종성으로 분리.

    Returns: (초성, 중성, 종성)
    """
    if not _is_hangul(char):
        return (char, "", "")

    code = ord(char) - _HANGUL_BASE
    cho = code // (_JUNGSUNG_COUNT * _JONGSUNG_COUNT)
    jung = (code % (_JUNGSUNG_COUNT * _JONGSUNG_COUNT)) // _JONGSUNG_COUNT
    jong = code % _JONGSUNG_COUNT

    return (CHOSUNG_LIST[cho], JUNGSUNG_LIST[jung], JONGSUNG_LIST[jong])


def decompose_string(text: str) -> str:
    """문자열의 모든 한글을 자모로 분리."""
    result = []
    for char in text:
        if _is_hangul(char):
            cho, jung, jong = decompose_hangul(char)
            result.extend([cho, jung])
            if jong:
                result.append(jong)
        else:
            result.append(char)
    return "".join(result)


# ──────────────────────────────────────────────
# 초성 추출 & 검색
# ──────────────────────────────────────────────

def extract_chosung(text: str) -> str:
    """문자열에서 초성만 추출. 예: "계란" → "ㄱㄹ"."""
    result = []
    for char in text:
        if _is_hangul(char):
            code = ord(char) - _HANGUL_BASE
            cho = code // (_JUNGSUNG_COUNT * _JONGSUNG_COUNT)
            result.append(CHOSUNG_LIST[cho])
        elif _is_chosung_char(char):
            result.append(char)
        else:
            result.append(char)
    return "".join(result)


def _is_all_chosung(text: str) -> bool:
    """문자열이 모두 초성으로만 이루어져 있는지 확인."""
    return all(_is_chosung_char(c) for c in text if c.strip())


def chosung_search(query: str, candidates: Optional[list[str]] = None,
                   limit: int = 10) -> list[str]:
    """
    초성 검색. 예: "ㄱㄹ" → ["계란", "갈비", "귤", ...]

    candidates 가 None 이면 KEYWORDS 의 word 를 사용.
    """
    if candidates is None:
        candidates = [kw["word"] for kw in KEYWORDS if kw["is_active"]]

    query_chosung = query if _is_all_chosung(query) else extract_chosung(query)

    results = []
    for word in candidates:
        word_chosung = extract_chosung(word)
        if word_chosung.startswith(query_chosung):
            results.append(word)

    return results[:limit]


# ──────────────────────────────────────────────
# 퍼지 매칭
# ──────────────────────────────────────────────

def _edit_distance(s1: str, s2: str) -> int:
    """레벤슈타인 편집 거리 계산."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _jamo_distance(s1: str, s2: str) -> int:
    """자모 분리 후 편집 거리 계산 (한글 특화)."""
    d1 = decompose_string(s1)
    d2 = decompose_string(s2)
    return _edit_distance(d1, d2)


def fuzzy_match(query: str, candidates: Optional[list[str]] = None,
                threshold: float = 0.5, limit: int = 10) -> list[tuple[str, float]]:
    """
    퍼지 매칭. 자모 분리 기반으로 유사도를 계산합니다.

    Args:
        query: 검색어
        candidates: 후보 목록 (None 이면 KEYWORDS 사용)
        threshold: 최소 유사도 (0~1)
        limit: 결과 수 제한

    Returns: [(word, similarity), ...] 유사도 내림차순
    """
    if candidates is None:
        candidates = [kw["word"] for kw in KEYWORDS if kw["is_active"]]

    query_decomposed = decompose_string(query)
    results = []

    for word in candidates:
        word_decomposed = decompose_string(word)
        max_len = max(len(query_decomposed), len(word_decomposed))
        if max_len == 0:
            continue

        dist = _edit_distance(query_decomposed, word_decomposed)
        similarity = 1.0 - (dist / max_len)

        if similarity >= threshold:
            results.append((word, similarity))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:limit]


# ──────────────────────────────────────────────
# 복합어 분리
# ──────────────────────────────────────────────

# 알려진 단어 목록 (키워드 + 카테고리명에서 추출)
_KNOWN_WORDS: Optional[set[str]] = None


def _build_known_words() -> set[str]:
    """알려진 단어 집합 구축."""
    global _KNOWN_WORDS
    if _KNOWN_WORDS is not None:
        return _KNOWN_WORDS

    words = set()
    for kw in KEYWORDS:
        words.add(kw["word"])
        words.update(kw.get("synonyms", []))
    for cat in CATEGORIES:
        words.add(cat["name"])

    # 너무 짧은 단어 제거 (1글자)
    _KNOWN_WORDS = {w for w in words if len(w) >= 2}
    return _KNOWN_WORDS


def split_compound(text: str) -> list[str]:
    """
    복합어를 알려진 단어들로 분리.

    예: "삼겹살구이" → ["삼겹살", "구이"]
        "김치찌개밀키트" → ["김치", "찌개", "밀키트"] 또는 ["김치찌개", "밀키트"]

    가장 긴 매칭 우선 (greedy).
    """
    known = _build_known_words()

    # 먼저 전체가 알려진 단어인지 확인
    if text in known:
        return [text]

    parts = []
    i = 0
    while i < len(text):
        best_match = ""
        # 긴 것부터 시도
        for end in range(len(text), i, -1):
            candidate = text[i:end]
            if candidate in known:
                best_match = candidate
                break

        if best_match:
            parts.append(best_match)
            i += len(best_match)
        else:
            # 매칭 실패 — 한 글자씩 전진
            i += 1

    return parts if parts else [text]


# ──────────────────────────────────────────────
# 카테고리 인식 검색 랭킹
# ──────────────────────────────────────────────

def search_with_ranking(query: str, limit: int = 10) -> list[dict]:
    """
    카테고리를 인식한 검색 랭킹.

    점수 계산:
    - 정확 일치: 100
    - 접두사 일치: 80
    - 동의어 일치: 70
    - 초성 일치: 50
    - 퍼지 매칭: 유사도 × 40
    - 인기도 보너스: search_count / 100 (최대 10)
    """
    resolved = resolve_synonym(query)
    results: dict[str, dict] = {}

    for kw in KEYWORDS:
        if not kw["is_active"]:
            continue

        score = 0.0
        word = kw["word"]
        word_lower = word.lower()
        query_lower = query.lower()
        resolved_lower = resolved.lower()

        # 정확 일치
        if word_lower == query_lower or word_lower == resolved_lower:
            score = 100.0
        # 접두사 일치
        elif word_lower.startswith(query_lower):
            score = 80.0
        # 동의어 접두사 일치
        else:
            for syn in kw.get("synonyms", []):
                if syn.lower().startswith(query_lower):
                    score = 70.0
                    break

        # 초성 매칭 (query 가 모두 초성인 경우)
        if score == 0.0 and _is_all_chosung(query):
            word_chosung = extract_chosung(word)
            if word_chosung.startswith(query):
                score = 50.0

        # 퍼지 매칭 (아직 점수 없으면)
        if score == 0.0 and len(query) >= 2:
            q_dec = decompose_string(query)
            w_dec = decompose_string(word)
            max_len = max(len(q_dec), len(w_dec))
            if max_len > 0:
                dist = _edit_distance(q_dec, w_dec)
                similarity = 1.0 - (dist / max_len)
                if similarity >= 0.5:
                    score = similarity * 40.0

        if score > 0:
            # 인기도 보너스
            popularity_bonus = min(kw.get("search_count", 0) / 100.0, 10.0)
            total_score = score + popularity_bonus

            if word not in results or results[word]["score"] < total_score:
                results[word] = {
                    "word": word,
                    "category_id": kw.get("category_id"),
                    "score": total_score,
                    "search_count": kw.get("search_count", 0),
                }

    ranked = sorted(results.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:limit]
