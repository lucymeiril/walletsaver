"""자동완성 키워드 라우트"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from services.base import get_session
from services.autocomplete import (
    search_keywords,
    add_keyword,
    update_search_count,
    get_popular_keywords,
    suggest_categories,
)
from storage.models import Keyword

router = APIRouter(prefix="/keywords", tags=["keywords"])


class KeywordCreate(BaseModel):
    word: str
    synonyms: Optional[list[str]] = None
    category_id: Optional[str] = None


class KeywordUpdate(BaseModel):
    word: Optional[str] = None
    synonyms: Optional[list[str]] = None
    category_id: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/")
def list_keywords(limit: int = 100, offset: int = 0):
    """키워드 전체 목록."""
    session = get_session()
    try:
        keywords = session.query(Keyword).offset(offset).limit(limit).all()
        return [
            {
                "id": kw.id, "word": kw.word,
                "synonyms": kw.synonyms or [],
                "category_id": kw.category_id,
                "search_count": kw.search_count,
                "is_active": kw.is_active,
            }
            for kw in keywords
        ]
    finally:
        session.close()


@router.get("/search")
def keyword_search(q: str = "", limit: int = 10):
    session = get_session()
    try:
        return search_keywords(session, q, limit)
    finally:
        session.close()


@router.post("/", status_code=201)
def create_keyword(body: KeywordCreate):
    session = get_session()
    try:
        return add_keyword(session, body.word, body.synonyms, body.category_id)
    finally:
        session.close()


@router.post("/{keyword_id}/count")
def increment_count(keyword_id: int):
    session = get_session()
    try:
        ok = update_search_count(session, keyword_id)
        if not ok:
            raise HTTPException(404, "Keyword not found")
        return {"success": True}
    finally:
        session.close()


@router.get("/popular")
def popular_keywords(limit: int = 20):
    session = get_session()
    try:
        return get_popular_keywords(session, limit)
    finally:
        session.close()


@router.get("/suggest")
def suggest(q: str = ""):
    session = get_session()
    try:
        return suggest_categories(session, q)
    finally:
        session.close()


@router.put("/{keyword_id}")
def update_keyword(keyword_id: int, body: KeywordUpdate):
    """키워드 수정."""
    session = get_session()
    try:
        kw = session.get(Keyword, keyword_id)
        if not kw:
            raise HTTPException(404, "Keyword not found")
        for key, val in body.model_dump(exclude_unset=True).items():
            setattr(kw, key, val)
        session.commit()
        session.refresh(kw)
        return {"id": kw.id, "word": kw.word}
    finally:
        session.close()


@router.delete("/{keyword_id}")
def delete_keyword(keyword_id: int):
    """키워드 삭제."""
    session = get_session()
    try:
        kw = session.get(Keyword, keyword_id)
        if not kw:
            raise HTTPException(404, "Keyword not found")
        session.delete(kw)
        session.commit()
        return {"deleted": True, "id": keyword_id}
    finally:
        session.close()
