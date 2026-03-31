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

router = APIRouter(prefix="/keywords", tags=["keywords"])


class KeywordCreate(BaseModel):
    word: str
    synonyms: Optional[list[str]] = None
    category_id: Optional[str] = None


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
