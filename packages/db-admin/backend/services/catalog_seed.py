"""Official catalog taxonomy seed helpers.

This seed only creates reviewed category/keyword dictionary rows. It does not
insert sample products or prices, so a cold DB can still represent a real
empty public catalog while preserving approved taxonomy links during ingestion.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from category_data import CATEGORIES, KEYWORDS
from storage.models import Category, Keyword

logger = logging.getLogger(__name__)


def ensure_catalog_taxonomy_seeded(engine: Engine) -> dict[str, int]:
    """Seed approved categories/keywords into an existing DB engine."""
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal.begin() as session:
        return seed_catalog_taxonomy(session)


def seed_catalog_taxonomy(session: Session) -> dict[str, int]:
    """Idempotently seed official categories and autocomplete keywords."""
    category_count = 0
    for data in CATEGORIES:
        category = session.get(Category, data["id"])
        if category is None:
            session.add(
                Category(
                    id=data["id"],
                    name=data["name"],
                    parent_id=data.get("parent_id"),
                    depth=data.get("depth", 0),
                    sort_order=data.get("sort_order", 0),
                    icon=data.get("icon"),
                    attributes=data.get("attributes") or None,
                    is_active=data.get("is_active", True),
                )
            )
            category_count += 1

    session.flush()
    known_category_ids = set(session.execute(select(Category.id)).scalars().all())

    keyword_count = 0
    repaired_keyword_count = 0
    for data in KEYWORDS:
        word = str(data["word"]).strip()
        if not word:
            continue
        existing = session.execute(select(Keyword).where(Keyword.word == word)).scalar_one_or_none()
        category_id = data.get("category_id")
        if category_id not in known_category_ids:
            category_id = None
        if existing is not None:
            changed = False
            if category_id and existing.category_id != category_id:
                existing.category_id = category_id
                changed = True
            if not existing.synonyms and data.get("synonyms"):
                existing.synonyms = data.get("synonyms") or []
                changed = True
            if not existing.is_active:
                existing.is_active = True
                changed = True
            if changed:
                repaired_keyword_count += 1
            continue
        session.add(
            Keyword(
                word=word,
                synonyms=data.get("synonyms") or [],
                category_id=category_id,
                search_count=data.get("search_count", 0),
                is_active=data.get("is_active", True),
            )
        )
        keyword_count += 1

    logger.info(
        "Catalog taxonomy seed complete: categories=%s keywords=%s repaired_keywords=%s",
        category_count,
        keyword_count,
        repaired_keyword_count,
    )
    return {
        "categories": category_count,
        "keywords": keyword_count,
        "repaired_keywords": repaired_keyword_count,
    }
