"""자동완성 키워드 서비스"""
from __future__ import annotations

import re
from typing import Optional
from sqlalchemy import select, or_, func, update
from sqlalchemy.orm import Session

from storage.models import Keyword, Category
from api.security import escape_like


# ── 한국어 키워드 유효성 검사 ──

# 낱개 자모 범위 (완성형 음절이 아닌 독립 자모)
_JAMO_RANGES = [
    (0x1100, 0x11FF),   # Hangul Jamo
    (0x3130, 0x318F),   # Hangul Compatibility Jamo (ㄱ, ㅏ 등)
    (0xA960, 0xA97F),   # Hangul Jamo Extended-A
    (0xD7B0, 0xD7FF),   # Hangul Jamo Extended-B
]


def _is_standalone_jamo(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _JAMO_RANGES)


def validate_keyword(word: str) -> tuple[bool, str]:
    """키워드 유효성 검사. (valid, error_message) 반환."""
    if not word or not word.strip():
        return False, "키워드가 비어 있습니다."

    word = word.strip()

    if len(word) < 1:
        return False, "키워드는 최소 1자 이상이어야 합니다."

    # 낱개 자모(ㄱ, ㅏ 등)가 포함된 불완전한 한글 시퀀스 거부
    for ch in word:
        if _is_standalone_jamo(ch):
            return False, f"'{word}'에 불완전한 한글 자모('{ch}')가 포함되어 있습니다."

    return True, ""


def search_keywords(session: Session, query: str, limit: int = 10) -> list[dict]:
    """접두어 매칭 + 동의어 검색.

    동의어 검색은 DB의 모든 키워드를 로드하는 대신,
    접두어 매칭 결과가 부족할 때만 수행하며 결과를 제한한다.
    """
    if not query:
        return []

    # 접두어 매칭
    prefix_rows = session.execute(
        select(Keyword).where(
            Keyword.is_active == True,
            Keyword.word.like(f"{escape_like(query)}%"),
        ).order_by(Keyword.search_count.desc()).limit(limit)
    ).scalars().all()

    results = []
    seen_ids = set()
    for kw in prefix_rows:
        seen_ids.add(kw.id)
        results.append({
            "id": kw.id,
            "word": kw.word,
            "search_count": kw.search_count,
            "category_id": kw.category_id,
            "match_type": "prefix",
        })

    # 동의어 검색 — 접두어로 부족할 때만 (limit 미달 시)
    remaining = limit - len(results)
    if remaining > 0:
        all_keywords = session.execute(
            select(Keyword).where(Keyword.is_active == True)
        ).scalars().all()

        for kw in all_keywords:
            if kw.id in seen_ids:
                continue
            synonyms = kw.synonyms or []
            for syn in synonyms:
                if isinstance(syn, str) and syn.startswith(query):
                    results.append({
                        "id": kw.id,
                        "word": kw.word,
                        "search_count": kw.search_count,
                        "category_id": kw.category_id,
                        "match_type": "synonym",
                        "matched_synonym": syn,
                    })
                    seen_ids.add(kw.id)
                    remaining -= 1
                    break
            if remaining <= 0:
                break

    return results[:limit]


def add_keyword(
    session: Session,
    word: str,
    synonyms: Optional[list[str]] = None,
    category_id: Optional[str] = None,
) -> dict:
    """키워드 추가 — 유효성 검사 후 이미 존재하는 단어라면 동의어/카테고리를 병합하여 갱신한다."""
    word = (word or "").strip()

    # 유효성 검사
    valid, err = validate_keyword(word)
    if not valid:
        raise ValueError(err)

    # 동의어도 유효성 검사 (잘못된 항목은 필터링)
    clean_synonyms: list[str] = []
    for syn in (synonyms or []):
        s = (syn or "").strip()
        if s and validate_keyword(s)[0]:
            clean_synonyms.append(s)

    existing = session.execute(
        select(Keyword).where(Keyword.word == word)
    ).scalar_one_or_none()

    if existing:
        # 기존 키워드에 동의어 병합, 카테고리 갱신
        merged_syns = list(set((existing.synonyms or []) + clean_synonyms))
        existing.synonyms = merged_syns
        if category_id:
            existing.category_id = category_id
        session.commit()
        session.refresh(existing)
        return {
            "id": existing.id,
            "word": existing.word,
            "synonyms": existing.synonyms,
            "category_id": existing.category_id,
            "merged": True,
        }

    kw = Keyword(
        word=word,
        synonyms=clean_synonyms,
        category_id=category_id,
        search_count=0,
        is_active=True,
    )
    session.add(kw)
    session.commit()
    session.refresh(kw)
    return {
        "id": kw.id,
        "word": kw.word,
        "synonyms": kw.synonyms,
        "category_id": kw.category_id,
    }


def update_search_count(session: Session, keyword_id: int) -> bool:
    """검색 횟수 증가"""
    kw = session.get(Keyword, keyword_id)
    if not kw:
        return False
    kw.search_count += 1
    session.commit()
    return True


def get_popular_keywords(session: Session, limit: int = 20) -> list[dict]:
    """인기 검색어"""
    rows = session.execute(
        select(Keyword).where(
            Keyword.is_active == True,
        ).order_by(Keyword.search_count.desc()).limit(limit)
    ).scalars().all()

    return [
        {
            "id": kw.id,
            "word": kw.word,
            "search_count": kw.search_count,
            "category_id": kw.category_id,
        }
        for kw in rows
    ]


def suggest_categories(session: Session, query: str) -> list[dict]:
    """검색어에서 카테고리 추천"""
    if not query:
        return []

    # 키워드에 연결된 카테고리 찾기
    keywords = session.execute(
        select(Keyword).where(
            Keyword.is_active == True,
            Keyword.word.like(f"%{escape_like(query)}%"),
            Keyword.category_id.isnot(None),
        )
    ).scalars().all()

    cat_ids = list({kw.category_id for kw in keywords})
    if not cat_ids:
        # 카테고리 이름에서 직접 검색
        categories = session.execute(
            select(Category).where(
                Category.is_active == True,
                Category.name.like(f"%{escape_like(query)}%"),
            )
        ).scalars().all()
        return [
            {"id": c.id, "name": c.name, "depth": c.depth}
            for c in categories
        ]

    categories = session.execute(
        select(Category).where(Category.id.in_(cat_ids))
    ).scalars().all()

    return [
        {"id": c.id, "name": c.name, "depth": c.depth}
        for c in categories
    ]
