"""자동완성 키워드 라우트"""
import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from sqlalchemy import select, func, or_, String as SAString

from services.base import get_session
from services.autocomplete import (
    search_keywords,
    add_keyword,
    update_search_count,
    get_popular_keywords,
    suggest_categories,
)
from storage.models import Keyword, Product

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


class BulkDeleteRequest(BaseModel):
    ids: Optional[list[int]] = None


@router.get("/")
def list_keywords(
    page: int = 1,
    per_page: int = 20,
    q: str = "",
    category_id: Optional[str] = None,
    sort_by: str = "search_count",
    sort_dir: str = "desc",
    show_unused: bool = False,
):
    """키워드 전체 목록 — 서버 사이드 검색·페이지네이션·필터."""
    session = get_session()
    try:
        base = select(Keyword).where(Keyword.is_active == True)

        if q:
            base = base.where(
                or_(
                    Keyword.word.ilike(f"%{q}%"),
                    Keyword.synonyms.cast(SAString).ilike(f"%{q}%"),
                )
            )

        if category_id:
            base = base.where(Keyword.category_id == category_id)

        if show_unused:
            base = base.where(Keyword.search_count == 0)

        sort_col = getattr(Keyword, sort_by, Keyword.search_count)
        base = base.order_by(
            sort_col.desc() if sort_dir == "desc" else sort_col.asc()
        )

        count_q = select(func.count()).select_from(base.subquery())
        total = session.execute(count_q).scalar() or 0
        total_pages = max(1, math.ceil(total / per_page))

        offset = (max(1, page) - 1) * per_page
        rows = session.execute(base.offset(offset).limit(per_page)).scalars().all()

        cat_ids = list({kw.category_id for kw in rows if kw.category_id})
        product_counts: dict = {}
        if cat_ids:
            try:
                cnt_rows = session.execute(
                    select(Product.category_id, func.count(Product.id))
                    .where(Product.category_id.in_(cat_ids))
                    .group_by(Product.category_id)
                ).all()
                product_counts = {cid: cnt for cid, cnt in cnt_rows}
            except Exception:
                pass

        items = [
            {
                "id": kw.id,
                "word": kw.word,
                "synonyms": kw.synonyms or [],
                "category_id": kw.category_id,
                "search_count": kw.search_count,
                "is_active": kw.is_active,
                "product_count": product_counts.get(kw.category_id, 0),
            }
            for kw in rows
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    finally:
        session.close()


@router.get("/stats")
def keyword_stats():
    """키워드 통계 — 미사용 키워드 수, 총 키워드 수."""
    session = get_session()
    try:
        total = session.execute(
            select(func.count()).select_from(
                select(Keyword.id).where(Keyword.is_active == True).subquery()
            )
        ).scalar() or 0
        unused = session.execute(
            select(func.count()).select_from(
                select(Keyword.id).where(
                    Keyword.is_active == True,
                    Keyword.search_count == 0,
                ).subquery()
            )
        ).scalar() or 0
        return {"total": total, "unused_count": unused}
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
    """키워드 추가 — 유효성 검사 실패 시 422, 중복 시 409 반환."""
    session = get_session()
    try:
        existing = session.execute(
            select(Keyword).where(Keyword.word == body.word)
        ).scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"'{body.word}' 키워드가 이미 존재합니다.",
            )

        try:
            return add_keyword(session, body.word, body.synonyms, body.category_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    finally:
        session.close()


@router.post("/bulk-delete")
def bulk_delete_keywords(body: BulkDeleteRequest):
    """미사용 키워드 벌크 삭제. ids가 없으면 search_count=0인 키워드 전부 삭제."""
    session = get_session()
    try:
        if body.ids:
            keywords = session.execute(
                select(Keyword).where(Keyword.id.in_(body.ids))
            ).scalars().all()
        else:
            keywords = session.execute(
                select(Keyword).where(
                    Keyword.is_active == True,
                    Keyword.search_count == 0,
                )
            ).scalars().all()

        count = len(keywords)
        for kw in keywords:
            session.delete(kw)
        session.commit()
        return {"deleted": count}
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
        return {
            "id": kw.id,
            "word": kw.word,
            "synonyms": kw.synonyms or [],
            "category_id": kw.category_id,
            "search_count": kw.search_count,
        }
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
