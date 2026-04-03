"""자동완성 키워드 서비스"""
from __future__ import annotations

from typing import Optional
from sqlalchemy import select, or_, func, update
from sqlalchemy.orm import Session

from storage.models import Keyword, Category


def search_keywords(session: Session, query: str, limit: int = 10) -> list[dict]:
    """접두어 매칭 + 동의어 검색"""
    if not query:
        return []

    # 접두어 매칭
    prefix_rows = session.execute(
        select(Keyword).where(
            Keyword.is_active == True,
            Keyword.word.like(f"{query}%"),
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

    # 동의어 검색 (JSON 배열에서 검색)
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
                break

    return results[:limit]


def add_keyword(
    session: Session,
    word: str,
    synonyms: Optional[list[str]] = None,
    category_id: Optional[str] = None,
) -> dict:
    """키워드 추가 — 이미 존재하는 단어라면 동의어/카테고리를 병합하여 갱신한다."""
    existing = session.execute(
        select(Keyword).where(Keyword.word == word)
    ).scalar_one_or_none()

    if existing:
        # 기존 키워드에 동의어 병합, 카테고리 갱신
        merged_syns = list(set((existing.synonyms or []) + (synonyms or [])))
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
        synonyms=synonyms or [],
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
            Keyword.word.like(f"%{query}%"),
            Keyword.category_id.isnot(None),
        )
    ).scalars().all()

    cat_ids = list({kw.category_id for kw in keywords})
    if not cat_ids:
        # 카테고리 이름에서 직접 검색
        categories = session.execute(
            select(Category).where(
                Category.is_active == True,
                Category.name.like(f"%{query}%"),
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
